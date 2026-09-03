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
    from cells.copilot.planning import pm
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
    from cells.copilot.planning import pm
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
    from spine.storage import configreview, projectconfig
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
        # WHAT IS PHYSICALLY STORED, beside what currently resolves. `rules`
        # above answers "which value applies and from which layer"; this answers
        # "which rows exist at all" - including rows for projects this request
        # did not select and rows nothing declares any more, neither of which the
        # resolved view can show by construction. Same request rather than a
        # second route: the two halves describe one store and would be read
        # together every time, and a screen that had to fetch them separately
        # could render them a refresh apart and disagree with itself.
        "stored": configreview.review(project),
    }, ensure_ascii=False))


def harness_brief_get(self, user):
    """THE BRIEF, READ-ONLY, as the owner may see it (design doc section 4.3).

    ?surface=pm|voice|wear|glass|... picks which of Henry's briefs; ?repo= picks
    the project layer, same as /harness/config. Segments rather than a string:
    the values arrive tagged with the rule that produced them, so the view can
    chip them in place and route a tap to the row that sets it - "highlighted
    means adjustable", which is the one thing every user of an email-template
    editor already knows.

    Same render as the spawn uses (harness.brief_segments shares brief()'s
    parts), so this cannot reassure the owner about a brief that is not the
    brief."""
    from urllib.parse import parse_qs, urlparse

    from spine.registry import harness
    from spine.storage import projectconfig
    q = parse_qs(urlparse(self.path).query)
    surface = (q.get("surface") or ["pm"])[0].strip()
    repo = (q.get("repo") or [""])[0].strip()
    surf = next((s for s in harness.SURFACES if s["key"] == surface), None)
    if surf is None:
        return self._send(404, json.dumps({"error": "no such surface: %s" % surface[:40]}))
    project = projectconfig.project_key(repo)
    segs = harness.brief_segments(surf["agent"], project)
    return self._send(200, json.dumps({
        "surface": surface, "label": surf["label"], "agent": surf["agent"],
        "project": project,
        "segments": segs,
        # The owner sees how big the thing is; the phase-2 acceptance already
        # tracks this number, so it is reported rather than recomputed here.
        "chars": sum(len(s["text"]) for s in segs),
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


EXPORT_VERSION = 1


def harness_export_get(self, user):
    """THE HARNESS, as one JSON document (config-consolidation phase 6, owner
    decree: "einer stellt seine harness ein und kann dieses exportieren").

    Everything that lives in the db config planes this decree moved config
    INTO, assembled read-only: workspace config, the composed policy doc,
    every project's overlay, every account's profile, Henry's memory, every
    process TEMPLATE (the process/config split, 2026-09-03: a template's step
    SHAPE is config an owner configures and should travel with the harness; a
    process RUN is work, deliberately excluded, same as cards). Deliberately
    NOT the harness .md brief files (board-copilot.md, pm.md, ...) - those are
    already version-controlled in the repo itself, which is a strictly better
    export than re-embedding their text in this JSON (git gives history and
    diffs; a JSON blob would not).

    Owner-only: workspace config can hold real secrets (jira.api_token,
    relay.sk, the fcm service account...). `?secrets=0` masks anything whose
    KEY name matches the same pattern save_settings already audits with
    (events._masked) - present so a support handoff can still see the SHAPE
    of a config without seeing the values."""
    if not user or user["role"] != "owner":
        return self._send(403, json.dumps({"error": "owner only"}))
    from urllib.parse import parse_qs, urlparse
    from spine.storage import db, events
    from spine.auth import policy
    mask_secrets = (parse_qs(urlparse(self.path).query).get("secrets") or ["1"])[0] == "0"

    workspace = events.settings()
    if mask_secrets:
        workspace = {k: events._masked(v, k) for k, v in workspace.items()}

    projects = {p: db.project_config_get(p) for p in db.project_config_projects()}
    accounts = {u: db.user_config_get(u) for u in db.user_config_users()}

    return self._send(200, json.dumps({
        "version": EXPORT_VERSION,
        "exported_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()),
        "workspace": workspace,
        "policy": policy.load(),
        "project_overlays": projects,
        "user_overlays": accounts,
        "memory": db.memory_all(),
        "process_templates": db.process_template_all(),
    }, ensure_ascii=False))


def harness_import_post(self, user, body):
    """Replay an exported harness document EXCLUSIVELY through the existing
    tracked writers - never a raw db write - so every validator, checkpoint
    and audit entry a hand-typed change would trigger fires here too. A
    section missing from the body is left untouched, not cleared: import is
    a MERGE onto whatever this workspace already has, the same reasoning
    save_settings already applies per-key.

    Owner-only, same reason as the export. Reports per-section success/error
    rather than failing the whole request on one bad project - one workspace
    that rejects a stale project overlay must not also lose the ninety that
    are fine."""
    if not user or user["role"] != "owner":
        return self._send(403, json.dumps({"error": "owner only"}))
    if not isinstance(body, dict):
        return self._send(400, json.dumps({"error": "import body must be an object"}))
    from spine.storage import db, events, projectconfig, userconfig
    from spine.auth import policy
    result = {}

    ws = body.get("workspace")
    if isinstance(ws, dict) and ws:
        events.save_settings(ws, actor=user["name"], reason="harness import")
        result["workspace"] = "ok"

    pol = body.get("policy")
    if isinstance(pol, dict):
        for section in ("policies", "charter", "capability_charter"):
            patch = pol.get(section)
            if isinstance(patch, dict) and patch:
                try:
                    policy.swap(section, patch, actor=user["name"], note="harness import")
                    result["policy." + section] = "ok"
                except policy.PolicyDenied as e:
                    result["policy." + section] = "refused: %s" % e

    for project, patch in (body.get("project_overlays") or {}).items():
        if not isinstance(patch, dict) or not patch:
            continue
        _, err = projectconfig.write(project, patch, actor=user["name"], note="harness import")
        result["project:" + project] = err or "ok"

    for account, patch in (body.get("user_overlays") or {}).items():
        if not isinstance(patch, dict) or not patch:
            continue
        _, _, err = userconfig.write(account, patch, actor=user["name"])
        result["user:" + account] = err or "ok"

    memory = body.get("memory")
    if isinstance(memory, dict):
        for name, note in memory.items():
            content = (note or {}).get("content")
            if isinstance(content, str):
                db.memory_put(name, content, actor=user["name"])
        if memory:
            result["memory"] = "ok"

    templates = body.get("process_templates")
    if isinstance(templates, dict):
        from cells.engineer.chains import processes
        for tid, doc in templates.items():
            if not isinstance(doc, dict):
                continue
            try:
                processes.save_template(doc.get("name", tid), doc.get("description", ""),
                                        doc.get("steps") or [], tid=tid, actor=user["name"])
                result["template:" + tid] = "ok"
            except ValueError as e:
                result["template:" + tid] = "refused: %s" % e

    return self._send(200, json.dumps({"ok": True, "result": result}, ensure_ascii=False))


GET_ROUTES = {
    "/settings": settings_get,
    "/nightshift": nightshift_get,
    "/usage": usage_get,
    "/automation": automation_get,
    "/harness/config": harness_config_get,
    "/harness/brief": harness_brief_get,
    "/harness/export": harness_export_get,
}
POST_ROUTES = {
    "/settings": settings_post,
    "/harness/config": harness_config_post,
    "/harness/import": harness_import_post,
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
    # The brief is the instruction set Henry's turns run under - the same
    # capability that guards the knobs around it, and the same one /harness
    # (the editor) already sits behind.
    "/harness/brief": "settings.read",
    # settings.read is the closed vocabulary's ceiling (operator can hold it);
    # the export handler enforces the STRICTER owner-only check itself
    # (it contains real secrets an operator must not read) - the capability
    # here is only what makes this route visible in the coverage sweep at
    # all, not the actual gate.
    "/harness/export": "settings.read",
}
POST_CAPS = {
    "/settings": "settings.write",
    "/harness/config": "settings.write",
    "/harness/import": "settings.write",
}
