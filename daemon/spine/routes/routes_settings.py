# -*- coding: utf-8 -*-
"""Settings/automation routes - third slice of server.py's dispatch-table
split (see routes_auth.py for the pattern/rationale). GET /settings, GET
/nightshift (alias - the PM loop is the system now), GET /usage (Claude
subscription usage), GET /automation (nightshift + policy + build-loop state,
one place for "what is the harness doing"), POST /settings (the single write
path for every config knob, via events.save_settings). Bodies are byte-
identical to the inline blocks they replace.
"""
import json

from daemon.spine.apimeta import _loop_machine, _config_schema


def settings_get(self, user):
    from daemon.spine import events
    if user["role"] != "owner":
        return self._send(403, json.dumps({"error": "owner only"}))
    return self._send(200, json.dumps(events.settings()))


def nightshift_get(self, user):
    from daemon.cells.pm import pm
    if user["role"] != "owner":
        return self._send(403, json.dumps({"error": "owner only"}))
    return self._send(200, json.dumps(pm.status()))


def usage_get(self, user):
    # Claude subscription usage (5h + weekly rate-limit windows) with pacing,
    # from the same source as Paseo's usage tab. Owner-only: it's the owner's
    # account. Cached in usage.py so a poll doesn't hammer the endpoint.
    if user["role"] != "owner":
        return self._send(403, json.dumps({"error": "owner only"}))
    from daemon.spine import usage
    return self._send(200, json.dumps(usage.snapshot()))


def automation_get(self, user):
    # everything about the auto-working machinery in one place: the
    # night shift (is it on, repos, limits, tonight's plan), the policy
    # (auto-dispatch/accept), and the build-loop state machine + where
    # it currently sits - so the UI can expose "what is the harness doing".
    from daemon.spine import events
    from daemon.cells.pm import pm
    if user["role"] != "owner":
        return self._send(403, json.dumps({"error": "owner only"}))
    s = events.settings(); pol = s.get("policy") or {}
    # ONE definition, shared with /loop/map (see _loop_machine). The
    # hand-written list that used to sit here had drifted: it still
    # promised BUILD would rebuild "Installer / APK / glasses" long
    # after ARTIFACT_SRC was cut down to the signed APK alone.
    _machine = _loop_machine()
    loop_states = [[st["key"], st["instruction"]] for st in _machine["states"]]
    current = _machine["current"]
    config_schema = _config_schema(s)
    return self._send(200, json.dumps({
        "nightshift": pm.status(),   # alias key: the PM loop's status
        "policy": {k: pol.get(k) for k in ("auto_dispatch_modes", "auto_dispatch_priority",
                  "auto_accept_green", "chat_admin_roles", "chat_configure_roles")},
        "config_schema": config_schema,
        "repos": (s.get("pm") or {}).get("repos") or [],
        "default_repo": s.get("default_repo"),
        "loop_states": [{"state": st, "desc": d} for st, d in loop_states],
        "loop_current": current,
        # which half of the loop this checkout is actually running
        "loop_mode": _machine.get("mode"),
        "loop_mode_note": _machine.get("mode_note"),
    }))


def settings_post(self, user, body):
    from daemon.spine import events
    if user["role"] != "owner":
        return self._send(403, json.dumps({"error": "owner only"}))
    rel = body.get("relay")
    if isinstance(rel, dict) and rel.get("url"):
        from daemon.spine import relay_client
        if relay_client.insecure_url(rel["url"]):
            return self._send(400, json.dumps({"error":
                "relay url must be https:// (or http://localhost for "
                "local testing) - pairing links carry a device token "
                "and must not cross the network unencrypted"}))
    return self._send(200, json.dumps(events.save_settings(body, actor=user["name"])))


GET_ROUTES = {
    "/settings": settings_get,
    "/nightshift": nightshift_get,
    "/usage": usage_get,
    "/automation": automation_get,
}
POST_ROUTES = {
    "/settings": settings_post,
}
