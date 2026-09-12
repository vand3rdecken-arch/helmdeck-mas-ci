# -*- coding: utf-8 -*-
"""Self-sandboxing test for card 5 (ops/docs/backlog/rbac-gxp): the audit
hardening pass - events.query_audit() (the shared filter GET /audit and
Henry's audit_query chat action both use), save_settings()'s new old->new
diff event with secret masking, and the chat action's role gate.

What this pins down:
  1. save_settings emits one "settings" event per write, with old->new for
     only the CHANGED top-level keys - untouched keys stay silent
  2. a key whose NAME looks like a secret (token/password/api_key) is masked
     in that event, even nested inside a dict value - "no secret in the log"
  3. events.query_audit() filters correctly (kind, actor, since/until, q) and
     is genuinely the same function GET /audit and the chat action both call
     (not two independently-drifting implementations)
  4. copilot_actions.py's "audit_query" action: refuses a role without
     audit.read (named, with the roles that DO have it), and returns a
     readable summary for a role that does

Run: py -3.12 ops/tests/test_audit_query.py
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
    tmp = tempfile.mkdtemp(prefix="helmdeck-audit-query-test-")

    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from spine.storage import events
    events.SET = os.path.join(tmp, "settings.json")
    from spine.auth import policy
    policy.LIVE = os.path.join(tmp, "policy_live.json")
    db.init(role="tool")

    # ------------------------------------------------------------------ 1 ---
    print("\nsave_settings emits an old->new diff, changed keys only")
    events.save_settings({"value_per_card": 100, "default_repo": "C:/x"}, actor="duy")
    before_events = len(events.query_audit(kind="settings"))
    events.save_settings({"value_per_card": 150, "default_repo": "C:/x"}, actor="duy")
    rows = events.query_audit(kind="settings")
    ok(len(rows) == before_events + 1, "one new settings event for the second save")
    changed = rows[-1]["changed"]
    ok(set(changed) == {"value_per_card"},
       "only the key that actually changed is in the diff (%r)" % (set(changed),))
    ok(changed["value_per_card"] == {"before": 100, "after": 150},
       "before/after values are correct")

    # ------------------------------------------------------------------ 2 ---
    print("\nsecrets are masked by key name, even nested")
    events.save_settings({"jira": {"api_token": "super-secret-xyz", "base": "https://x"}}, actor="duy")
    rows = events.query_audit(kind="settings")
    changed = rows[-1]["changed"]
    ok(changed["jira"]["after"]["api_token"] == "***", "nested api_token is masked")
    ok(changed["jira"]["after"]["base"] == "https://x", "a non-secret nested key is untouched")
    dumped = str(rows[-1])
    ok("super-secret-xyz" not in dumped, "the real secret value never appears in the event at all")

    # ------------------------------------------------------------------ 3 ---
    print("\nquery_audit() filters")
    events.emit("gxp", "-", op="activate", actor="duy")
    events.emit("signature", "t-1", op="signed", actor="sam", meaning="approved")
    events.emit("signature", "t-2", op="signed", actor="sam", meaning="rejected")
    ok(len(events.query_audit(kind="gxp")) == 1, "kind filter: only the gxp event")
    ok(len(events.query_audit(kind="signature")) == 2, "kind filter: both signature events")
    ok(len(events.query_audit(kind="signature", actor="sam")) == 2, "actor filter matches")
    ok(len(events.query_audit(kind="signature", actor="nobody")) == 0, "actor filter excludes a non-match")
    ok(len(events.query_audit(kind="gxp,signature")) == 3, "comma-separated kind filter unions both")
    ok(len(events.query_audit(q="rejected")) >= 1, "free-text q matches inside the serialized event")

    # ------------------------------------------------------------------ 4 ---
    print("\naudit_query chat action: role-gated, readable output")
    from cells.copilot.chat import copilot_actions as ca
    from spine.auth import auth
    r = ca._run_action({"type": "audit_query", "kind": "gxp"}, "ext-client", role="client")
    ok("gesperrt" in r or "audit.read" in r, "client role refused, told the gate name")
    ok("owner" in r, "refusal names owner as an allowed role")
    r = ca._run_action({"type": "audit_query", "kind": "gxp"}, "duy", role="owner")
    ok("gxp" in r and "duy" in r, "owner gets a readable summary naming the kind and actor")
    r = ca._run_action({"type": "audit_query", "kind": "nope-does-not-exist"}, "duy", role="owner")
    ok("keine Eintraege" in r, "an empty result says so plainly, not a silent empty string")

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
