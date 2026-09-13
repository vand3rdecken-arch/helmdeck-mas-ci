# -*- coding: utf-8 -*-
"""Read-only introspection routes - fifth slice of server.py's dispatch-table
split (see routes_auth.py for the pattern/rationale). /debt (structural debt
register), /charter (the capability charter), /loop/map (the lane/gate flow +
build loop + fixed harness laws, all DERIVED not hand-typed), /models
(available agent models), /harness + /harness/schema (the resolved agent
briefs/settings + spawn preview, and the JSON Schemas the write path
validates against). All GET, all read-only, no background jobs. Bodies are
byte-identical to the inline blocks they replace.
"""
import json
from urllib.parse import parse_qs, urlparse

from spine.http.apimeta import _lane_flow, _loop_machine, _config_schema


def _harness_state():
    """Which brief/settings layer each agent surface actually resolved to, and
    any harness file that failed to load. Without this a broken ops/harness/agents
    file is invisible: harness.py deliberately falls back to its built-in default
    rather than breaking a spawn, so nothing would otherwise SAY that an edit is
    being ignored."""
    try:
        from spine.registry import harness
        return harness.describe()
    except Exception as e:                                   # noqa: BLE001
        return {"agents": [], "errors": {"harness": str(e)[:200]}}


def debt_get(self, user):
    from spine.registry import debt
    return self._send(200, json.dumps(debt.list_debt()))


def charter_get(self, user):
    from spine.auth import charter
    from spine.storage import events
    return self._send(200, json.dumps(
        {"core": charter.CHARTER,
         "house_rules": (events.settings().get("policy") or {}).get("house_rules", "")}))


def loop_map_get(self, user):
    # the machine, made legible: the lane/gate flow + the build loop +
    # the fixed harness laws behind them (charter is code, shown read-only).
    #
    # BOTH graphs are now DERIVED, not described. This handler used to
    # carry a hand-typed copy of each, and /automation carried a second
    # copy of the build loop; they drifted apart and away from the code
    # (this one had silently lost the BUILD state altogether). The
    # renderer gets sessions.flow() and loop_state.machine() verbatim,
    # so a new state or a changed condition shows up here by itself.
    from spine.auth import charter
    from spine.storage import events
    _s = events.settings()
    ll = (_s.get("policy") or {}).get("lane_labels") or {}
    # ?repo= makes the map answer for ONE repo: which stations its template
    # leaves on, what the deploy step actually runs, where the owner has since
    # deviated from the template. Without it the answer is the general machine,
    # exactly as before - so every existing caller is unaffected.
    repo = (parse_qs(urlparse(self.path).query).get("repo") or [""])[0].strip()
    repo_view = None
    if repo:
        try:
            from spine.ops import projects
            repo_view = projects.resolve(repo)
        except Exception as e:                               # noqa: BLE001
            repo_view = {"repo": repo, "error": str(e)[:200]}
    return self._send(200, json.dumps({
        "runtime": dict(_lane_flow(ll, repo_view), title="Wie Arbeit fliesst"),
        # the repo half of the answer, or null when no repo was asked about
        "repo": repo_view,
        "build": _loop_machine(),
        "harness": _harness_state(),
        # WHICH of the dotted paths a node names can really be changed
        # in the app - i.e. exactly the ones /automation renders a
        # control for. The map used to turn EVERY `settings` entry
        # into a tappable chip pointing at /automation, but half of
        # them are not in that table at all (capacity.wip_limit lives
        # only in settings.json; env.SWARM_WIP_MINUTES is an
        # environment variable and never will be), so the owner was
        # sent to a screen that does not contain the knob it promised.
        # Derived from _config_schema, so a knob added there becomes
        # tappable here by itself - and one removed stops lying.
        "editable": sorted({e["path"] for e in _config_schema(_s)}),
        # the lane NAMES are data on every lane, whatever its kind
        "lane_labels_path": "policy.lane_labels",
        # Each law cites the module that ENFORCES it. A law the owner
        # cannot trace to code is just a promise on a screen; with the
        # pointer he can go read the thing that actually holds the
        # line. Same reason the graph nodes carry file:line.
        "laws": [
            {"key": "auth", "text": "Auth ist fix — nie geschwächt.",
             "source": "daemon/auth.py"},
            {"key": "audit", "text": "Append-only Audit/Events — Geschichte wird nie überschrieben.",
             "source": "daemon/events.py"},
            {"key": "gate", "text": "Gate-before-review — Qualität vor jeder Abnahme.",
             "source": "cells/engineer/sessions.py"},
            {"key": "economics", "text": "Gemessene Ökonomie — jeder Turn hat Kosten/Value.",
             "source": "daemon/usage.py"},
            {"key": "worktree", "text": "Worktree-Isolation — jeder Agent in eigenem Checkout.",
             "source": "cells/engineer/sessions.py"},
            {"key": "drivers", "text": "Driver-Kommandos sind fix — was Agents ausführen ist nicht frei konfigurierbar.",
             "source": "daemon/drivers.py"},
            {"key": "charter", "text": "Charter-Kern ist Code — nicht per Chat editierbar.",
             "source": "daemon/charter.py"},
        ],
        "charter": charter.CHARTER,
    }))


def models_get(self, user):
    from spine.agent import turnopts
    return self._send(200, json.dumps(turnopts.list_models()))


def harness_get(self, user):
    # The editable policy behind every agent surface, PLUS the
    # spawn preview: the resolved argv, which settings layers are
    # included/excluded and why, the brief's source file + content
    # hash, and the full hook matrix. Owner-only - the briefs are
    # the instructions his workers run under, and the layer list
    # names paths on his machine.
    if user["role"] != "owner":
        return self._send(403, json.dumps({"error": "owner only"}))
    from spine.registry import harness
    return self._send(200, json.dumps(harness.document(), ensure_ascii=False))


def harness_schema_get(self, user):
    # The two JSON Schemas the write path validates against, served
    # so the editor can show the rules instead of the owner
    # discovering them one rejected save at a time.
    if user["role"] != "owner":
        return self._send(403, json.dumps({"error": "owner only"}))
    from spine.registry import harness
    return self._send(200, json.dumps({
        "agent": harness.load_schema("agent"),
        "settings": harness.load_schema("settings"),
    }, ensure_ascii=False))


def escalations_get(self, user):
    # Henry's escalation log (spine bus, judged by the copilot cell) - the
    # owner reads WHAT was escalated and HOW Henry decided. Not for clients:
    # entries name repos, processes and failure detail from this machine.
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "not for clients"}))
    from spine.registry import escalations
    return self._send(200, json.dumps(escalations.list_all(), ensure_ascii=False))


def engines_get(self, user):
    # Engine snapshot (spine/agent/engines.py - the Paseo provider-snapshot
    # shape): every driver a card may carry, with its CLI probed live.
    # ?refresh=1 re-probes (the user just installed something).
    from spine.agent import engines
    q = parse_qs(urlparse(self.path).query)
    refresh = (q.get("refresh") or ["0"])[0] in ("1", "true")
    return self._send(200, json.dumps({"engines": engines.snapshot(refresh=refresh)},
                                      ensure_ascii=False))


GET_ROUTES = {
    "/engines": engines_get,
    "/debt": debt_get,
    "/charter": charter_get,
    "/loop/map": loop_map_get,
    "/models": models_get,
    "/harness": harness_get,
    "/harness/schema": harness_schema_get,
    "/escalations": escalations_get,
}
