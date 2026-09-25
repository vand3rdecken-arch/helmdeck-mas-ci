"""Stufe 3 (measure only, Jev only): progress ledger every 5 steps over whole card runs, label = card outcome.

Model: Magentic-One progress ledger (stall counter) + SWE-PRM (a process reward signal from a small judge over the trajectory).

  py -3.12 ops/tools/research/jev_loop_probe_v3.py select        # card list from a COPY of the HelmDeck db -> cards.json
  py -3.12 ops/tools/research/jev_loop_probe_v3.py run [SECONDS] # resumable: Jev calls until the time budget is used up
  py -3.12 ops/tools/research/jev_loop_probe_v3.py report        # metrics json -> stdout

Reads a snapshot of the live db (copied to %TEMP%/j3/snap.db, never opened in place, never written) and the transcripts
under ~/.claude/projects. TYPESAFE_API_KEY is read from the main tree .env inside this process only, never printed.
Raw session text stays in %TEMP%/j3, never in the repo.
"""
import collections
import concurrent.futures as cf
import glob
import json
import os
import random
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jev_loop_probe as v1  # noqa: E402

OUT = os.path.join(tempfile.gettempdir(), "j3")
DAEMON = r"C:\Users\Tien Duy Vo\Downloads\swarmdeck\daemon"
EVERY, WINDOW, MAXSTEPS = 5, 10, 400
SELF = "20260925-093039"  # this very card (status bounced by a daemon restart) must not grade itself
MUST = {"20260924-222503-direct-2": "02089b79", "20260924-223336-machine": "459913d5"}
QUESTIONS = {
    "solving": {"type": "choice",
                "instructions": ("Read `goal`, `last_owner_message`, `history_summary` and `recent_steps` (the most recent steps, oldest first). "
                                 "Is the agent on track to solve the goal?"),
                "criteria": {"on_track": "The recent steps make real progress toward the goal: new information, new edits, a moving plan.",
                             "stuck_or_looping": "The agent is stuck or going in circles: repeating the same actions, working around blocked commands, "
                                                 "polling in cycles, or exploring without getting closer to the goal."}},
    "waste_type": {"type": "choice",
                   "instructions": "Look at `recent_steps`. Which kind of wasted effort, if any, dominates them?",
                   "criteria": {"identical_retry": "The same action is repeated unchanged.",
                                "guard_workaround": "Commands are blocked by a hook or guard and the agent keeps rewording them.",
                                "bg_poll_cycle": "The agent starts background jobs and polls or waits for them in cycles, or a stop hook keeps blocking the end.",
                                "redundant_exploration": "The agent keeps reading or searching things it already saw.",
                                "none": "No notable waste."}},
}


def _cut(s, n=2000):
    s = str(s)
    return s if len(s) <= 2 * n else s[:n] + "\n...[cut]...\n" + s[-n:]


def _root(v):
    return re.sub(r"^.*?(helmdeck-worktrees[\\/]\w+[\\/][^\\/]+|Downloads[\\/]swarmdeck)[\\/]", "", str(v))


def _action(name, inp):
    if name == "Bash":
        return _cut(inp.get("command", ""), 400)
    if name in ("Edit", "Write", "Read", "NotebookEdit"):
        a = _root(inp.get("file_path", ""))
        if name == "Edit":
            a += " | " + str(inp.get("old_string", ""))[:150] + " -> " + str(inp.get("new_string", ""))[:150]
        elif name == "Write":
            a += f" ({len(str(inp.get('content', '')))} chars)"
        return a
    return _cut(json.dumps(inp, ensure_ascii=False), 400)


def _is_human(c):
    t = c if isinstance(c, str) else " ".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    t = t.strip()
    return t if t and not t.startswith(("<", "Stop hook feedback", "Caveat", "[Request interrupted")) else None


