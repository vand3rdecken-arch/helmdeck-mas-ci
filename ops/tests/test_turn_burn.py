# -*- coding: utf-8 -*-
"""Turn-Burn-Tripwire (token-burn-hardening Karte B): a per-turn usage
accumulator folded live off the stream (drivers._turn_burn_watch/_check),
compared against soft/hard %-of-weekly-quota thresholds. Pins the 190M-token/
94-minute incident's missing mechanism - nothing watched ONE turn's live
spend; auto-compact is post-turn, the 150k-bloat escalation is PM's idle tick.
soft must fire AT MOST ONCE per turn (Henry, mid-turn actionable); hard must
fire AT MOST ONCE and cancel over the real cancel(tid) path - no wall-clock
cap anywhere in this."""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, DAEMON)

SANDBOX = tempfile.mkdtemp(prefix="hd-turnburn-")
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()
from spine.ops import runs
runs.REC = os.path.join(SANDBOX, "runs"); os.makedirs(runs.REC, exist_ok=True)
from spine.agent import drivers
from cells.engineer.cards import sessions
from cells.copilot.planning import pm
from cells.copilot.planning import pm_comm
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


def _spawn(tid):
    _track(tid)
    return drivers._ClaudeSession({"perm": "acceptEdits", "idle_timeout": 30}, {"id": tid,
        "worktree": SANDBOX, "run_dir": os.path.join(runs.REC, tid), "machine": True})


# fixed, round calibration: 1% of the weekly quota == 1000 tokens
CALIB = [{"tokens_per_pct": 1000.0, "source": "measured"}]
events.plan_calibration = lambda *a, **k: CALIB[0]
CFG = {"turn_burn_soft_pct": 2.0, "turn_burn_hard_pct": 5.0}
pm._pm = lambda: dict(CFG)
HENRY = []
pm_comm._to_henry = lambda kind, detail, card=None, feed="": HENRY.append((kind, card, detail)) or ""

# --- 1) below both thresholds -> no escalation, no cancel ---------------------
HENRY.clear()
s = _spawn("burn-quiet")
s.run_turn("__BURN__:5:100", os.path.join(runs.REC, "burn-quiet"))   # 5*101 = 505 tok = 0.505%
s.kill()
check(not HENRY, "under soft threshold -> Henry never notified")
check("burn-quiet" not in drivers._cancelled, "under hard threshold -> never cancelled")

# --- 2) crosses soft, stays under hard -> exactly ONE Henry escalation --------
HENRY.clear()
s = _spawn("burn-soft")
# 25 * 101 = 2525 tok = 2.525% (soft=2%), well under hard=5% (5000 tok)
s.run_turn("__BURN__:25:100", os.path.join(runs.REC, "burn-soft"))
s.kill()
check(len(HENRY) == 1, "soft crossing -> exactly one Henry escalation (got %d)" % len(HENRY))
check(HENRY and HENRY[0][0] == "turn-burn" and HENRY[0][1] == "burn-soft",
      "escalation carries kind=turn-burn and the right card id")
check(HENRY and "%" in HENRY[0][2], "evidence detail carries the %-of-quota figure")
check("burn-soft" not in drivers._cancelled, "soft alone never cancels the turn")

# --- 3) crosses hard -> soft fired once en route, hard cancels exactly once ---
HENRY.clear()
s = _spawn("burn-hard")
# 60 * 101 = 6060 tok = 6.06%, crosses soft (~frame 20) then hard (~frame 50);
# the remaining ~10 frames after the hard crossing must not re-fire anything.
_, reply, meta = s.run_turn("__BURN__:60:100", os.path.join(runs.REC, "burn-hard"))
s.kill()
check(len(HENRY) == 1, "hard turn -> soft still fires exactly once on the way up (got %d)" % len(HENRY))
# _cancelled is consumed by the normal turn-completion path (drivers.py:1405),
# so the durable proof cancel(tid) ran is the turn's own outcome: the same
# clean '(turn cancelled by you)' / canceled=True the composer's Stop produces.
check(meta.get("canceled") is True and reply == "(turn cancelled by you)",
      "hard crossing -> cancel(tid) fired over the real cancel-intent path (reply=%r)" % reply)
from spine.ops.actionlog import read_timeline
notes = [r.get("detail", "") for r in read_timeline(os.path.join(runs.REC, "burn-hard"))
         if r.get("kind") == "note"]
check(any("Turn-Burn HARD" in n for n in notes), "burn report note landed in the card feed")

# --- 4) no calibration reachable -> tripwire stays silent, never guesses ------
HENRY.clear()
CALIB[0] = None
s = _spawn("burn-nocalib")
s.run_turn("__BURN__:80:1000", os.path.join(runs.REC, "burn-nocalib"))  # would be way over hard if calibrated
s.kill()
check(not HENRY, "no calibration -> no Henry escalation even on a huge burst")
check("burn-nocalib" not in drivers._cancelled, "no calibration -> never cancels")
CALIB[0] = {"tokens_per_pct": 1000.0, "source": "measured"}

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails)); sys.exit(1)
print("turn-burn: all pinned - PASS")
