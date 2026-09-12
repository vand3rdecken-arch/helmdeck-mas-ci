# -*- coding: utf-8 -*-
"""Self-sandboxing test for device-token LIFETIME and per-device grouping -
spine/auth/auth.py's _token_expired/sweep_tokens/issue_token(device=...) and
the /auth/login seam that uses them.

This pays debt [pair-token-no-ttl]: every /relay/pair click minted a bearer
token with NO expiry, so a pairing code that was never used stayed a live
credential forever over direct-LAN mode, long after the 15-minute pairing
window closed. And it closes the panel's other half - /auth/login minted one
more permanent token on EVERY sign-in, which is what grew the owner's token
list to 123 lines of indistinguishable rows.

What this pins down:
  1. an UNCLAIMED token dies after its claim window; one that was actually
     used does not - expiry is DERIVED per call, never a stored flag
  2. tokens written before this existed carry neither field and keep working
     (nothing already in someone's hands expires retroactively)
  3. pairing tokens are minted WITH the tight claim window (the debt's target)
  4. sweep_tokens() is housekeeping only: it removes what resolve() already
     refuses, and touches nothing live
  5. device grouping: signing in twice from the same device REPLACES that
     device's token instead of stacking; a different device gets its own row;
     a caller that sends no device id behaves exactly as before
  6. GET /users exposes device + last_active, so the panel can render members
     with devices under them instead of a raw token list

Sandbox: auth.USERS/SESS, events.EV/SET, db.ROOT/DBPATH, policy.LIVE.

Run: py -3.12 ops/tests/test_token_ttl.py
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


def _backdate(users_path, label, days):
    """Push a token's `created` into the past, on disk - the only honest way to
    test a time window without either sleeping for a day or letting the test
    reach into the clock the code under test reads."""
    rows = json.load(open(users_path, encoding="utf-8"))
    for u in rows:
        for t in u.get("tokens", []):
            if t.get("label") == label:
                t["created"] = time.strftime("%Y-%m-%d %H:%M:%S",
                                             time.localtime(time.time() - days * 86400))
    json.dump(rows, open(users_path, "w", encoding="utf-8"))


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-token-ttl-test-")

    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from spine.storage import events
    events.SET = os.path.join(tmp, "settings.json")
    from spine.auth import policy
    policy.LIVE = os.path.join(tmp, "policy_live.json")
    from spine.auth import auth
    auth.USERS = os.path.join(tmp, "users.json")
    db.init(role="tool")

    real_users = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")
    ok(auth.USERS != real_users, "sandboxed away from the real users.json")

    auth.create_user("duy", PW, "owner")

    # ---------------------------------------------------------------- 1 ---
    print("\n1. an UNCLAIMED token dies in its window; a used one does not")
    unclaimed = auth.issue_token("duy", "never-used", unused_days=1)
    ok(auth.resolve(token=unclaimed) is not None, "fresh, inside the window -> resolves")

    claimed = auth.issue_token("duy", "claimed-once", unused_days=1)
    ok(auth.resolve(token=claimed) is not None, "the second token resolves too...")
    ok(auth.get_user("duy") and any(t.get("last_used") for t in auth.get_user("duy")["tokens"]
                                    if t.get("label") == "claimed-once"),
       "...and that first use stamped last_used on it")

    # `unclaimed` was resolved once above, which stamps last_used - so re-mint a
    # genuinely untouched one to age. This is the case the debt is about: a code
    # generated, screenshotted and abandoned.
    abandoned = auth.issue_token("duy", "abandoned", unused_days=1)
    _backdate(auth.USERS, "abandoned", 3)
    _backdate(auth.USERS, "claimed-once", 3)
    ok(auth.resolve(token=abandoned) is None,
       "never presented + past its window -> refused, same as no such token")
    ok(auth.resolve(token=claimed) is not None,
       "a token the device actually used is a normal device token from then on")

    # ---------------------------------------------------------------- 2 ---
    print("\n2. tokens minted before this existed are untouched")
    legacy = auth.issue_token("duy", "pre-ttl-device", unused_days=None)
    rec = next(t for t in auth.get_user("duy")["tokens"] if t["label"] == "pre-ttl-device")
    ok("unused_days" not in rec and "expires" not in rec,
       "no lifetime fields at all when the caller asks for none")
    _backdate(auth.USERS, "pre-ttl-device", 400)
    ok(auth.resolve(token=legacy) is not None,
       "a 400-day-old never-used legacy token still authenticates - no retroactive expiry")

    # ---------------------------------------------------------------- 3 ---
    print("\n3. pairing tokens carry the tight claim window (the debt's target)")
    ok(auth.PAIR_UNUSED_TTL_DAYS < auth.UNUSED_TTL_DAYS,
       "pairing's window is tighter than the general one")
    from spine.http.routes import routes_relay
    src = open(routes_relay.__file__, encoding="utf-8").read()
    ok(src.count("PAIR_UNUSED_TTL_DAYS") == 2,
       "BOTH pairing routes (QR/link and spoken code) mint with the window")

    # ---------------------------------------------------------------- 4 ---
    print("\n4. sweep_tokens() is housekeeping, not enforcement")
    before = {t["id"] for t in auth.get_user("duy")["tokens"]}
    dead = {t["id"] for t in auth.get_user("duy")["tokens"] if auth._token_expired(t)}
    ok(bool(dead), "there is at least one expired record to collect")
    removed = auth.sweep_tokens()
    after = {t["id"] for t in auth.get_user("duy")["tokens"]}
    ok(removed == len(dead), "sweep removed exactly the expired ones (%d)" % removed)
    ok(after == before - dead, "...and nothing else")
    ok(auth.resolve(token=claimed) is not None, "live tokens still authenticate after a sweep")
    ok(auth.sweep_tokens() == 0, "a second sweep has nothing to do")

    # ---------------------------------------------------------------- 5 + 6 ---
    from spine.http import server
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

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

    def tokens_of(name):
        return (auth.get_user(name) or {}).get("tokens") or []

    try:
        print("\n5. one live token per DEVICE, not one per sign-in")
        n0 = len(tokens_of("duy"))
        st, r1 = call("POST", "/auth/login", {"name": "duy", "password": PW,
                                              "device": "phone-abc", "device_label": "Duy's phone"})
        ok(st == 200 and r1.get("token"), "sign-in from a phone -> 200 + token")
        st, r2 = call("POST", "/auth/login", {"name": "duy", "password": PW,
                                              "device": "phone-abc", "device_label": "Duy's phone"})
        ok(len(tokens_of("duy")) == n0 + 1,
           "signing in TWICE from the same device added ONE row, not two")
        ok(auth.resolve(token=r1["token"]) is None,
           "the previous token for that device was replaced (old credential is dead)")
        ok(auth.resolve(token=r2["token"]) is not None, "the newest one authenticates")

        st, r3 = call("POST", "/auth/login", {"name": "duy", "password": PW,
                                              "device": "laptop-xyz", "device_label": "Laptop"})
        ok(len(tokens_of("duy")) == n0 + 2, "a DIFFERENT device gets its own row")
        ok(auth.resolve(token=r2["token"]) is not None,
           "...and does not disturb the phone's token")

        st, r4 = call("POST", "/auth/login", {"name": "duy", "password": PW})
        st, r5 = call("POST", "/auth/login", {"name": "duy", "password": PW})
        ok(len(tokens_of("duy")) == n0 + 4,
           "a caller that sends NO device id behaves exactly as before (a row per call)")
        ok(auth.resolve(token=r4["token"]) is not None and auth.resolve(token=r5["token"]) is not None,
           "...and both of those still work - old clients are not broken")

        print("\n6. GET /users renders as members-with-devices")
        sid = auth.login("duy", PW)
        st, body = call("GET", "/users", None, {"Cookie": "sd_session=%s" % sid})
        ok(st == 200, "GET /users -> 200")
        u = next(x for x in body if x["name"] == "duy")
        ok("last_active" in u and u["last_active"], "the member row carries last_active")
        phone = next((t for t in u["tokens"] if t.get("device") == "phone-abc"), None)
        ok(phone is not None and phone["label"] == "Duy's phone",
           "a device row is identified by its device id and its human label")
        ok(all("th" not in t for t in u["tokens"]),
           "no token hash on the wire - id/tail only, as before")
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