def steps_full(path):
    """[{tool, action, result, ok, human}] - human = last owner/steer message before the step."""
    calls, out, human = {}, [], None
    for line in open(path, encoding="utf-8-sig"):
        try:
            o = json.loads(line)
        except ValueError:
            continue
        t, c = o.get("type"), (o.get("message") or {}).get("content")
        if t == "assistant" and isinstance(c, list):
            for b in c:
                if b.get("type") == "tool_use":
                    st = {"tool": b["name"], "action": _action(b["name"], b.get("input") or {}), "result": "", "ok": True, "human": human}
                    calls[b["id"]] = st
                    out.append(st)
        elif t == "user":
            if isinstance(c, list) and any(b.get("type") == "tool_result" for b in c):
                for b in c:
                    if b.get("type") == "tool_result" and b.get("tool_use_id") in calls:
                        st = calls[b["tool_use_id"]]
                        r = b.get("content")
                        if isinstance(r, list):
                            r = " ".join(x.get("text", "") for x in r if isinstance(x, dict))
                        st["result"] = _cut(r or "")
                        st["ok"] = not b.get("is_error") and not re.search(
                            r"(?i)\b(traceback|exit code [1-9]|not recognized|hook error)\b", st["result"][:300])
            elif isinstance(c, str) and c.startswith("Stop hook feedback"):
                out.append({"tool": "STOP_HOOK", "action": _cut(c, 300), "result": "stop blocked, the session must continue", "ok": False, "human": human})
            elif c:
                h = _is_human(c)
                if h:
                    human = _cut(h, 600)
    return out


def summary(steps):
    files = [re.sub(r" \|.*", "", s["action"]) for s in steps if s["tool"] in ("Edit", "Write")]
    blocked = [s["action"][:90] for s in steps if "hook error" in s["result"][:300] or "card_tool_guard" in s["result"][:300]]
    return {"steps_before": len(steps), "tool_counts": dict(collections.Counter(s["tool"] for s in steps).most_common(5)),
            "files_edited": list(dict.fromkeys(files))[-15:], "blocked_commands": len(blocked), "blocked_examples": blocked[-4:],
            "stop_hook_blocks": sum(s["tool"] == "STOP_HOOK" for s in steps), "failed_steps": sum(not s["ok"] for s in steps)}


def state_at(goal, steps, k):
    """State after k steps (k>=1): goal, last owner message, deterministic summary of the older steps, last WINDOW steps in full."""
    lo = max(0, k - WINDOW)
    recent = [{"n": i + 1, "tool": s["tool"], "action": s["action"], "result": s["result"], "ok": s["ok"]} for i, s in enumerate(steps[lo:k], lo)]
    st = {"goal": _cut(goal, 1500), "last_owner_message": steps[k - 1]["human"] or "", "history_summary": summary(steps[:lo]), "recent_steps": recent}
    if len(json.dumps(st, ensure_ascii=False)) > 90_000:  # ~ 25k tokens, stay under the 32k cap
        for r in recent:
            r["result"] = _cut(r["result"], 500)
    return st


