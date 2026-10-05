# -*- coding: utf-8 -*-
"""Chat-consent routes (backlog/team-rooms-member stage 7); logic and the rule
in cells/copilot/chat/chat_grants.py.

  GET  /chat/grants                 my grants (given, with who read what) and the
                                    grants naming me (received, active)
  POST /chat/grants                 {grantee, hours}: let an admin read MY chat
  POST /chat/grants/revoke          {id}: withdraw one of MY grants
  GET  /chat/admin?account=<name>   read <name>'s private chat - only under an
                                    active grant naming the caller

The account is ALWAYS the authenticated caller for the first three; only the
last takes an account, and there the grant is the whole authorization.
"""
import json
from urllib.parse import parse_qs, urlparse

from cells.copilot.chat import chat_grants


def grants_get(self, user):
    return self._send(200, json.dumps({
        "given": chat_grants.given(user["name"]),
        "received": chat_grants.received(user["name"])}))


def grants_post(self, user, body):
    hours = body.get("hours")
    try:
        # only a MISSING value defaults; 0 is a real (invalid) answer, not "24"
        g = chat_grants.grant(user["name"], (body.get("grantee") or "").strip(),
                              24 if hours is None else hours)
    except (ValueError, TypeError) as e:
        return self._send(400, json.dumps({"error": str(e)}))
    return self._send(200, json.dumps(g))


def grants_revoke_post(self, user, body):
    try:
        g = chat_grants.revoke(user["name"], body.get("id", ""))
    except ValueError as e:
        return self._send(404, json.dumps({"error": str(e)}))
    return self._send(200, json.dumps(g))


def chat_admin_get(self, user):
    account = (parse_qs(urlparse(self.path).query).get("account") or [""])[0]
    try:
        return self._send(200, json.dumps(chat_grants.read(user["name"], account)))
    except PermissionError:
        # the same answer for "no such account", "no chat" and "no grant"
        return self._send(403, json.dumps({"error": "no active grant from that account"}))


GET_ROUTES = {
    "/chat/grants": grants_get,
    "/chat/admin": chat_admin_get,
}
POST_ROUTES = {
    "/chat/grants": grants_post,
    "/chat/grants/revoke": grants_revoke_post,
}
