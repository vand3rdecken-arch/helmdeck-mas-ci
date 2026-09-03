# -*- coding: utf-8 -*-
"""Pins LOAD-AWARE ADMISSION (ops/docs/backlog/load-aware-admission) - the desktop
lock's pattern generalized from mutual EXCLUSION (only one card drives the
cursor) to mutual AWARENESS (several heavy ops may run at once while the box
has headroom; a NEW one waits to START while OBSERVED CPU load stays over
policy.load_admission's threshold - never a stored "busy" flag, never a
permanent refusal). Pins, through lanemachine._admit_heavy directly with
spine.ops.resources.cpu_percent faked (no real box load needed for a
deterministic test):
  1. load under the threshold admits immediately, no wait note;
  2. load over the threshold queues; the wait note NAMES the current holder
     (kind + card id) so the owner's chat says what it is waiting FOR;
  3. with no HelmDeck holder registered, high load still queues, named as
     unbekannt/extern (not from a HelmDeck card the seam can see);
  4. a policy threshold CHANGE (settings only, no code) flips whether the
     SAME observed load blocks or admits immediately;
  5. load that never drops still admits after wait_s, with a visible ANYWAY
     note - this is admission (defer the start), never a permanent block.

Self-sandboxing: patched events.settings/emit + resources.cpu_percent, a fake
ActionLog capturing notes, plain track dicts - no daemon, no real subprocess.

Run: py -3.12 ops/tests/test_load_admission.py
"""
import os, sys, threading, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from spine.storage import events
from spine.ops import resources
from spine.git import locks
from cells.engineer.cards import lanemachine

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


class FakeLog:
    def __init__(self):
        self.notes = []

    def log(self, kind, detail, **extra):
        self.notes.append(detail)


SETTINGS = {"policy": {"load_admission": {"enabled": True, "cpu_max_pct": 50,
                                          "wait_s": 5, "poll_s": 1}}}
events.settings = lambda: SETTINGS
events.emit = lambda *a, **k: None

_CPU = [10.0]
resources.cpu_percent = lambda interval=0.2: _CPU[0]


def reset(cpu_max=50, wait_s=5, poll_s=1):
    SETTINGS["policy"]["load_admission"].update(
        {"cpu_max_pct": cpu_max, "wait_s": wait_s, "poll_s": poll_s})


def track(tid):
    return {"id": tid}


# --- 1) load under threshold admits immediately, no wait note --------------
reset()
_CPU[0] = 10.0
log = FakeLog()
t0 = time.time()
token = lanemachine._admit_heavy(track("quick"), "gate", log)
dur = time.time() - t0
check(dur < 0.5, "load under threshold admits immediately (%.2fs)" % dur)
check(not log.notes, "no wait note when never queued")
locks._release_heavy(token)

# --- 2) load over threshold queues; the note NAMES the current holder;
#        admits once load drops ---------------------------------------------
reset(cpu_max=50, wait_s=10, poll_s=1)
_CPU[0] = 10.0
holder_log = FakeLog()
holder_token = lanemachine._admit_heavy(track("holder-card"), "gate", holder_log)
check(not holder_log.notes, "holder admitted immediately while load was low")
_CPU[0] = 90.0                      # load rises while the holder is still "running"
out = {}
def _waiter():
    log2 = FakeLog()
    out["log"] = log2
    out["token"] = lanemachine._admit_heavy(track("waiter-card"), "build", log2)
th = threading.Thread(target=_waiter, daemon=True)
th.start()
time.sleep(0.4)
check("token" not in out, "waiter has not admitted yet while load stays high")
check(bool(out.get("log") and out["log"].notes),
      "waiter logged a wait note while queued")
check(out.get("log") and any("holder-card" in n and "gate" in n for n in out["log"].notes),
      "the wait note NAMES the current holder (kind + card id): %r" % (out.get("log") and out["log"].notes))
_CPU[0] = 10.0                      # load drops
th.join(5)
check("token" in out, "waiter admitted once load dropped")
locks._release_heavy(holder_token)
if "token" in out:
    locks._release_heavy(out["token"])

