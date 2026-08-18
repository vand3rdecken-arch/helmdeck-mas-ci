# -*- coding: utf-8 -*-
"""Policy control-plane routes - second slice of server.py's dispatch-table
split (see routes_auth.py for the pattern/rationale). GET /policy (canonical
seeded policy/charter, full-dynamism decree), POST /policy/swap (the ONLY
mutation path - routed through policy.swap so every change is tracked +
reversible), POST /reconfig/track (mirrors app-kernel swaps into the same
append-only events sink as daemon swaps). Bodies are byte-identical to the
inline blocks they replace.
"""
import json


def policy_get(self, user):
    if not user or user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    import policy
    return self._send(200, json.dumps(policy.load()))


def policy_swap(self, user, body):
    if not user or user["role"] != "owner":
        return self._send(403, json.dumps({"error": "owner only"}))
    import policy
    try:
        before = policy.swap(body.get("section") or "policies",
                             body.get("patch") or {},
                             actor=body.get("actor") or "user",
                             note=body.get("note"))
    except policy.PolicyDenied as e:
        return self._send(403, json.dumps({"error": str(e)}))
    return self._send(200, json.dumps({"ok": True, "before": before,
                                       "policy": policy.load()}))


def reconfig_track(self, user, body):
    if not user or user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    import events
    events.emit("reconfig", "-", source="app",
                op=body.get("op"), pluginId=body.get("pluginId"),
                actor=body.get("actor"), replaced=body.get("replaced"),
                note=body.get("note"), by=user["name"])
    return self._send(200, json.dumps({"ok": True}))


GET_ROUTES = {
    "/policy": policy_get,
}
POST_ROUTES = {
    "/policy/swap": policy_swap,
    "/reconfig/track": reconfig_track,
}
