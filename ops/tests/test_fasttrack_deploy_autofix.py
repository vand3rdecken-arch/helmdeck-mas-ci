# -*- coding: utf-8 -*-
"""Fast-track lands, Henry ships (owner decree 2026-09-01, d66084f).

This file used to pin the auto-fix loop that ran the deploy hook INSIDE the
fast-track turn end and steered the worker with the build error, capped by
_DEPLOY_FIX_CAP. That loop is gone by decree: a finished fast-track turn is
gated and merged in the background, the card stays where it is, and the
DEPLOY is a ship-decision escalation to Henry - never automatic. The old
assertions (deploy_hook persisted, auto-fix steer, streak cap) pinned code
that no longer exists and failed on every run since.

What this pins now:
  1. gate green + merge ok -> request_ship_decision(card, "fast-track") is
     called exactly once; NO deploy hook runs; NO steer is issued
  2. gate red -> nothing merged, nothing requested, the reason is in the
     actionlog
  3. a chat-only turn (clean tree, nothing ahead) -> no gate, no merge

Sandboxed: FakeDB for the track store, sandboxed db for the actionlog rows,
git/gate/merge/threads stubbed - nothing touches a real repo.

Run: py -3.12 ops/tests/test_fasttrack_deploy_autofix.py
"""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from spine.storage import db                     # noqa: E402
db.DBPATH = os.path.join(tempfile.mkdtemp(prefix="hd-fasttrack-"), "test.db")
db.init()
from spine.storage import trackstore, events     # noqa: E402
from cells.engineer.cards import sessions        # noqa: E402
from spine.ops.actionlog import ActionLog, read_timeline   # noqa: E402


class FakeDB:
    def __init__(self):
        self.rows = {}

    def tracks_all(self):
        return [dict(v) for v in self.rows.values()]

    def track_get(self, tid):
        return dict(self.rows[tid]) if tid in self.rows else None

    def track_put(self, t):
        self.rows[t["id"]] = dict(t)

    def tracks_replace(self, ts):
        self.rows = {t["id"]: dict(t) for t in ts}

    def track_delete(self, tid):
        self.rows.pop(tid, None)


class FakeThreading:
    class Thread:
        def __init__(self, target=None, daemon=None, name=None, args=()):
            self._t, self._a = target, args

        def start(self):
            self._t(*self._a)      # run inline, synchronously


def _card(tid, run_dir, **over):
    t = {"id": tid, "repo": "C:/repo", "branch": "card/" + tid, "worktree": "C:/wt/" + tid,
         "task": "x", "lane": "working", "status": "needs_you", "fast_track": True,
         "run_dir": run_dir, "session_id": "s", "turns": 1}
    t.update(over)
    return t


def main():
    tmp = tempfile.mkdtemp(prefix="hd-fasttrack-run-")
    saved = (trackstore._db, events.emit, events.settings, sessions._threading, os.path.isdir,
             sessions._git_try, sessions._current_branch, sessions._autocommit, sessions._gate,
             sessions._merge_to_main, sessions.request_ship_decision, sessions.steer)
    fails = []

    def ok(cond, msg):
        print(("  ok   " if cond else "  FAIL ") + msg)
        if not cond:
            fails.append(msg)
    try:
        fake = FakeDB()
        trackstore._db = fake
        emitted = []
        events.emit = lambda kind, track, **f: emitted.append({"kind": kind, "track": track, **f})
        events.settings = lambda: {"policy": {}, "capacity": {}, "repo_hooks": {}}
        sessions._threading = FakeThreading
        os.path.isdir = lambda p: True
        sessions._git_try = lambda repo, *args: (
            (0, "M file.txt\n", "") if args and args[0] == "status" else (1, "", ""))
        sessions._current_branch = lambda repo: "main"
        sessions._autocommit = lambda t: "ok"
        sessions._gate = lambda t: (True, [])
        sessions._merge_to_main = lambda t: (True, "merged", "")
        asked, steered = [], []
        sessions.request_ship_decision = lambda t, source: asked.append((t["id"], source))
        sessions.steer = lambda tid, instr, **kw: steered.append(tid)

        print("1. green gate + merge -> ONE ship decision for Henry, no hook, no steer")
        rd = os.path.join(tmp, "t-ok"); os.makedirs(rd)
        fake.track_put(_card("t-ok", rd))
        sessions._maybe_fast_track_ship(fake.track_get("t-ok"), ActionLog(rd))
        ok(asked == [("t-ok", "fast-track")], "request_ship_decision called once with source fast-track (%r)" % asked)
        ok(steered == [], "no auto-fix steer exists any more")
        ok(any(e["kind"] == "merge" and e.get("ok") for e in emitted), "the merge was recorded as an event")
        ok(fake.track_get("t-ok")["lane"] == "working" and fake.track_get("t-ok")["status"] == "needs_you",
           "the card stays exactly where it was")
        notes = [r.get("detail") or "" for r in read_timeline(rd)]
        ok(any("Ship-Entscheidung liegt bei" in n for n in notes), "the actionlog says Henry decides the ship")

        print("2. red gate -> nothing merged, nothing requested, reason logged")
        asked.clear(); emitted.clear()
        sessions._gate = lambda t: (False, ["lint: 3 errors"])
        rd2 = os.path.join(tmp, "t-red"); os.makedirs(rd2)
        fake.track_put(_card("t-red", rd2))
        sessions._maybe_fast_track_ship(fake.track_get("t-red"), ActionLog(rd2))
        ok(asked == [], "no ship decision on a red gate")
        ok(not any(e["kind"] == "merge" for e in emitted), "no merge attempted")
        ok(any("lint: 3 errors" in (r.get("detail") or "") for r in read_timeline(rd2)),
           "the gate reason is in the actionlog")

        print("3. chat-only turn -> no gate at all")
        sessions._gate = lambda t: (_ for _ in ()).throw(AssertionError("gate must not run"))
        sessions._git_try = lambda repo, *args: (0, "", "")      # clean tree, nothing ahead
        rd3 = os.path.join(tmp, "t-chat"); os.makedirs(rd3)
        fake.track_put(_card("t-chat", rd3))
        sessions._maybe_fast_track_ship(fake.track_get("t-chat"), ActionLog(rd3))
        ok(asked == [] and not read_timeline(rd3), "nothing happens for a chat-only turn")
    finally:
        (trackstore._db, events.emit, events.settings, sessions._threading, os.path.isdir,
         sessions._git_try, sessions._current_branch, sessions._autocommit, sessions._gate,
         sessions._merge_to_main, sessions.request_ship_decision, sessions.steer) = saved
    print()
    if fails:
        print("FAILED: %d" % len(fails))
        return 1
    print("fast-track: all pinned - PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
