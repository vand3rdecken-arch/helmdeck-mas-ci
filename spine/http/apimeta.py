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


def _lane_flow(lane_labels):
    """The lane/gate graph. `lanes` (not `nodes`) is the wire name the app
    already reads, so the richer graph arrives as an ADDITION - `edges` is new,
    every existing field keeps its meaning."""
    try:
        from cells.engineer import sessions
        f = sessions.flow(lane_labels)
        return {"lanes": f["nodes"], "gate": f["gate"], "edges": f["edges"]}
    except Exception as e:                                   # noqa: BLE001
        return {"lanes": [], "gate": {}, "edges": [], "error": str(e)[:200]}


def _loop_machine():
    """The build loop: states + edges + where this checkout currently sits."""
    try:
        return _loop_state_mod().machine()
    except Exception as e:                                   # noqa: BLE001
        return {"title": "Wie Aenderungen gebaut werden", "states": [], "edges": [],
                "current": [{"state": "?", "action": "loop_state: %s" % str(e)[:120]}],
                "error": str(e)[:200]}


CONTROLS = ("toggle", "multi", "single", "text", "number", "labels")


# settings-ia-redesign (ops/docs/backlog/settings-ia-redesign), phase 1
# "settings-schema-v2": every knob below now also carries the metadata the
# planned settings hub needs to place and describe it WITHOUT a second,
# hand-maintained table:
#   door    - which of the hub's 6 doors renders this knob (all 9 knobs below
#             are policy/night-shift, so all are "automation" for now; other
#             doors get their own hand-built panels in settings-hub-shell,
#             per the plan's explicit "handgebaut bleiben nur ..." list -
#             this schema is for pure single-path policy knobs, not for
#             business/jira/users/devices, which stay hand-built).
#   level   - "basic" (the door's front, ~3-5 controls per NN/g progressive
#             disclosure) vs "advanced" (collapsed by default).
#   descKey - one-line i18n "what this does", separate from labelKey (the
#             control's own short label) - same two-language contract as
#             labelKey, checked by test_harness_layer.py.
#   scope   - "workspace" (daemon-wide, this file) vs "device"/"personal"
#             (not used yet - every current knob is workspace-scoped; the
#             hub's door 1 "Allgemein" gap for personal prefs is a SEPARATE,
#             not-yet-built endpoint per rbac-gxp's me.prefs.write plan, not
#             a scope value on THIS schema).
#
# Deliberately NOT added in this pass, to keep the metadata contract honest
# rather than claim "vollstaendig" prematurely: the PM subkeys, glance_*, and
# policy.load_admission from the settings inventory. They don't fit this
# schema's flat two-level-path model as-is (PM autonomy needs a real
# panel + gets one in the autonomy-dial card; glance_* are flat top-level
# keys, not nested groups; load_admission is a 4-field object, not a single
# knob) - each lands with its owning door/card instead of being force-fit
# here. See ops/docs/backlog/settings-ia-redesign/README.md.
def _config_schema(s):
    """The declarative config schema: the SINGLE source of truth for every
    editable knob ("policy is data"). The app renders each control generically
    and writes it back with saveSettings(nest(path, value)), so a new knob is one
    entry HERE, not hand-wiring in two screens. The fixed ops/harness/laws are NOT in
    this table - they live read-only in /loop/map.

    Module level, not inline in the /automation handler, for the same reason
    _lane_flow and _loop_machine are: the shape it produces is a contract with
    surfaces/app/src/app/(tabs)/automation.tsx, and a contract nothing can import is a
    contract nothing can check. ops/tests/test_harness_layer.py reads it from here
    and holds every `control` to the union the app actually renders and every
    `labelKey` to a two-language entry - a knob with a control the app has no
    branch for renders as NOTHING, silently, on an owner-only screen.

    CONTROLS above is that union. Adding a seventh means adding a branch to the
    app's Control component in the same commit; the gate will say so if not."""
    pol = s.get("policy") or {}
    ns = s.get("nightshift") or {}
    return [
        {"group": "policy", "path": "policy.auto_accept_green", "control": "toggle",
         "labelKey": "cfg.autoAccept", "value": bool(pol.get("auto_accept_green")),
         "door": "automation", "level": "basic", "descKey": "cfg.autoAccept.desc", "scope": "workspace"},
        {"group": "policy", "path": "policy.auto_dispatch_modes", "control": "multi",
         "labelKey": "cfg.autoModes", "options": ["do", "prepare", "cowork"],
         "value": pol.get("auto_dispatch_modes") or [],
         "door": "automation", "level": "basic", "descKey": "cfg.autoModes.desc", "scope": "workspace"},
        {"group": "policy", "path": "policy.auto_dispatch_priority", "control": "single",
         "labelKey": "cfg.autoPrio", "options": ["never", "urgent", "high"],
         "value": pol.get("auto_dispatch_priority") or "never",
         "door": "automation", "level": "basic", "descKey": "cfg.autoPrio.desc", "scope": "workspace"},
        {"group": "policy", "path": "policy.chat_configure_roles", "control": "multi",
         "labelKey": "cfg.chatRoles", "options": ["owner", "operator"],
         "value": pol.get("chat_configure_roles") or ["owner"],
         "door": "automation", "level": "advanced", "descKey": "cfg.chatRoles.desc", "scope": "workspace"},
        {"group": "policy", "path": "policy.lane_labels", "control": "labels",
         "labelKey": "cfg.laneLabels", "keys": ["backlog", "working", "review", "done"],
         "value": pol.get("lane_labels") or {},
         "door": "automation", "level": "advanced", "descKey": "cfg.laneLabels.desc", "scope": "workspace"},
        {"group": "night", "path": "nightshift.enabled", "control": "toggle",
         "labelKey": "cfg.nightEnabled", "value": bool(ns.get("enabled")),
         "door": "automation", "level": "basic", "descKey": "cfg.nightEnabled.desc", "scope": "workspace"},
        {"group": "night", "path": "nightshift.window", "control": "text",
         "labelKey": "cfg.nightWindow", "placeholder": "always", "value": ns.get("window") or "",
         "door": "automation", "level": "advanced", "descKey": "cfg.nightWindow.desc", "scope": "workspace"},
        {"group": "night", "path": "nightshift.max_cards", "control": "number",
         "labelKey": "cfg.nightMax", "value": ns.get("max_cards", 3),
         "door": "automation", "level": "advanced", "descKey": "cfg.nightMax.desc", "scope": "workspace"},
        {"group": "night", "path": "nightshift.idle_minutes", "control": "number",
         "labelKey": "cfg.nightIdle", "value": ns.get("idle_minutes", 20),
         "door": "automation", "level": "advanced", "descKey": "cfg.nightIdle.desc", "scope": "workspace"},
    ]
