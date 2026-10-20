# -*- coding: utf-8 -*-
"""Pins 2026-10-20 21:53-22:09 (py-spy): the broker's direct_task / machine_task
verbs filed a card with dispatch=True, so its whole first turn ran INLINE on the
broker's only thread - every other escalation (three empty-process wakes, new
deliveries) waited behind that one card. The verb must return once the card is
FILED; the first turn runs on its own thread (as the chat verbs since 10-10).
RED on the old code (_execute blocks until the turn ends).

Self-sandboxing: temp db, patched new_*_task + move_lane. Run:
  py -3.12 ops/tests/test_broker_card_start_detached.py
"""
import os, sys, tempfile, threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SANDBOX = tempfile.mkdtemp(prefix="hd-broker-detach-")
from spine.storage import db as _db
_db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
_db.init()
from cells.engineer.cards import sessions
from cells.copilot.broker import henry_broker

release = threading.Event()
turn_started = threading.Event()


def fake_new(*args, dispatch=True, **kw):
    t = {"id": "T%d" % (id(args) % 1000), "worktree": "C:/x", "branch": "(machine)"}
    if dispatch:                       # OLD behaviour: first turn inline
        turn_started.set(); release.wait(10)
    return t


def fake_move(tid, lane, actor="owner", **kw):
    turn_started.set(); release.wait(10)   # the first turn
    return {"id": tid}


sessions.new_machine_task = fake_new
sessions.new_direct_task = fake_new
sessions.move_lane = fake_move
sessions.machine_policy = lambda: {"enabled": True}

fails = 0
for action in ("machine_task", "direct_task"):
    turn_started.clear(); release.clear()
    done = []
    esc = {"id": "e-%s" % action, "kind": "idle-check", "card": None}
    th = threading.Thread(target=lambda: done.append(
        henry_broker._execute(action, "", "", "do it", esc, repo="C:/x")))
    th.start(); th.join(2)
    ok = bool(done) and done[0] is True
    print("%-13s _execute returns before the first turn ends: %s" % (action, "OK" if ok else "FAIL (blocked)"))
    fails += 0 if ok else 1
    release.set(); th.join(3)
print("ALL OK" if not fails else "FAILED")
sys.exit(1 if fails else 0)
