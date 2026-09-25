"""Measure-only probe: can Jev (TypeSafe System One) spot repetition loops in agent runs?

Model: AgentPProf idea - split a run into tool steps, classify each step against
its predecessor, then read the share of wasted steps (retry_same + recovery_variant).

  py -3.12 ops/tools/research/jev_loop_probe.py build            # sample sessions -> states.json
  py -3.12 ops/tools/research/jev_loop_probe.py show SESSION     # numbered compact steps (for hand labelling)
  py -3.12 ops/tools/research/jev_loop_probe.py run              # Jev on all steps, Sonnet on hand-labelled ones
  py -3.12 ops/tools/research/jev_loop_probe.py report           # metrics -> stdout (json)

Raw states hold session text: they live in %TEMP%/jev_loop_probe, never in the repo.
TYPESAFE_API_KEY is read from the main tree .env inside this process only, never printed.
"""
import concurrent.futures as cf
import glob
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

OUT = os.path.join(tempfile.gettempdir(), "jev_loop_probe")
PROJECTS = os.path.expanduser("~/.claude/projects")
ENV = r"C:\Users\Tien Duy Vo\Downloads\swarmdeck\.env"
URL = "https://api.typesafe.ai/v1/systemone"
MUST = {"02089b79": "20260924-222503-direct-2", "459913d5": "20260924-223336-machine"}
CLASSES = {
    "new_task": "The step starts different work than the previous step: a new goal, a new target or normal forward progress.",
    "retry_same": "The step repeats the same action as the previous step (same tool, same command or target), unchanged, after a failure or without any new information.",
    "recovery_variant": "The previous step failed or was blocked and this step tries a changed variant of the same goal (other flags, other path, other tool).",
}
QUESTION = {"type": "choice",
            "instructions": "Look at `step` and `previous`. Which class fits `step`?",
            "criteria": CLASSES}
MAX_STEPS = 200


def _short(s, n):
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s if len(s) <= n else s[: n - 3] + "..."


def _cmd(name, inp):
    # v1 bug: long worktree path prefixes ate the 160 chars, so Edit/Read of different files looked identical.
    root = lambda v: re.sub(r"^.*?(helmdeck-worktrees[\\/]\w+[\\/][^\\/]+|Downloads[\\/]swarmdeck)[\\/]", "", str(v))
    for k in ("command", "file_path", "path", "pattern", "url", "prompt", "description", "query"):
        if k in inp:
            v = _short(root(inp[k]) if k in ("file_path", "path") else inp[k], 160)
            if k == "pattern" and inp.get("path"):
                v += " @ " + _short(root(inp["path"]), 60)
            elif k == "file_path" and name == "Edit":
                v += " | " + _short(inp.get("old_string", ""), 50)
            return v
    return _short(json.dumps(inp, ensure_ascii=False), 160)


def steps_of(path):
    """Tool steps in order: {tool, cmd, result, ok}. Stop-hook feedback counts as a step."""
    calls, out = {}, []
    for line in open(path, encoding="utf-8-sig"):
        try:
            o = json.loads(line)
        except ValueError:
            continue
        t, msg = o.get("type"), o.get("message") or {}
        c = msg.get("content")
        if t == "assistant" and isinstance(c, list):
            for b in c:
                if b.get("type") == "tool_use":
                    st = {"tool": b["name"], "cmd": _cmd(b["name"], b.get("input") or {}), "result": "", "ok": True}
                    calls[b["id"]] = st
                    out.append(st)
        elif t == "user":
            if isinstance(c, list):
                for b in c:
                    if b.get("type") == "tool_result" and b.get("tool_use_id") in calls:
                        st = calls[b["tool_use_id"]]
                        r = b.get("content")
                        if isinstance(r, list):
                            r = " ".join(x.get("text", "") for x in r if isinstance(x, dict))
                        st["result"] = _short(r or "", 140)
                        st["ok"] = not b.get("is_error") and not re.search(
                            r"(?i)\b(error|traceback|exit code [1-9]|not recognized|denied)\b", st["result"][:200])
            elif isinstance(c, str) and c.startswith("Stop hook feedback"):
                out.append({"tool": "STOP_HOOK", "cmd": _short(c, 160), "result": "stop blocked, session must continue", "ok": False})
    return out


