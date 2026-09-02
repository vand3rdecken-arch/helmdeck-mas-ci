# -*- coding: utf-8 -*-
"""A QUEUED turn is a LIVE turn - the badge must never say 'stopped' while it runs.

Measured 2026-09-02 (owner report, cards 20260902-040607 / 20260901-202935):
_turn blocks up to 960s on the desktop (cursor) lock or the direct-tree lock
BEFORE drivers.run() creates a session. In that window has_session() and
turn_active() were both False while status was 'running', so:

  * sweep_zombies bounced the card with the phantom note "daemon restarted
    mid-turn" 63s after it was filed - then the lock freed and the very same
    turn spawned and ran for minutes under a red 'abgelehnt' badge;
  * the sibling card (worker alive from a prior turn) took the other branch and
    was settled green to needs_you while ITS turn sat in the same queue.

Both badges said stopped; both cards were burning tokens. The fix makes
'queued' an observation (drivers.turn_intent, registered at turnrunner._turn's
entry - the single call site of drivers.run) that every reconciler consults via
turn_inflight(). This pins it. Self-sandboxing: fake track store, no daemon.
"""
import os, sys, tempfile, threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
# run_dir lives in a temp dir: the sweep's ActionLog CREATES the directory it
# logs into, so pointing it inside the repo litters the tree on every run.
TMP = tempfile.mkdtemp(prefix="hd-queued-test-")
from spine.storage import db
db.init()
from cells.engineer import sessions, lifecycle
from spine.storage import trackstore, events
from spine.agent import drivers
from spine.comms import notify

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


saved = []
_track = {}


class FakeDB:
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
    """A worker process that exists but has no turn in flight - what a card
    looks like between turns (kept alive for --resume)."""
    def __init__(self, cur=None):
        self._cur = cur

    def alive(self):
        return True


TID = "TEST-QUEUED"


def sweep(status="running", session=None, idle=999):
    global _track
    saved.clear()
    # run_dir deliberately absent: a FRESH card has no actions.jsonl, so the
    # real _track_idle_s returns 1e9 ("very idle") and the min_idle_s guard
    # does NOT protect it. That is why the sweep reached the bounce at all.
    _track = {"id": TID, "status": status,
              "run_dir": os.path.join(TMP, "run"), "repo": None}
    drivers._sessions.pop(TID, None)
    if session is not None:
        drivers._sessions[TID] = session
    lifecycle._track_idle_s = lambda t: idle
    try:
        sessions.sweep_zombies(min_idle_s=45)
    finally:
        drivers._sessions.pop(TID, None)
    return saved[-1]["status"] if saved else "(untouched)"


# -- 1. the registry itself ---------------------------------------------------
check(not drivers.turn_queued(TID), "no intent -> turn_queued False")
with drivers.turn_intent(TID) as intent:
    check(drivers.turn_queued(TID), "inside turn_intent -> turn_queued True")
    check(drivers.turn_inflight(TID), "inside turn_intent -> turn_inflight True")
    check(not drivers.turn_active(TID),
          "queued is NOT active (no session yet) - the distinction the bug hid")
    check(not intent.cancelled, "fresh intent is not cancelled")
check(not drivers.turn_queued(TID), "intent released on exit")
check(not drivers.turn_inflight(TID), "turn_inflight False again after release")

# -- 2. THE BUG: the sweep must not bounce a queued turn ----------------------
check(sweep() == "bounced", "control: running + no session + idle -> bounced")
with drivers.turn_intent(TID):
    check(sweep() == "(untouched)",
          "QUEUED turn (desktop/direct lock) -> NOT bounced (was the phantom "
          "'daemon restarted mid-turn')")

# -- 3. the sibling branch: worker alive, turn queued -> not settled either ---
check(sweep(session=Stub(cur=None)) == "needs_you",
      "control: alive-but-idle worker -> settled to needs_you")
with drivers.turn_intent(TID):
    check(sweep(session=Stub(cur=None)) == "(untouched)",
          "QUEUED turn with a lingering worker -> NOT settled green")

# -- 4. present(): a queued turn keeps the running badge, flagged as queued ---
lifecycle._track_idle_s = lambda t: 999
t = {"id": TID, "status": "running", "run_dir": "", "repo": None}
check(lifecycle.present(t).get("status") == "needs_you",
      "control: stored 'running' with nothing in flight is coerced to needs_you")
with drivers.turn_intent(TID):
    p = lifecycle.present(t)
    check(p.get("status") == "running",
          "QUEUED turn stays 'running' on the way out (badge matches reality)")
    check(p.get("queued_for") == "lock",
          "queued turn is surfaced as queued_for=lock, not a mystery spinner")

# -- 5. Stop on a queued turn really stops it (cancel arms the intent) --------
with drivers.turn_intent(TID) as intent:
    check(not intent.cancelled, "not cancelled before Stop")
    drivers.cancel(TID)
    check(intent.cancelled, "drivers.cancel arms the QUEUED intent")
drivers._cancelled.discard(TID)

# -- 6. interrupt-and-replace must not cancel its own replacement -------------
#    (a shared per-card flag would; per-intent tokens must not)
with drivers.turn_intent(TID) as old:
    drivers.cancel(TID)                 # steer interrupts the old turn...
    with drivers.turn_intent(TID) as new:   # ...and starts the replacement
        check(old.cancelled, "old intent stays cancelled")
        check(not new.cancelled,
              "the REPLACEMENT turn is not collaterally cancelled")
drivers._cancelled.discard(TID)

# -- 7. nesting/concurrency: the registry survives overlapping intents --------
def _hold(barrier, done):
    with drivers.turn_intent(TID):
        barrier.wait()
        done.wait(2.0)


barrier, done = threading.Barrier(3), threading.Event()
ts = [threading.Thread(target=_hold, args=(barrier, done), daemon=True) for _ in range(2)]
for th in ts:
    th.start()
barrier.wait(2.0)
check(drivers.turn_queued(TID), "two overlapping intents -> queued")
done.set()
for th in ts:
    th.join(3.0)
check(not drivers.turn_queued(TID),
      "registry drains to empty when BOTH intents exit (no leaked 'forever busy')")

# -- 8. a daemon restart must still reap: the registry is process-local -------
check(not drivers.turn_queued("SOME-OTHER-CARD"),
      "a fresh process knows of no queued turns - startup sweep still reaps")

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails))
    sys.exit(1)
print("queued-turn-visible: all pinned - PASS")
