"""Stufe 2 (measure only): code-only repetition prefilter, then Jev / Sonnet only on the flagged windows.

Reuses states.json + hand.json from jev_loop_probe.py (same 20 sessions, same 160 hand labels).

  py -3.12 ops/tools/research/jev_loop_probe_v2.py prefilter   # prefilter alone -> stdout
  py -3.12 ops/tools/research/jev_loop_probe_v2.py run         # Jev + Sonnet on every flagged window -> results2.json
  py -3.12 ops/tools/research/jev_loop_probe_v2.py report      # metrics json -> stdout

TYPESAFE_API_KEY is read from the main tree .env inside this process only, never printed.
"""
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jev_loop_probe as v1  # noqa: E402

OUT = v1.OUT
WIN = 8
Q = {"type": "choice",
     "instructions": ("`attempt_1` and `attempt_2` are two similar tries of the same action; `between` are the steps in between. "
                      "Did something change between the two tries that justifies the second try "
                      "(new information, a different argument, a different error)?"),
     "criteria": {"progress": "Yes: the second try is justified by something new (new info, other argument, other error).",
                  "no_progress": "No: the second try repeats the first without anything new; the run is going in circles."}}


def sig(st):
    """tool + normalised target: numbers, hex, timestamps and the leading cd removed."""
    t = st["cmd"]
    if st["tool"] == "STOP_HOOK":
        return "STOP_HOOK"
    t = re.sub(r'^\s*cd\s+("[^"]*"|\S+)\s*(&&|;)\s*', "", t)
    t = t.split(" | ")[0] if st["tool"] == "Edit" else t
    t = re.sub(r"0x[0-9a-f]+|\b[0-9a-f]{7,}\b|\d+", "#", t.lower())
    return st["tool"] + ":" + re.sub(r"\s+", " ", t)[:100]


def flag(steps):
    """steps: list of step dicts. -> {index: (rule, j)} where j = index of the earlier attempt."""
    sg = [sig(s) for s in steps]
    out = {}
    for i in range(len(steps)):
        lo = max(0, i - WIN + 1)
        if sg[i] == "STOP_HOOK":
            prev = [k for k in range(lo, i) if sg[k] == "STOP_HOOK"]
            if prev:
                out[i] = ("stop", prev[-1])
                continue
        same = [k for k in range(lo, i) if sg[k] == sg[i]]
        if sg[i] != "STOP_HOOK" and len(same) >= 2:
            out[i] = ("sig", same[-1])
            continue
        for L in (2, 3, 4):
            if i - 2 * L + 1 >= 0 and sg[i - L + 1:i + 1] == sg[i - 2 * L + 1:i - L + 1]:
                out[i] = ("seq", i - L)
                break
    return out


def window_state(steps, j, i):
    def b(s, n):
        return {"tool": s["tool"], "target": sig(s).split(":", 1)[-1] if s["tool"] != "STOP_HOOK" else s["cmd"][:60],
                "result": s["result"][:n], "ok": s["ok"]}
    mid = steps[j + 1:i]
    if len(mid) > 6:
        mid = mid[:3] + mid[-3:]
    return {"attempt_1": b(steps[j], 140), "between": [b(s, 80) for s in mid], "attempt_2": b(steps[i], 140)}


def load():
    data = json.load(open(os.path.join(OUT, "states.json"), encoding="utf-8"))
    hand = json.load(open(os.path.join(OUT, "hand.json"), encoding="utf-8"))
    return {s: [x["step"] for x in d["states"]] for s, d in data.items()}, hand


def prefilter_metrics():
    steps, hand = load()
    tp = fp = fn = 0
    rules = {}
    for s, m in hand.items():
        fl = flag(steps[s])
        for i, h in m.items():
            w = h != "new_task"
            f = int(i) in fl
            tp += w and f
            fp += (not w) and f
            fn += w and not f
    for s, st in steps.items():
        for r, _ in flag(st).values():
            rules[r] = rules.get(r, 0) + 1
    tot = sum(len(v) for v in steps.values())
    nfl = sum(len(flag(v)) for v in steps.values())
    return {"tp": tp, "fp": fp, "fn": fn, "recall": round(tp / max(tp + fn, 1), 3), "precision": round(tp / max(tp + fp, 1), 3),
            "flagged_all": nfl, "steps_all": tot, "rules": rules}


def sonnet(state):
    prompt = (Q["instructions"] + "\n" + "\n".join(f"- {k}: {v}" for k, v in Q["criteria"].items())
              + "\nState JSON:\n" + json.dumps(state, ensure_ascii=False) + "\nAnswer with exactly one label and nothing else.")
    t = time.time()
    for _ in range(2):
        try:
            p = subprocess.run(["claude.cmd", "-p", "--model", "sonnet", "--output-format", "json", "--tools", "",
                                "--system-prompt", "You are a strict classifier.", "--no-session-persistence"],
                               input=prompt, capture_output=True, text=True, timeout=240, cwd=tempfile.gettempdir(), encoding="utf-8")
            j = json.loads(p.stdout)
            m = re.search(r"no_progress|progress", j.get("result", ""))
            if m:
                return {"label": m.group(0), "usd": j.get("total_cost_usd", 0), "ms": int((time.time() - t) * 1000)}
        except Exception:  # noqa: BLE001 - measurement, retry once then record None
            pass
    return {"label": None, "ms": int((time.time() - t) * 1000)}


