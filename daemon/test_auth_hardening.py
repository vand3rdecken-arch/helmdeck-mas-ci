# -*- coding: utf-8 -*-
"""Self-sandboxing test for the two remaining stage-0 auth gaps (S4 + S1).

S4 - brute force. There was no limit of any kind on password attempts, and the
relay exposes the login to the internet. A guesser could run flat out forever.

S1 - tokens at rest. Device tokens sat in users.json in the CLEAR, and
GET /users shipped them in full to the owner panel on every load while the UI
only ever displayed the last six characters.

What this pins down:
  1. LOCK_AFTER failures shut the door, and the refusal is indistinguishable
     from a wrong password (no account-enumeration oracle)
  2. a correct password before the limit clears the counter
  3. the lockout is audited, separately from an ordinary failure
  4. issue_token returns the plaintext exactly once and stores only a hash
  5. an EXISTING plaintext token keeps working across the migration and is
     rewritten to a hash on first read
  6. revoke works by token id - the panel never needs the secret
  7. users.json contains no usable token afterwards

Sandbox: auth.USERS/SESS, events.EV/SET, db.ROOT/DBPATH. users.json is a
git-ignored secret; no test may go near the real one.

Run: py -3.12 daemon/test_auth_hardening.py
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


PW = "a-real-password-42"


def audit_ops(events):
    rows = []
    with open(events.EV, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                if r.get("kind") == "auth":
                    rows.append(r)
    return rows


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-authhard-test-")

    from daemon.spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from daemon.spine.storage import events
    events.EV = os.path.join(tmp, "events.jsonl")
    events.SET = os.path.join(tmp, "settings.json")
    from daemon.spine.auth import auth
    auth.USERS = os.path.join(tmp, "users.json")
    auth.SESS = os.path.join(tmp, "sessions.json")

    real = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")
    ok(auth.USERS != real, "sandboxed away from the real users.json")

    auth.create_user("owner", PW, "owner")

    # ---------------------------------------------------------------- S4 ---
    print("\nS4 - a correct password before the limit clears the counter")
    for _ in range(auth.LOCK_AFTER - 1):
        auth.login("owner", "wrong")
    ok(auth.login("owner", PW) is not None, "still let in at LOCK_AFTER-1 failures")
    ok(auth.login("owner", PW) is not None, "counter was reset by the success")

    print("\nS4 - the door shuts after LOCK_AFTER failures")
    for i in range(auth.LOCK_AFTER):
        auth.login("owner", "wrong")
    ok(auth.login("owner", PW) is None,
       "the CORRECT password is refused while locked out")
    ok(auth._locked_until("owner") > 0, "lockout has time left on it")

    print("\nS4 - a locked refusal looks like any other refusal")
    ok(auth.login("owner", "wrong") is None and auth.login("owner", PW) is None,
       "wrong and right both return None - no enumeration oracle")

    ops = [r["op"] for r in audit_ops(events)]
    ok("login.blocked" in ops, "the lockout itself is audited")
    blocked = [r for r in audit_ops(events) if r["op"] == "login.blocked"][0]
    ok(blocked.get("locked_for_s", 0) > 0, "blocked event records the remaining time")
    flagged = [r for r in audit_ops(events)
               if r["op"] == "login.failed" and r.get("locks_out")]
    ok(bool(flagged), "the failure that tripped the lock is marked locks_out")

    auth._clear_failures("owner")
    ok(auth.login("owner", PW) is not None, "clearing the counter reopens the door")

    # ---------------------------------------------------------------- S1 ---
    print("\nS1 - a freshly issued token authenticates, but is not stored")
    tok = auth.issue_token("owner", "phone", actor="owner")
    ok(tok.startswith("sdk_"), "plaintext returned to the caller once")
    who = auth.resolve(token=tok)
    ok(who and who["name"] == "owner", "the token authenticates")
    raw = open(auth.USERS, encoding="utf-8").read()
    ok(tok not in raw, "the plaintext is NOT in users.json")
    ok(auth._token_hash(tok) in raw, "its hash is")

    print("\nS1 - an existing PLAINTEXT token survives the migration")
    users = json.load(open(auth.USERS, encoding="utf-8"))
    legacy = "sdk_legacy_device_token_value"
    users[0]["tokens"].append({"label": "old-phone", "token": legacy,
                               "created": "2026-01-01 00:00:00"})
    json.dump(users, open(auth.USERS, "w", encoding="utf-8"))
    ok("token" in json.load(open(auth.USERS, encoding="utf-8"))[0]["tokens"][-1],
       "legacy plaintext entry is in place before the read")

    who = auth.resolve(token=legacy)
    ok(who and who["name"] == "owner", "the OLD device still gets in - not locked out")
    raw = open(auth.USERS, encoding="utf-8").read()
    ok(legacy not in raw, "...and its plaintext was rewritten away on first read")
    migrated = json.load(open(auth.USERS, encoding="utf-8"))[0]["tokens"][-1]
    ok("token" not in migrated and "th" in migrated and "id" in migrated,
       "the record is now hash + id + tail")
    ok(migrated.get("tail") == legacy[-6:], "tail kept for human identification")

    print("\nS1 - revoke by id, never by the secret")
    users = json.load(open(auth.USERS, encoding="utf-8"))
    tid = [t for t in users[0]["tokens"] if t["label"] == "phone"][0]["id"]
    auth.revoke_token("owner", tid, actor="owner")
    ok(auth.resolve(token=tok) is None, "the revoked token no longer authenticates")
    ok(auth.resolve(token=legacy) is not None, "the other device is untouched")

    print("\nS1 - nothing usable left in the file")
    raw = open(auth.USERS, encoding="utf-8").read()
    ok('"token"' not in raw, "no `token` key anywhere in users.json")
    for secret in (tok, legacy, PW):
        ok(secret not in raw, "secret %s... absent" % secret[:12])

    blob = open(events.EV, encoding="utf-8").read()
    for secret in (tok, legacy, PW):
        ok(secret not in blob, "secret %s... absent from the audit too" % secret[:12])

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
