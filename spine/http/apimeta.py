# -*- coding: utf-8 -*-
"""Declarative app-contract data the API serves - extracted from server.py.
The lane/gate graph (_lane_flow via sessions.flow), the build-loop machine
(_loop_machine via ops/tools/loop_state.py), and _config_schema: the SINGLE
source of truth for every editable knob ("policy is data"), a contract with
app automation.tsx. Module-level so it is importable + checkable. server.py
re-imports the names. Not monkeypatched.
"""
import os

from daemon.paths import REPO_ROOT as _REPO_ROOT


def _loop_state_mod():
    """ops/tools/loop_state.py, imported from the daemon."""
    import sys as _sys
    tools = os.path.join(_REPO_ROOT, "ops", "tools")
    if tools not in _sys.path:
        _sys.path.insert(0, tools)
    import loop_state
    return loop_state


def _lane_flow(lane_labels, repo_view=None):
    """The lane/gate graph. `lanes` (not `nodes`) is the wire name the app
    already reads, so the richer graph arrives as an ADDITION - `edges` is new,
    every existing field keeps its meaning.

    `repo_view` (spine.ops.projects.resolve) makes it repo-specific: every
    station then also carries `active`/`off_reason`, and the `deploy` step joins
    `gate` as a node that sits on an edge. Omit it and the payload is exactly
    what it has always been."""
    try:
        from cells.engineer import sessions
        f = sessions.flow(lane_labels, repo_view=repo_view)
        return {"lanes": f["nodes"], "gate": f["gate"], "deploy": f.get("deploy") or {},
                "stations": f.get("stations") or [], "row": f.get("row") or {},
                "edges": f["edges"], "henry": _henry_track()}
    except Exception as e:                                   # noqa: BLE001
        return {"lanes": [], "gate": {}, "deploy": {}, "stations": [], "row": {},
                "edges": [], "henry": [], "error": str(e)[:200]}


def _henry_track():
    """The band under the station row: where Henry acts, and what he does there
    (harness-config-ui phase 4). Aggregated in spine/registry/behavior.py from
    the rules' `binds`, so the client keeps holding no station list and no rule
    list. Empty rather than absent on failure - a missing band is honest, a
    half-drawn one is not."""
    try:
        from spine.registry import behavior
        return behavior.track()
    except Exception:                                        # noqa: BLE001
        return []


def _loop_machine():
    """The build loop: states + edges + where this checkout currently sits."""
    try:
        return _loop_state_mod().machine()
    except Exception as e:                                   # noqa: BLE001
        return {"title": "Wie Aenderungen gebaut werden", "states": [], "edges": [],
                "current": [{"state": "?", "action": "loop_state: %s" % str(e)[:120]}],
                "error": str(e)[:200]}


CONTROLS = ("toggle", "multi", "single", "text", "number", "labels")

# ---------------------------------------------------------------------------
# THE TWO PLACEMENT VOCABULARIES (accounts-boards-prd phase 4, "settings-hub").
#
# DOORS is the hub's door list; SCOPES is PRD section 3's five-layer model -
# who OWNS a knob, which is simultaneously (a) the badge the row wears and
# (b) which endpoint the row writes to. Both are exported so the app can
# mirror them and ops/tests/test_settings_hub.py can hold the two halves
# equal - a knob tagged with a door the app has no page for, or a scope it
# has no badge for, would render nowhere and say nothing about why.
#
# The door order IS the order the hub lists them in ("boards" sits between
# "general" and "automation", per the PRD's amendment). The app reads this
# order off the schema rather than re-declaring it.
DOORS = ("general", "boards", "automation", "cells", "connections", "team", "system")
SCOPES = ("profile", "board", "workspace", "device", "system")


