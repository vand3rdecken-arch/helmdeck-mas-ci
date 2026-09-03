# -*- coding: utf-8 -*-
"""Pins the two SERVER-side halves of the archive bug (owner report 2026-08-27,
card 20260827-224828-machine: "active card shows up under the Archive tab").

1. UNARCHIVE HAS A ROUTE. archive_track has always taken on=True/False and the
   HTTP route has always read body.on, but every caller hardcoded True: the
   chat action archived only, and the app sent no body at all. copilot's board
   snapshot even tells the owner a card is " ARCHIVED" so he can ask for it
   back - and nothing could answer that. {"type":"archive","on":false} is now
   that answer (stringy "false" from the model counts too).

2. A ROLL-UP MAY NOT ARCHIVE A LIVE CARD. _CONSOLIDATE_ASK tells the PM to
   "Leave working/review/done cards alone", but apply_consolidation archived
   whatever ids came back. One slipped card is then invisible: hidden from
   every board view but the Archive scope, and never worked again (blockers
   skips archived cards). The prompt's rule is enforced in code now, and what
   it refused is REPORTED, not silently dropped.

Self-sandboxing: sessions/auth are stubbed in memory - no DB, no repo, no
board.

Run: py -3.12 ops/tests/test_archive_roundtrip.py
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from cells.copilot.chat import copilot_actions
from cells.engineer.cards import sessions
from cells.copilot.planning import pm
from spine.auth import auth

FAILED = []


def check(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        FAILED.append(what)


def _card(tid, lane="backlog", archived=False):
    return {"id": tid, "branch": "b-" + tid, "task": "task " + tid,
            "lane": lane, "status": "needs_you", "repo": "/fake/repo",
            "archived": archived}


def test_chat_can_unarchive():
    """{"type":"archive","on":false} must reach archive_track(on=False)."""
    calls = []
    board = [_card("20260827-224828-machine", lane="working", archived=True)]
    real = (sessions.list_tracks, sessions.archive_track, auth.chat_admin_roles)
    sessions.list_tracks = lambda: [dict(t) for t in board]
    sessions.archive_track = lambda tid, on=True, actor="owner": calls.append((tid, on))
    auth.chat_admin_roles = lambda: ["owner"]
    try:
        out = copilot_actions._run_action(
            {"type": "archive", "card": "224828", "on": False}, "owner", role="owner")
        check(calls == [("20260827-224828-machine", False)],
              "on:false unarchives (got %r)" % (calls,))
        check("unarchived" in out, "the answer says unarchived (got %r)" % out)

        # a model that answers with the STRING "false" must not archive again
        calls.clear()
        copilot_actions._run_action(
            {"type": "archive", "card": "224828", "on": "false"}, "owner", role="owner")
        check(calls == [("20260827-224828-machine", False)],
              'stringy "false" counts as off (got %r)' % (calls,))

        # default is still archive - the old callers keep working
        calls.clear()
        out = copilot_actions._run_action(
            {"type": "archive", "card": "224828"}, "owner", role="owner")
        check(calls == [("20260827-224828-machine", True)],
              "no `on` still archives (got %r)" % (calls,))
        check("unarchived" not in out, "the answer says archived (got %r)" % out)
    finally:
        sessions.list_tracks, sessions.archive_track, auth.chat_admin_roles = real


def test_consolidation_leaves_live_cards_alone():
    """A stream roll-up may only archive BACKLOG members."""
    board = [_card("t-backlog", lane="backlog"),
             _card("t-working", lane="working"),      # someone is on this one
             _card("t-review", lane="review"),
             _card("t-done", lane="done"),
             _card("t-already", lane="backlog", archived=True)]
    archived = []
    real = (sessions.list_tracks, sessions.new_track, sessions.archive_track)
    sessions.list_tracks = lambda: [dict(t) for t in board]
    sessions.new_track = lambda repo, branch, task, **kw: {"id": "t-stream", "task": task}
    sessions.archive_track = lambda tid, on=True, actor="owner": archived.append(tid)
    try:
        # the PM proposal names ALL of them - the code, not the prompt, decides
        res = pm.apply_consolidation([{"repo": "/fake/repo", "streams": [
            {"name": "backend", "title": "Backend-Stream",
             "members": ["t-backlog", "t-working", "t-review", "t-done",
                         "t-already", "t-does-not-exist"]}]}])
        check(archived == ["t-backlog"],
              "only the backlog member is archived (got %r)" % (archived,))
        check(sorted(res["refused"]) == ["t-already", "t-done", "t-review", "t-working"],
              "the rest is REPORTED, not silently dropped (got %r)" % (res["refused"],))
        check(len(res["created"]) == 1, "the stream card is still created")

        # a stream whose members are ALL live must create nothing at all -
        # an empty stream card would be pure noise on the board.
        archived.clear()
        res = pm.apply_consolidation([{"repo": "/fake/repo", "streams": [
            {"name": "ux", "title": "UX-Stream", "members": ["t-working", "t-review"]}]}])
        check(archived == [] and res["created"] == [],
              "an all-live stream creates nothing (got %r / %r)" % (archived, res["created"]))
        check(sorted(res["refused"]) == ["t-review", "t-working"],
              "and still reports what it refused (got %r)" % (res["refused"],))
    finally:
        sessions.list_tracks, sessions.new_track, sessions.archive_track = real


print("1. chat can bring a card back out of the archive")
test_chat_can_unarchive()
print("2. a stream roll-up never archives a live card")
test_consolidation_leaves_live_cards_alone()

if FAILED:
    print("\nFAILED (%d): %s" % (len(FAILED), "; ".join(FAILED)))
    sys.exit(1)
print("\nall archive round-trip checks passed")