def jev(state, key):
    import urllib.request
    body = json.dumps({"state": state, "model": "jev-latest", "questions": {"c": Q}}).encode()
    req = urllib.request.Request(v1.URL, body, {"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    t = time.time()
    for a in range(3):
        try:
            r = json.load(urllib.request.urlopen(req, timeout=60))
            x = r["answers"]["c"]
            return {"label": x.get("choice"), "tok": (r.get("usage") or {}).get("input_tokens", 0), "ms": int((time.time() - t) * 1000)}
        except Exception:  # noqa: BLE001
            time.sleep(1 + a)
    return {"label": None, "ms": int((time.time() - t) * 1000)}


def run():
    steps, _ = load()
    key = v1._key()
    jobs = [(s, i, window_state(st, j, i)) for s, st in steps.items() for i, (_, j) in flag(st).items()]
    print("windows", len(jobs), flush=True)
    res = {"jev": {}, "sonnet": {}}
    t0 = time.time()
    with cf.ThreadPoolExecutor(6) as ex:
        fs = {ex.submit(jev, st, key): (s, i) for s, i, st in jobs}
        for f in cf.as_completed(fs):
            s, i = fs[f]
            res["jev"][f"{s}:{i}"] = f.result()
    res["jev_wall_s"] = time.time() - t0
    json.dump(res, open(os.path.join(OUT, "results2.json"), "w"))
    t0 = time.time()
    with cf.ThreadPoolExecutor(8) as ex:
        fs = {ex.submit(sonnet, st): (s, i) for s, i, st in jobs}
        for f in cf.as_completed(fs):
            s, i = fs[f]
            res["sonnet"][f"{s}:{i}"] = f.result()
    res["sonnet_wall_s"] = time.time() - t0
    json.dump(res, open(os.path.join(OUT, "results2.json"), "w"))
    print("done")


def report():
    steps, hand = load()
    res = json.load(open(os.path.join(OUT, "results2.json")))
    out = {"prefilter": prefilter_metrics()}
    for name in ("jev", "sonnet"):
        tp = fp = fn = miss = 0
        share = {}
        for s, st in steps.items():
            fl = flag(st)
            n = sum(1 for i in fl if res[name].get(f"{s}:{i}", {}).get("label") == "no_progress")
            share[s] = n / len(st)
            miss += sum(1 for i in fl if not res[name].get(f"{s}:{i}", {}).get("label"))
        for s, m in hand.items():
            for i, h in m.items():
                w = h != "new_task"
                f = res[name].get(f"{s}:{i}", {}).get("label") == "no_progress"
                tp += w and f
                fp += (not w) and f
                fn += w and not f
        rs = list(res[name].values())
        rank = sorted(share, key=share.get, reverse=True)
        out["prefilter+" + name] = {
            "tp": tp, "fp": fp, "fn": fn, "recall": round(tp / max(tp + fn, 1), 3), "precision": round(tp / max(tp + fp, 1), 3),
            "windows": len(rs), "no_answer": miss,
            "no_progress_windows": sum(r.get("label") == "no_progress" for r in rs),
            "usd_per_window": round((sum(r.get("usd", 0) for r in rs) / max(len(rs), 1)) if name == "sonnet"
                                    else sum(r.get("tok", 0) for r in rs) / max(len(rs), 1) * 0.042 / 1e6, 5),
            "ms_avg": int(sum(r["ms"] for r in rs) / max(len(rs), 1)), "wall_s": round(res[name + "_wall_s"], 1),
            "avg_tok": int(sum(r.get("tok", 0) for r in rs) / max(len(rs), 1)) if name == "jev" else None,
            "rank_459913d5": rank.index("459913d5") + 1, "rank_02089b79": rank.index("02089b79") + 1,
            "share_459913d5": round(share["459913d5"], 3), "share_02089b79": round(share["02089b79"], 3)}
    # prefilter-alone rank
    sh = {s: len(flag(st)) / len(st) for s, st in steps.items()}
    rk = sorted(sh, key=sh.get, reverse=True)
    out["prefilter"]["rank_459913d5"] = rk.index("459913d5") + 1
    out["prefilter"]["rank_02089b79"] = rk.index("02089b79") + 1
    out["prefilter"]["share_459913d5"] = round(sh["459913d5"], 3)
    out["prefilter"]["share_02089b79"] = round(sh["02089b79"], 3)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    c = sys.argv[1]
    if c == "prefilter":
        print(json.dumps(prefilter_metrics()))
    elif c == "run":
        run()
    else:
        report()
