# -*- coding: utf-8 -*-
"""Turn-shape tripwire (order 77, debt tool-results-never-evicted-quadratic-
turn-cost - the MEASURE+WARN half only, eviction itself stays open): a
per-turn tool-call/token-split fold (drivers._turn_shape_watch/_check),
carried through the card's OWN turn commit (turnrunner._finish_turn ->
spine/turn/econ._record_turn_shape) so turn_tools/turn_in/turn_out/
turn_ratio/turn_history land on the CARD, not just in driver-local state.
Drives a synthetic many-tool-call turn through the REAL end-to-end path
(fake CLI -> drivers.run_turn -> turnrunner._finish_turn), same shape as
test_turn_burn.py. Sandboxed db/events/runs - never the live database."""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, DAEMON)

SANDBOX = tempfile.mkdtemp(prefix="hd-turnshape-")
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()
from spine.ops import runs
runs.REC = os.path.join(SANDBOX, "runs"); os.makedirs(runs.REC, exist_ok=True)
from spine.agent import drivers
from cells.engineer.cards import sessions
from cells.engineer.cards import turnrunner
from spine.registry import escalations
from spine.ops.actionlog import ActionLog, read_timeline
sessions.REC = runs.REC

# The turn-BURN tripwire (a separate mechanism, spine.agent.drivers.
# _turn_burn_check) shares the same stream and would otherwise call its OWN
# events.plan_calibration() un-mocked here - which kicks a REAL background
# refresh against the owner's actual Claude usage API (spine/ops/usage.py
# _kick_refresh) and, once that lands mid-run, can hard-cancel a turn on
# real-account numbers that have nothing to do with this test. Pin it off
# (same shape as test_turn_burn.py's own CALIB mock) so turn-shape's own
# WARN/ALARM path is the only thing under test, and so this test never
# makes a live network call.
events.plan_calibration = lambda *a, **k: None

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


def _session_for(tid):
    """A fresh driver session for an ALREADY-existing track row - unlike
    _spawn, never resets the card (needed for the turn_history test: each
    turn must land on the SAME card the prior turn already wrote)."""
    return drivers._ClaudeSession({"perm": "acceptEdits", "idle_timeout": 30}, {"id": tid,
        "worktree": SANDBOX, "run_dir": os.path.join(runs.REC, tid), "machine": True})


def _spawn(tid):
    _track(tid)
    return _session_for(tid)


def _run_and_finish(tid, prompt, fresh=True):
    """One turn through the REAL end-to-end path: driver.run_turn (the CLI
    stream fold) then turnrunner._finish_turn (the card commit) - the exact
    two calls dispatch/steer chain in production. fresh=False reuses the
    card's existing row (turn_history must accumulate across calls)."""
    run_dir = os.path.join(runs.REC, tid)
    s = _spawn(tid) if fresh else _session_for(tid)
    sid, reply, meta = s.run_turn(prompt, run_dir)
    s.kill()
    t, reason = turnrunner._finish_turn(tid, sid, reply, meta, ActionLog(run_dir))
    return t


def _esc_opens(kind, card):
    return [r for r in escalations.records()
            if r.get("event") == "open" and r.get("kind") == kind and r.get("card") == card]


def _notes(tid, needle):
    run_dir = os.path.join(runs.REC, tid)
    return [r for r in read_timeline(run_dir)
            if r.get("kind") == "note" and needle in r.get("detail", "")]


# --- 1) well under WARN -> shape still lands on the card, nothing fires -------
t = _run_and_finish("shape-quiet", "__SHAPE__:10:50:100")   # 10 tools, in=500 out=1000
check(t is not None and t.get("turn_tools") == 10, "under-threshold turn still records turn_tools (measure, not just warn)")
check(t.get("turn_ratio") == 0.5, "turn_ratio computed from THIS turn's own in/out (got %r)" % t.get("turn_ratio"))
check(not _notes("shape-quiet", "Turn-Form"), "under WARN -> no Turn-Form note")
check(not _esc_opens("turn-shape", "shape-quiet"), "under WARN -> no Henry escalation")

# --- 2) crosses WARN (40), stays under ALARM (80) -> one note, no escalation --
t = _run_and_finish("shape-warn", "__SHAPE__:55:100:10")    # 55 tools, in=5500 out=550
check(t.get("turn_tools") == 55, "WARN-range turn -> turn_tools == 55 on the card")
check(t.get("turn_ratio") == 10.0, "WARN-range turn -> turn_ratio == 10.0 (got %r)" % t.get("turn_ratio"))
warn_notes = _notes("shape-warn", "Turn-Form WARN")
check(len(warn_notes) == 1, "WARN crossing -> exactly one Turn-Form WARN note (got %d)" % len(warn_notes))
check(not _esc_opens("turn-shape", "shape-warn"), "WARN alone -> no Henry escalation")

# --- 3) crosses ALARM (80) -> WARN fired once en route, exactly one escalation
t = _run_and_finish("shape-alarm", "__SHAPE__:90:50:5")     # 90 tools, in=4500 out=450
check(t.get("turn_tools") == 90, "ALARM turn -> turn_tools == 90 on the card")
check(t.get("turn_ratio") == 10.0, "ALARM turn -> turn_ratio == 10.0 (got %r)" % t.get("turn_ratio"))
check(len(_notes("shape-alarm", "Turn-Form WARN")) == 1, "ALARM turn -> WARN still fired once on the way up")
alarm_esc = _esc_opens("turn-shape", "shape-alarm")
check(len(alarm_esc) == 1, "ALARM crossing -> exactly one turn-shape escalation (got %d)" % len(alarm_esc))
# fires the instant the count CROSSES 80 (tool call #81), not at the turn's
# eventual total (90) - the tripwire reports what it knew at that moment.
detail = (alarm_esc[0].get("detail", "") if alarm_esc else "")
check("81" in detail and "10:1" in detail,
      "escalation detail names the crossing call count and the ratio (got %r)" % detail)
check("shape-alarm" not in drivers._cancelled, "ALARM never cancels the turn (measure+warn only)")

# --- 4) history keeps the last 5 turns, oldest dropped -------------------------
tid = "shape-hist"
last = None
for i in range(6):
    last = _run_and_finish(tid, "__SHAPE__:%d:10:10" % (41 + i), fresh=(i == 0))   # 41..46 tools, WARN range
hist = last.get("turn_history") or []
check(len(hist) == 5, "turn_history capped at 5 entries (got %d)" % len(hist))
check([h["tools"] for h in hist] == [42, 43, 44, 45, 46],
      "turn_history keeps the last 5, oldest dropped (got %r)" % [h["tools"] for h in hist])
check(last.get("turn_tools") == 46, "the card's turn_tools is the LATEST turn's (got %r)" % last.get("turn_tools"))

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails)); sys.exit(1)
print("turn-shape: all pinned - PASS")
