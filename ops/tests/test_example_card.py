# -*- coding: utf-8 -*-
"""The onboarding example card (accounts-boards-prd phase 3).

One test per property PRD section 8's risk item actually names: `example:
true` must be inert everywhere - dispatcher, PM planning, economics, Henry's
snapshot - and visible to every role despite having no owning client. This is
NOT a re-test of auth_setup's HTTP plumbing (three lines calling already-
tested functions: auth.create_user, boards.ensure_default, dispatch.
seed_example_card) - it tests the flag's actual reach.

SANDBOXED: repoints daemon.paths.DAEMON_ROOT at a temp dir BEFORE importing
anything that resolves a path, same preamble as test_boards.py. Note
dispatch.seed_example_card() reads daemon.paths.REPO_ROOT (a separate name
bound at daemon.paths import time, not sandboxable the same way) - it always
names the REAL repo checkout on disk, which is fine because the card is never
dispatched into it (only read-only `git rev-parse` calls happen against it
while minting a branch NAME the card will never use).

Run:  py -3.12 ops/tests/test_example_card.py
"""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

_SANDBOX = tempfile.mkdtemp(prefix="hd-example-card-")
import daemon.paths
daemon.paths.DAEMON_ROOT = _SANDBOX

from spine.storage import db, events                            # noqa: E402
from spine.auth import auth                                     # noqa: E402

assert db.DBPATH.startswith(_SANDBOX), \
    "REFUSING TO RUN: db points at %s, not the sandbox" % db.DBPATH
assert auth.USERS.startswith(_SANDBOX), \
    "REFUSING TO RUN: users.json points at %s, not the sandbox" % auth.USERS

db.init()

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# The card this whole module exercises - minted once, like auth_setup mints it
# once at first-run.
from cells.engineer import dispatch                              # noqa: E402
CARD = dispatch.seed_example_card()


def test_shape():
    check(CARD.get("example") is True, "seed_example_card() stamps example=True")
    check(CARD.get("lane") == "backlog", "it is filed straight into backlog")
    check(CARD.get("billing") == "none" and CARD.get("value") == 0.0,
          "it carries no price - excluded from billing by construction, not "
          "merely by every reader remembering to skip it")


def test_never_dispatches():
    from cells.engineer import sessions
    for lane in ("working", "review", "done"):
        out = sessions.move_lane(CARD["id"], lane, actor="owner")
        check(bool(out.get("example_refused")),
              "move_lane(%r) is refused with a reason, not silently ignored" % lane)
        fresh = sessions.get_track(CARD["id"])
        check(fresh["lane"] == "backlog",
              "move_lane(%r) does not actually move the card" % lane)


def test_steer_never_dispatches_either():
    """steer() calls dispatch._start() DIRECTLY when a backlog card has no
    session yet - a second path into the same turn-spawning code that
    move_lane's refusal does not sit on, discovered because it runs a chat
    message in a background thread (routes_track_actions.tracks_steer_post),
    so a missed guard here would fail SILENTLY, not loudly."""
    from cells.engineer import sessions
    out = sessions.steer(CARD["id"], "hallo?", actor="owner")
    check(out.get("session_id") is None,
          "steering the example card never opens a session")
    fresh = sessions.get_track(CARD["id"])
    check(fresh["lane"] == "backlog" and fresh.get("session_id") is None,
          "the card is untouched after being steered")


def test_excluded_from_dispatcher():
    from cells.copilot import pm
    tracks = [CARD]
    todo = pm._backlog(tracks, pm._pm(), {"dispatched": []})
    check(CARD["id"] not in [t["id"] for t in todo],
          "pm._backlog() never offers the example card as a dispatch candidate")


def test_excluded_from_economics():
    m = events.metrics([CARD])
    ids = [c["id"] for c in m["cards"]]
    check(CARD["id"] not in ids,
          "events.metrics() drops the example card from its per-card totals "
          "(the single choke point every economics surface reads through)")
    check(m["totals"]["value_delivered"] == 0 and m["totals"]["ai_spend"] == 0,
          "an all-example board reports zero economics, not a phantom total")


def test_visible_to_every_role():
    client = {"name": "someone", "role": "client"}
    check(auth.owns_card(client, CARD),
          "a client-role account (which owns nothing) still sees the example "
          "card - PRD 4.2: never an empty screen")
    # regression guard on the rule this carve-out sits next to: an ORDINARY
    # unowned card (client="") must still stay hidden from a client role.
    ordinary = dict(CARD, example=False, client="")
    check(not auth.owns_card(client, ordinary),
          "the carve-out is example-specific - a real unowned card is still "
          "private from a client role")


for fn in (test_shape, test_never_dispatches, test_steer_never_dispatches_either,
           test_excluded_from_dispatcher, test_excluded_from_economics,
           test_visible_to_every_role):
    print(fn.__name__)
    fn()

print(("FAILED: %d" % len(_fails)) if _fails else "all example-card checks passed")
sys.exit(1 if _fails else 0)
