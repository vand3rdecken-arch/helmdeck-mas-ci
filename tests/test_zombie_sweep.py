# -*- coding: utf-8 -*-
"""Headless test for the startup zombie sweep (sessions.sweep_zombies).

The bug (found live 2026-07-28): a steer in flight when the daemon restarts
leaves the card status=running with no owning worker - cancel returns false,
the phone looks frozen forever. The sweep must flip exactly those tracks to
bounced with the visible restart note, audit + emit an event, and leave every
other card alone.

Self-sandboxing: temp sqlite DB, temp events.jsonl/settings.json, temp run
dirs - no daemon, no board state, no network (push_fcm no-ops without FCM
credentials)."""
import json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.join(os.path.dirname(HERE), "daemon")
sys.path.insert(0, DAEMON)

SANDBOX = tempfile.mkdtemp()

import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
import events
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

import drivers, sessions

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _track(tid, status):
    run_dir = os.path.join(SANDBOX, tid)
    os.makedirs(run_dir, exist_ok=True)
    return {"id": tid, "status": status, "lane": "working", "task": "t",
            "branch": tid, "run_dir": run_dir,
            "turns": 1, "updated": "2026-07-28 22:00:00"}


class _LiveTurn:
    """A worker session WITH a turn in flight. Since 063c94a 'running' is a
    derived observation (drivers.turn_active: alive AND _cur set), not mere
    dict membership - a bare object() would read as alive-but-idle and be
    settled to needs_you, which is exactly the lifecycle contract pinned by
    test_lifecycle_settle.py."""
    _cur = {"x": 1}

    def alive(self):
        return True


def test_sweep():
    db.track_put(_track("t-zombie", "running"))       # dead daemon's leftover
    db.track_put(_track("t-live", "running"))         # a turn actually in flight
    db.track_put(_track("t-idle", "needs_you"))       # untouched bystander
    drivers._sessions["t-live"] = _LiveTurn()         # simulate the live worker

    swept = sessions.sweep_zombies()

    check(swept == ["t-zombie"], "only the ownerless running track swept (got %r)" % swept)
    z = db.track_get("t-zombie")
    check(z["status"] == "bounced", "zombie flipped to bounced (got %r)" % z["status"])
    check(z.get("gate_report") == [sessions.ZOMBIE_NOTE],
          "visible note on the card (gate_report)")
    check(z["updated"] != "2026-07-28 22:00:00", "updated timestamp refreshed")
    check(db.track_get("t-live")["status"] == "running",
          "track with a live session left running")
    check(db.track_get("t-idle")["status"] == "needs_you",
          "non-running track untouched")

    with open(os.path.join(SANDBOX, "t-zombie", "actions.jsonl"), encoding="utf-8") as f:
        notes = [json.loads(l) for l in f if l.strip()]
    check(any(sessions.ZOMBIE_NOTE in (n.get("detail") or "") for n in notes),
          "restart note in the flight recorder")

    with open(events.EV, encoding="utf-8") as f:
        evs = [json.loads(l) for l in f if l.strip()]
    check(any(e["kind"] == "bounce" and e["track"] == "t-zombie"
              and e.get("reason") == "daemon_restart" for e in evs),
          "bounce event emitted with reason=daemon_restart")

    check(sessions.sweep_zombies() == [], "second sweep is a no-op (idempotent)")

    # break-it: recordings dir wiped between restarts - the audit note can't be
    # written, but the card must STILL get unstuck (audit is best-effort here).
    broken = _track("t-norundir", "running")
    broken["run_dir"] = os.path.join(SANDBOX, "does-not-exist", "nope")
    db.track_put(broken)
    swept2 = sessions.sweep_zombies()
    check(swept2 == ["t-norundir"], "zombie with a missing run_dir still swept")
    check(db.track_get("t-norundir")["status"] == "bounced",
          "missing-run_dir zombie bounced, sweep didn't crash")
    drivers._sessions.pop("t-live", None)


def test_escalation():
    """A card that keeps taking the daemon down with it - not just failing its
    own turn - must stop being told to blindly retry once the pattern repeats.
    consecutive_bounces is derived from the event trail (no stored counter),
    mirroring consecutive_gate_fails' contract."""
    tid = "t-repeat-crash"
    for i in range(sessions._BOUNCE_ESCALATE_AT):
        db.track_put(_track(tid, "running"))
        swept = sessions.sweep_zombies()
        check(tid in swept, "sweep %d catches the re-crashed card" % (i + 1))
        z = db.track_get(tid)
        note = (z.get("gate_report") or [""])[0]
        if i + 1 < sessions._BOUNCE_ESCALATE_AT:
            check(note == sessions.ZOMBIE_NOTE,
                  "bounce %d/%d still the routine note" % (i + 1, sessions._BOUNCE_ESCALATE_AT))
        else:
            check(str(i + 1) in note and "fork" in note.lower(),
                  "bounce %d/%d escalates with a fork suggestion, not a blind retry"
                  % (i + 1, sessions._BOUNCE_ESCALATE_AT))
    check(events.consecutive_bounces(tid) == sessions._BOUNCE_ESCALATE_AT,
          "consecutive_bounces counts the run")
    # a real completed turn resets the streak (mirrors consecutive_gate_fails)
    events.emit("turn", tid, cost=0.01, usage={}, models=[])
    check(events.consecutive_bounces(tid) == 0, "a completed turn resets the streak")


if __name__ == "__main__":
    test_sweep()
    test_escalation()
    print()
    if _fails:
        print("FAILED: %d check(s)" % len(_fails))
        sys.exit(1)
    print("ALL GREEN - zombie sweep holds its contract")
