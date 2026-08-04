# -*- coding: utf-8 -*-
"""A card's `mode` value must never block card dispatch (found live 2026-08-04:
a PM plan read the launch cards' mode='auto' - the auto/assisted completion
STATISTIC events._completion_mode writes on accept - as an execution mode,
concluded policy.auto_dispatch_modes ["do","prepare"] was blocking them, and
filed an alignment card. It wasn't: auto_dispatch_modes gates process STEPS
(processes.sync); card-level dispatch only excludes the needs-a-person modes
human/teach/cowork. The launch cards had in fact already dispatched.)

This pins that invariant on both card-dispatch paths so it cannot silently
regress into a real version of that misdiagnosis.

Self-sandboxing: fake DB, patched settings/emit, synchronous fake threads -
nothing touches the real board or event log, nothing really dispatches.

Run: py -3.12 daemon/test_mode_dispatch.py
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import events, pm, processes, sessions


class FakeDB:
    def __init__(self):
        self.tracks = {}
    def tracks_all(self):
        return [dict(t) for t in self.tracks.values()]
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
    real_db, real_emit = sessions._db, events.emit
    real_settings = events.settings
    real_threading, real_dispatch = processes.threading, processes._auto_dispatch
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
        fake.track_put(_card("t-launch", autopilot=True, mode="auto"))
        fake.track_put(_card("t-busy", lane="working", status="running"))
        sessions._db = fake
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
        print("ALL PASS")
    finally:
        sessions._db, events.emit = real_db, real_emit
        events.settings = real_settings
        processes.threading, processes._auto_dispatch = real_threading, real_dispatch


if __name__ == "__main__":
    main()
