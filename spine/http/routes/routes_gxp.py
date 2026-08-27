# -*- coding: utf-8 -*-
"""POST /gxp/activate - the UI entry point for GxP mode (ops/docs/backlog/
rbac-gxp card 6; spine/auth/gxp.py's own module docstring, WHY THIS IS CODE
AND NOT A POLICY FLAG). Deliberately the ONLY route this module has:
deactivation stays host-filesystem + daemon-restart only, by design.

Re-auth pattern is identical to routes_sign.py's (the existing GxP
e-signature precedent): password verified via auth.verify_password, actor is
ALWAYS the authenticated session's own name, never a body field - an actor
string is spoofable, a verified password is not. The capability check
(gxp.activate, owner-only in the seeded matrix) runs centrally in server.py
before this handler is even reached; this function only handles what a
capability check cannot: re-authentication and the write itself.
"""
import json

from spine.auth import auth


def gxp_state_get(self, user):
    from spine.auth import gxp
    return self._send(200, json.dumps(gxp.state()))


def gxp_activate_post(self, user, body):
    if not auth.verify_password(user["name"], body.get("password") or ""):
        return self._send(401, json.dumps({"error": "password not accepted"}))
    from spine.auth import gxp
    repos = body.get("repos")
    if repos is not None and not isinstance(repos, list):
        return self._send(400, json.dumps({"error": "repos must be a list of paths, or omitted for workspace-wide scope"}))
    rec = gxp.activate(repos=repos, four_eyes=bool(body.get("four_eyes")),
                       activated_by=user["name"])
    return self._send(200, json.dumps(rec))


GET_ROUTES = {"/gxp/state": gxp_state_get}
GET_CAPS = {"/gxp/state": "gxp.activate"}
POST_ROUTES = {"/gxp/activate": gxp_activate_post}
POST_CAPS = {"/gxp/activate": "gxp.activate"}
