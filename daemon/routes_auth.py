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
    import auth, events
    reg = events.settings().get("registration") or {}
    return self._send(200, json.dumps(
        {"setup_needed": not auth.list_users(), "user": user,
         "registration": bool(reg.get("open") or reg.get("invite_code")),
         "registration_open": bool(reg.get("open"))}))


def auth_setup(self, user, body):
    import auth
    if auth.list_users():
        return self._send(403, json.dumps({"error": "already set up"}))
    try:
        auth.create_user(body.get("name", ""), body.get("password", ""), "owner")
    except ValueError as e:
        return self._send(400, json.dumps({"error": str(e)}))
    sid = auth.login(body["name"], body["password"])
    return self._send_cookie(200, json.dumps({"ok": True}), sid=sid)


def auth_register(self, user, body):
    import auth, events, secrets as _s
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
        import threading, loops_client
        threading.Thread(target=loops_client.signup_contact,
                         args=(email, body.get("name", "")),
                         daemon=True).start()
    sid = auth.login(body["name"], body["password"])
    return self._send_cookie(200, json.dumps({"ok": True}), sid=sid)


def auth_login(self, user, body):
    import auth
    sid = auth.login(body.get("name", ""), body.get("password", ""))
    if not sid:
        return self._send(401, json.dumps({"error": "wrong name or password"}))
    return self._send_cookie(200, json.dumps({"ok": True}), sid=sid)


def auth_logout(self, user, body):
    import auth
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