# settings-ia-redesign (ops/docs/backlog/settings-ia-redesign) phase 1
# "settings-schema-v2" + accounts-boards-prd phase 4: every knob carries the
# metadata the settings hub needs to place, badge and describe it WITHOUT a
# second, hand-maintained table in the client:
#   door     - which of the hub's doors renders this knob (DOORS above).
#   station  - OR: which pipeline station's page renders it (harness-config-ui
#              section 6). Exactly one of door/station, never both: a knob
#              editable in two places is the duplication G4 forbids, and the
#              placement functions drop a row that has neither - which is why a
#              move and the screen that receives it must ship in ONE commit.
#              ops/tests/test_harness_layer.py holds every row to that rule.
#   group    - the section INSIDE that door this knob belongs to, and
#   groupKey - that section's i18n label. Carried on the knob, not in a
#              client-side group->label map, for the same reason `door` is:
#              a new section must cost one daemon entry, not a client edit.
#   level    - "basic" (the door's front, ~3-5 controls per NN/g progressive
#              disclosure) vs "advanced" (behind the door's "Erweitert" fold).
#   descKey  - one-line i18n "what this does", separate from labelKey (the
#              control's own short label) - same two-language contract as
#              labelKey, checked by test_harness_layer.py.
#   scope    - SCOPES above. This is the load-bearing one: the renderer badges
#              the row from it AND routes the write from it (profile ->
#              PUT /me/config, everything else -> POST /settings). G4's "every
#              knob has exactly one owner, one storage location, one edit
#              surface" is therefore a property of the DATA, not a convention
#              the client is trusted to keep.
#   optionLabels - optional {value: i18n key} for single/multi, so an option
#              can read "Deutsch" without the client knowing what "de" is.
#
# Deliberately NOT added, to keep the metadata contract honest rather than
# claim "vollstaendig": the PM subkeys (pm.autonomy gets a real dial in the
# autonomy-dial card), glance_* (door 4's connect wizards), worktree_seed and
# policy.load_admission (a glob LIST and a 4-field object - neither is a
# single knob any control in CONTROLS renders). Each lands with its owning
# card instead of being force-fit here.
def _config_schema(s):
    """The declarative config schema for everything backed by settings.json:
    the SINGLE source of truth for every editable workspace/board/system knob
    ("policy is data"). The app renders each control generically and writes it
    back with saveSettings(nest(path, value)), so a new knob is one entry HERE,
    not hand-wiring in two screens. The fixed ops/harness/laws are NOT in this
    table - they live read-only in /loop/map. The ACCOUNT's own knobs are not
    here either: they have a different owner and a different endpoint, so they
    are _profile_schema() below.

    Module level, not inline in the /automation handler, for the same reason
    _lane_flow and _loop_machine are: the shape it produces is a contract with
    surfaces/app/src/ui/settings_schema_page.tsx, and a contract nothing can
    import is a contract nothing can check. ops/tests/test_harness_layer.py
    reads it from here and holds every `control` to the union the app actually
    renders and every `labelKey` to a two-language entry - a knob with a
    control the app has no branch for renders as NOTHING, silently, on an
    owner-only screen.

    CONTROLS above is that union. Adding a seventh means adding a branch to the
    app's Control component in the same commit; the gate will say so if not."""
    pol = s.get("policy") or {}
    ns = s.get("nightshift") or {}
    cap = s.get("capacity") or {}
    tar = cap.get("tariff") or {}
    return [
        # ---- THE MOVE (design doc section 6). These three knobs GOVERN A
        # STATION, so they belong on that station's page, not in a door named
        # after a category. `station` is the same kind of metadatum `door` is
        # and moves a row the same way policy.lane_labels was moved from
        # Automation to Boards in phase 4 - with no client edit.
        #
        # "Landet bei" means MOVE, never duplicate: the `door` is GONE from each
        # of these in the same commit that gives the station page its rows.
        # Leaving both would put one knob in two places, which the card's own
        # acceptance criterion forbids - and placeRows DROPS a row that has
        # neither, so the two halves genuinely have to ship together.
        {"group": "stationReview", "groupKey": "harness.grp.review",
         "path": "policy.auto_accept_green", "control": "toggle",
         "labelKey": "cfg.autoAccept", "value": bool(pol.get("auto_accept_green")),
         "station": "review", "level": "basic", "descKey": "cfg.autoAccept.desc", "scope": "workspace"},
        {"group": "stationBacklog", "groupKey": "harness.grp.backlog",
         "path": "policy.auto_dispatch_modes", "control": "multi",
         "labelKey": "cfg.autoModes", "options": ["do", "prepare", "cowork"],
         "value": pol.get("auto_dispatch_modes") or [],
         "station": "backlog", "level": "basic", "descKey": "cfg.autoModes.desc", "scope": "workspace"},
        {"group": "stationBacklog", "groupKey": "harness.grp.backlog",
         "path": "policy.auto_dispatch_priority", "control": "single",
         "labelKey": "cfg.autoPrio", "options": ["never", "urgent", "high"],
         "value": pol.get("auto_dispatch_priority") or "never",
         "station": "backlog", "level": "basic", "descKey": "cfg.autoPrio.desc", "scope": "workspace"},
        {"group": "policy", "groupKey": "automation.configPolicy",
         "path": "policy.chat_configure_roles", "control": "multi",
         "labelKey": "cfg.chatRoles", "options": ["owner", "operator"],
         "value": pol.get("chat_configure_roles") or ["owner"],
         "door": "automation", "level": "advanced", "descKey": "cfg.chatRoles.desc", "scope": "workspace"},
        # The one knob that CHANGED door in phase 4. It names the stations a
        # board's columns fall back to, so its owner is the board layer, not
        # the automation one - and PRD section 6 has it migrating into the
        # default board's column labels outright. Tagging it scope "board"
        # and door "boards" is what moves it, with no client edit.
        {"group": "boardLabels", "groupKey": "hub.grp.boardLabels",
         "path": "policy.lane_labels", "control": "labels",
         "labelKey": "cfg.laneLabels", "keys": ["backlog", "working", "review", "done"],
         "value": pol.get("lane_labels") or {},
         "door": "boards", "level": "basic", "descKey": "cfg.laneLabels.desc", "scope": "board"},
        {"group": "night", "groupKey": "automation.nightSection",
         "path": "nightshift.enabled", "control": "toggle",
         "labelKey": "cfg.nightEnabled", "value": bool(ns.get("enabled")),
         "door": "automation", "level": "basic", "descKey": "cfg.nightEnabled.desc", "scope": "workspace"},
        {"group": "night", "groupKey": "automation.nightSection",
         "path": "nightshift.window", "control": "text",
         "labelKey": "cfg.nightWindow", "placeholder": "always", "value": ns.get("window") or "",
         "door": "automation", "level": "advanced", "descKey": "cfg.nightWindow.desc", "scope": "workspace"},
        {"group": "night", "groupKey": "automation.nightSection",
         "path": "nightshift.max_cards", "control": "number",
         "labelKey": "cfg.nightMax", "value": ns.get("max_cards", 3),
         "door": "automation", "level": "advanced", "descKey": "cfg.nightMax.desc", "scope": "workspace"},
        {"group": "night", "groupKey": "automation.nightSection",
         "path": "nightshift.idle_minutes", "control": "number",
         "labelKey": "cfg.nightIdle", "value": ns.get("idle_minutes", 20),
         "door": "automation", "level": "advanced", "descKey": "cfg.nightIdle.desc", "scope": "workspace"},
        # ---- door "system": the old hand-built business panel, dissolved.
        # These nine fields were a bespoke <FormGrid> in settings.tsx with
        # their own saveBusiness(). They are ordinary single-path knobs, so
        # they belong in the table like everything else - which is what makes
        # "settings.tsx dissolves into the hub" true rather than "settings.tsx
        # IS the hub and still hand-draws half of it".
        {"group": "business", "groupKey": "settings.sec.business",
         "path": "default_repo", "control": "text",
         "labelKey": "settings.business.repo", "value": s.get("default_repo") or "",
         "door": "system", "level": "basic", "descKey": "cfg.defaultRepo.desc", "scope": "workspace"},
        # Moved out of door System for the same reason as the three above: how
        # many cards may be in flight is a property of the station where work
        # is taken up, not of "business". Same trade as the others - the System
        # row is gone in this commit, the station row arrives in it.
        {"group": "stationBacklog", "groupKey": "harness.grp.backlog",
         "path": "capacity.wip_limit", "control": "number",
         "labelKey": "settings.business.wip", "value": cap.get("wip_limit", 0),
         "station": "backlog", "level": "basic", "descKey": "cfg.wipLimit.desc", "scope": "workspace"},
        {"group": "business", "groupKey": "settings.sec.business",
         "path": "value_per_card", "control": "number",
         "labelKey": "settings.business.value", "value": s.get("value_per_card", 0),
         "door": "system", "level": "basic", "descKey": "cfg.valuePerCard.desc", "scope": "workspace"},
        {"group": "business", "groupKey": "settings.sec.business",
         "path": "capacity.touch_budget_day", "control": "number",
         "labelKey": "settings.business.budget", "value": cap.get("touch_budget_day", 0),
         "door": "system", "level": "basic", "descKey": "cfg.touchBudget.desc", "scope": "workspace"},
        {"group": "business", "groupKey": "settings.sec.business",
         "path": "capacity.tariff.steer", "control": "number",
         "labelKey": "cfg.tariffSteer", "value": tar.get("steer", 1),
         "door": "system", "level": "advanced", "descKey": "cfg.tariffSteer.desc", "scope": "workspace"},
        {"group": "business", "groupKey": "settings.sec.business",
         "path": "capacity.tariff.review", "control": "number",
         "labelKey": "cfg.tariffReview", "value": tar.get("review", 1),
         "door": "system", "level": "advanced", "descKey": "cfg.tariffReview.desc", "scope": "workspace"},
        {"group": "business", "groupKey": "settings.sec.business",
         "path": "capacity.tariff.bounce", "control": "number",
         "labelKey": "cfg.tariffBounce", "value": tar.get("bounce", 3),
         "door": "system", "level": "advanced", "descKey": "cfg.tariffBounce.desc", "scope": "workspace"},
        # The one genuinely MACHINE-scoped knob with no UI before this card
        # (the settings inventory's `web_url`): where this daemon's web
        # surface is hosted. Not workspace policy - it describes this box.
        {"group": "machine", "groupKey": "hub.grp.machine",
         "path": "web_url", "control": "text",
         "labelKey": "cfg.webUrl", "placeholder": "http://localhost:3300",
         "value": s.get("web_url") or "",
         "door": "system", "level": "advanced", "descKey": "cfg.webUrl.desc", "scope": "system"},
    ]


