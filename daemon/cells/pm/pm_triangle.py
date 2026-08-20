# -*- coding: utf-8 -*-
"""PM golden-triangle gate - extracted from pm.py (god-file breakup, see
daemon/spine/registry/debt.py daemon-god-files).

The LLM plan proposes each triangle corner's colour (Budget/Timeline/Scope)
from narrative; _gate_triangle replaces that with a MEASURED verdict that can
only DOWNGRADE (green -> red), never upgrade a red the planner set - same
"only tightens" law as the verifier and gate-before-review. live_plan()
re-measures on every read (no LLM call); on_card_done re-judges the instant a
card lands in Done, cheap by default, only spending a re-scope when a corner
actually crosses the ok<->blocked line; reconcile_corner is the OWNER-
triggered evidence-gathering path for a red corner.

pm.py's own functions (get_goal, latest_plan, _write_artifact, economics,
_system_state, _ask, brief, make_plan) are imported LAZILY inside the
function bodies that need them - pm.py imports THIS module at module level
(to re-export these names unchanged for existing callers), so a top-level
import back would cycle."""
import threading
import time

from daemon.cells.pm.pm_budget import _pace, _budget_assess
from daemon.cells.pm.pm_state import _loopstate, _save_loopstate
from daemon.cells.pm.pm_comm import _activity
from daemon.cells.pm.pm_resolve import _resolving_lock


def live_plan():
    """The cached plan artifact, but with Budget/Timeline/Scope RECOMPUTED from
    LIVE economics + usage on every read. The triangle (and the budget panel)
    then always think in the CURRENT velocity/quota - not a figure frozen at
    plan time (a budget baked into the daily artifact is stale the moment usage
    moves). The LLM's content (milestones, scope, questions) is preserved; only
    the measured verdict + budget block are refreshed. Cheap: no LLM call."""
    from daemon.cells.pm.pm import latest_plan, economics
    plan = latest_plan()
    if not plan:
        return plan
    econ = economics()
    pace = _pace(econ)
    cum = sum(int(ms.get("est_turns") or 0) for ms in plan.get("milestones", [])
              if str(ms.get("status")) != "done")
    try:
        _gate_triangle(plan, econ, cum, pace)
    except Exception as e:
        print("live_plan gate error:", e)
    return plan


def _gate_triangle(out, econ, est_turns, pace):
    """Adversarially gate the golden triangle (Budget/Timeline/Scope). The LLM
    plan proposed each corner's colour from narrative; this replaces that with a
    MEASURED verdict that can only DOWNGRADE (green -> red), never upgrade a red
    the planner set. Attaches out['budget'] (plan-aware panel data) and, per
    downgraded corner, out['triage_reasons'][corner] so the board can say WHY.

    - Budget: the real bottleneck. Max -> subscription usage/pacing; API -> euro
      vs the monthly cap (_budget_assess). A window pacing to exhaust before its
      reset, or a projection over the cap, turns Budget red.
    - Timeline: measured VELOCITY. No turns yet (pace 0) => the ETA is a guess,
      not a commitment => red. Otherwise the launch date IS the measured ETA, so
      the planner can't be more optimistic than the math.
    - Scope: readiness. A plan the verifier left not-ready (open owner decision,
      undefined scope) can't be green scope, whatever the planner wrote."""
    tri = out.get("triage")
    if not isinstance(tri, dict):
        tri = {}
        out["triage"] = tri
    reasons = out.setdefault("triage_reasons", {})

    def downgrade(corner, reason):
        tri[corner] = "blocked"
        reasons[corner] = reason

    # -- Budget: measured usage/pacing or euro-vs-cap ------------------------
    out["budget"], bstate = _budget_assess(econ, est_turns, pace)
    if bstate == "blocked":
        downgrade("budget", out["budget"].get("note"))

    # -- Timeline: measured velocity underwrites the ETA --------------------
    if not pace or pace <= 0:
        downgrade("timeline", "Kein gemessenes Tempo (noch keine Turns) - die ETA ist "
                              "geschätzt, keine belastbare Zusage.")

    # -- Scope: a not-ready plan can't be green scope -----------------------
    if out.get("plan_status") in ("blocked", "needs_spike"):
        downgrade("scope", reasons.get("scope")
                  or "Plan ist nicht abnahmereif (offene Entscheidung / unklarer Scope).")


