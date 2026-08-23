# -*- coding: utf-8 -*-
"""Self-sandboxing test for the GxP chokepoint (phase B, the guard).

The finding this exists for: HelmDeck can land and DEPLOY a card with nobody
involved - Henry's `move`, per-card fast-track, the policy auto-accept, the
chat verb, machine cards. Every one of those calls sessions.move_lane, so one
check at the top of _move_lane closes all of them, and agents need no special
case because they are not accounts.

What this pins down:
  1. mode OFF changes nothing - every actor still gets through
  2. mode ON refuses every autonomous actor by name: henry, policy, pm, chain,
     board-Agent (auto), and an empty actor
  3. mode ON still lets a REAL account through (the mode is not a freeze)
  4. the refusal is audited and the card does not move
  5. the refusal sits BEFORE the idempotency short-circuit, so an already
     'accepted' card cannot be walked through either
  6. is_human is derived from the user registry, not a blocklist: a newly
     created account passes immediately, with no code change
  7. fails CLOSED - an unreadable user registry refuses rather than allows
  8. a malformed or enabled:false lock file means mode OFF

Deliberately NOT covered here: the real merge/deploy machinery. This tests the
gate, not the landing - _move_lane's later half needs a git repo and a worktree
and is exercised by actually running a card.

Run: py -3.12 daemon/test_gxp_guard.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_fails = []
def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)


AGENTS = ["henry", "policy", "pm", "chain", "board-Agent (auto)", "", None]


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-gxpguard-test-")

    from daemon.spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from daemon.spine.storage import events
    events.EV = os.path.join(tmp, "events.jsonl")
    events.SET = os.path.join(tmp, "settings.json")
    from daemon.spine.auth import auth
    auth.USERS = os.path.join(tmp, "users.json")
    auth.SESS = os.path.join(tmp, "sessions.json")
    from daemon import gxp
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

    # ------------------------------------------------------------------ 1 ---
    print("\nmode OFF - nothing is blocked")
    mode_off()
    ok(not gxp.active(), "no lock file -> mode off")
    ok(all(gxp.accept_block_reason(a) is None for a in AGENTS + ["duy"]),
       "every actor passes, agents included")
    ok(not gxp.disabled("fast_track"), "fast_track not disabled while off")

    # ------------------------------------------------------------------ 2 ---
    print("\nmode ON - every autonomous actor is refused")
    mode_on()
    ok(gxp.active(), "lock file -> mode on")
    for a in AGENTS:
        ok(gxp.accept_block_reason(a) is not None, "refused: %r" % (a,))

    # ------------------------------------------------------------------ 3 ---
    print("\nmode ON - a real account still lands cards")
    ok(gxp.accept_block_reason("duy") is None, "the owner is not blocked")

    # ------------------------------------------------------------------ 6 ---
    print("\nis_human is derived, not a blocklist")
    ok(gxp.accept_block_reason("newhire") is not None, "unknown name refused")
    auth.create_user("newhire", "another-password", "operator", actor="duy")
    ok(gxp.accept_block_reason("newhire") is None,
       "the SAME name passes once the account exists - no code change")

    # ------------------------------------------------------------------ 7 ---
    print("\nfails closed")
    saved = auth.USERS
    auth.USERS = os.path.join(tmp, "does-not-exist", "users.json")
    ok(gxp.accept_block_reason("duy") is not None,
       "unreadable registry refuses rather than allows")
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
    mode_on()
    ok(gxp.accept_block_reason("henry") is not None, "on: henry refused")
    mode_off()
    ok(gxp.accept_block_reason("henry") is None, "off again in the same process")

    # ------------------------------------------------------------- 4 and 5 ---
    print("\nthe lane machine itself refuses, and does not move the card")
    from daemon.spine.storage import trackstore
    from daemon.cells.engineer import lanemachine
    db.init()                     # create the sandboxed tables
    for status, label in (("submitted", "a card resting on review"),
                          ("accepted", "an ALREADY ACCEPTED card")):
        tid = "t-" + status
        db.track_put({"id": tid, "lane": "review", "status": status,
                      "task": "x", "repo": None, "branch": None})
        mode_on()
        before = trackstore._find(trackstore._load(), tid)["lane"]
        r = lanemachine.move_lane(tid, "done", actor="henry")
        after = trackstore._find(trackstore._load(), tid)["lane"]
        ok(r.get("gxp_refused"), "%s: refused with a reason" % label)
        ok(before == after == "review", "%s: lane unchanged" % label)

    rows = []
    with open(events.EV, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
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
    mode_on()
    tid = "t-submitted"
    for actor, expect_refusal in (("henry", True), ("duy", False)):
        try:
            r = lanemachine.move_lane(tid, "done", actor=actor)
            refused = bool(r.get("gxp_refused"))
        except Exception:
            refused = False       # blew up further in - therefore past the guard
        ok(refused == expect_refusal,
           "%s: %s" % (actor, "refused at the guard" if expect_refusal
                       else "reached the machinery beyond the guard"))

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
