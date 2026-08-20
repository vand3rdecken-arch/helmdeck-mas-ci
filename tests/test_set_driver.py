# -*- coding: utf-8 -*-
"""sessions.update_track's guards on the "driver" field - the ONE place a
card's execution engine can be changed after filing (server.py's
/tracks/<id>/update and copilot.py's set_driver action both route through
here). driver is technically in EDITABLE alongside benign fields like task/
priority, but switching to a windows-mcp-capable driver is a CAPABILITY
GRANT (real mouse/keyboard/screen control + screen recording), not a request
edit - these are the invariants no caller should be able to skip:
  - an unknown driver name is refused (never a free string)
  - a driver change is refused while a turn is running (no mid-turn
    capability shift into a context that already started)
  - granting a windows-mcp-capable driver leaves a VISIBLE note (never
    silent), downgrading does not (nothing new to warn about)
Self-sandboxing: temp sqlite DB, temp events.jsonl/settings.json, temp run
dirs - no daemon, no board state."""
import json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(HERE)
sys.path.insert(0, DAEMON)

SANDBOX = tempfile.mkdtemp()

from daemon.spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from daemon.spine.storage import events
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from daemon.spine.agent import drivers
from daemon.cells.engineer import sessions

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _track(tid, driver="claude"):
    run_dir = os.path.join(SANDBOX, tid)
    os.makedirs(run_dir, exist_ok=True)
    return {"id": tid, "status": "needs_you", "lane": "working", "task": "t",
            "branch": tid, "run_dir": run_dir, "driver": driver,
            "turns": 1, "updated": "2026-08-14 00:00:00"}


def _last_notes(run_dir, n=5):
    with open(os.path.join(run_dir, "actions.jsonl"), encoding="utf-8") as f:
        rows = [json.loads(l) for l in f if l.strip()]
    return [r.get("detail") or "" for r in rows if r.get("kind") == "note"][-n:]


def test_unknown_driver_refused():
    db.track_put(_track("t-unknown"))
    try:
        sessions.update_track("t-unknown", {"driver": "totally-not-a-real-driver"})
        check(False, "unknown driver should have raised ValueError")
    except ValueError as e:
        check("unknown driver" in str(e), "unknown driver raises ValueError (%r)" % str(e))
    check(db.track_get("t-unknown")["driver"] == "claude", "driver unchanged after the refusal")


def test_valid_driver_switch():
    db.track_put(_track("t-switch"))
    t = sessions.update_track("t-switch", {"driver": "claude-desktop"})
    check(t["driver"] == "claude-desktop", "driver switched to claude-desktop")
    notes = _last_notes(t["run_dir"])
    check(any("Desktop-Zugriff aktiviert" in n for n in notes),
          "granting a windows-mcp driver leaves a visible capability-grant note")


def test_downgrade_no_capability_note():
    db.track_put(_track("t-downgrade", driver="claude-desktop"))
    t = sessions.update_track("t-downgrade", {"driver": "claude"})
    check(t["driver"] == "claude", "downgraded back to plain claude")
    notes = _last_notes(t["run_dir"])
    check(not any("Desktop-Zugriff aktiviert" in n for n in notes),
          "downgrade leaves no capability-GRANT note (nothing was granted)")
    check(any("EDITED by" in n for n in notes), "still leaves the generic edit note")


def test_refused_mid_turn():
    db.track_put(_track("t-live"))
    drivers._sessions["t-live"] = type("Fake", (), {"_cur": {"x": 1}, "alive": lambda self: True})()
    try:
        sessions.update_track("t-live", {"driver": "claude-desktop"})
        check(False, "mid-turn switch should have raised RuntimeError")
    except RuntimeError as e:
        check("running" in str(e), "mid-turn driver switch refused (%r)" % str(e))
    check(db.track_get("t-live")["driver"] == "claude", "driver unchanged while the turn is live")
    drivers._sessions.pop("t-live", None)
    t = sessions.update_track("t-live", {"driver": "claude-desktop"})
    check(t["driver"] == "claude-desktop", "same switch succeeds once the turn ends")


def test_unchanged_driver_is_a_noop():
    db.track_put(_track("t-noop"))
    before = db.track_get("t-noop")["updated"]
    t = sessions.update_track("t-noop", {"driver": "claude"})   # already claude
    check(t["updated"] == before, "setting the SAME driver is a no-op (no spurious edit/note)")


def test_flip_drops_idle_session():
    """A driver's tool grant is baked in at process spawn, so the flip must
    tear down the IDLE old-grant worker or it lingers until the next turn
    notices - and the owner sees no effect. The flip should drop it eagerly
    so the very next turn respawns fresh under the new driver."""
    import threading
    db.track_put(_track("t-idle"))

    class Fake:
        def __init__(self):
            self._cur = None                 # idle: no turn in flight
            self._turn_lock = threading.Lock()
            self.killed = False
        def alive(self):
            return True
        def kill(self):
            self.killed = True

    fake = Fake()
    drivers._sessions["t-idle"] = fake
    t = sessions.update_track("t-idle", {"driver": "claude-desktop"})
    check(t["driver"] == "claude-desktop", "flip succeeds on an idle card")
    check("t-idle" not in drivers._sessions,
          "idle old-grant session dropped from the registry on the flip")
    check(fake.killed, "the idle session's process was tree-killed")


def test_flip_spares_a_live_turn():
    """The mid-turn guard already refuses the flip, but prove drop_session
    itself never yanks a session with a turn in flight - defence in depth."""
    import threading
    fake = type("Fake", (), {})()
    fake._cur = {"turn": 1}                   # a turn is running
    fake._turn_lock = threading.Lock()
    fake.killed = False
    fake.alive = lambda: True
    fake.kill = lambda: setattr(fake, "killed", True)
    drivers._sessions["t-live-drop"] = fake
    dropped = drivers.drop_session("t-live-drop")
    check(not dropped, "drop_session refuses a session with a live turn")
    check("t-live-drop" in drivers._sessions and not fake.killed,
          "the live session is left intact")
    drivers._sessions.pop("t-live-drop", None)


if __name__ == "__main__":
    test_unknown_driver_refused()
    test_valid_driver_switch()
    test_downgrade_no_capability_note()
    test_refused_mid_turn()
    test_unchanged_driver_is_a_noop()
    test_flip_drops_idle_session()
    test_flip_spares_a_live_turn()
    print()
    if _fails:
        print("FAILED: %d check(s)" % len(_fails))
        sys.exit(1)
    print("ALL GREEN - set_driver guards hold")
