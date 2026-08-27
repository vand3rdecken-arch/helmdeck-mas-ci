# -*- coding: utf-8 -*-
"""Dispatch failure must be visible (found live 2026-07-28: a card whose repo
was not a git repository dispatched into a silently-dying background thread and
fell back to backlog with no trace).

Self-sandboxing: runs against a temp directory and an in-memory fake DB, and
patches events.emit so nothing touches the real append-only event log.

Run: py -3.12 ops/tests/test_dispatch_visibility.py
"""
import os, shutil, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from cells.engineer import sessions
from spine.storage import events
from spine.storage import trackstore


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


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-test-")
    real_db, real_emit = trackstore._db, events.emit
    try:
        nongit = os.path.join(tmp, "not-a-repo")
        run_dir = os.path.join(tmp, "run")
        os.makedirs(nongit); os.makedirs(run_dir)

        fake = FakeDB()
        trackstore._db = fake
        emitted = []
        events.emit = lambda kind, track, **f: emitted.append(
            {"kind": kind, "track": track, **f})

        # -- is_git_repo: the /tracks/new intake check ---------------------
        assert not sessions.is_git_repo(nongit), "plain folder accepted as repo"
        assert not sessions.is_git_repo(os.path.join(tmp, "missing")), \
            "missing path accepted as repo"
        assert not sessions.is_git_repo(""), "empty path accepted as repo"
        this_repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        assert sessions.is_git_repo(this_repo), \
            "real git repo rejected: " + this_repo
        print("PASS is_git_repo: rejects non-repo paths, accepts a real repo")

        # -- dispatching a card at a non-git folder must mark the card -----
        t = {"id": "t-test", "repo": nongit, "branch": "b-test", "worktree": "",
             "task": "do a thing", "client": "", "session_id": None,
             "perm": "acceptEdits", "lane": "backlog", "status": "queued",
             "turns": 0, "run_dir": run_dir, "last_reply": "", "value": 50.0,
             "driver": "claude", "priority": "medium", "due": "", "rank": None,
             "model": "", "attachments": [], "ai_cost": 0.0, "tokens_in": 0,
             "tokens_out": 0, "models": [], "created": "", "updated": ""}
        fake.track_put(t)

        raised = False
        try:
            sessions._start("t-test")
        except Exception:
            raised = True
        assert raised, "_start swallowed the failure instead of re-raising"

        cur = fake.track_get("t-test")
        assert cur["status"] == "bounced", \
            "card not marked bounced, status=%r" % cur["status"]
        assert "DISPATCH FAILED" in cur["last_reply"], \
            "error not written to last_reply: %r" % cur["last_reply"][:120]
        assert any(e["kind"] == "error" and e["track"] == "t-test"
                   and e.get("where") == "dispatch" for e in emitted), \
            "no dispatch-error event emitted: %r" % emitted
        with open(os.path.join(run_dir, "actions.jsonl"), encoding="utf-8") as f:
            assert "DISPATCH FAILED" in f.read(), \
                "failure missing from the flight recorder"
        print("PASS dispatch failure: status=bounced, error in last_reply, "
              "event emitted, actionlog noted")
        print("ALL PASS")
    finally:
        trackstore._db = real_db
        events.emit = real_emit
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
