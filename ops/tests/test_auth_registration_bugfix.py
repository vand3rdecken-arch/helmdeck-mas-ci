# -*- coding: utf-8 -*-
"""Self-sandboxing test for the 2026-09-14 22:49 registration bug (owner
screenshot: signup with invite PFGYUQAL failed). Three independent root
causes, pinned down here so none of them regresses silently:

  A. spine/auth/auth.py's _load()/_save() were a tmp+os.replace file
     (daemon/users.json) with no retry on _save()'s side of the SAME Windows
     exclusive-lock window _load() already retried - which is what burned
     invitation PFGYUQAL with a raw "Access is denied ... users.json.tmp ->
     users.json". Root-caused rather than patched with a second retry loop
     (owner decree 2026-09-14): accounts are rows in the `users` table now
     (state-into-db ledger step 13, spine/storage/db.py's _m13), the same
     move sessions/invites/devices already made in ledger step 10. There is
     no rename left to race.
  B. spine/http/routes/routes_auth.py auth_register() only released the
     invitation on ValueError from create_user - an OSError (exactly what A
     used to produce) burned the invite with no account behind it, and leaked
     a Windows path to the client.
  C. spine/auth/invites.py migrate_legacy() stored the legacy code verbatim
     ("join-swarm"), but every comparison (claim/peek/revoke/release)
     normalizes with .strip().upper() - so a migrated legacy code could never
     be redeemed.

Sandbox: auth.USERS, events.EV/SET, db.ROOT/DBPATH - same discipline as
test_invites.py / test_auth_hardening.py. Never goes near the real
users.json/helmdeck.db. Section A's migration check follows test_db_schema.py's
fresh()-style pattern (repoint db.DBPATH, drop the thread-local connection) to
run a SECOND sandboxed db within the same process.

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

# The 5 accounts the owner named in done_when (their real names on the live
# daemon) - proven here as a MECHANISM against a synthetic legacy file, never
# against the real users.json/helmdeck.db (the sandboxing law this whole file
# lives under). Roles are illustrative; the real migration preserves whatever
# role each row already carried.
LEGACY_ACCOUNTS = [("owner", "owner"), ("acme", "operator"), ("newbie", "client"),
                   ("Hans", "operator"), ("op-test", "operator")]


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
        print("\nA. accounts are `users` db rows, not users.json - root cause, not a retry")
        legacy_path = os.path.join(tmp, "users.json")
        ok(not os.path.exists(legacy_path),
           "create_user + login above never touched users.json - nothing to touch")

        st, inv0 = call("POST", "/invites", {"role": "client"}, owner_hdr)
        st, r = call("POST", "/auth/register",
                     {"name": "nofile-signup", "password": PW, "invite": inv0["code"]})
        ok(st == 200 and auth.get_user("nofile-signup") is not None,
           "POST /auth/register succeeds with users.json absent from disk")
        ok(not os.path.exists(legacy_path),
           "...and still never created one - the db is the only store")

        applied = {name for _, name, _ in db.schema_applied()}
        ok("users-table" in applied,
           "a real numbered schema-ledger step created the table (not an ad hoc CREATE TABLE)")

        print("\nA. the 5 named accounts migrate from a legacy users.json and log in")
        mig_dir = tempfile.mkdtemp(prefix="helmdeck-authregbug-migrate-")
        mig_legacy = os.path.join(mig_dir, "users.json")
        with open(mig_legacy, "w", encoding="utf-8") as f:
            json.dump([{"name": n, "pw": auth._hash_pw(PW), "role": role,
                       "tokens": [], "created": "2026-01-01 00:00:00"}
                      for n, role in LEGACY_ACCOUNTS], f)
        open(mig_legacy + ".tmp", "w", encoding="utf-8").close()   # stray leftover from the old write path

        db.ROOT = mig_dir
        db.DBPATH = os.path.join(mig_dir, "migrated.db")
        db._local.c = None      # drop this thread's cached connection so init() opens the new file
        db.init(role="tool")

        for name, role in LEGACY_ACCOUNTS:
            msid = auth.login(name, PW)
            ok(msid is not None, "migrated account %r logs in with its pre-migration password" % name)
            ok(auth.get_user(name)["role"] == role, "...with its original role (%s)" % role)

        ok(not os.path.exists(mig_legacy), "users.json is gone from its original path")
        archived = os.path.join(mig_dir, "backups", "users.json.imported")
        ok(os.path.exists(archived), "...renamed to .imported under backups/, never deleted")
        ok(not os.path.exists(mig_legacy + ".tmp"), "the stray users.json.tmp leftover was cleaned up")
        ok("users-table" in {name for _, name, _ in db.schema_applied()},
           "the migration db recorded the same ledger step")

        # back to this file's own sandbox for everything below
        db.ROOT = tmp
        db.DBPATH = os.path.join(tmp, "test.db")
        db._local.c = None

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
