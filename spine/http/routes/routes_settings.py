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

from spine.http.apimeta import _loop_machine, _config_schema


def settings_get(self, user):
    from spine.storage import events
    return self._send(200, json.dumps(events.settings()))


def nightshift_get(self, user):
    from cells.pm import pm
    return self._send(200, json.dumps(pm.status()))


def usage_get(self, user):
    # Claude subscription usage (5h + weekly rate-limit windows) with pacing,
    # from the same source as Paseo's usage tab. Owner-only: it's the owner's
    # account. Cached in usage.py so a poll doesn't hammer the endpoint.
    from spine.ops import usage
    return self._send(200, json.dumps(usage.snapshot()))


def automation_get(self, user):
    # everything about the auto-working machinery in one place: the
    # night shift (is it on, repos, limits, tonight's plan), the policy
    # (auto-dispatch/accept), and the build-loop state machine + where
    # it currently sits - so the UI can expose "what is the harness doing".
    from spine.storage import events
    from cells.pm import pm
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


def harness_config_get(self, user):
    """HENRY'S RULES, resolved for one project (harness-config-ui phase 3).

    The half of the harness screen that /loop/map does not already answer.
    Deliberately NOT a superset of it: the stations, their knobs, the laws and
    the Henry track all arrive on /loop/map today and the screen reads both, so
    neither route describes the machine twice.

    ?repo= picks the project layer. Absent means the workspace layer, which is
    the honest answer for a board question that names no repo - not a fallback.
    The resolved `project` comes back so the screen can badge with the key the
    daemon actually used rather than re-deriving it from the repo string."""
    from urllib.parse import parse_qs, urlparse

    from spine.registry import behavior, harness
    from spine.storage import projectconfig
    repo = (parse_qs(urlparse(self.path).query).get("repo") or [""])[0].strip()
    project = projectconfig.project_key(repo)
    return self._send(200, json.dumps({
        "project": project,
        "repo": repo,
        # The badge vocabulary, server-owned like DOORS/SCOPES: the app mirrors
        # the order rather than re-declaring which layer beats which.
        "layers": list(projectconfig.LAYERS),
        "blocks": [dict(b) for b in behavior.BLOCKS],
        "rules": behavior.describe(project),
        # {key,label} only - the screen labels a per-surface row without
        # learning what a surface IS, and a surface added to harness.SURFACES
        # shows up here by itself.
        "surfaces": [{"key": s["key"], "label": s["label"]} for s in harness.SURFACES],
    }, ensure_ascii=False))


def harness_config_post(self, user, body):
    """Set or clear behaviour-rule values. {repo, values: {path: value|null}}.

    null CLEARS, which is how a row's "zuruecksetzen" link restores inheritance
    rather than pinning the current effective value - the difference the whole
    chain is built around.

    The caller does NOT choose the layer: projectconfig.write_scoped reads each
    rule's own `scope` and routes workspace rules to settings.json and project
    rules to the project table. That is what keeps the two edit paths this card
    ships - tap the row, or tell Henry - landing in the same place with the same
    audit entry, instead of agreeing by convention."""
    from spine.storage import projectconfig
    values = body.get("values")
    if not isinstance(values, dict) or not values:
        return self._send(400, json.dumps({"error": "values must be a non-empty object"}))
    project = projectconfig.project_key((body.get("repo") or "").strip())
    before, err = projectconfig.write_scoped(values, project=project,
                                             actor=user["name"], note="harness screen")
    if err:
        # 400 with the rule's own why-sentence: a refusal the owner cannot read
        # is indistinguishable from a bug, and the screen shows this text.
        return self._send(400, json.dumps({"error": err}, ensure_ascii=False))
    return self._send(200, json.dumps({"ok": True, "before": before, "project": project},
                                      ensure_ascii=False))


def settings_post(self, user, body):
    from spine.storage import events
    rel = body.get("relay")
    if isinstance(rel, dict) and rel.get("url"):
        from spine.comms import relay_client
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
    "/harness/config": harness_config_get,
}
POST_ROUTES = {
    "/settings": settings_post,
    "/harness/config": harness_config_post,
}
# Capability declarations (spine/auth/permissions.py) - the central guard in
# server.py enforces these BEFORE the handler runs; every check that used to
# be inline above is now here instead, one place, matched 1:1 to GET_ROUTES/
# POST_ROUTES.
GET_CAPS = {
    "/settings": "settings.read", "/nightshift": "settings.read",
    "/usage": "settings.read", "/automation": "settings.read",
    # The rules ARE workspace policy - the same capability that guards the knobs
    # they sit beside. Anything weaker would let a role read Henry's instructions
    # it may not read the settings behind.
    "/harness/config": "settings.read",
}
POST_CAPS = {
    "/settings": "settings.write",
    "/harness/config": "settings.write",
}