def _profile_schema(profile):
    """The ACCOUNT's own knobs, same entry shape, different owner.

    WHY A SECOND LIST rather than a `scope` filter over one: these two tables
    do not merely have different scopes, they have different SOURCES, different
    ENDPOINTS and different AUDIENCES. _config_schema reads settings.json and
    rides on /automation, which is `settings.read` - owner-only. A profile is
    the account's own view, readable and writable by a `client`, and it rides
    on /me, the one endpoint every role may call. Serving these rows on
    /automation would mean the weakest role - the one for whom door 1 exists -
    could never see them (accounts-boards-prd section 5's amendment: door 1 is
    account-backed, "jede Rolle").

    The app concatenates both lists and places every row by `door`, so from the
    renderer's side there is exactly one schema and this split is invisible."""
    from spine.storage import userconfig
    p = profile or {}
    app = p.get("appearance") or {}
    return [
        {"group": "profile", "groupKey": "profile.section",
         "path": "lang", "control": "single",
         "labelKey": "ui.language", "options": list(userconfig.LANGS),
         "optionLabels": {"de": "lang.de", "en": "lang.en"},
         "value": p.get("lang") or "de",
         "door": "general", "level": "basic", "descKey": "cfg.lang.desc", "scope": "profile"},
        {"group": "profile", "groupKey": "profile.section",
         "path": "appearance.backdrop", "control": "single",
         "labelKey": "settings.policy.backdrop", "options": list(userconfig.BACKDROPS),
         "value": app.get("backdrop") or "mesh",
         "door": "general", "level": "basic", "descKey": "cfg.backdrop.desc", "scope": "profile"},
    ]
