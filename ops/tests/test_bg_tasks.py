# -*- coding: utf-8 -*-
"""Background tasks as Paseo-style descriptors (ProviderSubagentStore): one
descriptor per task with an explicit lifecycle status (running -> completed |
failed | canceled), reconciled to terminal when the owning worker PROCESS dies
(finishAll). Pins the phantom-count bug: a dead build lingered as "waiting on N"
forever because nothing marked it terminal."""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, DAEMON)

SANDBOX = tempfile.mkdtemp(prefix="hd-bg-")
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()
from spine.ops import runs
runs.REC = os.path.join(SANDBOX, "runs"); os.makedirs(runs.REC, exist_ok=True)
from spine.agent import drivers, claude_sessions as cs
from cells.engineer.cards import sessions
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


def _save(tid, **extra):
    t = {"id": tid, "task": "t", "status": "needs_you", "lane": "working"}
    t.update(extra)
    ts = [x for x in sessions._load() if x["id"] != tid]; ts.append(t); sessions._save(ts)
    return t


# --- 1) status model: only 'running' blocks; terminal states don't -----------
_save("m1")
sessions.bg_upsert("m1", "a", title="Build A", status="running")
sessions.bg_upsert("m1", "b", title="Build B", status="running")
st, pay = cs.background_state(sessions._find(sessions._load(), "m1"))
check(st == "waiting" and pay["n"] == 2, "two running -> waiting n=2")
sessions.bg_upsert("m1", "a", status="completed", result="BUILD SUCCESSFUL")
st, pay = cs.background_state(sessions._find(sessions._load(), "m1"))
check(st == "waiting" and pay["n"] == 1, "one done -> only the running one blocks")
sessions.bg_upsert("m1", "b", status="completed")
st, _ = cs.background_state(sessions._find(sessions._load(), "m1"))
check(st == "clear", "all terminal -> clear (but descriptors kept for the app)")
check(len((sessions._find(sessions._load(), "m1") or {}).get("bg_tasks") or {}) == 2,
      "finished descriptors stay for the clickable history")

# --- 2) reconcile_bg (finishAll): running -> canceled ------------------------
_save("m2")
sessions.bg_upsert("m2", "x", title="Build X", status="running")
n = sessions.reconcile_bg("m2")
tk = sessions._find(sessions._load(), "m2")
check(n == 1 and tk["bg_tasks"]["x"]["status"] == "canceled", "reconcile cancels a running task")
check(cs.background_state(tk)[0] == "clear", "a canceled task no longer blocks the card")
check("beendet" in (tk["bg_tasks"]["x"].get("result") or ""), "canceled task records why")

# --- 3) history cap: running never dropped, terminal bounded -----------------
_save("m3")
sessions.bg_upsert("m3", "live", title="live", status="running")
for i in range(sessions._BG_HISTORY_CAP + 5):
    sessions.bg_upsert("m3", "d%d" % i, title="done %d" % i, status="completed")
tk = sessions._find(sessions._load(), "m3")
tasks = tk["bg_tasks"]
check("live" in tasks, "a running task is never evicted by the cap")
check(sum(1 for v in tasks.values() if v["status"] == "completed") == sessions._BG_HISTORY_CAP,
      "terminal history is bounded to the cap")

# --- 4) driver _scan_bg records a running descriptor from the stream ---------
rd = os.path.join(runs.REC, "d1"); os.makedirs(rd, exist_ok=True)
_save("d1", run_dir=rd, worktree=SANDBOX, machine=True)
s = drivers._ClaudeSession({"perm": "acceptEdits", "idle_timeout": 30},
                           {"id": "d1", "run_dir": rd, "worktree": SANDBOX, "machine": True})
s.run_turn("__BGLAUNCH__", rd)
tk = sessions._find(sessions._load(), "d1")
bg = (tk.get("bg_tasks") or {}).get("bg1") or {}
check(bg.get("status") == "running" and "gradle" in (bg.get("detail") or ""),
      "driver folded a run_in_background launch into a running descriptor")
s.kill()

# --- 5) _spawn reconciles a prior process's tasks (respawn = children dead) --
rd2 = os.path.join(runs.REC, "d2"); os.makedirs(rd2, exist_ok=True)
_save("d2", run_dir=rd2, worktree=SANDBOX, machine=True, session_id="prev")
sessions.bg_upsert("d2", "old", title="Build (dead process)", status="running")
# constructing a session for a card with a session_id spawns -> reconcile fires
s2 = drivers._ClaudeSession({"perm": "acceptEdits", "idle_timeout": 30},
                            {"id": "d2", "run_dir": rd2, "worktree": SANDBOX, "machine": True,
                             "session_id": "prev"})
tk = sessions._find(sessions._load(), "d2")
check(tk["bg_tasks"]["old"]["status"] == "canceled",
      "a fresh spawn cancels the prior process's orphaned tasks (finishAll)")
s2.kill()

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails)); sys.exit(1)
print("bg-tasks: all pinned - PASS")
