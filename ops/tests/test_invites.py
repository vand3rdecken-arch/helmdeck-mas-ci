# -*- coding: utf-8 -*-
"""Self-sandboxing test for the ONE invitation flow (owner decree 2026-09-09,
22:15: creating a user and inviting them are the same act, and the ROLE is
chosen at invitation time) - spine/auth/invites.py plus its two HTTP seams,
POST /invites and POST /auth/register.

What this pins down:
  1. the role travels IN the invitation: an operator invite produces an
     operator account, a client invite a client account - end to end over
     real HTTP, not by calling create_user with a role by hand
  2. single use: the same code cannot be redeemed twice
  3. a failed signup RELEASES the code instead of burning it
  4. revoke kills an open invitation; an expired one is refused too, and the
     refusal names which of the three it was
  5. owner is not an invitable role
  6. the legacy global registration.invite_code migrates into a real
     invitation object and the setting is cleared
  7. /auth/state derives "can anyone sign up" from live invitations, not from
     a settings flag
  8. no code + registration closed -> 403 (the door is actually shut)

Sandbox: auth.USERS, events.EV/SET, db.ROOT/DBPATH (sessions + invites are rows),
policy.LIVE. users.json and the workspace db are live secrets/state - no test
may go near the real ones (config-consolidation trap: patching events.SET
alone still writes the LIVE db).

Run: py -3.12 ops/tests/test_invites.py
"""
import http.client
import json
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_fails = []
def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)


