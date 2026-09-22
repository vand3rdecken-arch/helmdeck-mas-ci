# -*- coding: utf-8 -*-
"""Two desktop-capable card turns run AT THE SAME TIME (2026-09-22).

This file used to pin the opposite: that a second windows-mcp card WAITS for
the first card's whole turn (per-turn _desktop_lock, bounded queue). That
design is what serialized Henry's fan-out on 2026-09-19 - every machine card
is forced onto the windows-mcp driver, so an hour-long script card that never
clicked held the cursor and bounced three siblings, one hands run and its own
re-dispatch after 960s each. The cursor is now the per-call DESKTOP LEASE
(spine/git/desktop_lease.py, test_desktop_lease.py); the TURN holds nothing.

Pins, through the real sessions._turn with a stubbed drivers.run:
  1. a second windows-mcp card's turn starts while the first is still inside
     its turn (no wait, no bounce) - FAILS on the old code (the waiter sat in
     the 960s queue);
  2. a lease the card's hook took during the turn is released when the turn
     ends (the finally), so a finished card never leaves a stale lease;
  3. a lease held by ANOTHER owner is left alone by the turn end.

Self-sandboxing: patched events.settings/emit, stubbed drivers.run, temp
run_dirs, HELMDECK_DESKTOP_LEASE in a temp dir - no daemon, no real spawn.

Run: py -3.12 ops/tests/test_desktop_lock_wait.py
"""
import os, sys, tempfile, threading, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SANDBOX = tempfile.mkdtemp(prefix="hdlocktest-")
os.environ["HELMDECK_DESKTOP_LEASE"] = os.path.join(SANDBOX, "desktop.lease")

from spine.storage import events
from cells.engineer.cards import sessions
from spine.agent import drivers
from spine.git import desktop_lease


# --- sandbox ---------------------------------------------------------------
SETTINGS = {
    "drivers": {"desk": {"type": "claude",
                         "allowed_tools": ["mcp__windows-mcp__*"]}},
}
events.settings = lambda: SETTINGS
events.emit = lambda *a, **k: None

_release = threading.Event()          # test controls when the holder's turn ends
_inside = {}                          # tid -> time the stubbed turn body started

def fake_run(cfg, t, prompt, by=None):
    _inside[t["id"]] = time.time()
    if t["id"] == "holder":
        desktop_lease.acquire("holder", tool="mcp__windows-mcp__Click")   # what its hook would do
        _release.wait(timeout=30)     # a long turn
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


# --- 1) two desktop turns overlap -----------------------------------------
out = {}
th1 = turn_in_thread(track("holder"), out)
time.sleep(0.5)                        # holder is inside its turn
check("holder is inside its turn", "holder" in _inside)
check("holder's hook took the lease", desktop_lease.status().get("owner") == "holder")
th2 = turn_in_thread(track("second"), out)
th2.join(5)
check("second desktop card RAN while the holder was still mid-turn",
      isinstance(out.get("second"), tuple) and "holder" not in out)
check("...it entered its turn body within a second, no queue",
      _inside["second"] - _inside["holder"] < 3.0)
check("the holder's lease is untouched by the sibling's turn end",
      desktop_lease.status().get("owner") == "holder")

# --- 2) the turn end releases the card's own lease --------------------------
_release.set()
th1.join(10)
check("holder completed", isinstance(out.get("holder"), tuple))
check("holder's lease released at turn end", desktop_lease.status() == {})

# --- 3) a lease of another owner survives an unrelated turn end ------------
desktop_lease.acquire("hands-xyz", tool="mcp__windows-mcp__Type")
out = {}
turn_in_thread(track("third"), out).join(5)
check("third completed", isinstance(out.get("third"), tuple))
check("a foreign lease is not released by this card's turn end",
      desktop_lease.status().get("owner") == "hands-xyz")
desktop_lease.release("hands-xyz")

print("PASS test_desktop_lock_wait")
