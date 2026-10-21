# -*- coding: utf-8 -*-
"""delivered-parked that the runtime already overtook is closed by CODE, no
model turn (2026-10-21: 20 of 80 judgements in two days were Henry saying
"ueberholt"). Pure: _find_track / drivers / record_decision are stubbed, so no
db (live or sandbox), no daemon, no model is touched.
Run: py -3.12 ops/tests/test_broker_overtaken.py"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from cells.copilot.broker import henry_broker as hb          # noqa: E402
from spine.agent import drivers                              # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


PARKED = {"id": "c1", "lane": "working", "status": "needs_you"}
state = {"t": dict(PARKED), "inflight": False}
hb._find_track = lambda card: state["t"]
drivers.turn_inflight = lambda tid: state["inflight"]
decided, judged = [], []
hb.escalations.record_decision = lambda eid, action, card="", why="", kind="": decided.append((eid, action, why))
hb._decide = lambda esc: judged.append(esc["id"])
ESC = {"id": "e1", "kind": "delivered-parked", "card": "c1", "attempts": 0}


def run(esc=ESC, **t):
    state["t"] = dict(PARKED, **t) if t is not None else None
    decided.clear(); judged.clear()
    hb._decide_or_give_up(esc)


run()
check(not decided and judged == ["e1"], "a really parked, idle card still goes to Henry's judgement")
run(lane="review")
check(decided and decided[0][1] == "ignore" and not judged and "review" in decided[0][2], "already in review -> closed by code")
run(archived=True)
check(decided and not judged, "archived card -> closed by code")
run(status="working")
check(decided and not judged, "no longer parked (status) -> closed by code")
run(question={"id": "q"})
check(decided and not judged, "card now asks a question (not delivered) -> closed by code")
state["inflight"] = True
run()
check(decided and "Turn" in decided[0][2] and not judged, "a new turn is alive on the card -> closed by code")
state["inflight"] = False
state["t"] = None
decided.clear(); judged.clear()
hb._decide_or_give_up(ESC)
check(decided and not judged, "card gone -> closed by code")
# other kinds are never pre-closed, and the attempt cap still gives up as before
state["t"] = dict(PARKED, lane="review")
decided.clear(); judged.clear()
hb._decide_or_give_up({"id": "e2", "kind": "turn-shape", "card": "c1", "attempts": 0})
check(not decided and judged == ["e2"], "other kinds are untouched (Henry judges them)")
print("\n%d FAIL" % len(_fails) if _fails else "\nall ok")
sys.exit(1 if _fails else 0)
