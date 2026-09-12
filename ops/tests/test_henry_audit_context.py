# -*- coding: utf-8 -*-
"""Self-sandboxing test for card 5's deferred 'Consumer 2' (ops/docs/backlog/
rbac-gxp): cells/copilot/henry_broker.py's _audit_context(), which folds a
card's recent audit-trail events into Henry's autonomous judgement prompt -
the same audit_query the interactive chat action already has, wired into the
OTHER entry point (escalation resolution, not chat).

What this pins down:
  1. no card / no dispatched_by -> empty string, never a crash
  2. a card dispatched by a role WITHOUT audit.read (client, operator) ->
     empty string - Henry gets no more audit visibility than that account
     itself would have
  3. a card dispatched by a role WITH audit.read (owner, auditor) -> the
     card's own recent audit events are folded in, most recent last, capped
  4. events for a DIFFERENT card are never included (track filter is real)
  5. a storage/lookup failure degrades to "" rather than raising - this must
     never block a judgement turn

Run: py -3.12 ops/tests/test_henry_audit_context.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_fails = []
def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-henryaudit-test-")

    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from spine.storage import events
    events.EV = os.path.join(tmp, "events.jsonl")
    events.SET = os.path.join(tmp, "settings.json")
    from spine.auth import auth
    auth.USERS = os.path.join(tmp, "users.json")
    from spine.auth import policy
    policy.LIVE = os.path.join(tmp, "policy_live.json")
    db.init(role="tool")

    auth.create_user("duy", "a-real-password", "owner")
    auth.create_user("sam", "a-real-password", "operator")
    auth.create_user("aud", "a-real-password", "auditor")
    auth.create_user("ext", "a-real-password", "client")

    from cells.copilot.broker import henry_broker

    # ------------------------------------------------------------------ 1 ---
    print("\nno card / no dispatcher -> empty, never a crash")
    ok(henry_broker._audit_context(None) == "", "no track at all")
    ok(henry_broker._audit_context({"id": "t-1"}) == "", "no dispatched_by field")
    ok(henry_broker._audit_context({"id": "t-1", "dispatched_by": "nobody"}) == "",
       "dispatched_by names a nonexistent account")

    # seed some audit events for two different cards
    events.emit("gxp", "t-owner-card", op="accept_refused", actor="duy", reason="no signature")
    events.emit("signature", "t-owner-card", op="signed", actor="duy", meaning="approved")
    events.emit("gxp", "t-other-card", op="accept_refused", actor="sam", reason="unrelated")

    # ------------------------------------------------------------------ 2 ---
    print("\ndispatcher WITHOUT audit.read -> empty (no leak beyond that account's own view)")
    ok(henry_broker._audit_context({"id": "t-owner-card", "dispatched_by": "sam"}) == "",
       "operator dispatcher: operator has no audit.read by default -> empty")
    ok(henry_broker._audit_context({"id": "t-owner-card", "dispatched_by": "ext"}) == "",
       "client dispatcher -> empty")

    # ------------------------------------------------------------------ 3 ---
    print("\ndispatcher WITH audit.read -> the card's own events are folded in")
    ctx = henry_broker._audit_context({"id": "t-owner-card", "dispatched_by": "duy"})
    ok("AUDIT" in ctx, "owner dispatcher: audit section present")
    ok("gxp" in ctx and "signature" in ctx, "both of this card's events are present")
    ctx2 = henry_broker._audit_context({"id": "t-owner-card", "dispatched_by": "aud"})
    ok("AUDIT" in ctx2, "auditor dispatcher: audit section present too")

    # ------------------------------------------------------------------ 4 ---
    print("\nevents from a DIFFERENT card never leak in")
    ok("t-other-card" not in ctx and "unrelated" not in ctx,
       "the other card's event/reason text is not in this card's context")

    # ------------------------------------------------------------------ 5 ---
    print("\na lookup failure degrades to empty, never raises")
    real_users = auth.USERS
    auth.USERS = os.path.join(tmp, "does-not-exist", "users.json")
    try:
        r = henry_broker._audit_context({"id": "t-owner-card", "dispatched_by": "duy"})
        ok(r == "", "unreadable user registry -> empty context, no exception")
    except Exception as e:
        ok(False, "raised instead of degrading: %s" % e)
    finally:
        auth.USERS = real_users

    print()
    if _fails:
        print("FAILED (%d):" % len(_fails))
        for msg in _fails:
            print("  - " + msg)
        return 1
    print("all green - %s" % tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
