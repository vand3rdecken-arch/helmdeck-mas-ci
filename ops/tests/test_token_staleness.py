# -*- coding: utf-8 -*-
"""Self-sandboxing test for card 5 debt (rbac-audit-hardening-partial):
device-token TTL + staleness surfacing - spine/auth/auth.py's
issue_token(expires_days=...), resolve()'s expiry check, _touch_token's
throttled last_used, and _token_stale()'s >90d review signal.

What this pins down:
  1. a token with no expires_days behaves exactly as before (never expires) -
     the default must not change existing device behaviour
  2. an expired token is refused by resolve() (same as "no such token"),
     an unexpired one still works
  3. resolve() records last_used on first use, and does NOT rewrite the file
     on every subsequent call the same day (throttle)
  4. _token_stale(): a fresh token is not stale; a token whose last_used (or
     created, if never used) is >90 days old is
  5. GET /users surfaces last_used/expires/stale per token (real HTTP call)

Run: py -3.12 ops/tests/test_token_staleness.py
"""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_fails = []
def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-token-stale-test-")

    from spine.auth import auth
    auth.USERS = os.path.join(tmp, "users.json")
    auth.create_user("duy", "a-real-password", "owner")

    # ------------------------------------------------------------------ 1 ---
    print("\nno expires_days -> never expires, same as before")
    forever_tok = auth.issue_token("duy", "forever-device")
    u = auth.get_user("duy")
    rec = u["tokens"][0]
    ok("expires" not in rec, "no expires field at all when not requested")
    ok(auth.resolve(token=forever_tok) is not None, "resolves fine with no expiry")

    # ------------------------------------------------------------------ 2 ---
    print("\nexpires_days: an expired token is refused, an unexpired one works")
    expiring_tok = auth.issue_token("duy", "expiring-device", expires_days=30)
    ok(auth.resolve(token=expiring_tok) is not None, "not yet expired -> resolves")
    # force it into the past directly on disk (30 days from now, backdated)
    users = json.loads(open(auth.USERS, encoding="utf-8").read())
    for t in users[0]["tokens"]:
        if t["label"] == "expiring-device":
            t["expires"] = "2000-01-01"
    with open(auth.USERS, "w", encoding="utf-8") as f:
        json.dump(users, f)
    ok(auth.resolve(token=expiring_tok) is None, "expired token is refused by resolve()")
    ok(auth.resolve(token=forever_tok) is not None,
       "...the OTHER token on the same user is unaffected")

    # ------------------------------------------------------------------ 3 ---
    print("\nlast_used: set on use, throttled to once/day")
    u = auth.get_user("duy")
    tid = next(t["id"] for t in u["tokens"] if t["label"] == "forever-device")
    before_mtime = os.path.getmtime(auth.USERS)
    time.sleep(0.05)
    auth.resolve(token=forever_tok)  # already touched today by call #1 above
    after_mtime = os.path.getmtime(auth.USERS)
    ok(after_mtime == before_mtime, "same-day re-use does NOT rewrite users.json (throttle)")
    u = auth.get_user("duy")
    lu = next(t.get("last_used") for t in u["tokens"] if t["id"] == tid)
    ok(lu is not None and lu[:10] == time.strftime("%Y-%m-%d"), "last_used was recorded on first use")

    # ------------------------------------------------------------------ 4 ---
    print("\n_token_stale(): fresh vs >90d")
    fresh = {"created": time.strftime("%Y-%m-%d %H:%M:%S")}
    ok(not auth._token_stale(fresh), "a just-created token is not stale")
    old_ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 91 * 86400))
    stale_by_created = {"created": old_ts}
    ok(auth._token_stale(stale_by_created), ">90d since created, never used -> stale")
    stale_by_last_used = {"created": time.strftime("%Y-%m-%d %H:%M:%S"), "last_used": old_ts}
    ok(auth._token_stale(stale_by_last_used),
       ">90d since last_used wins over a recent created date")
    recently_used = {"created": old_ts, "last_used": time.strftime("%Y-%m-%d %H:%M:%S")}
    ok(not auth._token_stale(recently_used),
       "old created but recent last_used -> NOT stale (last_used is the real signal)")

    # ------------------------------------------------------------------ 5 ---
    print("\nGET /users surfaces last_used/expires/stale (real HTTP round trip)")
    import http.client
    import threading
    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from spine.storage import events
    events.SET = os.path.join(tmp, "settings.json")
    from spine.auth import policy
    policy.LIVE = os.path.join(tmp, "policy_live.json")
    db.init(role="tool")

    from spine.http import server
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    port = httpd.server_address[1]
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    try:
        sid = auth.login("duy", "a-real-password")
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conn.request("GET", "/users", headers={"Cookie": "sd_session=%s" % sid})
        r = conn.getresponse()
        body = json.loads(r.read())
        conn.close()
        ok(r.status == 200, "GET /users -> 200")
        u = next(x for x in body if x["name"] == "duy")
        fields = {k for tk in u["tokens"] for k in tk}
        ok({"last_used", "expires", "stale"} <= fields,
           "every token in the response carries last_used/expires/stale")
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