def select():
    os.makedirs(OUT, exist_ok=True)
    for f in ("helmdeck.db", "helmdeck.db-wal"):
        shutil.copy(os.path.join(DAEMON, f), os.path.join(OUT, "snap" + f[len("helmdeck"):]))
    c = sqlite3.connect(os.path.join(OUT, "snap.db"))
    files = {os.path.basename(p)[:-6]: p for p in glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl"))}
    tr = {i: json.loads(d) for i, d in c.execute("select id,data from tracks")}
    ev = collections.defaultdict(set)
    for t, k, d in c.execute("select track,kind,data from events where kind in ('burn','error','rewind','bounce','lane')"):
        d = json.loads(d)
        if k == "lane" and (d.get("frm"), d.get("to")) in (("done", "working"), ("review", "working")):
            ev[t].add("rework")
        elif k == "bounce" and d.get("reason") != "daemon_restart":
            ev[t].add("bounce_" + str(d.get("reason")))
        elif k in ("burn", "error", "rewind"):
            ev[t].add(k)
    cand = {"solved": [], "notsolved": []}
    for t, d in tr.items():
        sid = d.get("session_id")
        if sid not in files or t in MUST:
            continue
        n = len(steps_full(files[sid]))
        if not 15 <= n <= MAXSTEPS:
            continue
        if d["status"] == "accepted" and not ev.get(t):
            cand["solved"].append((t, n))
        elif ev.get(t) or d["status"] == "bounced":
            cand["notsolved"].append((t, n, sorted(ev.get(t, [])) or [d["status"]]))
    rng = random.Random(925)
    rng.shuffle(cand["solved"])
    cards = [{"id": t, "label": "notsolved", "n": n, "why": w} for t, n, w in cand["notsolved"]]
    cards += [{"id": t, "label": "solved", "n": n, "why": ["accepted"]} for t, n in cand["solved"][:len(cand["notsolved"])]]
    cards += [{"id": t, "label": "must", "n": len(steps_full(files[[s for s in files if s.startswith(sid)][0]])), "why": ["accepted, known loop"]}
              for t, sid in MUST.items()]
    for cd in cards:
        cd["sid"] = tr[cd["id"]]["session_id"]
        cd["path"] = files[cd["sid"]]
        cd["goal"] = (tr[cd["id"]].get("task") or "") + "\n" + (tr[cd["id"]].get("description") or "")
    json.dump(cards, open(os.path.join(OUT, "cards.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(collections.Counter(c["label"] for c in cards), "steps", sum(c["n"] for c in cards))


def jev(state, key):
    body = json.dumps({"state": state, "model": "jev-latest", "questions": QUESTIONS}).encode()
    req = urllib.request.Request(v1.URL, body, {"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    t = time.time()
    err = ""
    for a in range(3):
        try:
            r = json.load(urllib.request.urlopen(req, timeout=90))
            return {"answers": r["answers"], "tok": (r.get("usage") or {}).get("input_tokens", 0), "ms": int((time.time() - t) * 1000)}
        except Exception as e:  # noqa: BLE001 - measurement
            err = str(e)[:80]
            time.sleep(1 + a)
    return {"err": err, "ms": int((time.time() - t) * 1000)}


def run(budget=250):
    cards = json.load(open(os.path.join(OUT, "cards.json"), encoding="utf-8"))
    resf = os.path.join(OUT, "results3.jsonl")
    done = set()
    if os.path.exists(resf):
        done = {(j["id"], j["k"]) for j in map(json.loads, open(resf, encoding="utf-8")) if "answers" in j}
    key = v1._key()
    jobs = []
    for cd in cards:
        steps = None
        n = cd["n"]
        for k in sorted(set(range(EVERY, n + 1, EVERY)) | {n}):
            if (cd["id"], k) not in done:
                jobs.append((cd, k))
    print("todo", len(jobs), flush=True)
    t0 = time.time()
    cache = {}

    def work(cd, k):
        if time.time() - t0 > budget:
            return None
        if cd["id"] not in cache:
            cache[cd["id"]] = steps_full(cd["path"])
        st = state_at(cd["goal"], cache[cd["id"]], k)
        r = jev(st, key)
        r.update(id=cd["id"], k=k)
        return r
    n_ok = 0
    with cf.ThreadPoolExecutor(6) as ex, open(resf, "a", encoding="utf-8") as f:
        for r in ex.map(lambda a: work(*a), jobs):
            if r:
                f.write(json.dumps(r) + "\n")
                n_ok += "answers" in r
    print("done this run", n_ok, "remaining", len(jobs) - n_ok, flush=True)


def auc(pos, neg):
    """Mann-Whitney AUC, ties count half."""
    if not pos or not neg:
        return None
    w = sum((p > q) + 0.5 * (p == q) for p in pos for q in neg)
    return round(w / (len(pos) * len(neg)), 3)


def p_stuck(a):
    s = a["solving"]
    pr = s.get("probabilities") or {}
    if "stuck_or_looping" in pr:
        return float(pr["stuck_or_looping"])
    c = float(s.get("confidence") or 0.5)
    return c if s.get("choice") == "stuck_or_looping" else 1 - c


def curves():
    cards = {c["id"]: c for c in json.load(open(os.path.join(OUT, "cards.json"), encoding="utf-8"))}
    cur = collections.defaultdict(list)
    for j in map(json.loads, open(os.path.join(OUT, "results3.jsonl"), encoding="utf-8")):
        if "answers" in j and not j["id"].startswith(SELF):
            a = j["answers"]
            cur[j["id"]].append({"k": j["k"], "p": p_stuck(a), "choice": a["solving"].get("choice"),
                                 "waste": a["waste_type"].get("choice"), "tok": j["tok"], "ms": j["ms"]})
    for v in cur.values():
        v.sort(key=lambda x: x["k"])
    return cards, cur


def ledger(pts, alarm=3):
    """Magentic-One stall counter: +1 stuck, -1 on_track (floor 0); returns (max counter, step k of first alarm or None)."""
    c = mx = 0
    first = None
    for x in pts:
        c = c + 1 if x["choice"] == "stuck_or_looping" else max(0, c - 1)
        mx = max(mx, c)
        if c >= alarm and first is None:
            first = x["k"]
    return mx, first


def report():
    cards, cur = curves()
    lab = {i: cards[i]["label"] for i in cur}
    ids = {g: [i for i in cur if lab[i] == g] for g in ("solved", "notsolved", "must")}
    feats = {}
    for i, pts in cur.items():
        ps = [x["p"] for x in pts]
        third = ps[-max(1, len(ps) // 3):]
        mx, first = ledger(pts)
        feats[i] = {"last": ps[-1], "max": max(ps), "mean_last_third": sum(third) / len(third), "ledger_max": mx,
                    "alarm": first is not None, "lead": (pts[-1]["k"] - first) if first else None, "n": pts[-1]["k"],
                    "stuck_share": sum(x["choice"] == "stuck_or_looping" for x in pts) / len(pts)}
    out = {"cards": {g: len(v) for g, v in ids.items()}}
    pos = [feats[i] for i in ids["notsolved"]]
    neg = [feats[i] for i in ids["solved"]]
    out["auc"] = {k: auc([f[k] for f in pos], [f[k] for f in neg]) for k in ("last", "max", "mean_last_third", "ledger_max", "stuck_share")}
    out["ledger_alarm"] = {"hit_notsolved": sum(f["alarm"] for f in pos), "of_notsolved": len(pos),
                           "false_alarm_solved": sum(f["alarm"] for f in neg), "of_solved": len(neg),
                           "lead_steps_median": sorted(f["lead"] for f in pos if f["lead"] is not None)[len([f for f in pos if f["lead"] is not None]) // 2]
                           if any(f["lead"] is not None for f in pos) else None,
                           "lead_frac_of_run_median": sorted(round(f["lead"] / f["n"], 2) for f in pos if f["lead"] is not None)[
                               len([f for f in pos if f["lead"] is not None]) // 2] if any(f["lead"] is not None for f in pos) else None}
    thr = {}
    for k in ("last", "max", "mean_last_third"):  # best-accuracy threshold, in-sample, so an upper bound
        best = max(((sum(f[k] >= t for f in pos) + sum(f[k] < t for f in neg)) / (len(pos) + len(neg)), t)
                   for t in [x / 20 for x in range(1, 21)])
        thr[k] = {"acc": round(best[0], 3), "thr": best[1]}
    out["best_threshold_in_sample"] = thr
    out["waste_types"] = {g: dict(collections.Counter(x["waste"] for i in ids[g] for x in cur[i]).most_common()) for g in ids}
    allp = [x for v in cur.values() for x in v]
    n_steps = sum(cards[i]["n"] for i in cur)
    out["cost"] = {"calls": len(allp), "steps": n_steps, "avg_tok": int(sum(x["tok"] for x in allp) / len(allp)),
                   "usd_per_1000_steps": round(sum(x["tok"] for x in allp) * 0.042 / 1e6 / n_steps * 1000, 4),
                   "ms_avg": int(sum(x["ms"] for x in allp) / len(allp)), "max_tok": max(x["tok"] for x in allp)}
    out["must_curves"] = {cards[i]["sid"][:8]: [(x["k"], round(x["p"], 2), x["waste"]) for x in cur[i]] for i in ids["must"]}
    out["ids"] = {g: sorted(ids[g]) for g in ids}
    ln = {g: [cards[i]["n"] for i in ids[g]] for g in ("solved", "notsolved")}
    out["auc"]["run_length_only"] = auc(ln["notsolved"], ln["solved"])  # confounder check: steps count alone
    out["median_steps"] = {g: sorted(v)[len(v) // 2] for g, v in ln.items()}
    out["feats_notsolved_vs_solved"] = {"ns_last_mean": round(sum(f["last"] for f in pos) / len(pos), 3),
                                        "s_last_mean": round(sum(f["last"] for f in neg) / len(neg), 3),
                                        "ns_alarm_lead_n": sum(f["lead"] is not None for f in pos)}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    c = sys.argv[1]
    if c == "select":
        select()
    elif c == "run":
        run(int(sys.argv[2]) if len(sys.argv) > 2 else 250)
    else:
        report()
