# -*- coding: utf-8 -*-
"""Nothing may SILENTLY stop an opted-in card from dispatching.

Two invariants, both from the same live investigation (2026-08-04):

1. A card's `mode` value must never block card dispatch (found live 2026-08-04:
a PM plan read the launch cards' mode='auto' - the auto/assisted completion
STATISTIC events._completion_mode writes on accept - as an execution mode,
concluded policy.auto_dispatch_modes ["do","prepare"] was blocking them, and
filed an alignment card. It wasn't: auto_dispatch_modes gates process STEPS
(processes.sync); card-level dispatch only excludes the needs-a-person modes
human/teach/cowork. The launch cards had in fact already dispatched.)

2. The autopilot's one-shot stamps must not survive a re-queue. Looking for a
REAL version of (1) turned one up: `autopilot_dispatched` is written once and
nothing ever cleared it, so an autopilot card moved back to Backlog kept
autopilot=true and never dispatched again - it sat in Backlog looking like a
normal queued card, no bounce, no event, no escalation. Exactly the silent
waiting the autopilot exists to remove. move_lane now clears the stamps.

This pins both invariants on the card-dispatch paths so they cannot regress.

Self-sandboxing: fake DB, patched settings/emit, synchronous fake threads -
nothing touches the real board or event log, nothing really dispatches.

Run: py -3.12 ops/tests/test_mode_dispatch.py
"""
import os, shutil, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from spine.storage import events
from cells.pm import pm
from cells.process import processes
from cells.engineer import sessions
from spine.storage import trackstore


class FakeDB:
    def __init__(self):
        self.tracks = {}
    def tracks_all(self):
        return [dict(t) for t in self.tracks.values()]
    def tracks_replace(self, ts):
        self.tracks = {t["id"]: dict(t) for t in ts}
    def track_put(self, t):
        self.tracks[t["id"]] = dict(t)
    def track_get(self, tid):
        t = self.tracks.get(tid)
        return dict(t) if t else None


class SyncThread:
    """threading.Thread stand-in: runs the target inline on start()."""
    def __init__(self, target=None, args=(), daemon=None, **_kw):
        self._target, self._args = target, args
    def start(self):
        self._target(*self._args)


class FakeThreading:
    Thread = SyncThread


def _card(tid, **over):
    t = {"id": tid, "task": "task " + tid, "lane": "backlog", "status": "queued",
         "priority": "medium", "repo": "", "created": "", "archived": None}
    t.update(over)
    return t


