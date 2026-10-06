# -*- coding: utf-8 -*-
"""Silent-truncation / closed-world defects in agent-facing text: every cut or
filter now says what it cut. Pure helpers + sandbox db (db.DBPATH first - the
live db is never touched).
Run: py -3.12 ops/tests/test_disclosure_cuts.py
"""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
SANDBOX = tempfile.mkdtemp(prefix="hd-disclose-")
from spine.storage import db, events
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# 4. broker snapshot: lock/load lines survive, the card cut is named
from cells.copilot.broker import henry_broker as hb
from spine.storage import trackstore
fake = [{"id": "c%02d" % i, "lane": "working", "status": "running", "task": "t%d" % i}
        for i in range(60)]
orig_load = trackstore._load
trackstore._load = lambda: fake
try:
    from spine.agent import drivers
    drivers.turn_active = lambda cid: False
    snap = hb._snapshot()
finally:
    trackstore._load = orig_load
check("ship.lock" in snap and "weitere Karten nicht gezeigt" in snap, "snapshot keeps lock line, discloses the card cut")
check("nur live" in snap and snap.index("ship.lock") < snap.index("card c00"), "card filter stated, locks before cards")
check(len(snap.splitlines()) <= 42, "snapshot stays bounded")

# 9. aborted-task names
from cells.engineer.cards import lifecycle
s = lifecycle._bg_names(["task-%d" % i + "x" * 30 for i in range(9)])
check(s.startswith("9 Task(s):") and "weitere)" in s, "bg names carry count + (+N weitere): %s" % s)
check(lifecycle._bg_names(["a", "b"]) == "2 Task(s): a, b", "short list untouched")

# 23. gate tails
from cells.engineer.cards import lanemachine as lm
check(lm._gate_tail("x" * 1500).startswith("[... 300 Zeichen davor nicht gezeigt]"), "gate tail marks the head cut")
check(lm._gate_tail("short") == "short", "short gate output unmarked")
check("[... 100 Zeichen gekuerzt]" in lm._cut_note("y" * 900, 800), "head cut marked")

# 24. loop_state
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "ops", "tools"))
import loop_state
check(loop_state._joined(["a", "b", "c", "d"]) == "a | b (+2 weitere)", "stop-hook list says (+N weitere)")
check(loop_state._joined(["a"]) == "a", "one item untouched")

# 11. board_state --find empty result
import io, contextlib
import board_state
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    board_state.main(["--find", "zzz-nothing-zzz"])
check("no card matches" in buf.getvalue() and "gesucht in id, task" in buf.getvalue(),
      "find names searched fields (%s)" % buf.getvalue().strip()[:80])

# 13/14. goal line
from cells.copilot.planning import goal_drive
gs = {"goal": "G", "days_left": None, "share": None, "live": ["a", "b", "c"], "working": 1,
      "last_move": None, "needs": [{"label": "n%d" % i} for i in range(5)],
      "facts": ["f%d" % i for i in range(10)]}
gl = goal_drive.goal_line(gs, 1000.0)
check("3 Ziel-Karten offen (davon 1 in Arbeit)" in gl, "goal cards: offen, not laufen")
check("(+2 weitere)" in gl and "8 von 10 Owner-Fakten" in gl, "needs + facts cuts disclosed")

# 16. process ref miss
from cells.copilot.chat import copilot_actions as ca
m0 = ca._process_ref_miss("edit_process", "x", [])
m2 = ca._process_ref_miss("edit_process", "x", [{"id": "p%d" % i, "request": "R%d" % i} for i in range(7)])
check("matches 0 processes" in m0, "0 matches stated")
check("matches 7 processes" in m2 and "p4 (R4)" in m2 and "p5" not in m2 and "2 weitere" in m2, "many: 5 candidates + rest count")

# 27. suppressed escalation is noted on the open one
from spine.registry import escalations
from cells.copilot.planning import pm_comm
eid = escalations.emit("ctx-high", card="cardX", detail="first")
pm_comm._to_henry("ctx-high", "second wording here", card="cardX")
pm_comm._to_henry("ctx-high", "third", card="cardX")
e = escalations.fold()[eid]
check("2 neuere gleichartige Meldung(en) unterdrueckt" in (e.get("last_note") or ""), "suppression noted (%s)" % e.get("last_note"))
check("zuletzt: third" in (e.get("last_note") or ""), "latest text quoted")

print("FAILED: %s" % _fails if _fails else "ALL OK")
sys.exit(1 if _fails else 0)
