# -*- coding: utf-8 -*-
"""Route-level smoke test for server.py's H handler (Route 1: prerequisite for
splitting the do_GET/do_POST dispatch into modules — this pins the OBSERVABLE
behavior of a representative route slice so a future refactor can be verified
against real HTTP responses, not just import-time compile checks).

Self-sandboxing: db/auth/events are ALL redirected to a temp dir BEFORE any of
them touch disk, so this never reads or writes the real helmdeck.db/users.json/
settings.json. The server binds to 127.0.0.1:0 (OS-assigned ephemeral port) in
a background thread — it never touches :8140, so it cannot collide with (or
evict) a live daemon. `serve()` itself is NEVER called (it takes the singleton
port lock and would evict a running daemon).

Run: py -3.12 test_server_routes.py
"""
import http.client
import json
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_fails = []
def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-route-test-")

    # sandbox EVERYTHING with disk state, before any of it is touched. db.ROOT
    # is the critical one: db.init() reads/MIGRATES ROOT/tracks.json and
    # ROOT/events.jsonl (renaming them to *.imported) using that same global -
    # patching only DBPATH still lets init() touch the REAL daemon/events.jsonl
    # (measured the hard way: a first draft of this test renamed the live
    # events.jsonl to .imported before this guard existed - recovered by
    # renaming it back, no data lost, but never again: ROOT must be sandboxed).
    import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    import auth
    auth.USERS = os.path.join(tmp, "users.json")
    auth.SESS = os.path.join(tmp, "sessions.json")
    import events
    events.SET = os.path.join(tmp, "settings.json")

    db.init(role="tool")   # NOT role="daemon" - this process owns no driver sessions

    # a real owner user + session, so authenticated routes are exercised too
    auth.create_user("routetest-owner", "s4ndb0x-pw", "owner")
    sid = auth.login("routetest-owner", "s4ndb0x-pw")
    ok(bool(sid), "sandbox owner created + logged in")

    import server
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.H)
    port = httpd.server_address[1]
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    try:
        def req(method, path, body=None, cookie=None, expect=None):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            headers = {"Content-Type": "application/json"}
            if cookie:
                headers["Cookie"] = "sd_session=%s" % cookie
            payload = json.dumps(body).encode("utf-8") if body is not None else None
            conn.request(method, path, body=payload, headers=headers)
            r = conn.getresponse()
            data = r.read()
            conn.close()
            try:
                parsed = json.loads(data) if data else None
            except ValueError:
                parsed = None
            if expect is not None:
                ok(r.status == expect, "%s %s -> %d (want %d)" % (method, path, r.status, expect))
            return r.status, parsed

        # -- public route: no auth needed, no cookie -------------------------
        status, body = req("GET", "/auth/state", expect=200)
        ok(isinstance(body, dict) and "setup_needed" in body, "/auth/state shape: setup_needed present")
        ok(body.get("user") is None, "/auth/state: anonymous request has no user")

        # -- unauthenticated request to an owner-only route is refused -------
        req("GET", "/policy", expect=403)

        # -- authenticated routes, real session cookie ------------------------
        status, body = req("GET", "/me", cookie=sid, expect=200)
        ok(isinstance(body, dict) and body.get("name") == "routetest-owner",
           "/me returns the logged-in owner")

        status, body = req("GET", "/tracks", cookie=sid, expect=200)
        ok(isinstance(body, list) and body == [], "/tracks: empty list on a fresh sandboxed DB")

        status, body = req("GET", "/dashboard/data", cookie=sid, expect=200)
        ok(isinstance(body, dict) and "capacity" in body, "/dashboard/data shape: capacity present")

        # -- settings/automation group (routes_settings.py) --------------------
        status, body = req("GET", "/settings", cookie=sid, expect=200)
        ok(isinstance(body, dict), "/settings shape: a dict (the raw settings blob)")

        status, body = req("GET", "/nightshift", cookie=sid, expect=200)
        ok(isinstance(body, dict), "/nightshift shape: a dict (pm.status() alias)")

        status, body = req("GET", "/usage", cookie=sid, expect=200)
        ok(isinstance(body, dict), "/usage shape: a dict (usage.snapshot())")

        status, body = req("GET", "/automation", cookie=sid, expect=200)
        ok(isinstance(body, dict) and "config_schema" in body and "loop_states" in body,
           "/automation shape: config_schema+loop_states present")

        status, body = req("POST", "/settings", {"value_per_card": 123}, cookie=sid, expect=200)
        ok(isinstance(body, dict), "/settings POST accepted a patch, returned the saved settings")
        status, body = req("GET", "/settings", cookie=sid, expect=200)
        ok(body.get("value_per_card") == 123, "/settings POST actually persisted the patch")

        # -- glasses group (routes_glance.py) - token-gated, no session needed ---
        status, body = req("GET", "/glance", expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/glance with no token configured: refused")

        status, body = req("GET", "/glance/voice/doesnotexist.mp3", expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/glance/voice with no token configured: refused")

        status, body = req("POST", "/glance/talk", {"message": "hi"}, expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/glance/talk with no token configured: refused")

        status, body = req("POST", "/glance/answer", {"id": "x"}, expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/glance/answer with no token configured: refused")

        # set a real glance_token, then exercise the token-checked (not the
        # feature-flag-checked) half of each route - proves the dispatch-table
        # move preserved the token comparison exactly.
        req("POST", "/settings", {"glance_token": "test-tok-123"}, cookie=sid, expect=200)
        status, body = req("GET", "/glance?token=wrong", expect=403)
        ok(isinstance(body, dict) and body.get("error"), "/glance with wrong token: refused")
        status, body = req("GET", "/glance?token=test-tok-123", expect=200)
        ok(isinstance(body, dict) and "needs_you" in body and "econ" in body,
           "/glance with correct token: real glance_payload shape (needs_you+econ)")
        status, body = req("POST", "/glance/talk", {"token": "test-tok-123", "message": "hi"}, expect=403)
        ok(body.get("error", "").startswith("talking to the board agent"),
           "/glance/talk with correct token but glance_talk unset: feature-flag refusal (not a token error)")
        status, body = req("POST", "/glance/answer", {"token": "test-tok-123", "id": "x"}, expect=403)
        ok(body.get("error", "").startswith("deciding from the glasses"),
           "/glance/answer with correct token but glance_decide unset: feature-flag refusal")

        # rejected relay url (plain http, not localhost) - real validation path
        status, body = req("POST", "/settings", {"relay": {"url": "http://evil.example.com"}},
                           cookie=sid, expect=400)
        ok(isinstance(body, dict) and body.get("error"), "/settings POST rejects an insecure relay url")

        status, body = req("GET", "/loop/map", cookie=sid, expect=200)
        ok(isinstance(body, dict) and "runtime" in body and "build" in body,
           "/loop/map shape: runtime+build present (apimeta._lane_flow + _loop_machine)")

        status, body = req("GET", "/policy", cookie=sid, expect=200)
        ok(isinstance(body, dict) and "policies" in body, "/policy shape: policies present (owner authorized)")

        # -- a POST route: filing a real card through the live HTTP path -----
        status, body = req("POST", "/tracks/new",
                           {"repo": tmp, "task": "route-smoke-test card", "lane": "backlog"},
                           cookie=sid)
        # tmp is not a git repo, so this should be REJECTED, not silently accepted
        # (test_dispatch_visibility.py pins the same "no silent backlog fallback" law)
        ok(status in (400, 200), "/tracks/new against a non-repo path returns a real status: %d" % status)
        if status == 200:
            ok(isinstance(body, dict) and body.get("error"), "/tracks/new non-repo: error surfaced in the 200 body")

        # -- logout: cookie is invalidated, the general auth gate (line ~259 of
        # server.py: `if p not in self.OPEN and not user: 401`) now refuses /me
        # before its route body (which assumes an authenticated user) ever runs.
        req("POST", "/auth/logout", cookie=sid, expect=200)
        status, body = req("GET", "/me", cookie=sid, expect=401)
        ok(isinstance(body, dict) and body.get("error") == "auth required",
           "/me after logout: refused by the general auth gate")

    finally:
        httpd.shutdown()
        th.join(timeout=5)

    print(("\n%d FAILURE(S)" % len(_fails)) if _fails else "\nALL PASS")
    sys.exit(1 if _fails else 0)


if __name__ == "__main__":
    main()
