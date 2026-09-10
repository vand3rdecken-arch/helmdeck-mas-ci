# -*- coding: utf-8 -*-
"""Invitation routes (owner decree 2026-09-09, 22:15) - the ONE way a person
joins this workspace. See spine/auth/invites.py for the object model.

Same dispatch-table shape as routes_auth.py, and the capability declarations
below are what spine/auth/permissions.py's central gate reads: there is no
inline `if user["role"] != "owner"` in this module, because managing who is in
the workspace is exactly `users.manage` - the same capability that already
guards /users. Adding a second, hand-rolled floor here would be the drift the
permission registry exists to remove.
"""
import json


def invites_get(self, user):
    from spine.auth import invites
    return self._send(200, json.dumps(invites.list_all()))


def invites_post(self, user, body):
    """Create an invitation. The role is chosen HERE, at invitation time -
    that is the whole point of the redesign, and why there is no longer a
    workspace-wide `default_role` for a signup to inherit."""
    from spine.auth import invites
    try:
        inv = invites.create(role=(body.get("role") or "").strip(),
                             actor=user["name"],
                             ttl_days=body.get("ttl_days"),
                             note=body.get("note") or "")
    except ValueError as e:
        return self._send(400, json.dumps({"error": str(e)}))
    return self._send(200, json.dumps(inv))


def invite_revoke_post(self, user, code):
    from spine.auth import invites
    try:
        return self._send(200, json.dumps(invites.revoke(code, actor=user["name"])))
    except ValueError as e:
        return self._send(400, json.dumps({"error": str(e)}))


GET_ROUTES = {"/invites": invites_get}
POST_ROUTES = {"/invites": invites_post}
# Read by permissions.cap_for() through _CAP_MODULES. The per-code revoke is a
# path-param route and therefore lives in permissions.PATTERNS instead, next to
# the /users/* entries it mirrors.
GET_CAPS = {"/invites": "users.manage"}
POST_CAPS = {"/invites": "users.manage"}
