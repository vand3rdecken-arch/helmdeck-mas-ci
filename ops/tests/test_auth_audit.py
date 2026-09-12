# -*- coding: utf-8 -*-
"""Self-sandboxing test for the auth audit trail (A5).

Before this, spine/auth/auth.py did not import `events` at all
(`grep -c emit auth.py` -> 0). Creating and deleting users, changing a password
or a role, issuing and revoking device tokens, and every login - successful or
not - happened with no record whatsoever. A failed login was a bare
`return None`, so there was nothing to rate-limit or lock out on.

What this pins down:
  1. all nine identity operations emit an `auth` event
  2. the actor (WHO did it) and the subject (to WHOSE account) are both there
  3. a role change records the BEFORE value, not just the new one
  4. a failed login is distinguishable from a successful one, and the two
     failure modes (unknown user / wrong password) are distinguishable from
     each other
  5. no password, no password hash, no session id and no full token ever
     reaches the audit file

Point 5 is checked by searching the produced file for the actual secrets used
in the test, which is the only version of that assertion worth having.

Sandbox: auth.USERS/auth.SESS, events.EV/events.SET and db.ROOT/db.DBPATH all
point at a temp dir. auth.py and events.py hold INDEPENDENT module globals -
patching one does not cover the other, and users.json is a git-ignored secret
that must never be touched by a test.

Run: py -3.12 ops/tests/test_auth_audit.py
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


PW_OWNER = "correct-horse-battery"
PW_BOB = "bob-password-9999"
PW_BOB_NEW = "bob-rotated-1234"


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-authaudit-test-")

    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    db.init()          # login sessions are rows (state-into-db phase G)
    from spine.storage import events
    events.EV = os.path.join(tmp, "events.jsonl")
    events.SET = os.path.join(tmp, "settings.json")
    from spine.auth import auth
    auth.USERS = os.path.join(tmp, "users.json")
    real = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")
    ok(auth.USERS != real, "sandboxed away from the real users.json")

    print("exercising all nine identity operations")
    auth.create_user("owner", PW_OWNER, "owner")                       # 1
    auth.create_user("bob", PW_BOB, "client", actor="owner")           # 2
    auth.set_password("bob", PW_BOB_NEW, actor="owner")                # 3
    auth.set_role("bob", "operator", actor="owner")                    # 4
    tok = auth.issue_token("bob", "phone", actor="owner")              # 5
    auth.revoke_token("bob", tok, actor="owner")                       # 6
    sid = auth.login("bob", PW_BOB_NEW)                                # 7
    auth.logout(sid)                                                   # 8
    auth.login("bob", "definitely-wrong")                              # 9a
    auth.login("ghost", "whatever")                                    # 9b
    auth.delete_user("bob", actor="owner")                             # 10

    rows = []
    with open(events.EV, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    auth_rows = [r for r in rows if r.get("kind") == "auth"]
    ops = [r["op"] for r in auth_rows]
    print("  events: %s" % ", ".join(ops))

    for want in ("user.create", "user.password", "user.role", "token.issue",
                 "token.revoke", "login", "logout", "login.failed", "user.delete"):
        ok(want in ops, "%s recorded" % want)

    by_op = {}
    for r in auth_rows:
        by_op.setdefault(r["op"], []).append(r)

    ok(all(r.get("actor") for r in auth_rows), "every event names an actor")
    ok(all(r.get("subject") for r in auth_rows), "every event names a subject")
    ok(all(r.get("at_utc", "").endswith("Z") for r in auth_rows),
       "every event carries a UTC timestamp")

    role = by_op["user.role"][0]
    ok(role.get("frm") == "client" and role.get("to") == "operator",
       "role change kept the BEFORE value (client -> operator)")
    ok(role.get("actor") == "owner" and role.get("subject") == "bob",
       "role change: owner acted on bob")

    fails = by_op["login.failed"]
    reasons = sorted(r.get("reason") for r in fails)
    ok(reasons == ["bad_password", "no_such_user"],
       "both failure modes distinguishable (got %s)" % reasons)
    ok(len(by_op["login"]) == 1, "exactly one successful login recorded")

    dele = by_op["user.delete"][0]
    ok(dele.get("role") == "operator", "delete recorded the role that was removed")
    ok(dele.get("sessions_killed") == 0 and dele.get("existed") is True,
       "delete recorded blast radius (sessions=%s, existed=%s)"
       % (dele.get("sessions_killed"), dele.get("existed")))

    issued = by_op["token.issue"][0]
    ok(issued.get("tail", "").startswith("...") and len(issued["tail"]) == 7,
       "token recorded as a 4-char tail, not in full")

    print("no secret may appear in the audit file")
    blob = open(events.EV, encoding="utf-8").read()
    for secret, what in ((PW_OWNER, "owner password"),
                         (PW_BOB, "bob's first password"),
                         (PW_BOB_NEW, "bob's rotated password"),
                         (tok, "the full device token"),
                         (sid, "the session id")):
        ok(secret not in blob, "%s absent from the audit" % what)
    ok("pbkdf2$" not in blob, "no password hash in the audit")

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
