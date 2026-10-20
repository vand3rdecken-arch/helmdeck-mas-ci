# -*- coding: utf-8 -*-
"""External-agent access grants (logic: spine/auth/access_grants.py; the door
they open: spine/http/mcp.py).

  GET  /access/grants          my grants (never the token) + their last uses
  POST /access/grants          {label, hours, scope:[{kind,id,write}]} -> the
                               grant AND its one-time claim code, shown this once
  POST /access/grants/revoke   {id}

The issuer is ALWAYS the authenticated caller; a grant never reaches further
than the caller does, checked at issue and again at every call.
"""
import json

from spine.auth import access_grants


def grants_get(self, user):
    from spine.comms import mcp_door
    return self._send(200, json.dumps({"grants": access_grants.mine(user),
                                       "door": mcp_door.state()}))


def grants_post(self, user, body):
    hours = body.get("hours")
    try:
        g, code = access_grants.grant(user, body.get("label", ""), body.get("scope"),
                                       24 if hours is None else hours,
                                       sealed_only=body.get("sealed_only", True) is not False)
    except (ValueError, TypeError) as e:
        return self._send(400, json.dumps({"error": str(e)}))
    from spine.comms import mcp_door
    return self._send(200, json.dumps(dict(g, code=code, url=mcp_door.public_url(),
                                           key=mcp_door.door_pub(), shim_sha=mcp_door.shim_sha())))


def grants_revoke_post(self, user, body):
    try:
        return self._send(200, json.dumps(access_grants.revoke(user, body.get("id", ""))))
    except ValueError as e:
        return self._send(404, json.dumps({"error": str(e)}))


GET_ROUTES = {"/access/grants": grants_get}
POST_ROUTES = {"/access/grants": grants_post, "/access/grants/revoke": grants_revoke_post}
