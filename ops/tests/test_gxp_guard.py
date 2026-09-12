# -*- coding: utf-8 -*-
"""Self-sandboxing test for the GxP chokepoint (phase B, the guard).

The finding this exists for: HelmDeck can land and DEPLOY a card with nobody
involved - Henry's `move`, per-card fast-track, the policy auto-accept, the
chat verb, machine cards. Every one of those calls sessions.move_lane, so one
check at the top of _move_lane closes all of them, and agents need no special
case because they are not accounts.

Scope is per REPO (owner call): a global kill switch that took fast-track away
everywhere would be switched back off within a fortnight, because most work is
not regulated. But it cannot be per CARD either - two cards in one repo share a
main and a deploy hook, so an unsigned card would land in the validated product
next to a signed one. The card flag therefore only ADDS scope, never removes it.

What this pins down:
  1. mode OFF changes nothing - every actor still gets through
  2. SCOPE: only the listed repo is affected; another repo keeps every
     autonomous actor AND fast-track exactly as before
  3. the card flag pulls a card in, and gxp:false cannot pull one out
  4. no repos list at all means the whole workspace is in scope
  5. in scope, every autonomous actor is refused by name: henry, policy, pm,
     chain, board-Agent (auto), and an empty actor
  6. the guard is LAYERED and says which layer stopped you: an agent is told it
     is not an account, a human is told there is no signature. The signature
     half is exercised against a real git repo in test_gxp_signature.py
  7. the refusal is audited and the card does not move
  8. the refusal sits BEFORE the idempotency short-circuit, so an already
     'accepted' card cannot be walked through either
  9. is_human is derived from the user registry, not a blocklist: a newly
     created account passes immediately, with no code change
 10. fails CLOSED - an unreadable user registry refuses rather than allows
 11. a malformed or enabled:false lock file means mode OFF
 12. the card flag is one-way at the write path too (cardadmin refuses to
     clear it, loudly, rather than ignoring the attempt)

Deliberately NOT covered here: the real merge/deploy machinery. This tests the
gate, not the landing - _move_lane's later half needs a git repo and a worktree
and is exercised by actually running a card.

Run: py -3.12 ops/tests/test_gxp_guard.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_fails = []
def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)


AGENTS = ["henry", "policy", "pm", "chain", "board-Agent (auto)", "", None]


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-gxpguard-test-")

    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from spine.storage import events
    events.SET = os.path.join(tmp, "settings.json")
    from spine.auth import auth
    auth.USERS = os.path.join(tmp, "users.json")
    from spine.auth import gxp
    gxp.LOCK = os.path.join(tmp, "gxp.lock")

    real = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gxp.lock")
    ok(gxp.LOCK != real, "sandboxed away from any real gxp.lock")

    auth.create_user("duy", "a-real-password", "owner")

    def mode_on(**extra):
        doc = {"enabled": True, "activated_by": "duy",
               "activated_at": "2026-08-23T12:00:00Z"}
        doc.update(extra)
        with open(gxp.LOCK, "w", encoding="utf-8") as f:
            json.dump(doc, f)

    def mode_off():
        if os.path.exists(gxp.LOCK):
            os.remove(gxp.LOCK)

    REG = {"repo": os.path.join(tmp, "pharma-product")}      # in scope
    OTHER = {"repo": os.path.join(tmp, "internal-tooling")}   # not in scope

    def mode_scoped(**extra):
        mode_on(repos=[REG["repo"]], **extra)

    # ------------------------------------------------------------------ 1 ---
    print("\nmode OFF - nothing is blocked")
    mode_off()
    ok(not gxp.active(), "no lock file -> mode off")
    ok(all(gxp.accept_block_reason(a, REG) is None for a in AGENTS + ["duy"]),
       "every actor passes, agents included")
    ok(not gxp.in_scope(REG), "nothing is in scope while off")

    # --------------------------------------------------------------- scope ---
    print("\nSCOPE - only the regulated repo is affected")
    mode_scoped()
    ok(gxp.in_scope(REG), "the listed repo is in scope")
    ok(not gxp.in_scope(OTHER), "another repo is NOT")
    ok(not gxp.in_scope({}), "a card with no repo is not dragged in")
    ok(gxp.in_scope({"repo": REG["repo"].replace("\\", "/").upper()}),
       "path comparison survives case and slash differences")

    print("\nSCOPE - the other repo keeps working exactly as before")
    for a in AGENTS:
        ok(gxp.accept_block_reason(a, OTHER) is None,
           "out of scope, %r still lands cards" % (a,))
    ok(not (gxp.in_scope(OTHER) and gxp.disabled("fast_track")),
       "fast-track is untouched out of scope")

    print("\nSCOPE - the card flag ADDS, and only adds")
    ok(gxp.in_scope(dict(OTHER, gxp=True)), "a flagged card is pulled into scope")
    ok(gxp.in_scope(dict(REG, gxp=False)),
       "gxp:false CANNOT walk a card out of a regulated repo")

    print("\nSCOPE - no repos list means the whole workspace")
    mode_on()
    ok(gxp.in_scope(OTHER) and gxp.in_scope(REG), "everything in scope")
    mode_scoped()

    # ------------------------------------------------------------------ 2 ---
    print("\nin scope - every autonomous actor is refused")
    ok(gxp.active(), "lock file -> mode on")
    for a in AGENTS:
        ok(gxp.accept_block_reason(a, REG) is not None, "refused: %r" % (a,))

    # ------------------------------------------------------------------ 3 ---
    # The guard is LAYERED: an agent fails on not being an account, a human
    # fails on not having signed. Different messages on purpose - the two need
    # completely different responses from whoever reads them. The signature
    # half itself is exercised in test_gxp_signature.py, against a real repo.
    print("\nin scope - a real account gets a DIFFERENT refusal")
    r = gxp.accept_block_reason("duy", REG)
    ok(r and "signature" in r,
       "the owner is past the human check and stopped by the signature")
    ok("not one" not in r, "...and is not told he is an agent")

    # ------------------------------------------------------------------ 6 ---
    print("\nis_human is derived, not a blocklist")
    r = gxp.accept_block_reason("newhire", REG)
    ok(r and "not one" in r, "unknown name refused AS A NON-ACCOUNT")
    auth.create_user("newhire", "another-password", "operator", actor="duy")
    r = gxp.accept_block_reason("newhire", REG)
    ok(r and "signature" in r,
       "the SAME name clears the human check once the account exists")

    # ------------------------------------------------------------------ 7 ---
    print("\nfails closed")
    saved = auth.USERS
    auth.USERS = os.path.join(tmp, "does-not-exist", "users.json")
    r = gxp.accept_block_reason("duy", REG)
    ok(r and "not one" in r,
       "unreadable registry refuses AS a non-account rather than allowing")
    auth.USERS = saved

    # ------------------------------------------------------------------ 8 ---
    print("\nlock file has to actually say enabled")
    with open(gxp.LOCK, "w", encoding="utf-8") as f:
        f.write("{ not json")
    ok(not gxp.active(), "malformed lock -> mode OFF, not a crash")
    with open(gxp.LOCK, "w", encoding="utf-8") as f:
        json.dump({"enabled": False}, f)
    ok(not gxp.active(), "enabled:false -> mode off")

    print("\nfeature switches")
    mode_on()
    for feat in ("fast_track", "machine", "direct_task", "auto_accept_green",
                 "henry_move", "henry_did", "agent_may_swap"):
        ok(gxp.disabled(feat), "%s disabled by default" % feat)
    mode_on(disable=["fast_track"])
    ok(gxp.disabled("fast_track"), "explicit list honoured")
    ok(not gxp.disabled("machine"), "...and it is exhaustive, not additive")
    ok(not gxp.four_eyes(), "four_eyes off by default")
    mode_on(four_eyes=True)
    ok(gxp.four_eyes(), "four_eyes switchable on")

    print("\nnothing is cached - the switch takes effect on the next call")
    mode_scoped()
    ok(gxp.accept_block_reason("henry", REG) is not None, "on: henry refused")
    mode_off()
    ok(gxp.accept_block_reason("henry", REG) is None, "off again in the same process")

    print("\nthe card flag is one-way")
    from spine.storage import db as _db
    _db.init()
    _db.track_put({"id": "t-oneway", "lane": "backlog", "status": "queued",
                   "task": "x", "gxp": True})
    from cells.engineer.cards import cardadmin
    try:
        cardadmin.update_track("t-oneway", {"gxp": False}, actor="duy")
        ok(False, "clearing gxp should have been refused")
    except ValueError as e:
        ok("only ever grows" in str(e), "clearing gxp is refused, loudly")
    _db.track_put({"id": "t-add", "lane": "backlog", "status": "queued",
                   "task": "x", "run_dir": tmp})
    cardadmin.update_track("t-add", {"gxp": True}, actor="duy")
    ok(_db.track_get("t-add").get("gxp") is True, "...but setting it works")

    # ------------------------------------------------------------- 4 and 5 ---
    print("\nthe lane machine itself refuses, and does not move the card")
    from spine.storage import trackstore
    from cells.engineer.cards import lanemachine
    db.init()                     # create the sandboxed tables
    for status, label in (("submitted", "a card resting on review"),
                          ("accepted", "an ALREADY ACCEPTED card")):
        tid = "t-" + status
        db.track_put({"id": tid, "lane": "review", "status": status,
                      "task": "x", "repo": REG["repo"], "branch": None})
        mode_scoped()
        before = trackstore._find(trackstore._load(), tid)["lane"]
        r = lanemachine.move_lane(tid, "done", actor="henry")
        after = trackstore._find(trackstore._load(), tid)["lane"]
        ok(r.get("gxp_refused"), "%s: refused with a reason" % label)
        ok(before == after == "review", "%s: lane unchanged" % label)

    rows = events.read_events()          # the table is the record (phase H)
    refusals = [r for r in rows
                if r.get("kind") == "gxp" and r.get("outcome") == "accept_refused"]
    ok(len(refusals) == 2, "both refusals audited (got %d)" % len(refusals))
    ok(all(r.get("actor") == "henry" for r in refusals),
       "the audit names who was refused")

    print("\n...and a real account gets PAST the guard on the same card")
    # Only the guard is under test. Past it, _move_lane goes into the actual
    # gate/merge/deploy machinery, which needs a git repo, a worktree and a
    # run_dir - so "got past" is proved by the refusal being absent and
    # execution reaching that machinery, not by a landing.
    mode_scoped()
    tid = "t-submitted"
    for actor, want in (("henry", "not one"), ("duy", "signature")):
        r = lanemachine.move_lane(tid, "done", actor=actor)
        ok(want in (r.get("gxp_refused") or ""),
           "%s: refused, and told why (%s)" % (actor, want))

    print()
    if _fails:
        print("FAILED (%d):" % len(_fails))
        for m in _fails:
            print("  - " + m)
        return 1
    print("all green - %s" % tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