def _triage_shape(plan):
    """The ok/blocked SHAPE of the golden triangle as a stable dict, for detecting
    a corner that crossed the line. None when there is nothing to compare (no plan,
    or a legacy plan without a triage block)."""
    tri = (plan or {}).get("triage") or {}
    if not tri:
        return None
    return {k: ("blocked" if tri.get(k) == "blocked" else "ok")
            for k in ("budget", "timeline", "scope")}


def on_card_done(tid):
    """EVENT hook (sessions calls it when a card lands in Done): re-judge the golden
    triangle NOW rather than waiting for the daily plan. A completion moves real
    signals - economics, and via _system_state the world a card just changed. Cheap
    by default: live_plan() re-measures with NO model call. Only when a corner
    CROSSES the ok<->blocked line do we spend one re-scope (make_plan), so a normal
    completion costs zero planning turns. Threaded so the accept path never blocks
    on a model call (mirrors review_burn)."""
    from daemon.spine.registry import cells
    if not cells.enabled_id("pm"):
        return
    threading.Thread(target=_on_card_done, args=(tid,), daemon=True,
                     name="pm-card-done").start()


def _on_card_done(_tid):
    from daemon.spine.storage import events
    from daemon.cells.pm.pm import get_goal, make_plan
    try:
        if not get_goal():
            return
        shape = _triage_shape(live_plan())   # re-measures budget/timeline/scope, no LLM
        if shape is None:
            return
        with _resolving_lock:
            st = _loopstate()
            prev = st.get("plan_triage_shape")
            st["plan_triage_shape"] = shape
            _save_loopstate(st)
        if not prev or prev == shape:
            return                            # first observation, or no corner flipped
        flipped = [k for k in ("budget", "timeline", "scope") if prev.get(k) != shape.get(k)]
        _activity("planned", "Karte fertig - Dreieck bewegt sich (%s), plane neu."
                  % ", ".join(flipped))
        make_plan(actor="pm")                 # the flip is the ONLY re-scope spend
    except Exception as e:
        try:
            events.log("pm", "on_card_done error: %s" % e)
        except Exception:
            pass


RECONCILE_PROMPT = """A corner of the plan's golden triangle (Budget/Timeline/Scope) is RED.
Your job is NOT to declare it green - it is to gather OBSERVABLE EVIDENCE about the REAL
state behind that corner, so the plan can be re-derived from FACTS instead of a stale
snapshot. Look at what has ACTUALLY been provisioned/built (users/accounts, features,
deploys) - not what a card's lane claims. Report only what you can verify.

Corner: %s
Goal: %s

Reply with ONLY this JSON:
{"corner":"%s",
 "evidence":["observable fact you verified", ...],
 "already_done":["scope items that are in fact already DONE in the real world"],
 "still_open":["what genuinely remains"]}"""


def reconcile_corner(corner, actor="owner"):
    """OWNER-triggered when a triangle corner is RED: dispatch an agent to gather
    EVIDENCE about the real world behind that corner (did the users actually get set
    up? is the feature live?), fold that evidence into the plan, then RE-PLAN so the
    planner re-scopes and _gate_triangle re-derives the corner from FACTS.

    Law-abiding (NO MONKEY PATCHES): the agent never stamps a corner's colour - it
    supplies the facts the planner was missing; the corner stays DERIVED, folded in
    at this event, mutated at one owner (_gate_triangle)."""
    from daemon.cells.copilot import copilot
    from daemon.cells.pm.pm import get_goal, _system_state, _ask, latest_plan, _write_artifact, brief
    corner = (corner or "").strip().lower()
    if corner not in ("budget", "timeline", "scope"):
        return {"error": "corner must be budget|timeline|scope"}
    goal = get_goal()
    prompt = (RECONCILE_PROMPT % (corner, goal or "(kein Ziel gesetzt)", corner)
              + "\n\nSYSTEM STATE:\n" + _system_state()
              + "\n\nBOARD SNAPSHOT:\n" + copilot._snapshot())
    ev = _ask(prompt)
    ev = ev if isinstance(ev, dict) else {}
    plan = latest_plan() or {}
    plan.setdefault("reconcile", {})[corner] = {
        "at": time.strftime("%Y-%m-%d %H:%M:%S"), "actor": actor,
        "evidence": ev.get("evidence") or [],
        "already_done": ev.get("already_done") or [],
        "still_open": ev.get("still_open") or []}
    _write_artifact(plan)                 # persist evidence so brief() reads it as prev
    b = brief()                           # re-scope on the evidence; gate re-derives
    return {"corner": corner, "evidence": plan["reconcile"][corner],
            "triage": b.get("triage"), "triage_reasons": b.get("triage_reasons")}
