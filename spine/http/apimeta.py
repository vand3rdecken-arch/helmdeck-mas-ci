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
         "labelKey": "cfg.autoAccept", "value": bool(pol.get("auto_accept_green"))},
        {"group": "policy", "path": "policy.auto_dispatch_modes", "control": "multi",
         "labelKey": "cfg.autoModes", "options": ["do", "prepare", "cowork"],
         "value": pol.get("auto_dispatch_modes") or []},
        {"group": "policy", "path": "policy.auto_dispatch_priority", "control": "single",
         "labelKey": "cfg.autoPrio", "options": ["never", "urgent", "high"],
         "value": pol.get("auto_dispatch_priority") or "never"},
        {"group": "policy", "path": "policy.chat_configure_roles", "control": "multi",
         "labelKey": "cfg.chatRoles", "options": ["owner", "operator"],
         "value": pol.get("chat_configure_roles") or ["owner"]},
        {"group": "policy", "path": "policy.lane_labels", "control": "labels",
         "labelKey": "cfg.laneLabels", "keys": ["backlog", "working", "review", "done"],
         "value": pol.get("lane_labels") or {}},
        {"group": "night", "path": "nightshift.enabled", "control": "toggle",
         "labelKey": "cfg.nightEnabled", "value": bool(ns.get("enabled"))},
        {"group": "night", "path": "nightshift.window", "control": "text",
         "labelKey": "cfg.nightWindow", "placeholder": "always", "value": ns.get("window") or ""},
        {"group": "night", "path": "nightshift.max_cards", "control": "number",
         "labelKey": "cfg.nightMax", "value": ns.get("max_cards", 3)},
        {"group": "night", "path": "nightshift.idle_minutes", "control": "number",
         "labelKey": "cfg.nightIdle", "value": ns.get("idle_minutes", 20)},
    ]