# --- 3) no HelmDeck holder registered -> named as unbekannt/extern ---------
reset(cpu_max=50, wait_s=10, poll_s=1)
_CPU[0] = 90.0
log3 = FakeLog()
out3 = {}
def _lonely_waiter():
    out3["token"] = lanemachine._admit_heavy(track("lonely"), "gate", log3)
th3 = threading.Thread(target=_lonely_waiter, daemon=True)
th3.start()
time.sleep(0.4)
check(any("unbekannt/extern" in n for n in log3.notes),
      "high load with NO tracked HelmDeck holder is named unbekannt/extern, not blamed on a phantom card")
_CPU[0] = 10.0
th3.join(5)
if "token" in out3:
    locks._release_heavy(out3["token"])

# --- 4) policy threshold (settings only, no code) governs whether the SAME
#        observed load blocks or admits immediately -------------------------
_CPU[0] = 60.0
reset(cpu_max=50, wait_s=1.5, poll_s=1)    # 60 > 50 -> must queue (small wait_s: just prove it's slower, don't wait it out)
log4a = FakeLog()
t0 = time.time()
tok4a = lanemachine._admit_heavy(track("thresh-blocked"), "gate", log4a)
dur4a = time.time() - t0
check(dur4a > 0.5, "60%% CPU against a 50%% threshold queues (%.2fs)" % dur4a)
locks._release_heavy(tok4a)

reset(cpu_max=70, wait_s=10, poll_s=1)     # same 60%% load, raised threshold
log4b = FakeLog()
t0 = time.time()
tok4b = lanemachine._admit_heavy(track("thresh-admits"), "gate", log4b)
dur4b = time.time() - t0
check(dur4b < 0.5, "the SAME 60%% load admits immediately once the threshold policy raised - "
                    "no code changed (%.2fs)" % dur4b)
locks._release_heavy(tok4b)

# --- 5) load that never drops still admits after wait_s (never permanent),
#        and the give-up is REPORTED to Henry as a load-contention escalation
#        (exactly once - deduped against an already-open one) ---------------
from spine.registry import escalations
_emitted = []
escalations.emit = lambda kind, card=None, detail="": _emitted.append(
    {"kind": kind, "card": card, "detail": detail}) or "esc-test"
_open = []
escalations.list_open = lambda: _open

reset(cpu_max=50, wait_s=1.5, poll_s=1)
_CPU[0] = 95.0
log5 = FakeLog()
t0 = time.time()
token5 = lanemachine._admit_heavy(track("stuck"), "gate", log5)
dur5 = time.time() - t0
check(0.5 <= dur5 < 10.0, "gave up waiting near wait_s, not forever (%.2fs)" % dur5)
check(any("trotzdem" in n for n in log5.notes), "the give-up note says it is starting ANYWAY: %r" % log5.notes)
check(len(_emitted) == 1 and _emitted[0]["kind"] == "load-contention",
      "the give-up emitted ONE load-contention escalation for Henry: %r" % _emitted)
check(_emitted and "stuck" in _emitted[0]["detail"] and "CPU 95" in _emitted[0]["detail"],
      "the escalation detail names the op's card and the measured load")
locks._release_heavy(token5)

# a second give-up while one is still OPEN must not stack a duplicate
_open.append({"kind": "load-contention"})
log5b = FakeLog()
token5b = lanemachine._admit_heavy(track("stuck-again"), "build", log5b)
check(len(_emitted) == 1, "no duplicate escalation while one is already open")
locks._release_heavy(token5b)

# --- 6) Henry's snapshot line reads the SAME seam the admission decides by -
from cells.copilot.broker import henry_broker
_CPU[0] = 42.0
tok6 = lanemachine._admit_heavy(track("visible-holder"), "gate", FakeLog())
line = henry_broker._box_load_line()
check("CPU 42%" in line, "Henry's box-last line carries the measured CPU: %r" % line)
check("gate (visible-holder" in line, "…and NAMES the registered heavy-op holder: %r" % line)
locks._release_heavy(tok6)
line_empty = henry_broker._box_load_line()
check("schwere Ops: keine" in line_empty,
      "with no holder the line says keine, not unbekannt: %r" % line_empty)

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails))
    sys.exit(1)
print("load-admission: all pinned - PASS")
