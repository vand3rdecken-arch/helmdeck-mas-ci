# -*- coding: utf-8 -*-
"""Auth routes - the first slice of server.py's H handler split into a
dispatch table (proof of the pattern, verified by test_server_routes.py).

Each function is the EXACT body that used to live inline in do_GET/do_POST's
`if p == "/auth/...":` chain, now taking `self` (the H instance - so
self._send/_send_cookie/_sid/rfile/headers are unchanged) plus the already-
computed `user` and, for POST, the parsed `body`. server.py's do_GET/do_POST
check GET_ROUTES/POST_ROUTES BEFORE falling through to the remaining inline
chain, so this is purely additive - every other route is byte-identical to
before.
"""
import json


def auth_state(self, user):
    from spine.auth import auth
    from spine.storage import events
    reg = events.settings().get("registration") or {}
    return self._send(200, json.dumps(
        {"setup_needed": not auth.list_users(), "user": user,
         "registration": bool(reg.get("open") or reg.get("invite_code")),
         "registration_open": bool(reg.get("open"))}))


def auth_setup(self, user, body):
    from spine.auth import auth
    if auth.list_users():
        return self._send(403, json.dumps({"error": "already set up"}))
    try:
        auth.create_user(body.get("name", ""), body.get("password", ""), "owner")
    except ValueError as e:
        return self._send(400, json.dumps({"error": str(e)}))
    sid = auth.login(body["name"], body["password"])
    # Same reasoning as auth_login below: the app's request layer needs a real
    # Bearer token, not just the cookie, to actually use the account it just
    # created.
    tok = auth.issue_token(body["name"], "web-login")
    return self._send_cookie(200, json.dumps({"ok": True, "token": tok}), sid=sid)


def auth_register(self, user, body):
    import secrets as _s
    from spine.auth import auth
    from spine.storage import events
    reg = events.settings().get("registration") or {}
    code = (body.get("invite") or "").strip()
    if not reg.get("open"):
        want = reg.get("invite_code") or ""
        if not want or not code or not _s.compare_digest(code, want):
            return self._send(403, json.dumps({"error": "valid invite code required"}))
    try:
        auth.create_user(body.get("name", ""), body.get("password", ""),
                         reg.get("default_role", "client"))
    except ValueError as e:
        return self._send(400, json.dumps({"error": str(e)}))
    # optional enrichment only - never touches the user record
    # above, never blocks/fails the signup if Loops is down.
    email = (body.get("email") or "").strip()
    if email:
        import threading
        from spine.comms import loops_client
        threading.Thread(target=loops_client.signup_contact,
                         args=(email, body.get("name", "")),
                         daemon=True).start()
    sid = auth.login(body["name"], body["password"])
    # Same reasoning as auth_login below: the app's request layer needs a real
    # Bearer token, not just the cookie.
    tok = auth.issue_token(body["name"], "web-login")
    return self._send_cookie(200, json.dumps({"ok": True, "token": tok}), sid=sid)


def auth_login(self, user, body):
    from spine.auth import auth
    name = body.get("name", "")
    sid = auth.login(name, body.get("password", ""))
    if not sid:
        return self._send(401, json.dumps({"error": "wrong name or password"}))
    # The app's own request layer (client.ts) authenticates every call with a
    # Bearer token from useConfig().token, not the sd_session cookie below -
    # that cookie alone would never actually authenticate the app's fetches
    # (different mechanism, cross-origin in dev besides). Mint a real device
    # token for the just-authenticated user too, via the SAME auth.issue_token
    # the owner-only /users/<name>/tokens route and /surfaces/relay/pair's QR flow
    # already use - no new auth primitive. Backward compatible: the cookie is
    # still set for anything that reads it, `token` is just an added field.
    tok = auth.issue_token(name, "web-login")
    return self._send_cookie(200, json.dumps({"ok": True, "token": tok}), sid=sid)


def auth_logout(self, user, body):
    from spine.auth import auth
    if self._sid():
        auth.logout(self._sid())
    return self._send_cookie(200, json.dumps({"ok": True}), clear=True)


GET_ROUTES = {
    "/auth/state": auth_state,
}
POST_ROUTES = {
    "/auth/setup": auth_setup,
    "/auth/register": auth_register,
    "/auth/login": auth_login,
    "/auth/logout": auth_logout,
}
