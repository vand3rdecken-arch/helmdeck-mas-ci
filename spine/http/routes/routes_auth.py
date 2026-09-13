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
    from spine.auth import auth, invites
    from spine.storage import events
    reg = events.settings().get("registration") or {}
    # `registration` = "is there a way to sign up at all", DERIVED from whether
    # any invitation is actually open rather than from a settings flag that
    # could say yes with no live invitation behind it. It used to read
    # `reg.invite_code`, one workspace-wide string; the count leaks nothing (no
    # code, no role, no number) beyond "someone was invited".
    open_invites = invites.count_open()
    return self._send(200, json.dumps(
        {"setup_needed": not auth.list_users(), "user": user,
         "registration": bool(reg.get("open")) or open_invites > 0,
         "registration_open": bool(reg.get("open"))}))


def auth_setup(self, user, body):
    from spine.auth import auth
    if auth.list_users():
        return self._send(403, json.dumps({"error": "already set up"}))
    try:
        auth.create_user(body.get("name", ""), body.get("password", ""), "owner")
    except ValueError as e:
        return self._send(400, json.dumps({"error": str(e)}))
    # accounts-boards-prd phase 3 (section 4.1): the SAME first-run transaction
    # that creates the owner also seeds the default board + one guided example
    # card, so "fresh daemon" and "working board" are never two separate steps
    # an owner could stop between. Best-effort: a seed failure must never lose
    # the account that was just created - the owner would otherwise be locked
    # out of a daemon that thinks it is already set up.
    try:
        from spine.storage import boards
        boards.ensure_default()
        from cells.engineer.cards import dispatch
        dispatch.seed_example_card()
    except Exception as e:                                         # noqa: BLE001
        print("auth_setup: board/example seed failed (%s) - owner account is "
              "still created" % e, flush=True)
    sid = auth.login(body["name"], body["password"])
    # Same reasoning as auth_login below: the app's request layer needs a real
    # Bearer token, not just the cookie, to actually use the account it just
    # created.
    tok = auth.issue_token(body["name"], _device_label(body), device=_device_id(body))
    return self._send_cookie(200, json.dumps({"ok": True, "token": tok}), sid=sid)


def auth_register(self, user, body):
    """Sign up. The role comes from the INVITATION, not from a workspace-wide
    default (owner decree 2026-09-09, 22:15) - so "who is this person allowed
    to be" is decided by the owner who invited them, at the moment they were
    invited, and is carried by the code itself.

    Open registration (no code) is the one remaining exception and it is hard-
    wired to `client`, the weakest role: the knob that used to let self-signup
    mint operators is gone with `default_role`, and a public door that can only
    produce the least-privileged account is the only public door worth having.
    """
    from spine.auth import auth, invites
    from spine.storage import events
    reg = events.settings().get("registration") or {}
    code = (body.get("invite") or "").strip()
    name = (body.get("name") or "").strip()
    claimed = None
    if code:
        try:
            role = invites.claim(code, name)
        except ValueError as e:
            return self._send(403, json.dumps({"error": str(e)}))
        claimed = code
    elif reg.get("open"):
        role = "client"
    else:
        return self._send(403, json.dumps({"error": "valid invite code required"}))
    try:
        auth.create_user(name, body.get("password", ""), role)
    except ValueError as e:
        # The claim is atomic and happens FIRST (invites.claim's docstring), so
        # a rejected password must hand the invitation back - otherwise a typo
        # burns the link and the owner has to mint another one.
        if claimed:
            invites.release(claimed, name)
        return self._send(400, json.dumps({"error": str(e)}))
    # optional enrichment only - never touches the user record
    # above, never blocks/fails the signup if Loops is down.
    email = (body.get("email") or "").strip()
    if email:
        import threading
        from spine.comms import loops_client
        threading.Thread(target=loops_client.signup_contact,
                         args=(email, name), daemon=True).start()
    sid = auth.login(name, body["password"])
    # Same reasoning as auth_login below: the app's request layer needs a real
    # Bearer token, not just the cookie.
    tok = auth.issue_token(name, _device_label(body), device=_device_id(body))
    return self._send_cookie(200, json.dumps({"ok": True, "token": tok}), sid=sid)


# The app sends a stable per-installation id (data/config.ts's `deviceId`) and
# a human label with every sign-in. Both are advisory - an old client, a
# script or curl sends neither, and then this behaves exactly as before: an
# ungrouped token labelled "web-login". Sanitised here rather than trusted:
# the id is a grouping KEY that decides which existing token gets replaced, so
# an over-long or exotic value must not travel into users.json unbounded.
def _device_id(body):
    did = (body.get("device") or "").strip()[:64]
    return "".join(c for c in did if c.isalnum() or c in "-_") or None


def _device_label(body):
    return ((body.get("device_label") or "").strip()[:40]) or "web-login"


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
    # the owner-only /users/<name>/tokens route and /relay/pair's QR flow
    # already use - no new auth primitive. Backward compatible: the cookie is
    # still set for anything that reads it, `token` is just an added field.
    #
    # `device=` is what stops this route from being a token FACTORY: it used to
    # mint one more permanent credential on EVERY sign-in, so the owner panel
    # accumulated a row per login (the 123-line list this card replaces). One
    # live token per device now - signing in again on the same phone replaces
    # that phone's token instead of stacking beside it.
    tok = auth.issue_token(name, _device_label(body), device=_device_id(body))
    return self._send_cookie(200, json.dumps({"ok": True, "token": tok}), sid=sid)


def auth_logout(self, user, body):
    from spine.auth import auth
    if self._sid():
        auth.logout(self._sid())
    return self._send_cookie(200, json.dumps({"ok": True}), clear=True)


def auth_delete_account(self, user, body):
    """Self-service account deletion (App Store guideline 5.1.1(v): an app that
    lets people create an account must let them delete it IN the app). The
    caller can only ever delete THEMSELVES - the name comes from the session,
    never from the body - and must re-prove the password, the same re-auth
    step signing uses, so a phone left unlocked cannot erase an account in one
    tap. The removal itself is auth.delete_user, the one owner of accounts: it
    already drops tokens, sessions, profile rows and personal boards, audits
    the removal, and refuses to delete the last owner."""
    from spine.auth import auth
    if not user:
        return self._send(401, json.dumps({"error": "auth required"}))
    if not auth.verify_password(user["name"], body.get("password") or ""):
        return self._send(401, json.dumps({"error": "password not accepted"}))
    try:
        auth.delete_user(user["name"], actor=user["name"])
    except ValueError as e:
        return self._send(400, json.dumps({"error": str(e)}))
    return self._send_cookie(200, json.dumps({"ok": True}), clear=True)


GET_ROUTES = {
    "/auth/state": auth_state,
}
POST_ROUTES = {
    "/auth/setup": auth_setup,
    "/auth/register": auth_register,
    "/auth/login": auth_login,
    "/auth/logout": auth_logout,
    "/auth/delete-account": auth_delete_account,
}
