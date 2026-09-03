# -*- coding: utf-8 -*-
"""Pins the desktop-lock QUEUE semantics (converted from fail-fast 2026-08-17).

Live failure this pays for: a wedged COWORK desktop turn held _desktop_lock and
a second machine card (the trooper Postgres debug) was refused OUTRIGHT at
dispatch - "Desktop control already in use" - and sat bounced until the owner
noticed. Dispatch/steer already run on background threads and threading.Lock
has its own wait queue, so contention should QUEUE (bounded blocking acquire,
settings desktop_lock_wait_s) and only bounce after the wait expires.

Pins, through the real sessions._turn with a stubbed drivers.run:
  1. a second desktop turn WAITS while the first holds the lock, then runs
     (serialized, both complete - no bounce);
  2. a holder that outlives desktop_lock_wait_s bounces the waiter with the
     visible "Waited ...s ... gave up" reason;
  3. after any outcome the lock is FREE again (released in the finally).

Self-sandboxing: patched events.settings/emit, stubbed drivers.run, temp
run_dirs - no daemon, no real spawn, no board.

Run: py -3.12 ops/tests/test_desktop_lock_wait.py
"""
import os, sys, tempfile, threading, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from spine.storage import events
from cells.engineer.cards import sessions
from spine.agent import drivers


# --- sandbox ---------------------------------------------------------------
SETTINGS = {
    "drivers": {"desk": {"type": "claude",
                         "allowed_tools": ["mcp__windows-mcp__*"]}},
    "desktop_lock_wait_s": 5,
}
events.settings = lambda: SETTINGS
events.emit = lambda *a, **k: None

_release = threading.Event()          # test controls when the holder's turn ends

def fake_run(cfg, t, prompt, by=None):
    if t["id"] == "holder":
        _release.wait(timeout=30)     # holds the desktop lock until told
    return ("sid-" + t["id"], "ok", {})

drivers.run = fake_run

def track(tid):
    d = tempfile.mkdtemp(prefix="hdlocktest-")
    return {"id": tid, "driver": "desk", "model": "opus", "machine": True,
            "run_dir": d, "task": "t"}

def turn_in_thread(t, out):
    def _go():
        try:
            out[t["id"]] = sessions._turn(t, "go")
        except Exception as e:
            out[t["id"]] = e
    th = threading.Thread(target=_go, daemon=True)
    th.start()
    return th

def check(desc, ok):
    assert ok, desc
    print("  ok: " + desc)


# --- 1) contention queues, then runs --------------------------------------
out = {}
th1 = turn_in_thread(track("holder"), out)
time.sleep(0.5)                        # holder is inside its turn, lock held
check("holder owns the lock", sessions._desktop_lock.locked())
th2 = turn_in_thread(track("waiter"), out)
time.sleep(0.5)
check("waiter has NOT bounced while queued", "waiter" not in out)
_release.set()                         # holder's turn ends
th1.join(10); th2.join(10)
check("holder completed", isinstance(out.get("holder"), tuple))
check("queued waiter RAN after the lock freed (no bounce)",
      isinstance(out.get("waiter"), tuple))
check("lock free after both turns", not sessions._desktop_lock.locked())

# --- 2) a wait longer than desktop_lock_wait_s bounces visibly -------------
SETTINGS["desktop_lock_wait_s"] = 1
_release.clear()
out = {}
th1 = turn_in_thread(track("holder"), out)
time.sleep(0.5)
th2 = turn_in_thread(track("late"), out)
th2.join(10)
check("waiter past the bound got the RuntimeError",
      isinstance(out.get("late"), RuntimeError))
check("...with the waited-and-gave-up reason", "Waited" in str(out.get("late")))
_release.set()
th1.join(10)
check("holder still completed after the waiter gave up",
      isinstance(out.get("holder"), tuple))
check("lock free at the end", not sessions._desktop_lock.locked())

print("PASS test_desktop_lock_wait")
