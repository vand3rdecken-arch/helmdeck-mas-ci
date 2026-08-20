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


def test_gating_pipeline():
    """status='gating' is a live gate/merge pipeline, not a stuck turn. The old
    reap bound here was a duration GUESS ("a real gate runs ~2min") and the day
    the suite outgrew it (2026-08-20, ~5min) the reconciler bounced every LIVE
    gate at ~120s with a phantom 'daemon restarted' note while the real gate
    finished minutes later. Liveness must be an in-process OBSERVATION
    (lanemachine.lane_active, drivers.turn_active's pattern): a registered
    pipeline is never reaped no matter how long it runs; an UNregistered gating
    card (daemon died mid-gate / pipeline thread crashed) still is - with the
    gating-specific note, since there was no instruction to resend."""
    from daemon.cells.engineer import lanemachine

    tid = "t-gate-live"
    g = _track(tid, "gating")
    g["gate_report"] = ["gate FAILED:\nold punch list"]   # prior substance must survive
    db.track_put(g)
    # the empty run_dir reads as VERY idle - far past the old 120s bound, so
    # pre-fix this sweep reaped the live gate; only the observation saves it
    lanemachine._LANE_LIVE[tid] = 1
    try:
        swept = sessions.sweep_zombies(min_idle_s=45)
        check(tid not in swept, "LIVE pipeline never reaped, however long the suite runs")
        check(db.track_get(tid)["status"] == "gating",
              "card stays 'gating' while its pipeline is verifiably alive")
    finally:
        lanemachine._LANE_LIVE.pop(tid, None)

    swept = sessions.sweep_zombies(min_idle_s=45)
    check(tid in swept, "unregistered gating card (pipeline died) still reaped")
    z = db.track_get(tid)
    check(z["status"] == "bounced", "dead-pipeline card bounced (got %r)" % z["status"])
    gr = z.get("gate_report") or []
    check(gr and gr[0] == sessions.GATE_CUT_NOTE,
          "gating cut gets the gate note, not 'resend the last instruction'")
    check("gate FAILED:\nold punch list" in gr,
          "prior gate report preserved under the note")


def test_move_lane_registration():
    """move_lane registers the pipeline BEFORE its body runs (so no observer can
    see 'gating' unregistered), releases it on every exit, and counts DEPTH -
    park_and_retry_merge re-enters move_lane('review') from inside a 'done'
    pipeline and the outer registration must survive the inner unwind."""
    from daemon.cells.engineer import lanemachine

    tid = "t-lane-reg"
    calls = []
    real = lanemachine._move_lane

    def _fake(t_id, lane, actor="owner", _autopark=True):
        calls.append((lane, lanemachine.lane_active(t_id)))
        if _autopark:   # re-enter once - the park_and_retry_merge shape
            lanemachine.move_lane(t_id, "review", actor=actor, _autopark=False)
            calls.append(("after-inner", lanemachine.lane_active(t_id)))
        return {"id": t_id}

    lanemachine._move_lane = _fake
    try:
        lanemachine.move_lane(tid, "done")
    finally:
        lanemachine._move_lane = real
    check(calls == [("done", True), ("review", True), ("after-inner", True)],
          "pipeline observable inside the body, incl. across re-entry (got %r)" % calls)
    check(not lanemachine.lane_active(tid), "registration released once the move returns")

    # break-it: the body raising must still release the registration
    def _boom(t_id, lane, actor="owner", _autopark=True):
        raise RuntimeError("gate blew up")

    lanemachine._move_lane = _boom
    try:
        try:
            lanemachine.move_lane(tid, "done")
            check(False, "raising body propagated")
        except RuntimeError:
            check(True, "raising body propagated")
    finally:
        lanemachine._move_lane = real
    check(not lanemachine.lane_active(tid),
          "registration released even when the pipeline raises")


if __name__ == "__main__":
    test_sweep()
    test_escalation()
    test_gating_pipeline()
    test_move_lane_registration()
    print()
    if _fails:
        print("FAILED: %d check(s)" % len(_fails))
        sys.exit(1)
    print("ALL GREEN - zombie sweep holds its contract")
