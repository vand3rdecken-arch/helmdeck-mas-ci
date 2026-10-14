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


def test_a_live_but_silent_card_does_not_block_the_check():
    """Owner 2026-10-14: a wedged card (turn "in flight", no frame for longer
    than the tool cap) used to keep the idle-check silent for good. Silent
    work no longer counts as live, and the Lagebild names it. Observed via
    _anything_live/_stalled/situation_snapshot so the once-per-stretch dedup
    the next test relies on is not consumed here."""
    _go_idle()
    db.track_put({"id": "t-wedged", "status": "running", "lane": "working",
                 "task": "t", "branch": "t-wedged", "run_dir": SANDBOX, "turns": 1,
                 "updated": "2026-09-20 00:00:00"})

    class _Silent(_LiveTurn):
        _cur = {"last_event": time.time() - (idle_check.STALL_S + 240)}

    class _Busy(_LiveTurn):
        _cur = {"last_event": time.time() - 20}

    try:
        drivers._sessions["t-wedged"] = _Busy()
        check(idle_check._anything_live() is True, "a card that spoke 20 s ago is working: live")
        check(idle_check._stalled() == [], "...and not reported as standing still")

        drivers._sessions["t-wedged"] = _Silent()
        check(idle_check._anything_live() is False, "a card silent past the stall limit no longer blocks the check")
        st = idle_check._stalled()
        check(len(st) == 1 and st[0][1] == "t-wedged" and st[0][2] >= idle_check.STALL_S,
              "it is reported as standing still, with how long")
        snap = idle_check.situation_snapshot()
        check("stehen still: karte t-wedged" in snap, "the Lagebild names the stalled card")
    finally:
        drivers._sessions.pop("t-wedged", None)
        db.track_put({"id": "t-wedged", "status": "needs_you", "lane": "working",
                     "task": "t", "branch": "t-wedged", "run_dir": SANDBOX, "turns": 1,
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


def test_snapshot_is_three_facts_and_names_what_the_daemon_owns():
    # Owner decree 2026-10-14: the Lagebild no longer curates tabs/ports/
    # worktrees/locks (Henry reads those himself); it carries only what he
    # cannot fetch - which processes are the DAEMON's. Measured need: on
    # 2026-10-13 he ended a Paseo-owned claude.exe because nothing said whose
    # it was.
    import subprocess
    from spine.agent import proctable
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    proctable.own(child)
    try:
        time.sleep(0.5)
        owned_pids = [p for p, _e, _s in proctable.owned()]
        check(child.pid in owned_pids, "a process the daemon spawned and adopted is listed as ITS OWN")
        check(os.getpid() not in owned_pids, "the daemon itself is not listed as its own child")

        snap = idle_check.situation_snapshot()
        print(snap)
        lines = snap.splitlines()
        check(len(lines) == 3, "exactly three lines: owner, owned processes, load")
        check(lines[0].startswith("owner:"), "line 1: the owner's absence")
        check(lines[1].startswith("dem Daemon gehoeren:") and str(child.pid) in lines[1],
              "line 2 names the daemon's own processes by pid")
        check("last: CPU" in lines[2], "line 3: CPU/RAM")
        check(not any(w in snap for w in ("browser:", "dev-ports:", "worktrees", "locks mit")),
              "the curated tab/port/worktree/lock lists are gone")
        check(len(snap) <= 1500, "the snapshot fits the escalation detail budget on its own")
    finally:
        child.kill()


if __name__ == "__main__":
    test_never_fires_while_a_card_is_live()
    test_a_live_but_silent_card_does_not_block_the_check()
    test_fires_once_per_idle_stretch()
    test_not_idle_enough_does_not_fire()
    test_snapshot_is_three_facts_and_names_what_the_daemon_owns()
    print()
    if _fails:
        print("FAILED: %d check(s)" % len(_fails))
        sys.exit(1)
    print("ALL GREEN - idle-check trigger holds its contract")