def states_of(steps):
    def brief(s):
        return {k: s[k] for k in ("tool", "cmd", "result", "ok")} if s else None
    return [{"step": brief(s), "previous": brief(steps[i - 1] if i else None)} for i, s in enumerate(steps)]


def session_paths():
    """Card sessions: worktree/daemon-card project dirs and the main-tree project dir."""
    return sorted(glob.glob(os.path.join(PROJECTS, "*", "*.jsonl")))


def build():
    os.makedirs(OUT, exist_ok=True)
    picked = {}
    for p in session_paths():
        sid = os.path.basename(p)[:8]
        if sid in MUST:
            picked[sid] = p
    rng = random.Random(925)
    pool = [p for p in session_paths()
            if re.search(r"worktrees-1mmjd8p4-(?!chat-test-nur)|Downloads-swarmdeck(-daemon)?$", os.path.dirname(p))
            and os.path.basename(p)[:8] not in MUST]
    rng.shuffle(pool)
    for p in pool:
        if len(picked) >= 20:
            break
        try:
            n = len(steps_of(p))
        except OSError:
            continue
        if 25 <= n <= 300:
            picked[os.path.basename(p)[:8]] = p
    data = {}
    for sid, p in picked.items():
        st = steps_of(p)[:MAX_STEPS]
        data[sid] = {"path": p, "card": MUST.get(sid), "states": states_of(st)}
    json.dump(data, open(os.path.join(OUT, "states.json"), "w", encoding="utf-8"), ensure_ascii=False)
    for sid, d in data.items():
        print(sid, len(d["states"]), d["card"] or "")


def show(sid, lo=0, hi=10**9):
    d = json.load(open(os.path.join(OUT, "states.json"), encoding="utf-8"))[sid]
    for i, s in enumerate(d["states"][lo:hi], lo):
        x = s["step"]
        print(f"{i:3d} {'ok ' if x['ok'] else 'ERR'} {x['tool']}: {x['cmd'][:110]} => {x['result'][:70]}")


def _key():
    for l in open(ENV, encoding="utf-8"):
        if l.startswith("TYPESAFE_API_KEY="):
            return l.split("=", 1)[1].strip().strip("\"'")
    raise SystemExit("no TYPESAFE_API_KEY")


