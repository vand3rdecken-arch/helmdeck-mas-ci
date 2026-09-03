# -*- coding: utf-8 -*-
"""Burn guard: the driver FOLDS a loop signal (N identical consecutive tool
calls), sessions.flag_burn persists it First-Class and hands the JUDGEMENT to
the PM, which corrects the worker (bounded) and escalates to the owner only if
its correction doesn't take. Never an auto-kill. Pins the token-burn-in-a-loop
gap the inactivity watchdog cannot see (a looping worker keeps streaming)."""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, DAEMON)

SANDBOX = tempfile.mkdtemp(prefix="hd-burn-")
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()
from spine.ops import runs
runs.REC = os.path.join(SANDBOX, "runs"); os.makedirs(runs.REC, exist_ok=True)
from spine.agent import drivers
from cells.engineer import sessions
from cells.copilot import pm
sessions.REC = runs.REC

_WRAP = os.path.join(tempfile.mkdtemp(), "fake_claude.cmd")
with open(_WRAP, "w", encoding="utf-8") as f:
    f.write('@echo off\r\n"%s" "%s" %%*\r\n' % (sys.executable, os.path.join(HERE, "fake_claude.py")))
drivers.CLAUDE = _WRAP
drivers._PIDFILE = os.path.join(tempfile.mkdtemp(), "driver_pids.json")

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _track(tid, **extra):
    run_dir = os.path.join(runs.REC, tid); os.makedirs(run_dir, exist_ok=True)
    t = {"id": tid, "task": "Tester recruiting", "status": "running", "lane": "working",
         "machine": True, "run_dir": run_dir, "worktree": SANDBOX}
    t.update(extra)
    tracks = sessions._load(); tracks = [x for x in tracks if x["id"] != tid]; tracks.append(t)
    sessions._save(tracks)
    return t


# --- 1) driver folds identical tool calls -> flag_burn persists + calls PM ----
seen = []
pm.review_burn = lambda tid: seen.append(tid)          # stub the model side
_track("burn-1")
s = drivers._ClaudeSession({"perm": "acceptEdits", "idle_timeout": 30}, {"id": "burn-1",
    "worktree": SANDBOX, "run_dir": os.path.join(runs.REC, "burn-1"), "machine": True})
s.run_turn("__LOOP__:6", os.path.join(runs.REC, "burn-1"))
s.kill()
t = sessions._find(sessions._load(), "burn-1")
b = (t or {}).get("burn") or {}
check(b.get("n", 0) >= 5 and b.get("name") == "Bash", "6 identical tool calls flagged (n=%s)" % b.get("n"))
check(b.get("corrections") == 0, "flag starts with 0 corrections")
check("burn-1" in seen, "the PM was handed the judgement (review_burn called)")

# --- 2) a clean turn end clears the stale burn signal -------------------------
sessions._finish_turn("burn-1", "sess-x", "all good, done", {"subtype": "success"},
                      __import__("spine.ops.actionlog", fromlist=["ActionLog"]).ActionLog(t["run_dir"]))
check(not (sessions._find(sessions._load(), "burn-1") or {}).get("burn"),
      "a clean turn end clears the burn signal")

# --- 3) PM judges LOOP -> exactly one corrective steer, corrections bumped ----
steers = []
sessions.steer = lambda tid, text, **kw: steers.append((tid, kw.get("source"), text)) or {"id": tid}
pm._ask = lambda prompt, model="": {"verdict": "loop", "why": "same failing cmd", "fix": "try X"}
_track("burn-3", burn={"n": 5, "name": "Bash", "sample": "{}", "corrections": 0})
pm._review_burn("burn-3")
check(len(steers) == 1 and steers[0][1] == "pm-burn", "loop verdict -> one pm-burn steer")
check((sessions._find(sessions._load(), "burn-3") or {})["burn"]["corrections"] == 1,
      "correction count bumped to 1")

# --- 4) PM judges LEGIT -> no steer ------------------------------------------
steers.clear()
pm._ask = lambda prompt, model="": {"verdict": "legit", "why": "polling with backoff"}
_track("burn-4", burn={"n": 6, "name": "Bash", "sample": "{}", "corrections": 0})
pm._review_burn("burn-4")
check(not steers, "legit verdict -> worker left alone (no steer)")

# --- 5) already corrected _RESOLVE_MAX times -> escalate, no steer -----------
steers.clear()
pushes = []
from spine.comms import notify
notify.push_fcm = lambda title, body, tid="": pushes.append(tid)
pm._ask = lambda prompt, model="": {"verdict": "loop", "fix": "x"}
_track("burn-5", burn={"n": 20, "name": "Bash", "sample": "{}", "corrections": pm._RESOLVE_MAX})
pm._review_burn("burn-5")
check(not steers and pushes, "exhausted corrections -> escalate to owner, no more steers")

# --- 6) autonomy=notify -> never touches the worker --------------------------
steers.clear(); pushes.clear()
events.settings = lambda: {"pm": {"autonomy": "notify"}}
pm._ask = lambda prompt, model="": {"verdict": "loop", "fix": "x"}
_track("burn-6", burn={"n": 5, "name": "Bash", "sample": "{}", "corrections": 0})
pm._review_burn("burn-6")
check(not steers and pushes, "autonomy=notify -> only owner push, never a steer")

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails)); sys.exit(1)
print("burn-guard: all pinned - PASS")
