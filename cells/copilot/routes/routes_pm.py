# -*- coding: utf-8 -*-
"""PM (proactive daily-loop) routes - sixth slice of server.py's dispatch-table
split (see routes_auth.py for the pattern/rationale). GET /pm/economics
(cheap no-LLM snapshot), GET /pm/plan (cached briefing + live economics),
POST /pm/config (owner sets the loop policy - whitelisted keys only), POST
/pm/consolidate (propose/apply the small-cards rollup), POST /pm/report (ONE
model turn - the proactive briefing), POST /pm/reconcile (re-derive a red
golden-triangle corner from real evidence). Bodies are byte-identical to the
inline blocks they replace.

Capability-gated (ops/docs/backlog/rbac-gxp card 2, spine/auth/permissions.py):
pm.view (owner+operator - economics/plan/report/reconcile) and pm.manage
(owner-only - config/consolidate, both change the loop's own policy).
"""
import json


def pm_economics_get(self, user):
    # cheap, no-LLM economics snapshot + the stored MVP goal
    from cells.copilot.planning import pm
    return self._send(200, json.dumps({"goal": pm.get_goal(), "economics": pm.economics()}))


def pm_plan_get(self, user):
    # the last PM briefing (cached artifact) + live economics - no LLM,
    # so the Dashboard shows instantly; /pm/report refreshes it.
    from cells.copilot.planning import pm
    return self._send(200, json.dumps({"goal": pm.get_goal(),
        "economics": pm.economics(), "plan": pm.live_plan(),
        "config": pm._pm(), "activity": pm.activity()}))


def pm_config_post(self, user, body):
    # owner sets the proactive-loop policy (on/off, autonomy ladder,
    # repos allowlist, timing/caps). Whitelisted keys only.
    from cells.copilot.planning import pm
    from spine.storage import events
    allowed = ("loop_enabled", "autonomy", "repos", "window", "idle_minutes",
               "replan_minutes", "max_dispatch_per_day", "goal", "plan",
               "monthly_eur", "quota_turns_per_day")
    merged = dict(events.settings().get("pm") or {})
    for k in allowed:
        if k in body:
            merged[k] = body[k]
    if merged.get("autonomy") not in ("notify", "ask", "act"):
        merged["autonomy"] = "act"
    events.save_settings({"pm": merged})
    # No automatic goal check on a goal edit any more (2026-09-13): the
    # title-only check kept re-proposing shipped work as "missing". The owner
    # asks Henry ("was fehlt zum Ziel?") -> chat action goal_check.
    return self._send(200, json.dumps(pm._pm()))


def pm_consolidate_post(self, user, body):
    # Phase 3: propose (read-only) or apply (non-destructive) the
    # roll-up of many small cards into 2-5 stream cards per repo.
    from cells.copilot.planning import pm
    try:
        if body.get("mode") == "apply":
            return self._send(200, json.dumps(pm.apply_consolidation(
                body.get("repos") or [], actor=user["name"])))
        return self._send(200, json.dumps(pm.consolidation_proposal(
            model=body.get("model", ""))))
    except Exception as e:
        return self._send(500, json.dumps({"error": str(e)[:300]}))


def pm_report_post(self, user, body):
    # Proactive PM/CTO briefing: tasks-to-goal, prioritized next,
    # token/cost projection grounded in real spend. One model turn.
    from cells.copilot.planning import pm
    try:
        return self._send(200, json.dumps(pm.brief(
            goal=body.get("goal"), model=body.get("model", ""))))
    except Exception as e:
        return self._send(500, json.dumps({"error": str(e)[:300]}))


def pm_reconcile_post(self, user, body):
    # Gather real evidence behind a RED golden-triangle corner and re-plan
    # (pm.reconcile_corner). The agent supplies facts; the gate re-derives
    # the corner (no monkey patch). Owner+operator (pm.view), same tier as
    # report - despite the name, this isn't config-changing (pm.manage).
    from cells.copilot.planning import pm
    try:
        return self._send(200, json.dumps(pm.reconcile_corner(
            body.get("corner", ""), actor=user["name"])))
    except Exception as e:
        return self._send(500, json.dumps({"error": str(e)[:300]}))


GET_ROUTES = {
    "/pm/economics": pm_economics_get,
    "/pm/plan": pm_plan_get,
}
POST_ROUTES = {
    "/pm/config": pm_config_post,
    "/pm/consolidate": pm_consolidate_post,
    "/pm/report": pm_report_post,
    "/pm/reconcile": pm_reconcile_post,
}
GET_CAPS = {
    "/pm/economics": "pm.view",
    "/pm/plan": "pm.view",
}
POST_CAPS = {
    "/pm/config": "pm.manage",
    "/pm/consolidate": "pm.manage",
    "/pm/report": "pm.view",
    "/pm/reconcile": "pm.view",
}