def jev(state, key):
    body = json.dumps({"state": state, "model": "jev-latest", "questions": {"cls": QUESTION}}).encode()
    req = urllib.request.Request(URL, body, {"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    t = time.time()
    for attempt in range(3):
        try:
            r = json.load(urllib.request.urlopen(req, timeout=60))
            a = r["answers"]["cls"]
            return {"label": a.get("choice"), "conf": a.get("confidence"), "tok": (r.get("usage") or {}).get("input_tokens", 0),
                    "ms": int((time.time() - t) * 1000)}
        except Exception as e:  # noqa: BLE001 - measurement script, record and go on
            err = str(e)[:80]
            time.sleep(1 + attempt)
    return {"label": None, "err": err, "ms": int((time.time() - t) * 1000)}


def sonnet(state):
    prompt = ("Classify the agent step below against the previous step.\nClasses:\n"
              + "\n".join(f"- {k}: {v}" for k, v in CLASSES.items())
              + "\nState JSON:\n" + json.dumps(state, ensure_ascii=False)
              + "\nAnswer with exactly one class name and nothing else.")
    t = time.time()
    try:
        p = subprocess.run(["claude.cmd", "-p", "--model", "sonnet", "--output-format", "json", "--tools", "",
                            "--system-prompt", "You are a strict classifier.", "--no-session-persistence"],
                           input=prompt, capture_output=True, text=True, timeout=180, cwd=tempfile.gettempdir(), encoding="utf-8")
        j = json.loads(p.stdout)
        m = re.search(r"new_task|retry_same|recovery_variant", j.get("result", ""))
        return {"label": m.group(0) if m else None, "usd": j.get("total_cost_usd", 0), "ms": int((time.time() - t) * 1000)}
    except Exception as e:  # noqa: BLE001
        return {"label": None, "err": str(e)[:80], "ms": int((time.time() - t) * 1000)}


def run():
    data = json.load(open(os.path.join(OUT, "states.json"), encoding="utf-8"))
    hand = json.load(open(os.path.join(OUT, "hand.json"), encoding="utf-8"))  # {sid: {idx: label}}
    key = _key()
    res = {"jev": {}, "sonnet": {}}
    jobs = [(sid, i) for sid, d in data.items() for i in range(len(d["states"]))]
    t0 = time.time()
    with cf.ThreadPoolExecutor(6) as ex:
        futs = {ex.submit(jev, data[s]["states"][i], key): (s, i) for s, i in jobs}
        for f in cf.as_completed(futs):
            s, i = futs[f]
            res["jev"].setdefault(s, {})[i] = f.result()
    res["jev_wall_s"] = time.time() - t0
    jobs = [(s, int(i)) for s, m in hand.items() for i in m]
    t0 = time.time()
    with cf.ThreadPoolExecutor(4) as ex:
        futs = {ex.submit(sonnet, data[s]["states"][i]): (s, i) for s, i in jobs}
        for f in cf.as_completed(futs):
            s, i = futs[f]
            res["sonnet"].setdefault(s, {})[i] = f.result()
    res["sonnet_wall_s"] = time.time() - t0
    json.dump(res, open(os.path.join(OUT, "results.json"), "w"))
    print("done", {k: len(v) for k, v in res.items() if isinstance(v, dict)})


def report():
    data = json.load(open(os.path.join(OUT, "states.json"), encoding="utf-8"))
    hand = json.load(open(os.path.join(OUT, "hand.json"), encoding="utf-8"))
    res = json.load(open(os.path.join(OUT, "results.json")))
    out = {}
    for name in ("jev", "sonnet"):
        n = agree = miss = 0
        conf = {}
        for s, m in hand.items():
            for i, h in m.items():
                r = res[name].get(s, {}).get(i) or res[name].get(s, {}).get(str(i))
                if not r or not r.get("label"):
                    miss += 1
                    continue
                n += 1
                agree += r["label"] == h
                conf[(h, r["label"])] = conf.get((h, r["label"]), 0) + 1
        out[name] = {"n": n, "agree": agree, "missing": miss, "pct": round(100 * agree / max(n, 1), 1),
                     "confusion": {f"{h}>{p}": c for (h, p), c in sorted(conf.items())}}
    jr = [r for s in res["jev"].values() for r in s.values()]
    steps = len(jr)
    out["jev_cost"] = {"steps": steps, "in_tok": sum(r.get("tok", 0) for r in jr),
                       "usd_per_1000": round(sum(r.get("tok", 0) for r in jr) / max(steps, 1) * 1000 * 0.042 / 1e6, 4),
                       "ms_avg": int(sum(r["ms"] for r in jr) / max(steps, 1)), "wall_s": round(res["jev_wall_s"], 1),
                       "null": sum(1 for r in jr if not r.get("label"))}
    sr = [r for s in res["sonnet"].values() for r in s.values()]
    out["sonnet_cost"] = {"steps": len(sr), "usd_per_1000": round(sum(r.get("usd", 0) for r in sr) / max(len(sr), 1) * 1000, 2),
                          "ms_avg": int(sum(r["ms"] for r in sr) / max(len(sr), 1))}
    rank = []
    for s, m in res["jev"].items():
        labs = [r.get("label") for r in m.values() if r.get("label")]
        w = sum(l != "new_task" for l in labs)
        rank.append((round(w / max(len(labs), 1), 3), s, len(labs), sum(l == "retry_same" for l in labs)))
    rank.sort(reverse=True)
    out["rank"] = [{"pos": k + 1, "sid": s, "waste": w, "steps": n, "retry": r, "known_loop": s in MUST}
                   for k, (w, s, n, r) in enumerate(rank)]
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "build":
        build()
    elif cmd == "show":
        show(sys.argv[2], *map(int, sys.argv[3:]))
    elif cmd == "run":
        run()
    else:
        report()