PW = "a-real-password-42"


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-invites-test-")

    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from spine.storage import events
    events.SET = os.path.join(tmp, "settings.json")
    from spine.auth import policy
    policy.LIVE = os.path.join(tmp, "policy_live.json")
    from spine.auth import auth, invites
    auth.USERS = os.path.join(tmp, "users.json")
    db.init(role="tool")

    real_users = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")
    ok(auth.USERS != real_users, "sandboxed away from the real users.json")
    ok(db.DBPATH.startswith(tmp), "sandboxed away from the real helmdeck.db")

    auth.create_user("duy", PW, "owner")

    from spine.http import server
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    sid = auth.login("duy", PW)
    owner_hdr = {"Cookie": "sd_session=%s" % sid, "Content-Type": "application/json"}

    def call(method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request(method, path, json.dumps(body or {}) if body is not None else None,
                     headers or {"Content-Type": "application/json"})
        r = conn.getresponse()
        raw = r.read()
        conn.close()
        try:
            return r.status, json.loads(raw or b"{}")
        except ValueError:
            return r.status, {"raw": raw.decode("utf-8", "replace")}

    try:
        # -------------------------------------------------------------- 1 ---
        print("\n1. the ROLE travels in the invitation (operator + client)")
        st, op_inv = call("POST", "/invites", {"role": "operator"}, owner_hdr)
        ok(st == 200 and len(op_inv.get("code", "")) == 8,
           "POST /invites -> 200 with an 8-char code")
        ok(op_inv.get("role") == "operator" and op_inv.get("state") == "open",
           "the invitation carries role=operator and reads open")
        ok(set(op_inv["code"]) <= set(invites.ALPHABET),
           "the code avoids O/0 and I/1 (dictatable over the phone)")

        st, r = call("POST", "/auth/register",
                     {"name": "mara", "password": PW, "invite": op_inv["code"]})
        ok(st == 200 and r.get("ok"), "signing up with the code -> 200")
        ok(auth.get_user("mara")["role"] == "operator",
           "the new account is an OPERATOR - the role came from the invitation")
        ok(bool(r.get("token")), "the new member gets a device token to work with")

        st, cl_inv = call("POST", "/invites", {"role": "client"}, owner_hdr)
        st, r = call("POST", "/auth/register",
                     {"name": "tom", "password": PW, "invite": cl_inv["code"]})
        ok(st == 200 and auth.get_user("tom")["role"] == "client",
           "a client invitation produces a CLIENT account - same flow, other role")

        # -------------------------------------------------------------- 2 ---
        print("\n2. single use")
        st, r = call("POST", "/auth/register",
                     {"name": "impostor", "password": PW, "invite": op_inv["code"]})
        ok(st == 403 and "already been used" in r.get("error", ""),
           "the same code a second time -> 403, and says why")
        ok(auth.get_user("impostor") is None, "...and no account was created")
        spent = next(i for i in invites.list_all() if i["code"] == op_inv["code"])
        ok(spent["state"] == "used" and spent["used_by"] == "mara",
           "the invitation records WHO redeemed it")

        # -------------------------------------------------------------- 3 ---
        print("\n3. a failed signup releases the code instead of burning it")
        st, keep = call("POST", "/invites", {"role": "client"}, owner_hdr)
        st, r = call("POST", "/auth/register",
                     {"name": "shorty", "password": "abc", "invite": keep["code"]})
        ok(st == 400, "a too-short password is rejected")
        live = next(i for i in invites.list_all() if i["code"] == keep["code"])
        ok(live["state"] == "open", "...and the invitation is open again, not spent")
        st, r = call("POST", "/auth/register",
                     {"name": "shorty", "password": PW, "invite": keep["code"]})
        ok(st == 200 and auth.get_user("shorty") is not None,
           "the retry with a real password works on the SAME code")

        # -------------------------------------------------------------- 4 ---
        print("\n4. revoke, and expiry")
        st, doomed = call("POST", "/invites", {"role": "client"}, owner_hdr)
        st, r = call("POST", "/invites/%s/revoke" % doomed["code"], {}, owner_hdr)
        ok(st == 200 and r.get("state") == "revoked", "revoke -> 200, state revoked")
        st, r = call("POST", "/auth/register",
                     {"name": "nope", "password": PW, "invite": doomed["code"]})
        ok(st == 403 and "revoked" in r.get("error", ""),
           "a revoked code is refused, and the refusal names the reason")

        st, old = call("POST", "/invites", {"role": "client", "ttl_days": 1}, owner_hdr)
        rows = invites._load()
        for row in rows:
            if row["code"] == old["code"]:
                row["expires"] = "2000-01-01 00:00:00"
        invites._save(rows)
        st, r = call("POST", "/auth/register",
                     {"name": "late", "password": PW, "invite": old["code"]})
        ok(st == 403 and "expired" in r.get("error", ""),
           "an expired code is refused - the link does not live forever")
        ok(auth.get_user("late") is None, "...and no account came out of it")

        st, r = call("POST", "/auth/register",
                     {"name": "ghost", "password": PW, "invite": "ZZZZZZZZ"})
        ok(st == 403 and "unknown" in r.get("error", ""), "a made-up code is refused")

        # -------------------------------------------------------------- 5 ---
        print("\n5. owner is not an invitable role")
        st, r = call("POST", "/invites", {"role": "owner"}, owner_hdr)
        ok(st == 400 and "role must be one of" in r.get("error", ""),
           "POST /invites role=owner -> 400 (promotion stays a deliberate act)")
        st, r = call("POST", "/invites", {"role": "client", "ttl_days": 900}, owner_hdr)
        ok(st == 400, "an absurd ttl is refused rather than silently clamped")

        # -------------------------------------------------------------- 6 ---
        print("\n6. the legacy global invite_code migrates into an object")
        events.save_settings({"registration": {"open": False,
                                               "invite_code": "OLDCODE1",
                                               "default_role": "operator"}})
        ok(invites.migrate_legacy() is True, "migrate_legacy ran")
        ok((events.settings().get("registration") or {}).get("invite_code") == "",
           "the global key is CLEARED - one door left, not two")
        moved = next((i for i in invites.list_all() if i["code"] == "OLDCODE1"), None)
        ok(moved is not None and moved["role"] == "operator",
           "the old code became an invitation carrying the old default_role")
        ok(invites.migrate_legacy() is False, "running it again is a no-op (idempotent)")
        st, r = call("POST", "/auth/register",
                     {"name": "legacyfriend", "password": PW, "invite": "OLDCODE1"})
        ok(st == 200 and auth.get_user("legacyfriend")["role"] == "operator",
           "a link already sent out still works - exactly once, with its role")

        # -------------------------------------------------------------- 7 ---
        print("\n7. /auth/state derives sign-up availability from live invitations")
        for row in invites._load():
            if invites.state(row) == "open":
                call("POST", "/invites/%s/revoke" % row["code"], {}, owner_hdr)
        st, state = call("GET", "/auth/state", None, owner_hdr)
        ok(st == 200 and state.get("registration") is False,
           "no open invitation + registration closed -> registration False")
        st, fresh = call("POST", "/invites", {"role": "client"}, owner_hdr)
        st, state = call("GET", "/auth/state", None, owner_hdr)
        ok(state.get("registration") is True and state.get("registration_open") is False,
           "one open invitation flips `registration` on, `registration_open` stays off")

        # -------------------------------------------------------------- 8 ---
        print("\n8. no code, registration closed -> the door is shut")
        st, r = call("POST", "/auth/register", {"name": "walkin", "password": PW})
        ok(st == 403, "signing up with no invitation at all -> 403")
        ok(auth.get_user("walkin") is None, "...no account")
        events.save_settings({"registration": {"open": True}})
        st, r = call("POST", "/auth/register", {"name": "walkin", "password": PW})
        ok(st == 200 and auth.get_user("walkin")["role"] == "client",
           "open registration still works and is hard-wired to the WEAKEST role")

        print("\naudit trail")
        blob = open(events.EV, encoding="utf-8").read()
        for op in ("invite.create", "invite.redeem", "invite.revoke", "invite.release"):
            ok(op in blob, "%s is audited" % op)
        ok(PW not in blob, "no password anywhere in the audit sink")
    finally:
        httpd.shutdown()

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
