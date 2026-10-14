# -*- coding: utf-8 -*-
"""Self-sandboxing test for the signed-out password reset (reset code).

A person who forgot their password could not get back in: only an owner could
set one (typing it for them), and the login screen had no way to ask. The fix
is an owner-minted single-use code in the `invites` table (kind="reset",
for_user=name) that the person redeems with a password of their own choosing.

Pinned here, each against the REAL path (auth.reset_password_with_code):
  1. the code resets exactly the account it was minted for, the new password
     works and the old one does not
  2. single use, wrong account, revoked, expired, garbage: all refused with the
     SAME message (no oracle for "this name has a reset pending")
  3. a too-short password does not burn the code
  4. an invitation code cannot reset a password, and a reset code cannot sign
     anyone up (claim/peek refuse it) nor makes the sign-up tab appear
     (count_open ignores it)
  5. wrong codes count against the login lockout, so this is not the cheaper door

Sandbox: db.ROOT/db.DBPATH and events.SET point at a temp dir - the live
helmdeck.db must never be touched by a test.

Run: py -3.12 ops/tests/test_password_reset.py
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


def refused(fn, *a):
    try:
        fn(*a)
    except ValueError as e:
        return str(e)
    return None


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-pwreset-test-")
    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    db.init()
    from spine.storage import events
    events.SET = os.path.join(tmp, "settings.json")
    from spine.auth import auth, invites

    auth.create_user("owner", "owner-password-1", "owner")
    auth.create_user("carl", "carl-old-password", "client")
    auth.create_user("dora", "dora-old-password", "client")

    r = invites.create_reset("carl", "client", actor="owner")
    ok(r["kind"] == "reset" and r["for_user"] == "carl" and r["state"] == "open", "reset code minted for carl")
    ok(invites.count_open() == 0, "an open reset code does not open sign-up")

    # 3. short password first: the code must survive it
    ok(refused(auth.reset_password_with_code, "carl", r["code"], "short") is not None, "short password refused")
    ok(invites.list_all()[0]["state"] == "open", "short password did not burn the code")

    # 2. wrong account / garbage give the same message as a real miss
    m_wrong = refused(auth.reset_password_with_code, "dora", r["code"], "dora-new-password")
    m_junk = refused(auth.reset_password_with_code, "carl", "NOPENOPE", "carl-new-password")
    ok(m_wrong and m_wrong == m_junk, "wrong account and unknown code are the same refusal")
    ok(auth.login("dora", "dora-old-password"), "dora's password untouched")

    # 1. the happy path
    auth.reset_password_with_code("carl", r["code"].lower(), "carl-new-password")
    ok(auth.login("carl", "carl-new-password") is not None, "new password works")
    ok(auth.login("carl", "carl-old-password") is None, "old password no longer works")
    ok(refused(auth.reset_password_with_code, "carl", r["code"], "carl-third-password") == m_junk,
       "code is single use")

    # revoked + expired
    r2 = invites.create_reset("carl", "client", actor="owner")
    invites.revoke(r2["code"], actor="owner")
    ok(refused(auth.reset_password_with_code, "carl", r2["code"], "carl-fourth-pw") == m_junk, "revoked code refused")
    r3 = invites.create_reset("carl", "client", actor="owner")
    rows = invites._load()
    for row in rows:
        if row["code"] == r3["code"]:
            row["expires"] = "2000-01-01 00:00:00"
    invites._save(rows)
    ok(refused(auth.reset_password_with_code, "carl", r3["code"], "carl-fifth-pw") == m_junk, "expired code refused")

    # 4. the two kinds do not cross over
    inv = invites.create("client", actor="owner")
    ok(refused(auth.reset_password_with_code, "carl", inv["code"], "carl-sixth-pw") == m_junk,
       "an invitation code cannot reset a password")
    r4 = invites.create_reset("carl", "client", actor="owner")
    ok(refused(invites.claim, r4["code"], "newperson") is not None, "a reset code cannot sign anyone up (claim)")
    ok(refused(invites.peek, r4["code"]) is not None, "a reset code cannot sign anyone up (peek)")
    ok(invites.count_open() == 1, "only the real invitation counts as open sign-up")
    ok(refused(invites.create_reset, "carl", "client", "owner", 5) is not None, "odd ttl refused")

    # 5. lockout
    auth._fails.clear()
    for _ in range(auth.LOCK_AFTER):
        refused(auth.reset_password_with_code, "dora", "WRONGWRO", "dora-new-password")
    ok(refused(auth.reset_password_with_code, "dora", "WRONGWRO", "dora-new-password") is not None
       and auth._locked_until("dora") > 0, "wrong reset codes lock the name out like wrong passwords")
    auth._fails.clear()

    print("\n%s" % ("ALL OK" if not _fails else "FAILED: %d" % len(_fails)))
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
