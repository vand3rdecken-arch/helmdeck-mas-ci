# -*- coding: utf-8 -*-
"""Self-sandboxing test for the 2026-09-14 22:49 registration bug (owner
screenshot: signup with invite PFGYUQAL failed). Three independent root
causes, pinned down here so none of them regresses silently:

  A. spine/auth/auth.py _save() had no retry around os.replace, though _load()
     already retries the SAME Windows exclusive-lock window. A signup that
     landed inside that window died with a raw PermissionError.
  B. spine/http/routes/routes_auth.py auth_register() only released the
     invitation on ValueError from create_user - an OSError (exactly what A
     produces) burned the invite with no account behind it, and leaked a
     Windows path to the client.
  C. spine/auth/invites.py migrate_legacy() stored the legacy code verbatim
     ("join-swarm"), but every comparison (claim/peek/revoke/release)
     normalizes with .strip().upper() - so a migrated legacy code could never
     be redeemed.

Sandbox: auth.USERS, events.EV/SET, db.ROOT/DBPATH - same discipline as
test_invites.py / test_auth_hardening.py. Never goes near the real
users.json/helmdeck.db.

Run: py -3.12 ops/tests/test_auth_registration_bugfix.py
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
    tmp = tempfile.mkdtemp(prefix="helmdeck-authregbug-test-")

    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from spine.storage import events
    events.SET = os.path.join(tmp, "settings.json")
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
        # -------------------------------------------------------------- A ---
        print("\nA. _save() retries os.replace through the Windows lock window")
        import os as _os
        real_replace = _os.replace
        calls = {"n": 0}

        def flaky_replace(src, dst):
            calls["n"] += 1
            if calls["n"] <= 3:
                raise PermissionError(5, "Access is denied")
            return real_replace(src, dst)

        auth.os.replace = flaky_replace
        try:
            auth.set_password("duy", PW + "-rotated", actor="duy")
        except PermissionError:
            pass
        finally:
            auth.os.replace = real_replace
        ok(calls["n"] == 4, "os.replace was retried past the flaky window (4 attempts)")
        ok(auth._check_pw(PW + "-rotated", auth.get_user("duy")["pw"]),
           "...and the write actually landed once the retry succeeded")

        calls["n"] = 0

        def always_locked(src, dst):
            calls["n"] += 1
            raise PermissionError(5, "Access is denied")

        auth.os.replace = always_locked
        raised = False
        try:
            auth.set_password("duy", PW, actor="duy")
        except PermissionError:
            raised = True
        finally:
            auth.os.replace = real_replace
        ok(raised and calls["n"] == 5,
           "a lock that never clears still raises (5 tries), not silently swallowed")
        auth.set_password("duy", PW, actor="duy")   # restore real password for later steps
        sid = auth.login("duy", PW)
        owner_hdr = {"Cookie": "sd_session=%s" % sid, "Content-Type": "application/json"}

        # -------------------------------------------------------------- B ---
        print("\nB. a non-ValueError from create_user releases the invite and hides the path")
        st, inv = call("POST", "/invites", {"role": "client"}, owner_hdr)
        ok(st == 200, "invite minted")

        real_create_user = auth.create_user

        def boom(name, password, role, actor=None):
            raise OSError(5, "Access is denied: 'C:\\\\daemon\\\\users.json.tmp' -> "
                              "'C:\\\\daemon\\\\users.json'")

        auth.create_user = boom
        try:
            st, r = call("POST", "/auth/register",
                         {"name": "pfgyuqal", "password": PW, "invite": inv["code"]})
        finally:
            auth.create_user = real_create_user
        ok(st == 500, "a disk-level failure surfaces as 500, not a raw crash")
        ok("users.json" not in json.dumps(r) and "WinError" not in json.dumps(r)
           and "Access is denied" not in json.dumps(r),
           "the Windows path/message is not echoed to the client")
        ok(auth.get_user("pfgyuqal") is None, "no half-created account")

        live = next(i for i in invites.list_all() if i["code"] == inv["code"])
        ok(live["state"] == "open",
           "the invitation was RELEASED, not burned, by the OSError")

        st, r = call("POST", "/auth/register",
                     {"name": "pfgyuqal", "password": PW, "invite": inv["code"]})
        ok(st == 200 and auth.get_user("pfgyuqal") is not None,
           "the same code signs up cleanly once the disk error is gone")

        # -------------------------------------------------------------- C ---
        print("\nC. a lowercase legacy invite code is redeemable after migration")
        events.save_settings({"registration": {"open": False,
                                               "invite_code": "join-swarm",
                                               "default_role": "operator"}})
        ok(invites.migrate_legacy() is True, "migrate_legacy ran")
        stored = next((i for i in invites.list_all() if i["code"] == "JOIN-SWARM"), None)
        ok(stored is not None, "the migrated row is stored normalized (upper-case)")
        ok(invites.peek("join-swarm") == "operator",
           "peek() with the original lower-case code still resolves the role")
        st, r = call("POST", "/auth/register",
                     {"name": "legacyjoin", "password": PW, "invite": "join-swarm"})
        ok(st == 200 and auth.get_user("legacyjoin") is not None,
           "signup with the untouched lower-case legacy code succeeds end to end")
        ok(auth.get_user("legacyjoin")["role"] == "operator",
           "...with the role the legacy default_role carried")
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
