# -*- coding: utf-8 -*-
"""Pins 2026-10-10 16:27-16:38: Henry's `machine_task` / `direct_task` actions
blocked on the card's whole first turn, so an action list of four started the
cards one by one (each when the previous first turn ended) and his next turn
refiled three twins. The action must return as soon as the card is FILED; the
first turn runs on its own thread. RED on the old code (action blocks).

Self-sandboxing: temp db, patched new_*_task + move_lane. Run:
  py -3.12 ops/tests/test_action_start_detached.py
"""
import os, sys, tempfile, threading, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SANDBOX = tempfile.mkdtemp(prefix="hd-act-detach-")
from spine.storage import db as _db
_db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
_db.init()
from cells.engineer.cards import sessions
from cells.copilot.chat import copilot_actions as ca

release = threading.Event()
started = []


def fake_new(*args, dispatch=True, **kw):
    t = {"id": "T%d" % (len(started) + 1), "worktree": "C:/x", "branch": "(machine)"}
    started.append(t["id"])
    if dispatch:                       # OLD behaviour: first turn inline
        release.wait(10)
    return t


def fake_move(tid, lane, actor="owner"):
    release.wait(10)                   # the first turn
    return {"id": tid}


sessions.new_machine_task = fake_new
sessions.new_direct_task = fake_new
sessions.move_lane = fake_move
sessions.machine_policy = lambda: {"enabled": True, "roles": ["owner"]}
events.settings = lambda: {"default_repo": "C:/x"}
ca._file_links = lambda *a, **k: None

fails = 0
for kind, extra in (("machine_task", {"cwd": "C:/x"}), ("direct_task", {"repo": "C:/x"})):
    done = []
    a = dict({"type": kind, "task": "do it"}, **extra)
    th = threading.Thread(target=lambda: done.append(ca._run_action(a, "owner", "owner")))
    th.start(); th.join(2)
    ok = bool(done) and a.get("_card") and "T" in done[0]
    print("%-13s returns before first turn ends: %s" % (kind, "OK" if ok else "FAIL (blocked)"))
    fails += 0 if ok else 1
    release.set(); th.join(3); release.clear()
print("ALL OK" if not fails else "FAILED")
sys.exit(1 if fails else 0)
