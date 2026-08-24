# -*- coding: utf-8 -*-
"""Pins the fast_track-toggle-on CONVERSION for worktree-isolated cards
(added 2026-08-20).

Live bug: fast-track was supposed to be the no-gate escape hatch, but a card
that STARTED worktree-isolated kept the full gate+merge ship for life - so
the card carrying the gate's own daemon fix could never pass the gate the
buggy daemon ran (chicken-and-egg; the merge had to be done by hand).
`update_track` now converts an isolated card onto the live-tree rails when
fast_track flips on: idle-turn-only (raises mid-turn), autocommit (markers
refuse), accept-path merge WITHOUT a gate run, worktree reclaimed, card
repointed direct/live-tree, idle session dropped.

Self-sandboxing: fake DB, patched settings/emit, stubbed git/merge/reclaim/
driver helpers - nothing touches a real repo, gate, or the live board.

Run: py -3.12 daemon/test_fasttrack_convert.py
"""
import os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from spine.storage import events
from cells.engineer import sessions
from spine.storage import trackstore
from spine.agent import drivers
from spine.git import worktrees
from cells.engineer import lanemachine


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
    def __init__(self, target=None, args=(), daemon=None, **_kw):
        self._target, self._args = target, args
    def start(self):
        self._target(*self._args)


class FakeThreading:
    Thread = SyncThread
    import threading as _real
    Lock = _real.Lock


def _card(tid, run_dir, **over):
    t = {"id": tid, "task": "task " + tid, "lane": "working", "status": "needs_you",
         "fast_track": False, "machine": False, "direct": False, "question": None,
         "session_id": "sess-" + tid, "run_dir": run_dir,
         "worktree": "/fake/wt/" + tid, "repo": "/fake/repo", "branch": "card/" + tid,
         "priority": "medium", "created": "", "archived": None}
    t.update(over)
    return t


