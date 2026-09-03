# -*- coding: utf-8 -*-
"""Pins the fast_track-toggle-on ship trigger (fixed 2026-08-15).

Live bug: a card finished a turn, THEN the owner flipped fast_track on and
asked to deploy. `_maybe_fast_track_ship` only ran from the turn-end path
(`_run_turn`), so toggling the flag on an already-finished, undeployed turn
did nothing until the NEXT turn completed - the card just sat there and the
worker (unaware fast-track exists) told the owner to use Review/accept
instead. `update_track` now calls `_maybe_fast_track_ship` itself when
`fast_track` is turned on (False/absent -> True), so enabling it ships
immediately if there's a finished turn with something to deploy.

Self-sandboxing: fake DB, patched settings/emit, a SyncThread stand-in that
runs `_ship` inline, and stubbed git/gate/merge helpers - nothing touches a
real repo, gate, or the live board.

Run: py -3.12 ops/tests/test_fasttrack_toggle.py
"""
import os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from spine.storage import events
from cells.engineer.cards import sessions
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
    import threading as _real
    Lock = _real.Lock


def _card(tid, **over):
    # session_id is set: the pinned scenario is a card with a FINISHED turn
    # (which always has a session) - update_track routes the toggle-on ship
    # by it since the no-worktree fast-track split (a session-less card has
    # nothing to ship and gets routed onto the live-tree rails at dispatch).
    t = {"id": tid, "task": "task " + tid, "lane": "working", "status": "needs_you",
         "fast_track": False, "machine": False, "question": None,
         "session_id": "sess-" + tid,
         "worktree": "/fake/wt", "repo": "/fake/repo", "branch": "card/" + tid,
         "priority": "medium", "created": "", "archived": None}
    t.update(over)
    return t


def main():
    (real_db, real_emit, real_settings, real_threading, real_isdir,
     real_git_try, real_current_branch, real_autocommit, real_gate,
     real_merge, real_hook) = (
        trackstore._db, events.emit, events.settings, sessions._threading,
        os.path.isdir, sessions._git_try, sessions._current_branch,
        sessions._autocommit, sessions._gate, sessions._merge_to_main,
        sessions._repo_hook)
    tmp = tempfile.mkdtemp(prefix="helmdeck-test-")
    try:
        fake = FakeDB()
        run_dir = os.path.join(tmp, "run")
        os.makedirs(run_dir)
        fake.track_put(_card("t-ft", run_dir=run_dir))
        trackstore._db = fake
        events.emit = lambda *a, **k: None
        events.settings = lambda: {"policy": {}, "capacity": {}}
        sessions._threading = FakeThreading
        os.path.isdir = lambda p: True   # fake worktree "exists"
        sessions._git_try = lambda repo, *args: (
            (0, "M file.txt\n", "") if args and args[0] == "status" else (1, "", ""))
        sessions._current_branch = lambda repo: "main"
        shipped = []
        sessions._autocommit = lambda t: "ok"
        sessions._gate = lambda t: (True, [])
        sessions._merge_to_main = lambda t: shipped.append(t["id"]) or (True, "merged", "")
        sessions._repo_hook = lambda t, kind: True

        # -- toggling fast_track ON with a finished/undeployed turn ships now,
        #    not on some future turn ---------------------------------------
        got = sessions.update_track("t-ft", {"fast_track": True}, actor="owner")
        assert got["fast_track"] is True, "flag not persisted: %r" % got
        assert shipped == ["t-ft"], \
            "toggling fast_track on did not trigger an immediate ship: %r" % shipped
        print("PASS update_track(fast_track=True): immediate ship fired for a "
              "card with a finished, undeployed turn")

        # -- toggling it back OFF must NOT ship again -----------------------
        shipped.clear()
        sessions.update_track("t-ft", {"fast_track": False}, actor="owner")
        assert shipped == [], "turning fast_track OFF must not trigger a ship: %r" % shipped
        print("PASS update_track(fast_track=False): no ship on disable")

        # -- editing an unrelated field while fast_track is already on must
        #    NOT re-ship on every edit ---------------------------------------
        fake.track_put(_card("t-ft2", run_dir=run_dir, fast_track=True))
        shipped.clear()
        sessions.update_track("t-ft2", {"priority": "high"}, actor="owner")
        assert shipped == [], \
            "editing an unrelated field re-triggered a ship: %r" % shipped
        print("PASS update_track(unrelated field, fast_track already on): no re-ship")

        print("ALL PASS")
    finally:
        (trackstore._db, events.emit, events.settings, sessions._threading,
         os.path.isdir, sessions._git_try, sessions._current_branch,
         sessions._autocommit, sessions._gate, sessions._merge_to_main,
         sessions._repo_hook) = (
            real_db, real_emit, real_settings, real_threading, real_isdir,
            real_git_try, real_current_branch, real_autocommit, real_gate,
            real_merge, real_hook)


if __name__ == "__main__":
    main()
