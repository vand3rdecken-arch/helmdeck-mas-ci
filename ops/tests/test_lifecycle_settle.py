# -*- coding: utf-8 -*-
"""The frozen-card class must STAY closed (Paseo lifecycle model, 063c94a).

'running' is a derived observation, never a remembered flag: the reconciler
(sessions.sweep_zombies) must judge a card by whether a TURN is actually in
flight (drivers.turn_active: session alive AND _cur set), not by whether a
worker process merely exists (has_session) - a soft cancel keeps the process
alive for --resume, which is exactly how a card froze at 'running' for 164
minutes with the sweep blind. Pins the three-way verdict + the guards.
Self-sandboxing: monkeypatched load/save, no daemon, no real audit writes."""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, DAEMON)
from spine.storage import db
db.init()
from cells.engineer import sessions
from cells.engineer import lifecycle
from spine.storage import trackstore
from spine.agent import drivers
from spine.storage import events
from spine.comms import notify

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# -- isolate from production: no real saves, no audit pollution, no push ------
saved = []
_track = {}


class FakeDB:
    """lifecycle.sweep_zombies calls _load/_mutate imported directly from
    trackstore, not through sessions - so the fake backing store has to sit
    under trackstore._db, not sessions."""
    def tracks_all(self):
        return [dict(_track)]
    def track_put(self, t):
        saved.append(dict(t))
    def track_get(self, tid):
        return dict(_track) if _track.get("id") == tid else None


trackstore._db = FakeDB()
events.emit = lambda *a, **k: None
notify.card_event = lambda *a, **k: None
lifecycle._promote_live_session = lambda t: False


class Stub:
    def __init__(self, cur):
        self._cur = cur

    def alive(self):
        return True


class Broken:
    _cur = {"x": 1}

    def alive(self):
        raise RuntimeError("boom")


def sweep(status, session, idle=999):
    global _track
    saved.clear()
    _track = {"id": "TEST-X", "status": status,
              "run_dir": os.path.join(HERE, "nonexistent"), "repo": None}
    drivers._sessions.pop("TEST-X", None)
    if session is not None:
        drivers._sessions["TEST-X"] = session
    lifecycle._track_idle_s = lambda t: idle
    try:
        sessions.sweep_zombies(min_idle_s=45)
    finally:
        drivers._sessions.pop("TEST-X", None)
    return saved[-1]["status"] if saved else "(untouched)"


# 1) a turn genuinely in flight (_cur set) is left alone - long silent turns
#    are protected by turn_active BEFORE any idle check
check(sweep("running", Stub(cur={"x": 1})) == "(untouched)",
      "turn in flight -> untouched")

# 2) worker alive but NO turn in flight (the after-cancel race that froze the
#    card): settle QUIETLY to needs_you - no bounce, session stays resumable
check(sweep("running", Stub(cur=None)) == "needs_you",
      "alive-but-idle -> settled to needs_you (not bounced)")

# 3) no session at all: the turn died with a prior daemon - bounce with note
check(sweep("running", None) == "bounced",
      "dead session -> bounced")

# 4) a session whose alive() throws must not count as active
check(sweep("running", Broken()) in ("needs_you", "bounced"),
      "broken session object -> still settled")

# 5) the steer-start spawn window (idle < min_idle_s) is never reaped
check(sweep("running", Stub(cur=None), idle=3) == "(untouched)",
      "spawn window (idle<min) -> untouched")

# 6) turn_active itself: dict membership alone (has_session semantics) is NOT
#    enough - the exact confusion that made the reconciler blind
drivers._sessions["TEST-Y"] = Stub(cur=None)
check(drivers.has_session("TEST-Y") and not drivers.turn_active("TEST-Y"),
      "has_session True but turn_active False for an idle worker")
drivers._sessions.pop("TEST-Y", None)
check(not drivers.turn_active("TEST-Z"), "no session -> turn_active False")

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails))
    sys.exit(1)
print("lifecycle-settle: all pinned - PASS")