def main():
    saved = (trackstore._db, events.emit, events.settings, sessions._threading,
             os.path.isdir, sessions._autocommit, sessions._merge_to_main,
             sessions._repo_hook, drivers.turn_active, drivers.drop_session,
             worktrees.reclaim_worktree, lanemachine.dispatch_conflict_resolution)
    tmp = tempfile.mkdtemp(prefix="helmdeck-test-")
    try:
        fake = FakeDB()
        run_dir = os.path.join(tmp, "run")
        os.makedirs(run_dir)
        trackstore._db = fake
        events.emit = lambda *a, **k: None
        events.settings = lambda: {"policy": {}, "capacity": {}}
        sessions._threading = FakeThreading
        os.path.isdir = lambda p: True

        merged, reclaimed, dropped, deployed, resolved = [], [], [], [], []
        lanemachine.dispatch_conflict_resolution = (
            lambda tid, actor=None, background=True: resolved.append(tid) or "steered")
        sessions._autocommit = lambda t: True
        sessions._merge_to_main = lambda t: merged.append(t["id"]) or (True, "merged", "")
        sessions._repo_hook = lambda t, kind: deployed.append((t["id"], kind)) or True
        drivers.turn_active = lambda tid: False
        drivers.drop_session = lambda tid: dropped.append(tid)
        worktrees.reclaim_worktree = lambda t, log=None, force=False: reclaimed.append(t["id"]) or True

        # -- idle worktree card converts: branch merged (no gate), worktree
        #    reclaimed, repointed direct/live-tree, session dropped, deployed --
        fake.track_put(_card("t-conv", run_dir))
        got = sessions.update_track("t-conv", {"fast_track": True}, actor="owner")
        assert got["fast_track"] is True
        assert merged == ["t-conv"], "conversion did not merge the branch: %r" % merged
        assert reclaimed == ["t-conv"], "worktree not reclaimed: %r" % reclaimed
        assert got["direct"] is True and got["machine"] is True, \
            "card not repointed onto the live-tree rails: %r" % got
        assert got["worktree"] == got["repo"], "worktree not repointed to repo"
        assert dropped == ["t-conv"], "idle session not dropped: %r" % dropped
        assert ("t-conv", "deploy") in deployed, "merged commits not deployed: %r" % deployed
        print("PASS convert: idle worktree card lands branch + moves to live-tree rails")

        # -- mid-turn flip refuses loudly, nothing half-converted ------------
        merged.clear(); reclaimed.clear(); dropped.clear()
        fake.track_put(_card("t-busy", run_dir))
        drivers.turn_active = lambda tid: True
        try:
            sessions.update_track("t-busy", {"fast_track": True}, actor="owner")
            raise AssertionError("mid-turn fast-track flip must raise")
        except RuntimeError:
            pass
        t = fake.track_get("t-busy")
        assert not t["fast_track"] and not t["direct"] and not merged and not reclaimed, \
            "mid-turn refusal must leave the card untouched: %r" % t
        print("PASS convert: mid-turn flip raises, card untouched")
        drivers.turn_active = lambda tid: False

        # -- conflict markers: NOT converted yet, but the worker is AUTO-
        #    steered to resolve (chat must never dead-end) -------------------
        fake.track_put(_card("t-mark", run_dir))
        sessions._autocommit = lambda t: "markers"
        got = sessions.update_track("t-mark", {"fast_track": True}, actor="owner")
        assert got["fast_track"] is True and not got.get("direct") and not merged, \
            "markers must defer conversion, card stays isolated: %r" % got
        assert resolved == ["t-mark"], \
            "markers must auto-dispatch conflict resolution: %r" % resolved
        assert fake.track_get("t-mark").get("ft_resolve_tries") == 1
        print("PASS convert: markers -> worker auto-steered (try 1), card isolated")
        sessions._autocommit = lambda t: True

        # -- merge conflict: same self-healing, nothing reclaimed ------------
        resolved.clear()
        fake.track_put(_card("t-conf", run_dir))
        sessions._merge_to_main = lambda t: (False, "conflict", "app.py")
        got = sessions.update_track("t-conf", {"fast_track": True}, actor="owner")
        assert not got.get("direct") and not reclaimed and not dropped, \
            "merge conflict must leave the card isolated: %r" % got
        assert resolved == ["t-conf"], \
            "merge conflict must auto-dispatch resolution: %r" % resolved
        print("PASS convert: merge conflict -> worker auto-steered, worktree kept")

        # -- bounded: after 2 automatic tries it escalates, no third steer ---
        resolved.clear()
        fake.track_put(_card("t-cap", run_dir, ft_resolve_tries=2))
        sessions._autocommit = lambda t: "markers"
        sessions.update_track("t-cap", {"fast_track": True}, actor="owner")
        assert resolved == [], "3rd auto-resolve must NOT fire (RESOLVE ladder cap): %r" % resolved
        print("PASS convert: resolve ladder capped at 2, escalates to owner")
        sessions._autocommit = lambda t: True
        sessions._merge_to_main = lambda t: merged.append(t["id"]) or (True, "merged", "")

        # -- nothing-to-land card (already_merged) converts without a deploy --
        deployed.clear()
        fake.track_put(_card("t-clean", run_dir))
        sessions._merge_to_main = lambda t: (True, "already_merged", "")
        got = sessions.update_track("t-clean", {"fast_track": True}, actor="owner")
        assert got["direct"] is True and got["worktree"] == got["repo"], \
            "already-merged card must still convert: %r" % got
        assert not deployed, "no commits landed - deploy hook must not fire: %r" % deployed
        print("PASS convert: already-merged branch converts cleanly, no deploy")

        print("ALL PASS")
    finally:
        (trackstore._db, events.emit, events.settings, sessions._threading,
         os.path.isdir, sessions._autocommit, sessions._merge_to_main,
         sessions._repo_hook, drivers.turn_active, drivers.drop_session,
         worktrees.reclaim_worktree, lanemachine.dispatch_conflict_resolution) = saved


if __name__ == "__main__":
    main()
