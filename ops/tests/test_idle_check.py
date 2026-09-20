# -*- coding: utf-8 -*-
"""Headless test for the idle-check trigger (spine/ops/idle_check.py).

This module does NOT clean anything up - it only decides WHETHER to file
one kind=idle-check escalation (Henry judges and acts from there, see
cells/copilot/broker/henry_broker.py). What's tested here, on the real code
paths: the trigger does not fire while a card is genuinely live (turn_active,
not just a stored status flag - drivers._sessions), it fires exactly once per
idle stretch once the owner is away long enough and nothing runs, and the
situation snapshot it attaches carries all four resource categories.

Self-sandboxing: temp sqlite DB, temp settings.json - no daemon, no real
Chrome, no network except a fast connection-refused probe to 127.0.0.1:9222.

Run: py -3.12 ops/tests/test_idle_check.py
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, DAEMON)

SANDBOX = tempfile.mkdtemp()
os.environ["HELMDECK_LOCK_DIR"] = os.path.join(SANDBOX, "locks")   # never the real ~/.helmdeck/locks

from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from spine.comms import presence
from spine.agent import drivers
from spine.registry import escalations
from spine.ops import idle_check

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _go_idle(minutes=31):
    presence.clear()
    presence.record("owner", "phone", app_visible=True,
                    activity_at=time.time() - minutes * 60)


class _LiveTurn:
    """A worker session WITH a turn in flight - drivers.turn_active is an
    OBSERVATION (alive AND _cur set), not mere dict membership, same as
    test_zombie_sweep.py's fixture."""
    _cur = {"x": 1}

    def alive(self):
        return True


def test_never_fires_while_a_card_is_live():
    """Run FIRST, before any idle-check has ever been opened - liveness must
    block the trigger on its own, with no dedup state to confound the read."""
    _go_idle()
    db.track_put({"id": "t-live", "status": "running", "lane": "working",
                 "task": "t", "branch": "t-live", "run_dir": SANDBOX, "turns": 1,
                 "updated": "2026-09-20 00:00:00"})
    drivers._sessions["t-live"] = _LiveTurn()
    try:
        eid = idle_check.check()
        check(eid is None, "idle-check does not fire while a card is genuinely live (turn_active)")
    finally:
        drivers._sessions.pop("t-live", None)
        db.track_put({"id": "t-live", "status": "needs_you", "lane": "working",
                     "task": "t", "branch": "t-live", "run_dir": SANDBOX, "turns": 1,
                     "updated": "2026-09-20 00:00:00"})


def test_fires_once_per_idle_stretch():
    _go_idle()
    check(idle_check._anything_live() is False, "nothing live once the card above is settled")

    eid1 = idle_check.check()
    check(eid1 is not None, "idle-check fires once the owner is idle past the threshold and nothing runs")
    row = [r for r in escalations.records() if r.get("id") == eid1][0]
    check(row.get("kind") == "idle-check", "the escalation carries kind=idle-check")
    check(row.get("card") is None or row.get("card") == "", "a machine-wide observation has no card")

    eid2 = idle_check.check()
    check(eid2 is None, "a second check within the SAME idle stretch does not re-fire (dedup)")

    check(idle_check.check(force=True) is not None, "force=True bypasses every gate (manual/test use)")


def test_not_idle_enough_does_not_fire():
    presence.clear()
    presence.record("owner", "phone", app_visible=True, activity_at=time.time())
    check(idle_check.check() is None, "a fresh heartbeat means not idle enough - no fire")


def test_snapshot_has_all_four_categories():
    # sandboxed CDP port (a plain closed TCP port, not the machine's real
    # HelmDeck Chrome, if one happens to be running) - the category must
    # appear either way, and the test must not depend on or print whatever
    # the owner actually has open right now.
    from spine.media import browsercap
    browsercap.DEFAULT_PORT = 65535

    db.track_put({"id": "t-dev", "status": "needs_you", "lane": "working",
                 "dev_port": 3777, "task": "t", "branch": "t-dev", "run_dir": SANDBOX,
                 "turns": 1, "updated": "2026-09-20 00:00:00"})
    lockdir = os.path.join(os.environ["HELMDECK_LOCK_DIR"], "android-build")
    os.makedirs(lockdir, exist_ok=True)
    # a pid no real process can ever hold (os.kill(pid, 0) is otherwise a
    # genuine PID-REUSE RACE on Windows - measured live here: a just-exited
    # subprocess's pid was already reassigned to an unrelated live process by
    # the time the check ran, same trap proctable._is_ours exists to guard
    # against elsewhere. An implausible fixed pid is dead deterministically.)
    dead_pid = 99999999
    with open(os.path.join(lockdir, "pid"), "w", encoding="utf-8") as f:
        f.write("%d\n%d\n" % (dead_pid, dead_pid))

    snap = idle_check.situation_snapshot()
    print(snap)
    check(snap.startswith("browser:"), "category 1: harness browser targets")
    check("dev-ports:" in snap and "t-dev:3777" in snap, "category 2: registered dev ports with card status")
    check("worktrees ohne git-Registrierung:" in snap, "category 3: worktree folders with no git registration")
    check("locks mit toter PID:" in snap and "android-build" in snap, "category 4: locks with a dead holder pid")
    check("last: CPU" in snap, "RAM/CPU load rides along too")
    check(len(snap) <= 1500, "the snapshot fits the escalation detail budget on its own")


if __name__ == "__main__":
    test_never_fires_while_a_card_is_live()
    test_fires_once_per_idle_stretch()
    test_not_idle_enough_does_not_fire()
    test_snapshot_has_all_four_categories()
    print()
    if _fails:
        print("FAILED: %d check(s)" % len(_fails))
        sys.exit(1)
    print("ALL GREEN - idle-check trigger holds its contract")
