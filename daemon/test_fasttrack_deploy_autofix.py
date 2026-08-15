# -*- coding: utf-8 -*-
"""Pins two fixes shipped together (2026-08-15) after a live incident: a
fast-track card's native APK build broke (Gradle task failure), merged to
main anyway (merge and deploy are separate steps), and just sat there with
a red "Deploy-Hook rot" note until the owner happened to notice.

1. `_repo_hook`'s result (`t["deploy_hook"]`) was NEVER PERSISTED for the
   fast-track path - `_ship()` called it but never wrote the result back to
   the DB (unlike move_lane's `_land()`, which does). So the earlier fix
   that made `_pending_context()` surface deploy_hook to the worker's next
   steer (2026-08-15, same day) was silently a no-op for every fast-track
   ship specifically - the field only ever lived in `_ship()`'s local `t`.

2. On a real failure, nothing acted on it - fast-track is supposed to be
   unattended, so leaving a broken main branch for the owner to spot isn't
   good enough. `_try_auto_fix_deploy` now feeds the worker the actual
   error and lets it try to fix it, bounded by `_DEPLOY_FIX_CAP` attempts
   in a row (mirrors the existing gate thrash-guard) so a persistently
   broken build doesn't burn turns forever unattended either.

Self-sandboxing: fake DB, patched settings/emit/threading, stubbed git/gate/
merge/hook, and `sessions.steer` itself replaced with a recorder - nothing
touches a real repo, gate, board, or spawns an actual worker turn.

Run: py -3.12 daemon/test_fasttrack_deploy_autofix.py
"""
import os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import events, sessions
from actionlog import ActionLog


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
    t = {"id": tid, "task": "task " + tid, "lane": "working", "status": "needs_you",
         "fast_track": True, "machine": False, "question": None,
         "worktree": "/fake/wt", "repo": "/fake/repo", "branch": "card/" + tid,
         "priority": "medium", "created": "", "archived": None}
    t.update(over)
    return t


def main():
    (real_db, real_emit, real_settings, real_threading, real_isdir,
     real_git_try, real_current_branch, real_autocommit, real_gate,
     real_merge, real_hook, real_steer) = (
        sessions._db, events.emit, events.settings, sessions._threading,
        os.path.isdir, sessions._git_try, sessions._current_branch,
        sessions._autocommit, sessions._gate, sessions._merge_to_main,
        sessions._repo_hook, sessions.steer)
    tmp = tempfile.mkdtemp(prefix="helmdeck-test-")
    try:
        fake = FakeDB()
        run_dir = os.path.join(tmp, "run")
        os.makedirs(run_dir)
        sessions._db = fake
        events.emit = lambda *a, **k: None
        events.settings = lambda: {"policy": {}, "capacity": {}}
        sessions._threading = FakeThreading
        os.path.isdir = lambda p: True
        sessions._git_try = lambda repo, *args: (
            (0, "M file.txt\n", "") if args and args[0] == "status" else (1, "", ""))
        sessions._current_branch = lambda repo: "main"
        sessions._autocommit = lambda t: "ok"
        sessions._gate = lambda t: (True, [])
        sessions._merge_to_main = lambda t: (True, "merged", "")
        steered = []
        sessions.steer = lambda tid, instr, **kw: steered.append(
            {"tid": tid, "instr": instr, **kw})

        # -- a FAILING hook: writes t["deploy_hook"], returns False ----------
        def _hook_fails(t, kind):
            t["deploy_hook"] = {"ok": False, "tail": "BUILD FAILED: Gradle task X"}
            return False
        sessions._repo_hook = _hook_fails

        fake.track_put(_card("t-fail", run_dir=run_dir))
        sessions._maybe_fast_track_ship(fake.track_get("t-fail"), ActionLog(run_dir))

        # -- 1: deploy_hook was actually PERSISTED to the DB, not just local --
        persisted = fake.track_get("t-fail")
        assert persisted.get("deploy_hook", {}).get("ok") is False, \
            "deploy_hook result was not persisted to the DB: %r" % persisted.get("deploy_hook")
        print("PASS: fast-track deploy_hook failure IS persisted to the DB "
              "(previously silently local-only)")

        # -- 2: a failure triggers an auto-fix steer with the real error -----
        assert len(steered) == 1, "expected exactly one auto-fix steer: %r" % steered
        s = steered[0]
        assert s["tid"] == "t-fail"
        assert "BUILD FAILED: Gradle task X" in s["instr"], \
            "auto-fix steer did not carry the actual hook error: %r" % s["instr"]
        assert s.get("source") == "fast-track-deploy-fix"
        assert fake.track_get("t-fail").get("deploy_fail_streak") == 1
        print("PASS: a deploy hook failure auto-steers the worker with the real error")

        # -- 3: the streak caps out - no infinite auto-retry ------------------
        steered.clear()
        t2 = _card("t-cap", run_dir=run_dir, deploy_fail_streak=sessions._DEPLOY_FIX_CAP)
        fake.track_put(t2)
        sessions._maybe_fast_track_ship(fake.track_get("t-cap"), ActionLog(run_dir))
        assert steered == [], \
            "auto-fix must stop retrying once the cap is exceeded: %r" % steered
        print("PASS: auto-fix stops retrying once _DEPLOY_FIX_CAP is exceeded "
              "(no infinite loop on a persistently broken build)")

        # -- 4: a SUCCESSFUL hook resets the streak ---------------------------
        sessions._repo_hook = lambda t, kind: True
        t3 = _card("t-ok", run_dir=run_dir, deploy_fail_streak=2)
        fake.track_put(t3)
        sessions._maybe_fast_track_ship(fake.track_get("t-ok"), ActionLog(run_dir))
        assert "deploy_fail_streak" not in fake.track_get("t-ok"), \
            "a successful deploy must reset the fail streak"
        print("PASS: a successful fast-track deploy resets the fail streak")

        print("ALL PASS")
    finally:
        (sessions._db, events.emit, events.settings, sessions._threading,
         os.path.isdir, sessions._git_try, sessions._current_branch,
         sessions._autocommit, sessions._gate, sessions._merge_to_main,
         sessions._repo_hook, sessions.steer) = (
            real_db, real_emit, real_settings, real_threading, real_isdir,
            real_git_try, real_current_branch, real_autocommit, real_gate,
            real_merge, real_hook, real_steer)


if __name__ == "__main__":
    main()