def main():
    real_db, real_emit = trackstore._db, events.emit
    real_settings = events.settings
    real_threading, real_dispatch = processes.threading, processes._auto_dispatch
    tmp = tempfile.mkdtemp(prefix="helmdeck-test-")
    try:
        # -- pm._backlog: unset mode and the 'auto' completion stat dispatch;
        #    only the needs-a-person modes are held back for the human --------
        tracks = [_card("t-none"), _card("t-auto", mode="auto"),
                  _card("t-do", mode="do"), _card("t-human", mode="human"),
                  _card("t-teach", mode="teach"), _card("t-cowork", mode="cowork")]
        got = {t["id"] for t in pm._backlog(tracks, {"repos": []}, {"dispatched": []})}
        assert got == {"t-none", "t-auto", "t-do"}, \
            "wrong dispatch candidates: %r" % got
        print("PASS pm._backlog: mode None/'auto'/'do' dispatchable, "
              "human/teach/cowork excluded")

        # -- processes._autopilot on the exact live launch-card shape:
        #    backlog + autopilot=true + completion stat mode='auto' -----------
        fake = FakeDB()
        run_dir = os.path.join(tmp, "run")
        os.makedirs(run_dir)
        fake.track_put(_card("t-launch", autopilot=True, mode="auto",
                             run_dir=run_dir))
        fake.track_put(_card("t-busy", lane="working", status="running"))
        trackstore._db = fake
        emitted, dispatched = [], []
        events.emit = lambda kind, track, **f: emitted.append(
            {"kind": kind, "track": track, **f})
        events.settings = lambda: {
            "policy": {"auto_dispatch_modes": ["do", "prepare"],
                       "auto_accept_green": False},
            "capacity": {"wip_limit": 3}}
        processes.threading = FakeThreading
        processes._auto_dispatch = dispatched.append

        processes._autopilot()

        assert dispatched == ["t-launch"], \
            "autopilot did not dispatch the launch card: %r" % dispatched
        assert fake.track_get("t-launch")["autopilot_dispatched"] is True, \
            "dispatch not stamped on the card"
        assert any(e.get("action") == "autopilot_dispatch"
                   and e.get("card") == "t-launch" for e in emitted), \
            "no autopilot_dispatch event emitted: %r" % emitted
        print("PASS processes._autopilot: launch card (autopilot, mode='auto') "
              "dispatches, is stamped, event emitted")

        # -- a re-queued autopilot card dispatches AGAIN --------------------
        # drive the real board move (sessions.move_lane), not a hand-built
        # card, so the reset is pinned where the lane actually changes.
        moved = sessions.move_lane("t-launch", "backlog", actor="owner")
        for k in ("autopilot_dispatched", "autopilot_accepted",
                  "autopilot_alerted", "autopilot_ts", "priority_dispatched"):
            assert k not in moved, "%s survived the move back to Backlog" % k
        assert moved["lane"] == "backlog" and moved["status"] == "queued", \
            "re-queue did not reset lane/status: %r" % moved
        assert moved.get("autopilot") is True, "re-queue dropped the opt-in"

        dispatched.clear()
        processes._autopilot()
        assert dispatched == ["t-launch"], \
            "re-queued autopilot card did not dispatch again: %r" % dispatched
        print("PASS move_lane->backlog: autopilot stamps cleared, card "
              "dispatches again (opt-in preserved)")

        # -- _priority_dispatch must not re-dispatch a card forever ---------
        # A failed dispatch leaves the card in backlog (status=bounced, lane
        # untouched), and the chain poller runs every 20s - so an unguarded
        # pass hammered the same broken card three times a minute forever.
        events.settings = lambda: {"policy": {"auto_dispatch_priority": "high"},
                                   "capacity": {"wip_limit": 3}}
        fake.track_put(_card("t-broken", priority="high", run_dir=run_dir,
                             status="bounced",
                             last_reply="DISPATCH FAILED: not a git repository"))
        dispatched.clear()
        for _tick in range(5):
            processes._priority_dispatch()
        assert dispatched == ["t-broken"], \
            "broken card re-dispatched every tick: %r" % dispatched
        assert fake.track_get("t-broken")["priority_dispatched"] is True, \
            "priority dispatch not stamped on the card"
        print("PASS _priority_dispatch: one attempt over 5 poller ticks, "
              "not one per tick")

        # ...and Backlog stays the retry handle for it, like every other stamp
        dispatched.clear()
        sessions.move_lane("t-broken", "backlog", actor="owner")
        processes._priority_dispatch()
        assert dispatched == ["t-broken"], \
            "re-queued card was not retried by priority dispatch: %r" % dispatched
        print("PASS move_lane->backlog: priority stamp cleared, card retried")

        # -- the CHAIN's own step stamp must clear on a re-queue too ---------
        # It lives in processes.json, not on the card, so move_lane cannot
        # reach it with the loop above - the card came back clean while the
        # step still said "already dispatched" and never ran again.
        events.settings = lambda: {
            "policy": {"auto_dispatch_modes": ["do", "prepare"],
                       "auto_accept_green": False},
            "capacity": {"wip_limit": 3}}
        fake.track_put(_card("t-chain", run_dir=run_dir))
        proc = [{"id": "p1", "status": "running",
                 "steps": [{"title": "step one", "mode": "do", "track": "t-chain"}]}]
        real_pload, real_psave = processes._load, processes._save
        processes._load, processes._save = (lambda: proc), (lambda ps: None)
        try:
            dispatched.clear()
            processes.sync()
            assert dispatched == ["t-chain"], \
                "chain step did not dispatch: %r" % dispatched
            assert proc[0]["steps"][0].get("auto_dispatched") is True, \
                "chain dispatch not stamped on the step"

            # the step's card ran, then the owner re-queues it to run again
            fake.track_put({**fake.track_get("t-chain"),
                            "lane": "working", "status": "running"})
            sessions.move_lane("t-chain", "backlog", actor="owner")
            assert "auto_dispatched" not in proc[0]["steps"][0], \
                "step stamp survived the move back to Backlog"

            dispatched.clear()
            processes.sync()
            assert dispatched == ["t-chain"], \
                "re-queued chain step did not dispatch again: %r" % dispatched
            print("PASS move_lane->backlog: chain step stamp cleared, step "
                  "dispatches again")
        finally:
            processes._load, processes._save = real_pload, real_psave
        print("ALL PASS")
    finally:
        trackstore._db, events.emit = real_db, real_emit
        events.settings = real_settings
        processes.threading, processes._auto_dispatch = real_threading, real_dispatch
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
