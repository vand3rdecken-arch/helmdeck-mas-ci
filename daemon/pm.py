# -*- coding: utf-8 -*-
"""PM / CTO planning ROLE, run by the thin harness here.

The PM's brain is DATA (pm.role.md + settings.pm), not code. This module only:
  - gathers signals (board + REAL economics + quota/velocity + goal),
  - runs the configured role for ONE plan-mode turn,
  - prices/times the plan in code (LLM judges effort in turns, code converts to
    days at the measured velocity and to shadow-€ at the real cost/turn),
  - writes a reviewable artifact,
  - and hands the actionable items to whoever executes (the night ticker).

On a flat plan (settings.pm.plan == "max") the bottleneck is quota-TIME, not €,
so timelines are in DAYS and the € is leverage/ROI, not cash. Nothing here
executes work; turning items into cards stays an explicit, gated step.
"""
import json, math, os, re, subprocess, threading, time

import i18n as _i18n

ROOT = os.path.dirname(os.path.abspath(__file__))
ROLE_FILE = os.path.join(ROOT, "pm.role.md")
PLANS = os.path.join(ROOT, "pm")

PM_DEFAULTS = {
    "goal": "",
    # "auto" detects the plan from the CLI's real auth (events.plan_effective:
    # subscription login -> "max", API key / Console login -> "api"); the
    # explicit values stay as owner overrides.
    "plan": "auto",             # "auto" | "max" (flat quota) | "api" (per-token €) | "mixed"
    "monthly_eur": 200,
    # the weekly plan allowance in TOKENS, if the owner knows it. 0 = derive it
    # from the live usage window (events.plan_calibration), which is how cost
    # surfaces turn a card's tokens into "% of the subscription".
    "plan_tokens_week": 0,
    "quota_turns_per_day": 0,   # 0 = derive pace from measured velocity
    "role_extra": "",           # house additions appended to the role charter
    # -- the single proactive loop (absorbs the old nightshift ticker) --
    "loop_enabled": False,      # proactive loop off until the owner turns it on
    "repos": [],                # safety allowlist: repos the PM may act in
    "window": "",               # "" / "always" = whenever idle; "HH:MM-HH:MM" restricts
    "idle_minutes": 20,         # you must be away this long before the PM acts
    "replan_minutes": 120,      # re-run the PM plan (LLM) at most this often
    "max_dispatch_per_day": 3,  # cap on autonomous dispatches/day (quota guard)
    # escalation ladder (LangChain ambient-agents / Horvitz mixed-initiative):
    #   "notify" = only refresh the plan, change nothing (advise-only)
    #   "ask"    = also file backlog cards (reversible), but never auto-dispatch
    #   "act"    = also dispatch within the WIP/quota gates (merge/accept stay gated)
    "autonomy": "act",
    # -- per-card budget watchdog (_cost_watch: code thresholds, no LLM) ------
    "watch_base_pct": 5.0,      # BAC of a MEDIUM card: absolute % of the plan budget
    "watch_reserve_pct": 40.0,  # management reserve: share never allocated to cards
    "watch_floor_usd": 5.0,     # fallback ladder (API-equivalent $) while calibration is cold
    "watch_ctx_floor": 150_000, # context tokens considered runaway (window nearly full)
}


def _pm():
    import events
    c = dict(PM_DEFAULTS)
    c.update(events.settings().get("pm") or {})
    return c


def get_goal():
    return (_pm().get("goal") or "").strip()


def set_goal(goal):
    import events
    pm = dict(events.settings().get("pm") or {})
    pm["goal"] = (goal or "").strip()
    events.save_settings({"pm": pm})
    return pm["goal"]


# -- CLARIFICATIONS: the owner answers a PM question straight in chat ---------
# brief() only ever read the goal text + the live board - an owner reply to an
# open_question in chat was heard (the copilot replied) but never reached the
# planner, so the NEXT plan repeated the same question. This is the fix: the
# chat action "clarify_goal" (copilot._run_action) calls add_clarification(),
# which is folded into every brief() prompt as ground truth until the goal
# text itself changes (a new goal invalidates old answers - set_goal clears
# them). Small, capped, persisted in the same loop.json the PM already owns.
_CLARIFY_MAX = 12


def add_clarification(text, actor="owner"):
    text = (text or "").strip()
    if not text:
        return []
    with _resolving_lock:
        st = _loopstate()
        cl = st.setdefault("clarifications", [])
        cl.append({"text": text[:500], "at": time.strftime("%Y-%m-%d %H:%M"), "actor": actor,
                   "goal": get_goal()})
        st["clarifications"] = cl[-_CLARIFY_MAX:]
        _save_loopstate(st)
        return st["clarifications"]


def _clarifications_block():
    """Only clarifications recorded against the CURRENT goal text - a goal edit
    (set_goal) makes prior answers stale, so they drop out here rather than
    misleading a re-scoped plan."""
    goal = get_goal()
    cl = [c for c in (_loopstate().get("clarifications") or []) if c.get("goal") == goal]
    if not cl:
        return ""
    lines = ["\n\nOWNER CLARIFICATIONS (answered live in chat - trust these as GROUND TRUTH, "
             "they supersede any guess/assumption in a prior plan or the snapshot):"]
    lines += ["  - %s (%s)" % (c["text"], c.get("at", "")) for c in cl]
    return "\n".join(lines)


def _role():
    try:
        with open(ROLE_FILE, encoding="utf-8") as f:
            role = f.read()
    except OSError:
        role = "You are the HelmDeck PM/CTO. Reply with JSON: {summary, done_pct, milestones, next, risks}."
    extra = (_pm().get("role_extra") or "").strip()
    return role + ("\n\n## House additions\n" + extra if extra else "")


def economics():
    """Real spend/token/velocity facts, so estimates are grounded in THIS board."""
    import sessions, events
    from datetime import datetime
    tracks = sessions.list_tracks()
    m = events.metrics(tracks)
    spend = m["totals"]["ai_spend"]
    turns = sum(t.get("turns", 0) for t in tracks)
    toks = sum((t.get("tokens_in", 0) + t.get("tokens_out", 0)) for t in tracks)
    fmt = "%Y-%m-%d %H:%M:%S"
    created = []
    for t in tracks:
        try:
            created.append(datetime.strptime(t["created"], fmt))
        except (KeyError, ValueError, TypeError):
            pass
    span_days = 1.0
    if created:
        span_days = max(1.0, (datetime.strptime(time.strftime(fmt), fmt) - min(created)).total_seconds() / 86400.0)
    pm = _pm()
    # the RESOLVED plan ("max"/"api"), not the raw setting: _budget_assess picks
    # its bottleneck (quota windows vs € cap) off this, and with plan="auto" the
    # raw value names no plan at all. plan_source keeps the evidence visible.
    plan_eff, plan_src = events.plan_effective()
    return {
        "plan": plan_eff,
        "plan_source": plan_src,
        "plan_setting": pm.get("plan", "auto"),
        "monthly_eur": pm.get("monthly_eur", 200),
        "spend_to_date": round(spend, 4),
        "turns_to_date": turns,
        "tokens_to_date": toks,
        "avg_cost_per_turn": round(spend / turns, 4) if turns else 0.0,
        "avg_tokens_per_turn": round(toks / turns) if turns else 0,
        "active_days": round(span_days, 1),
        "velocity_turns_per_day": round(turns / span_days, 1) if turns else 0.0,
        "quota_turns_per_day": pm.get("quota_turns_per_day", 0),
        "value_delivered": m["totals"]["value_delivered"],
        "margin": m["totals"]["margin"],
        "capacity": m["capacity"],
        "spend_by_model": {k: v.get("cost", 0) for k, v in m["ai_by_model"].items()},
        "currency": events.settings().get("currency", "EUR"),
    }


def _system_state():
    """Real WORLD state the board otherwise can't see: what's been PROVISIONED
    OUTSIDE the card lanes (users/accounts, registration). A card agent that set
    up users changes the world, not a card's lane - and _snapshot() only carries
    lanes, so without this the planner re-scopes work that is already done (the
    'board didn't know about the users' gap). FACTS only; the planner and the
    gate derive scope from them, they are never a stamped verdict."""
    lines = []
    try:
        import auth
        users = auth.list_users()
        roles = {}
        for u in users:
            r = u.get("role", "?")
            roles[r] = roles.get(r, 0) + 1
        lines.append("USERS: %d Konto/Konten (%s)" % (
            len(users), ", ".join("%d×%s" % (n, r) for r, n in sorted(roles.items())) or "keine"))
    except Exception:
        pass
    try:
        import events
        reg = events.settings().get("registration")
        if reg:
            lines.append("REGISTRATION: " + json.dumps(reg, ensure_ascii=False)[:200])
    except Exception:
        pass
    return "\n".join(lines) or "(keine gesonderten System-Fakten)"


from pm_budget import (_pace, _days, _quota_signal, _budget_assess, _fmt_when,
                       _usage_flag_text, _quota_floor, _goal_budget_text, _triage_green)
from pm_state import touch, _loopstate, _save_loopstate, _today, _in_window, _board_idle, LOOPSTATE


def live_plan():
    """The cached plan artifact, but with Budget/Timeline/Scope RECOMPUTED from
    LIVE economics + usage on every read. The triangle (and the budget panel)
    then always think in the CURRENT velocity/quota - not a figure frozen at
    plan time (a budget baked into the daily artifact is stale the moment usage
    moves). The LLM's content (milestones, scope, questions) is preserved; only
    the measured verdict + budget block are refreshed. Cheap: no LLM call."""
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
    import cells
    if not cells.enabled_id("pm"):
        return
    threading.Thread(target=_on_card_done, args=(tid,), daemon=True,
                     name="pm-card-done").start()


def _on_card_done(_tid):
    import events
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
    import copilot
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


def _ask(prompt, model=""):
    import copilot, drivers
    # drivers._cmd_line, not ["cmd","/c",...] - the cmd.exe route mangles quoted
    # args on a .cmd shim (see drivers._real_claude_exe).
    argv = [copilot.CLAUDE, "-p", "--output-format", "json", "--permission-mode", "plan"]
    if model:
        argv += ["--model", model]
    cmd = drivers._cmd_line(argv)
    p = subprocess.Popen(cmd, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    stdout, stderr = p.communicate(input=prompt, timeout=300)
    if not (stdout or "").strip():
        raise RuntimeError("pm: no model output: " + (stderr or "").strip()[:200])
    d = json.loads(stdout)
    txt = d.get("result", "")
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        return {"summary": txt.strip()[:400], "milestones": [], "next": [], "risks": []}
    try:
        return json.loads(m.group(0))
    except ValueError:
        return {"summary": txt.strip()[:400], "milestones": [], "next": [], "risks": []}


VERIFY_PROMPT = """You are a SKEPTICAL plan reviewer - a second, INDEPENDENT pass, not the
planner. Given a PM plan plus the real economics, the live quota/budget and the board, find
the reasons this plan is NOT ready to commit to firm estimates. Be adversarial: assume it is
over-optimistic, and only pass a plan that genuinely holds up.

Check specifically:
- A milestone with a FIRM est_turns whose effort is actually UNKNOWN (needs a spike first)?
- A fixed CALENDAR duration (an N-day test / trial / waiting period) estimated as if it were
  effort instead of wait time?
- A HUMAN prerequisite / LONG POLE (recruiting people, an approval, an account) that hasn't
  started, gates everything after it, and isn't Step 1?
- An unresolved OWNER decision the plan silently assumed away?
- Budget/quota that cannot actually fund it by any stated deadline?

Reply with ONLY this JSON:
{"ready": true|false,
 "gate": "if not ready: the ONE binding reason, in plain owner language",
 "issues": ["short, concrete problems found"],
 "must_ask": ["owner decisions/questions that must be answered before firm estimates"]}
If the plan genuinely holds, ready=true with empty arrays."""


def _verify_plan(plan, econ, quota):
    """The GATE's second opinion (paseo worker/verifier pattern): an independent, skeptical
    pass that can DOWNGRADE a plan to not-ready (it never upgrades). Catches the over-confident
    failure - a 14-day calendar test sized as 2 days, a not-yet-started recruiting long-pole,
    an unresolved decision. Fail-open: if the pass errors, don't block."""
    try:
        import turnopts
        cli_model, _ = turnopts.resolve_model("auto", "verify plan", False, signals={"priority": "high"})
        keep = {k: plan.get(k) for k in ("goal", "summary", "milestones", "feasibility",
                                         "assumptions", "open_questions", "budget")}
        prompt = (VERIFY_PROMPT + "\n\nPLAN:\n" + json.dumps(keep)
                  + "\n\nECONOMICS:\n" + json.dumps(econ)
                  + "\n\nQUOTA/BUDGET (live):\n" + json.dumps(quota))
        v = _ask(prompt, cli_model)
        return {"ready": bool(v.get("ready", True)), "gate": v.get("gate", "") or "",
                "issues": v.get("issues") or [], "must_ask": v.get("must_ask") or []}
    except Exception as e:
        return {"ready": True, "gate": "", "issues": [], "must_ask": [], "error": str(e)[:120]}


def _write_artifact(out):
    try:
        os.makedirs(PLANS, exist_ok=True)
        with open(os.path.join(PLANS, "plan-%s.json" % time.strftime("%Y%m%d")), "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1, ensure_ascii=False)
    except OSError:
        pass


def latest_plan():
    if not os.path.isdir(PLANS):
        return None
    days = sorted(f for f in os.listdir(PLANS) if f.startswith("plan-"))
    if not days:
        return None
    try:
        with open(os.path.join(PLANS, days[-1]), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _memory(prev, econ):
    """The PM's memory: its previous plan + a hard calibration signal (turns
    actually spent since, and progress) so it self-corrects instead of guessing
    fresh each time. Empty on the first ever plan."""
    if not prev:
        return ""
    lines = ["\n\nYOUR PREVIOUS PLAN (%s) - MEMORY. Compare against it: call out what "
             "SLIPPED or was mis-estimated, and CALIBRATE this plan's est_turns from "
             "what actually happened (don't just re-guess):" % prev.get("generated_at", "?")]
    lines.append("  prev done_pct: %s" % prev.get("done_pct"))
    pe = (prev.get("economics") or {}).get("turns_to_date")
    if pe is not None:
        lines.append("  turns actually spent SINCE that plan: %d" % max(0, (econ.get("turns_to_date", 0) or 0) - pe))
    pb = prev.get("budget") or {}
    if pb.get("est_turns_to_goal") is not None:
        lines.append("  you then estimated %s turns / ~%s days to goal - was that on track?"
                     % (pb.get("est_turns_to_goal"), pb.get("eta_days")))
    for m in (prev.get("milestones") or [])[:6]:
        lines.append("  - %s: was %s turns, eta ~%sd" % (m.get("name"), m.get("est_turns"), m.get("eta_days")))
    return "\n".join(lines)


def _reconcile_block(prev):
    """When the owner ran a corner reconciliation (reconcile_corner), the vetted
    EVIDENCE it gathered is fed back to the planner as FACTS to trust over the raw
    snapshot - so the re-plan actually re-scopes on the real world (e.g. 'users
    already set up' stops being counted as open scope)."""
    rec = (prev or {}).get("reconcile") or {}
    if not rec:
        return ""
    return ("\n\nRECONCILED EVIDENCE (the owner ran a check on a RED triangle corner - "
            "trust these observed FACTS over the snapshot when scoping):\n"
            + json.dumps(rec, ensure_ascii=False)[:1500])


def brief(goal=None, model=""):
    """The PM/CTO report: milestones with timelines, next actions, budget grounded
    in quota-time (Max plan) or € (API). `goal` overrides + persists the MVP goal."""
    import copilot, turnopts, events
    if goal is not None and goal.strip():
        set_goal(goal)
    goal = (goal or "").strip() or get_goal()
    econ = economics()
    quota = _quota_signal()   # live budget, fed to the planner AND the verifier
    prev = latest_plan()      # MEMORY: read the last plan BEFORE we overwrite it
    cli_model, _ = turnopts.resolve_model(model or "auto", goal or "plan the mvp",
                                          False, signals={"priority": "high"})
    prompt = (_role()
              + "\n\nGOAL:\n" + (goal or "(no goal set - infer a reasonable MVP from the board and debt)")
              + "\n\nPOLICY:\n" + json.dumps(events.settings().get("policy") or {})
              + "\n\nECONOMICS (real, to date):\n" + json.dumps(econ)
              + "\n\nQUOTA/BUDGET (live - judge budget-fit against THIS):\n" + json.dumps(quota)
              + "\n\nSYSTEM STATE (provisioned OUTSIDE the card lanes - derive scope from THIS too, "
                "not just the cards):\n" + _system_state()
              + _reconcile_block(prev)
              + _clarifications_block()
              + _memory(prev, econ)
              + "\n\nBOARD SNAPSHOT (%s):\n" % time.strftime("%Y-%m-%d %H:%M") + copilot._snapshot())
    out = _ask(prompt, cli_model)

    # price + time in CODE: LLM judged est_turns; we convert to days, dates & €.
    from datetime import datetime, timedelta
    today = datetime.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d")
    pace = _pace(econ)
    cum = 0
    for ms in out.get("milestones", []):
        tt = int(ms.get("est_turns") or 0) if str(ms.get("status")) != "done" else 0
        cum += tt
        ms["est_turns"] = tt
        ms["eta_days"] = _days(tt, pace)
        ms["cumulative_eta_days"] = _days(cum, pace)
        # a concrete TARGET DATE, so the board Timeline lays the roadmap out and
        # the milestone reads "by Thu" not just "~3d".
        ms["target_date"] = (today + timedelta(days=ms["cumulative_eta_days"])).strftime("%Y-%m-%d")
    est_turns = cum
    out["economics"] = econ
    # carry forward any owner-run corner reconciliations so the evidence persists
    # across re-plans (and stays visible to the NEXT brief's _reconcile_block).
    if (prev or {}).get("reconcile"):
        out["reconcile"] = prev["reconcile"]
    out["goal"] = goal
    out["model"] = cli_model or "default"
    out["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    # GATE: an independent verifier can only DOWNGRADE readiness, never upgrade it.
    ver = _verify_plan(out, econ, quota)
    out["verify"] = ver
    if not ver.get("ready", True):
        out["plan_status"] = "blocked"
        if not (out.get("gate") or "").strip():
            out["gate"] = ver.get("gate", "")
    oq = list(out.get("open_questions") or [])          # verifier's must-asks join the questions
    for q in ver.get("must_ask", []):
        if isinstance(q, str) and q.strip() and q not in oq:
            oq.append(q)
    out["open_questions"] = oq
    # CRITICAL GATE over the golden triangle - AFTER the verifier so it sees the
    # final plan_status. The LLM PROPOSES each corner; this MEASURED check only
    # DOWNGRADES (ok -> blocked), never beautifies - without it the triangle was
    # the planner's own optimism ("Budget gruen" at 111% weekly pacing). Same
    # "only tightens" law as the verifier and gate-before-review.
    _gate_triangle(out, econ, est_turns, pace)
    _write_artifact(out)
    return out


def _epic_description(ms):
    """The PMP-scoped, owner-language body for ONE epic card: a user story,
    acceptance criteria (Definition of Done), why it's next, and the work
    breakdown (WBS) as an in-card checklist - never separate tickets. No card
    ids, file paths, or internal jargon; the owner reads this cold."""
    parts = []
    story = (ms.get("user_story") or "").strip()
    if story:
        parts.append("NUTZERGESCHICHTE\n" + story)
    done_when = [str(d).strip() for d in (ms.get("done_when") or []) if str(d).strip()]
    if done_when:
        parts.append("FERTIG, WENN\n" + "\n".join("- " + d for d in done_when))
    why_now = (ms.get("why_now") or "").strip()
    if why_now:
        parts.append("WARUM JETZT\n" + why_now)
    steps = [str(s).strip() for s in (ms.get("steps") or []) if str(s).strip()]
    if steps:
        parts.append("ENTHÄLT\n" + "\n".join("- " + s for s in steps))
    return "\n\n".join(parts) or (ms.get("name") or "")


def plan_items(b=None):
    """The actionable NEW epics from a brief (milestones not yet on the board),
    ordered by priority - what an executor (the night ticker) should file as
    cards. ONE card PER MILESTONE (epic): its steps stay a checklist inside
    that card, not separate tickets, so a card is a long-lived, context-rich
    chat instead of a fragment. Returns (items, brief). Each item:
    {title, description, priority, repo}."""
    import events
    b = b or brief()
    order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    default_repo = events.settings().get("default_repo") or ""
    items = []
    for ms in b.get("milestones", []):
        if str(ms.get("status")) == "done" or ms.get("card"):
            continue
        title = (ms.get("name") or "").strip()
        if not title:
            continue
        items.append({"title": title,
                      "description": _epic_description(ms),
                      "priority": ms.get("priority", "medium"),
                      "repo": ms.get("repo") or default_repo})
        # due dates are NOT set here - the OVERVIEW loop state builds the
        # Timeline from the plan, so that capability lives in the loop, not
        # in this filing code (see _build_overview).
    items.sort(key=lambda x: order.get(x.get("priority"), 2))
    return items, b


# -- Phase 3: stream-card consolidation (propose -> confirm -> merge) ---------
# Fewer, bigger, context-rich cards: 2-5 durable STREAM cards per repo
# (backend / ux / feature / infra / docs), so a card is a long-lived chat with
# context - not a pile of micro-tickets that fragment it. The PM PROPOSES the
# mapping (read-only); applying it is explicit and NON-DESTRUCTIVE (members are
# reversibly archived, their gist rolled into the stream card).

_CONSOLIDATE_ASK = """The board has too many small cards, which fragments context.
Propose consolidating the BACKLOG cards into 2-5 durable STREAM cards PER REPO
(streams: backend / ux / feature-<x> / infra / docs). For each stream give a
clear title and the EXISTING backlog card ids that roll into it. Leave
working/review/done cards alone. Prefer FEW streams. Reply with ONLY JSON:
{"repos":[{"repo":"<abs repo path>","streams":[
  {"name":"backend","title":"<stream card title>","members":["<card id>", ...],"why":"<one line>"}]}]}"""


def consolidation_proposal(model=""):
    """Read-only: the PM's proposed roll-up of backlog cards into stream cards."""
    import copilot, turnopts
    cli_model, _ = turnopts.resolve_model(model or "auto", "consolidate the board",
                                          False, signals={"priority": "high"})
    prompt = _CONSOLIDATE_ASK + "\n\nBOARD SNAPSHOT:\n" + copilot._snapshot()
    out = _ask(prompt, cli_model)
    return {"repos": out.get("repos", []) if isinstance(out, dict) else [],
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S")}


def apply_consolidation(repos, actor="owner"):
    """Non-destructive: create each stream card, then REVERSIBLY archive its
    members (their titles roll into the stream card's description). Returns what
    changed so the caller can show/undo it."""
    import sessions
    tracks = {t["id"]: t for t in sessions.list_tracks()}
    created, archived = [], []
    for rp in repos or []:
        repo = rp.get("repo") or ""
        if not repo:
            continue
        for st in rp.get("streams", []):
            members = [m for m in (st.get("members") or []) if m in tracks]
            if not members:
                continue
            rolled = "\n".join("- " + (tracks[m].get("task") or "") for m in members)
            body = ("Stream-Karte (%s) - kontextreich, langlebig.\n\nEingerollte Tickets:\n%s"
                    % (st.get("name") or "stream", rolled))
            slug = re.sub(r"[^a-z0-9]+", "-", (st.get("name") or "stream").lower())[:20]
            nt = sessions.new_track(repo, "stream-" + slug,
                                    st.get("title") or st.get("name") or "Stream",
                                    lane="backlog", description=body,
                                    priority="medium", actor=actor)
            created.append({"id": nt["id"], "title": nt.get("task"), "members": members})
            for m in members:
                try:
                    sessions.archive_track(m, on=True, actor=actor)
                    archived.append(m)
                except Exception:
                    pass
    return {"created": created, "archived": archived}


# ============================================================================
# THE SINGLE PROACTIVE LOOP  (this replaced daemon/nightshift.py)
#
# Pattern: helpful, not nagging.
#   1. QUIET BY DEFAULT   - it updates the plan/board silently; silence = on-track.
#   2. PRESENCE-AWARE     - acts only while you are AWAY (idle >= idle_minutes) and
#                           backs off the moment you touch any surface; never
#                           competes for your attention or quota.
#   3. REVERSIBLE->AUTO   - it files + dispatches work within the WIP/quota gates
#      IRREVERSIBLE->ASK    (all reversible); merge/accept stay at the gate/human.
#   4. RATE-LIMITED       - a daily dispatch cap + a ~5h pause on the flat-plan
#                           quota signal (_limit_hit). Interrupts only for blockers.
#   5. ONE VOICE          - one loop, one plan artifact, one Dashboard digest.
# ============================================================================



def _limit_hit(track):
    """Flat-plan budget signal: the driver hit a usage limit. Prefer the
    structured subtype/error the driver surfaced; fall back to prose for legacy."""
    subtype = (track.get("last_subtype") or "").lower()
    if subtype:
        err = (track.get("last_error") or "").lower()
        return ("limit" in subtype or "usage limit" in err or "rate limit" in err
                or "limit reached" in err)
    txt = (track.get("last_reply") or "").lower()
    return "usage limit" in txt or "rate limit" in txt or "limit reached" in txt


def make_plan(actor="owner"):
    """Run the PM role now and file its NEW items as backlog cards (deduped).
    The reviewable brief is the day's plan artifact. One planning brain."""
    import sessions
    items, brief = plan_items()
    # When a goal is set it is managed as a PROCESS (epic): the process owns the goal-path
    # cards (step -> card, dated, in a SoW), built from THIS plan's vetted milestones once
    # triage is green. Keep the brief as the analysis artifact but never flat-file cards for
    # a goal - that was the duplication that left tickets unassigned.
    if get_goal():
        items = []
    have = {t.get("task", "").strip().lower() for t in sessions.list_tracks()}
    allow = {os.path.normcase(r) for r in (_pm().get("repos") or [])}
    filed = 0
    for it in items:
        repo = it.get("repo") or ""
        if not repo or not os.path.isdir(repo):
            continue
        if allow and os.path.normcase(repo) not in allow:
            continue                      # safety allowlist
        if it["title"].strip().lower() in have:
            continue
        sessions.new_track(
            repo, "pm-" + re.sub(r"[^a-z0-9]+", "-", it["title"].lower())[:24],
            it["title"], lane="backlog", description=it.get("description", ""),
            priority=it.get("priority", "medium"), actor="pm")
        filed += 1
        have.add(it["title"].strip().lower())
    st = _loopstate()
    st["last_plan"] = time.strftime("%Y-%m-%d %H:%M")
    st.setdefault(_today(), {"dispatched": [], "paused_at": 0})
    _save_loopstate(st)
    _activity("planned", ("Geplant: %d neue Aufgabe(n) angelegt." % filed) if filed
              else "Plan geprüft – nichts Neues nötig.")
    if filed:                                   # only speak up when something changed
        summary = (brief.get("summary") or "").strip()
        _say(("Kurzes Update: ich hab %d neue Aufgabe(n) fuer dein Ziel eingeplant." % filed)
             + (("\n\n" + summary[:350]) if summary else ""))
    print("PM plan: %d Kandidaten, %d neue Karten" % (len(items), filed))
    return {"filed": filed, "candidates": len(items), "brief": brief}


def _notify_deliveries(day, tracks, st, pm):
    """Essential-only, rate-limited PUSH (the 'notify' channel): when a card the
    PM started DELIVERS (needs your review) or BOUNCES, ping ONCE. Silence
    otherwise - this is the proactive-not-nagging bit. NOT presence-gated: a
    delivery matters whether or not you're idle.

    A bounce is only escalated to you AFTER the coordinator has EXHAUSTED its
    delegation attempts (id in day['resolved']) - or immediately if autonomy isn't
    'act', when the PM won't auto-resolve. Every escalation carries a CONCRETE
    unblock proposal (_unblock_proposal), never just 'it is stuck'. The chat
    message goes out even without FCM - push is an extra channel, not the gate."""
    auto = pm.get("autonomy", "act")
    resolved = set(day.get("resolved", []))
    fcm = None
    try:
        import notify
        if notify.fcm_ready():
            fcm = notify
    except Exception:
        pass
    notified = set(day.setdefault("notified", []))
    disp = set(day.get("dispatched", []))
    changed = False
    for t in tracks:
        if t["id"] in notified:
            continue
        s = t.get("status")
        task = (t.get("task") or "").replace("\n", " ")[:60]
        if s == "needs_you" and t["id"] in disp and t.get("waiting_on") == "background":
            continue        # waiting on its OWN background task: not delivered and
                            # not the owner's move - stay quiet (Phase 2.5)
        if s == "needs_you" and t["id"] in disp and t.get("question"):
            # asking, not finished. notify.card_event already pushed this one
            # through the presence policy (and deduped it), so the PM only
            # speaks in chat here - a second push would defeat that policy.
            import ask
            _say(_i18n.t("pm.asking", task=task,
                         question=ask.summary(t["question"])[:140]))
            notified.add(t["id"]); changed = True
        elif s == "needs_you" and t["id"] in disp:
            if fcm:
                fcm.push_fcm(_i18n.t("push.pmDone"), _i18n.t("push.pmDoneBody", task=task), t["id"])
            _say(_i18n.t("pm.delivered", task=task))
            notified.add(t["id"]); changed = True
        elif s == "bounced" and (t["id"] in resolved or (auto != "act" and t["id"] in disp)):
            # escalate only once the coordinator gave up (or won't auto-resolve) -
            # and ALWAYS with a concrete next step attached
            prop = _unblock_proposal(t)
            if fcm:
                fcm.push_fcm(_i18n.t("push.pmStuck"),
                             _i18n.t("push.pmStuckBody", task=task, proposal=prop[:140]), t["id"])
            _say(_i18n.t("pm.stillStuck", task=task, proposal=prop))
            notified.add(t["id"]); changed = True
    if changed:
        day["notified"] = list(notified)
        _save_loopstate(st)


def _backlog(tracks, pm, day):
    """Dispatch candidates: un-started backlog cards in ALLOWED repos, prio-first."""
    allow = {os.path.normcase(r) for r in (pm.get("repos") or [])}
    rank = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    return sorted(
        (t for t in tracks
         if t.get("lane") == "backlog" and t["id"] not in day.get("dispatched", [])
         and t.get("mode") not in ("human", "teach", "cowork")
         and (not allow or os.path.normcase(t.get("repo") or "") in allow)),
        key=lambda t: (rank.get(t.get("priority"), 2), t.get("created") or ""))


# -- RESOLVE: the coordinator's resilience ladder ------------------------------
# On ANY bounce the PM actively finds a path forward before it ever bothers you:
#   classify the blocker (dispatch failed / dirty shared checkout / real merge
#   conflict / gate red) -> delegate the matching fix -> RE-SUBMIT so the gate,
#   not a human, decides whether the card is unstuck -> if it bounces AGAIN,
#   retry once with a DIFFERENT approach -> only then escalate, and always with
#   a concrete unblock proposal attached (_unblock_proposal).
_RESOLVE_MAX = 2            # delegation attempts per card per day before escalating
_resolving = set()          # card ids with a fix currently in flight (thread running)
_resolving_lock = threading.Lock()   # guards _resolving + loopstate writes from threads


def _bounce_kind(t):
    """Classify WHY a card bounced, from its persisted state:
      dispatch - never got a worktree (dispatch/start failed) -> retry the start
      dirty    - 'conflict' that is really git refusing to merge over an
                 uncommitted shared checkout -> park_and_retry_merge (resolve_blocker)
      conflict - real <<<<<<< markers -> the card's own worker resolves by editing
      gate     - gate red / error / zombie note -> steer the worker with the reason"""
    import sessions
    wt = t.get("worktree")
    if not wt or not os.path.isdir(wt):
        return "dispatch"
    if sessions._is_dirty_block(t.get("merge_report") or ""):
        return "dirty"
    if t.get("merge_kind") == "conflict" and t.get("merge_report"):
        return "conflict"
    return "gate"


def _unblock_proposal(t):
    """The concrete next step attached to EVERY escalation - the owner never gets
    a bare 'it is stuck', always a decision they can take in one move."""
    kind = _bounce_kind(t)
    branch = t.get("branch") or t.get("id", "")
    if kind == "dispatch":
        err = ((t.get("last_reply") or "").split("\n")[0])[:160] or "Dispatch-Fehler"
        return ("Vorschlag: Repo/Setup pruefen (%s) und die Karte dann wieder auf "
                "'In Arbeit' ziehen - meine automatischen Neustarts haben es nicht behoben." % err)
    if kind == "dirty":
        return _i18n.t("unblock.dirty", branch=branch)
    if kind == "conflict":
        rep = ((t.get("merge_report") or "").split("\n")[0])[:160]
        return _i18n.t("unblock.conflict", branch=branch, detail=rep)
    reason = (" | ".join(p.split("\n")[0] for p in (t.get("gate_report") or []))
              or (t.get("last_error") or ""))[:200] or _i18n.t("unblock.reasonFallback")
    return _i18n.t("unblock.gate", reason=reason)


def _bump_attempt(tid):
    """Count a delegation attempt (thread-safe: resolve threads and the tick
    share the loopstate file). Returns the attempt number just started (1-based)."""
    with _resolving_lock:
        st = _loopstate()
        day = st.setdefault(_today(), {"dispatched": [], "paused_at": 0})
        att = day.setdefault("resolve_attempts", {})
        att[tid] = att.get(tid, 0) + 1
        _save_loopstate(st)
        return att[tid]


def _give_up(tid):
    """Mark a card escalation-ready: attempts exhausted, _notify_deliveries now
    pings the owner ONCE - with the unblock proposal attached."""
    with _resolving_lock:
        st = _loopstate()
        day = st.setdefault(_today(), {"dispatched": [], "paused_at": 0})
        if tid not in day.setdefault("resolved", []):
            day["resolved"].append(tid)
        _save_loopstate(st)


def _bounced_to_resolve(tracks, pm, day):
    """Bounced cards in ALLOWED repos the coordinator can still move forward:
    fewer than _RESOLVE_MAX attempts today, not given up on (day['resolved']),
    no fix currently in flight. Cards WITHOUT a worktree count too - a failed
    dispatch is retried, not silently abandoned."""
    allow = {os.path.normcase(r) for r in (pm.get("repos") or [])}
    given_up = set(day.get("resolved", []))
    attempts = day.get("resolve_attempts") or {}
    with _resolving_lock:
        busy = set(_resolving)
    return [t for t in tracks
            if t.get("status") == "bounced" and t["id"] not in given_up
            and t["id"] not in busy
            and attempts.get(t["id"], 0) < _RESOLVE_MAX
            and t.get("mode") not in ("human", "teach", "cowork")
            and not t.get("autopilot")   # autopilot drives its own cards (processes._autopilot)
            and (not allow or os.path.normcase(t.get("repo") or "") in allow)]


def _resolve_next(pm, st, day):
    """Kick ONE delegation attempt for the next bounced card, on its own thread
    (a fix can take minutes; the tick must not block). Attempts are counted in
    day['resolve_attempts']; after _RESOLVE_MAX failed attempts the card moves to
    day['resolved'] and _notify_deliveries escalates it WITH a proposal."""
    import sessions
    todo = _bounced_to_resolve(sessions.list_tracks(), pm, day)
    if not todo:
        return
    t = todo[0]
    with _resolving_lock:
        if t["id"] in _resolving:
            return
        _resolving.add(t["id"])
    attempt = _bump_attempt(t["id"])
    threading.Thread(target=_resolve_card, args=(t["id"], attempt), daemon=True,
                     name="pm-resolve").start()


def mark_notified(tid):
    """Record that this card's escalation has already gone out, so the PM's own
    _notify_deliveries doesn't push it a SECOND time. The autopilot escalates
    its cards itself (it must work even with the PM loop switched off) and
    calls this so the owner still gets exactly one ping per stuck card."""
    with _resolving_lock:
        st = _loopstate()
        day = st.setdefault(_today(), {"dispatched": [], "paused_at": 0})
        if tid not in day.setdefault("notified", []):
            day["notified"].append(tid)
            _save_loopstate(st)


# -- BURN GUARD: the PM judges a driver-flagged loop and acts on the ladder ----
# The driver folds the mechanical signal (N identical tool calls - it alone sees
# the frames); the PM owns the JUDGEMENT (legit retry vs. real loop, it knows the
# card + goal) and the owner is the LAST instance (escalated to only if the PM's
# own correction doesn't take). Same shape as resolve_card_now: classify ->
# correct -> re-check -> escalate, bounded by _RESOLVE_MAX.
_burn_lock = threading.Lock()
_burn_active = set()


def review_burn(tid):
    """Entry point (called by sessions.flag_burn). Judges on its OWN thread so the
    driver's event pump never blocks on a model call; one review per card at a
    time."""
    with _burn_lock:
        if tid in _burn_active:
            return
        _burn_active.add(tid)
    threading.Thread(target=_review_burn, args=(tid,), daemon=True, name="pm-burn").start()


def _burn_judge(b, t):
    """One model call: is the repetition a legit retry or a real loop? Returns
    {verdict: legit|loop, why, fix}. A judge failure defaults to 'loop' - the
    signal already crossed the threshold, and a wrong correction only costs a
    detour turn (interrupt-and-replace keeps the session)."""
    prompt = (
        "Ein Worker-Agent hat denselben Tool-Aufruf %d Mal HINTEREINANDER gemacht:\n"
        "  Tool: %s\n  Input (gekuerzt): %s\n"
        "Aufgabe der Karte: %s\n\n"
        "Ist das ein LEGITIMER Retry (Warten/Polling mit Backoff, bewusste Wiederholung) "
        "oder ein sinnloser LOOP (immer derselbe fehlschlagende Schritt)?\n"
        "Antworte NUR als JSON: {\"verdict\":\"legit\"|\"loop\",\"why\":\"kurz\","
        "\"fix\":\"eine konkrete Kurskorrektur an den Worker, falls loop\"}"
        % (b.get("n", 0), b.get("name", ""), (b.get("sample") or "")[:200],
           (t.get("task") or "")[:200]))
    try:
        d = _ask(prompt)
        v = str(d.get("verdict", "")).lower()
        return {"verdict": "legit" if v == "legit" else "loop",
                "why": d.get("why", ""), "fix": d.get("fix", "")}
    except Exception:
        return {"verdict": "loop", "why": "Urteil fehlgeschlagen", "fix": ""}


def _push_burn(t, task, b):
    n, tool, corr = b.get("n", 0), b.get("name", ""), b.get("corrections", 0)
    try:
        import notify
        notify.push_fcm(_i18n.t("push.pmBurn"),
                        _i18n.t("push.pmBurnBody", task=task, n=n, tool=tool), t["id"])
    except Exception:
        pass
    _say(_i18n.t("pm.burnStuck", task=task, n=n, tool=tool, corr=corr))


def _review_burn(tid):
    import sessions
    try:
        t = sessions._find(sessions._load(), tid)
        b = (t or {}).get("burn")
        if not t or not b or t.get("status") != "running":
            return                              # turn already ended - nothing to correct
        task = (t.get("task") or "").replace("\n", " ")[:60]
        corrections = b.get("corrections", 0)
        if corrections >= _RESOLVE_MAX:         # corrected enough - hand it to the owner
            _activity("blocked", "Loop besteht trotz %d Korrekturen - eskaliere: %s"
                      % (corrections, task), card=tid)
            _push_burn(t, task, b)
            return
        verdict = _burn_judge(b, t)
        if verdict["verdict"] == "legit":
            _activity("resolve", "Wiederholung ist legitim (%s) - lasse laufen: %s"
                      % ((verdict.get("why") or "Backoff/Warten")[:60], task), card=tid)
            return
        if _pm().get("autonomy", "act") == "notify":   # advise-only: never touch the worker
            _activity("blocked", "Loop-Verdacht (%dx %s) - melde an Owner: %s"
                      % (b.get("n"), b.get("name"), task), card=tid)
            _push_burn(t, task, b)
            return
        fix = verdict.get("fix") or (
            "Du wiederholst denselben Schritt (%s) %dx mit gleichem Ergebnis. Brich diesen "
            "Ansatz ab, lies die letzte Fehlermeldung woertlich und mach den kleinsten ANDEREN "
            "Schritt, der die Ursache trifft." % (b.get("name"), b.get("n")))

        def _bump(tt):
            if tt.get("burn"):
                tt["burn"]["corrections"] = corrections + 1
        sessions._mutate(tid, _bump)
        _activity("resolve", "Loop erkannt - korrigiere Worker (Versuch %d): %s"
                  % (corrections + 1, task), card=tid)
        # steer-while-running = interrupt-and-replace: breaks the loop and
        # continues the SAME session with the correction (a36d962).
        sessions.steer(tid, fix, actor="pm", source="pm-burn")
    except Exception as e:
        _activity("resolve", "Burn-Review-Fehler: %s" % str(e)[:120], card=tid)
    finally:
        with _burn_lock:
            _burn_active.discard(tid)


def resolve_card_now(tid):
    """Run ONE rung of the resilience ladder for a SPECIFIC card, outside the
    proactive loop's gating (loop_enabled / window / idle / repo allowlist).
    The per-card autopilot (processes._autopilot) calls this so an opted-in
    card gets exactly the same classify -> delegate -> re-submit -> escalate
    treatment without waiting for the PM's idle window - ONE ladder, not two.
    Attempts share the PM's day budget (_RESOLVE_MAX), so a card can't be
    worked twice per day by two callers. Returns:
      "started"   - an attempt is now running on its own thread
      "busy"      - a fix for this card is already in flight
      "exhausted" - attempts used up; the caller escalates (_unblock_proposal)"""
    day = _loopstate().get(_today(), {})
    if tid in set(day.get("resolved", [])) \
       or (day.get("resolve_attempts") or {}).get(tid, 0) >= _RESOLVE_MAX:
        return "exhausted"
    with _resolving_lock:
        if tid in _resolving:
            return "busy"
        _resolving.add(tid)
    attempt = _bump_attempt(tid)
    threading.Thread(target=_resolve_card, args=(tid, attempt), daemon=True,
                     name="pm-resolve-auto").start()
    return "started"


def _resolve_card(tid, attempt):
    """One delegation attempt (runs on its own thread): pick the matching unblock
    path, then RE-SUBMIT to Review so the gate verdict decides whether the card
    is unstuck - the loop never waits for a human to press retry. A second
    attempt explicitly demands a DIFFERENT approach from the worker."""
    import sessions
    note = ""
    try:
        t = sessions._find(sessions._load(), tid)
        if not t or t.get("status") != "bounced":
            return
        kind = _bounce_kind(t)
        task = (t.get("task") or "").replace("\n", " ")[:60]
        if attempt == 1 and kind != "dispatch":
            _say(_i18n.t("pm.onIt", task=task, kind=kind))
        if kind == "dispatch":
            _activity("resolve", "Dispatch schlug fehl - starte neu (Versuch %d): %s"
                      % (attempt, task), card=tid)
            sessions.move_lane(tid, "working", actor="pm")   # idempotent re-dispatch
        elif kind == "dirty":
            _activity("resolve", "Unsauberer Haupt-Checkout blockiert - parke + pruefe neu: "
                      + task, card=tid)
            note = sessions.park_and_retry_merge(tid, actor="pm")
        else:
            if kind == "conflict":
                _activity("resolve", "Merge-Konflikt an Worker delegiert (Versuch %d): %s"
                          % (attempt, task), card=tid)
                note = sessions.dispatch_conflict_resolution(tid, actor="pm", background=False)
                if "resolve_blocker" in note:
                    # mis-filed: the 'conflict' is really a dirty shared checkout -
                    # switch tools instead of stalling on the wrong one
                    _activity("resolve", "Kein Marker-Konflikt, sondern Checkout-Blocker - "
                              "wechsle auf park+retry: " + task, card=tid)
                    note = sessions.park_and_retry_merge(tid, actor="pm")
            else:   # gate red / error / zombie
                reason = (" | ".join(t.get("gate_report") or []) or t.get("last_error")
                          or "Review rot")[:500]
                if attempt <= 1:
                    instr = ("Die Karte ist beim Review gebounct. Grund: %s. Behebe die "
                             "Ursache im Code (nur editieren, kein git); das Neu-Einreichen "
                             "uebernehme ich." % reason)
                else:
                    instr = ("Zweiter Anlauf - der erste Fix hat den Bounce NICHT behoben. "
                             "Grund weiterhin: %s. Waehle einen ANDEREN Ansatz: hinterfrage "
                             "die Annahme hinter dem letzten Fix, lies die Fehlermeldung "
                             "woertlich und mach die kleinste Aenderung, die die Ursache "
                             "trifft (nur editieren, kein git)." % reason)
                _activity("resolve", "Fix an Worker delegiert (Versuch %d): %s"
                          % (attempt, task), card=tid)
                sessions.steer(tid, instr, actor="pm", source="pm-resolve")
            # delegate-then-verify: re-submit so the gate re-runs NOW; a green gate
            # parks the card on Review as 'submitted' for your accept (accept/merge
            # stay gated to you - the law), a red one bounces for the next rung.
            # Unconditional on status: 'already resolved, just re-submit' is a
            # real dispatch_conflict_resolution outcome that leaves it bounced.
            cur = sessions._find(sessions._load(), tid)
            if cur and cur.get("lane") in ("working", "review"):
                sessions.move_lane(tid, "review", actor="pm")
    except Exception as e:
        note = ("%s" % e)[:200]
    finally:
        with _resolving_lock:
            _resolving.discard(tid)
    t = sessions._find(sessions._load(), tid)
    task = ((t or {}).get("task") or "").replace("\n", " ")[:60]
    if t and t.get("status") != "bounced":
        _activity("resolve", "Wieder frei (Versuch %d): %s" % (attempt, task), card=tid)
        _say(_i18n.t("pm.freeAgain", task=task, note=(" - " + note[:200]) if note else "."))
    elif attempt >= _RESOLVE_MAX:
        _give_up(tid)
        _activity("blocked", "Haengt trotz %d Fix-Versuchen - eskaliere mit Vorschlag: %s"
                  % (attempt, task), card=tid)
        # the escalation itself (push + proposal) goes out via _notify_deliveries
    else:
        _activity("resolve", "Versuch %d hat nicht gereicht - naechster Anlauf mit anderem "
                  "Ansatz: %s" % (attempt, task), card=tid)


def _launch_checkin(pm, st):
    """Proactive coordinator question, ONCE per goal: surface the human-only
    launch prerequisites for the store deploy so the owner isn't the late
    bottleneck. The PM drives everything else itself. Re-asks only if the goal
    text changes (a new north star)."""
    goal = pm.get("goal") or ""
    if not any(k in goal.lower() for k in ("launch", "store", "android", "play", "deploy")):
        return
    if st.get("launch_asked") == goal:
        return
    st["launch_asked"] = goal
    _save_loopstate(st)
    _say(_i18n.t("pm.launchCheck"))



def _usage_checkin(st):
    """Proactive quota pacing: flag when the weekly Claude window burns ahead of pace
    (e.g. 40% by Wednesday, projected over 100% before the Saturday reset). Once per
    weekly window (keyed on its reset), so it's a heads-up, not a nag - the live usage
    meter carries the running numbers."""
    try:
        import usage
        flag = usage.weekly_pacing_flag()
    except Exception:
        return
    if not flag:
        return
    if st.get("usage_flagged_reset") == (flag.get("resetsAt") or ""):
        return
    st["usage_flagged_reset"] = flag.get("resetsAt") or ""
    _save_loopstate(st)
    _escalate(_usage_flag_text(flag), title=_i18n.t("push.pmQuota"))


def _plan_gate_notice(st):
    """The planning GATE speaks: when the plan isn't 'ready' - a decision, a spike, or a
    prerequisite blocks a confident estimate - the PM says so plainly and holds, instead of
    pretending with a shallow schedule. Once per distinct gate (content-deduped)."""
    plan = latest_plan() or {}
    if not get_goal() or _triage_green(plan):     # gate is GREEN (or no goal) -> nothing to say
        return
    tri = plan.get("triage") or {}
    red = [k for k in ("budget", "timeline", "scope") if tri.get(k) == "blocked"]
    gate = (plan.get("gate") or "").strip()
    ver = plan.get("verify") or {}
    issues = [i for i in (ver.get("issues") or []) if isinstance(i, str) and i.strip()]
    import hashlib
    key = hashlib.sha1(("|".join(red) + "|" + gate + "|" + "\n".join(issues)).encode("utf-8")).hexdigest()[:12]
    if st.get("plan_gate_key") == key:
        return
    st["plan_gate_key"] = key
    _save_loopstate(st)
    corner = {"budget": "Budget", "timeline": "Timeline", "scope": "Scope"}
    head = ("Ziel-Plan-Gate ROT — die Triage hält (%s). Kein Dispatch, bis das grün ist."
            % ", ".join(corner[c] for c in red) if red else
            "Ziel-Plan-Gate ROT — ich kann noch nicht seriös schätzen. Kein Dispatch, bis geklärt.")
    msg = head + ((" Gate: %s" % gate) if gate else "")
    if issues:
        msg += "\n" + "\n".join("• " + i for i in issues[:4])
    if red:
        # never dead-end: a red corner is ACTIONABLE - offer the evidence check
        # that can re-derive it (reconcile_corner), not just a hold.
        msg += ("\nSag „prüfe %s“, dann hole ich die echte Evidenz zu der roten Ecke "
                "nach und plane damit neu." % corner[red[0]])
    _say(msg)


def _needs_from_owner(st):
    """The PM ASKS instead of silently guessing: surface the plan's open_questions
    (material info the PM is missing) to the owner. Best-effort planning still needs
    answers a good PM chases. Deduped by content, so the same set isn't re-asked every
    plan - it re-asks only when the questions actually change, and stays silent when
    the plan has none."""
    plan = latest_plan() or {}
    qs = [q.strip() for q in (plan.get("open_questions") or []) if isinstance(q, str) and q.strip()]
    if not qs:
        return
    import hashlib
    key = hashlib.sha1("\n".join(qs).encode("utf-8")).hexdigest()[:12]
    if st.get("asked_questions") == key:
        return
    st["asked_questions"] = key
    _save_loopstate(st)
    body = "\n".join("• " + q for q in qs[:5])
    msg = ("Bevor ich weiterplane, fehlt mir Info — kannst du kurz klären?\n" + body
           + "\n(Ich plane derweil bestmöglich mit Annahmen weiter; siehe Plan.)")
    _say(msg)


def _triangle_watch(st):
    """Management by exception: between the DAILY plans, inspect the iron triangle
    (Budget / Timeline / Scope) against today's baseline and ESCALATE to the owner the
    moment a corner tilts. Daily planning sets the baseline; this is the ongoing monitor.
    Deduped by the tilt's content; clears itself when the triangle is level again."""
    corners = []
    # BUDGET — the weekly quota is burning ahead of pace
    try:
        import usage
        bf = usage.weekly_pacing_flag()
    except Exception:
        bf = None
    if bf:
        corners.append("Budget: Wochenkontingent voraus (projiziert ~%s%%, vor dem Reset erschöpft)"
                       % round(bf.get("projected_pct") or 0))
    # TIMELINE + SCOPE — from the goal's process (epic)
    gp = st.get("goal_process") or {}
    if gp.get("pid") and gp.get("goal") == get_goal():
        try:
            import processes
            p = processes.get(gp["pid"])
        except Exception:
            p = None
        if p:
            steps = p.get("steps") or []
            today = time.strftime("%Y-%m-%d")
            overdue = [s for s in steps if s.get("status") != "done" and (s.get("due") or "9999") < today]
            if overdue:
                corners.append("Timeline: %d Schritt(e) über Termin (z. B. „%s“ seit %s)"
                               % (len(overdue), (overdue[0].get("title") or "")[:40], overdue[0].get("due")))
            base = st.get("scope_baseline")
            if not base or base.get("goal") != get_goal():
                st["scope_baseline"] = {"goal": get_goal(), "n": len(steps)}   # self-baseline
                _save_loopstate(st)
            elif len(steps) > base.get("n", len(steps)):
                corners.append("Scope: %d neue Schritt(e) seit Baseline (%d → %d)"
                               % (len(steps) - base["n"], base["n"], len(steps)))
    if not corners:
        if st.get("triangle_key"):
            st.pop("triangle_key", None)
            _save_loopstate(st)
        return
    import hashlib
    key = hashlib.sha1("|".join(corners).encode("utf-8")).hexdigest()[:12]
    if st.get("triangle_key") == key:
        return
    st["triangle_key"] = key
    _save_loopstate(st)
    msg = ("⚠ Dreieck schief — Abweichung von der Tages-Baseline:\n" + "\n".join("• " + c for c in corners)
           + "\nWelche Ecke ist dir heilig (Zeit/Budget/Scope)? Dann steuere ich gegen; sonst entscheidest du.")
    _escalate(msg, title=_i18n.t("push.pmTriangle"))


_WATCH_PRIO = {"urgent": 2.0, "high": 1.5, "medium": 1.0, "low": 0.5}


def _watch_budget_ctx():
    """How this board's REAL budget is denominated, for the watchdog (PMBOK:
    a cost baseline needs a funding source before variances mean anything):
      ("pct", calib) - Max plan with a warm calibration: the honest unit is %
                       of the weekly quota (cost basis when calibrated, else
                       tokens - see events.plan_calibration).
      ("eur", None)  - API plan with a monthly cap: real money.
      ("usd", None)  - no plan size known (cold calibration, capless API):
                       the measured API-equivalent $ - degraded but never
                       silent, and never labeled as spend (ai_billing)."""
    import events
    plan, _src = events.plan_effective()
    if plan == "api" and (_pm().get("monthly_eur") or 0) > 0:
        return "eur", None
    try:
        calib = events.plan_calibration()
    except Exception:
        calib = None
    if plan != "api" and calib and (calib.get("cost_per_pct") or calib.get("tokens_per_pct")):
        return "pct", calib
    return "usd", None


def _watch_bac_pct(base_pct, reserve, prio, weight_sum):
    """One card's Budget At Completion, as an ABSOLUTE % of the plan budget:
    base% x its priority weight (low earns less budget than high), capped by
    its fair share of the allocatable pool - (100% - reserve) split over the
    working set's weights - so allocations SHRINK when more work draws on the
    same window. The reserve is PMBOK's management reserve: the slice never
    allocated to cards (the owner's own interactive use + risk)."""
    w = _WATCH_PRIO.get(prio, 1.0)
    pool = max(0.0, 100.0 - reserve)
    crowd = pool * w / weight_sum if weight_sum > 0 else pool * w
    return max(0.0, min(base_pct * w, crowd))


def _cost_watch(st, tracks):
    """PER-CARD BUDGET WATCHDOG - PMBOK cost control in code, deliberately NOT
    LLM-judged (a judge call per tick would itself be spend, and a budget
    overrun needs no judgement, only arithmetic). The 843/226M-token card ran
    three DAYS with the owner actively steering and not one ping: every
    existing guard is either presence-gated (_board_idle) or watches the WEEK
    (_usage_checkin) - nothing watched ONE card's burn.

    Owner-decreed units: thresholds are ABSOLUTE shares of the REAL budget,
    never shadow-euros (on a Max plan € is a foreign currency - ai_billing),
    and priority earns budget - low gets less than high. So each working card
    gets a Budget At Completion (_watch_bac_pct): watch_base_pct x priority
    weight, capped by its fair share of (100% - watch_reserve_pct) split over
    the cards sharing the window. The BAC recomputes EVERY tick from live
    calibration + WIP + priority - self-adjusting by construction; only the
    SPENT baseline is snapshotted when the card enters 'working'.

    Escalation = PMBOK control thresholds, not a ping per tick: first at 1x
    BAC, re-armed at 2x, 4x, ... (spend is monotonic and can never 'come back
    under'; doubling the rung is what 'clears' this corner). The unit degrades
    honestly (_watch_budget_ctx): % of the weekly quota -> € vs the monthly
    cap -> measured API-equivalent $. ctx_tokens keeps its absolute floor -
    plan-neutral (a full window costs on every plan), clears on compaction,
    re-fires on the next crossing.

    Baselines live in loopstate (survive restarts); a card leaving 'working'
    drops its entry and re-baselines fresh on re-entry. Runs on EVERY tick,
    NOT behind the acting (_in_window/_board_idle) gates - the failure mode is
    burn WHILE the owner is around."""
    pm = _pm()
    ctx_floor = int(pm.get("watch_ctx_floor") or 0) or 150_000
    base_pct = float(pm.get("watch_base_pct") or 0) or 5.0
    reserve = min(95.0, max(0.0, float(pm.get("watch_reserve_pct") or 0.0)))
    watch = st.setdefault("cost_watch", {})
    working = {t["id"]: t for t in tracks
               if t.get("lane") == "working" and not t.get("archived")}
    changed = False
    for tid in [k for k in watch if k not in working]:
        del watch[tid]; changed = True           # left 'working' -> fresh next time
    kind, calib = _watch_budget_ctx()
    weight_sum = sum(_WATCH_PRIO.get(t.get("priority"), 1.0) for t in working.values())
    for tid, t in working.items():
        cost = float(t.get("ai_cost") or 0.0)
        tok = int(t.get("tokens_in") or 0) + int(t.get("tokens_out") or 0)
        ctx = int(t.get("ctx_tokens") or 0)
        w = watch.get(tid)
        if w is None:                            # first tick in 'working' = baseline
            watch[tid] = {"cost": cost, "tok": tok, "mult": 1.0, "ctx_hot": False}
            changed = True
            continue
        task = (t.get("task") or "").replace("\n", " ")[:60]
        prio = t.get("priority") or "medium"
        bac_pct = _watch_bac_pct(base_pct, reserve, prio, weight_sum)
        d_cost = max(0.0, cost - float(w.get("cost") or 0.0))
        d_tok = max(0, tok - int(w.get("tok") or 0))
        if kind == "pct":
            cpp = (calib or {}).get("cost_per_pct")
            spent = d_cost / cpp if cpp else d_tok / float(calib["tokens_per_pct"])
            budget = bac_pct
        elif kind == "eur":
            spent = d_cost
            budget = float(pm.get("monthly_eur") or 0) * bac_pct / 100.0
        else:                                    # cold calibration: shadow-$ ladder
            spent = d_cost
            budget = (float(pm.get("watch_floor_usd") or 0) or 5.0) * _WATCH_PRIO.get(prio, 1.0)
        mult = float(w.get("mult") or 1.0)
        if budget > 0 and spent >= budget * mult:
            # jump PAST the current spend, so one huge turn fires ONE rung -
            # not a backlog of pings on the following ticks
            while budget * mult <= spent:
                mult *= 2.0
            w["mult"] = mult; changed = True
            nxt = budget * mult
            if kind == "pct":
                _activity("blocked", "Budget ueberschritten (%.1f%% von %.1f%% Woche): %s"
                          % (spent, budget, task), card=tid)
                _escalate("💸 Budget-Watchdog: „%s“ liegt über Budget: ~%.1f%% vom "
                          "Wochenkontingent verbraucht, zugeteilt ~%.1f%% (Prio %s, "
                          "%d Karte(n) im Fenster, %.0f%% Reserve). Stoppen, steuern "
                          "oder bewusst weiterlaufen lassen? Nächste Meldung bei ~%.1f%%."
                          % (task, spent, budget, prio, len(working), reserve, nxt),
                          tid=tid, title=_i18n.t("push.pmCost"))
            elif kind == "eur":
                _activity("blocked", "Budget ueberschritten (EUR %.2f von %.2f): %s"
                          % (spent, budget, task), card=tid)
                _escalate("💸 Budget-Watchdog: „%s“ liegt über Budget: ~€%.2f verbraucht, "
                          "zugeteilt ~€%.2f (%.1f%% vom Monats-Cap, Prio %s). Stoppen, "
                          "steuern oder weiterlaufen lassen? Nächste Meldung bei ~€%.2f."
                          % (task, spent, budget, bac_pct, prio, nxt),
                          tid=tid, title=_i18n.t("push.pmCost"))
            else:
                _activity("blocked", "Budget ueberschritten (USD %.2f API-Gegenwert): %s"
                          % (spent, task), card=tid)
                _escalate("💸 Kosten-Watchdog: „%s“ hat seit Arbeitsbeginn ~$%.2f "
                          "API-Gegenwert verbrannt (Kontingent-Kalibrierung noch kalt - "
                          "kein €-Spend auf dem Abo, aber Kontingent). Stoppen, steuern "
                          "oder weiterlaufen lassen? Nächste Meldung bei ~$%.2f."
                          % (task, spent, nxt),
                          tid=tid, title=_i18n.t("push.pmCost"))
        hot = ctx >= ctx_floor
        if hot and not w.get("ctx_hot"):
            w["ctx_hot"] = True; changed = True
            _activity("blocked", "Kontext-Drift: ~%dk Tokens Fenster - eskaliere: %s"
                      % (ctx // 1000, task), card=tid)
            _escalate("🧠 Kontext-Watchdog: „%s“ schleppt ~%dk Tokens Kontext (Schwelle "
                      "%dk) - jeder weitere Turn zahlt das fast volle Fenster. Karte "
                      "kompaktieren, aufteilen oder abschliessen."
                      % (task, ctx // 1000, ctx_floor // 1000),
                      tid=tid, title=_i18n.t("push.pmCtx"))
        elif not hot and w.get("ctx_hot"):
            w["ctx_hot"] = False; changed = True     # compacted back under - re-armed
    if changed:
        _save_loopstate(st)


def _goal_has_process(st):
    """True when the current goal is already tracked as a process (the epic)."""
    gp = st.get("goal_process") or {}
    return bool(gp.get("pid")) and gp.get("goal") == get_goal()


def _goal_process(pm, st):
    """PMP initiation: a new goal becomes a PROCESS (the epic) so goal <-> timeline
    <-> cost are analysable through the existing process/SoW machinery instead of a
    flat card list. Proposes the step breakdown once per goal (processes.create runs
    the proposer in the background, laying end-to-end due dates), and asks the owner
    for the deadline/scope/budget so the schedule and budget are real - the intake
    the PM was missing. The owner reviews/accepts steps in the Prozesse tab; each
    accepted step becomes a card linked to the process (step.track)."""
    goal = get_goal()
    if not goal or _goal_has_process(st):
        return
    # Build the epic from the BRAIN's plan - but only once that plan passed the golden
    # triage (Budget/Timeline/Scope green). While it's blocked, the TRIAGE gate/ask drives
    # (missing deadline/scope/budget/recruitment is surfaced there); we don't commit a
    # process on a shaky plan. This is the fix for "the process came from the dumb proposer":
    # the steps ARE the vetted, dated milestones now, not a context-blind checklist.
    plan = latest_plan() or {}
    if plan.get("goal") != goal or not _triage_green(plan):
        return
    mss = [m for m in (plan.get("milestones") or []) if str(m.get("status")) != "done"]
    if not mss:
        return
    pace = _pace(plan.get("economics") or {})
    steps = []
    for m in mss:
        title = re.sub(r"^\s*M\d+\s*[:\-]\s*", "", (m.get("name") or "").strip())
        if not title:
            continue
        steps.append({"title": title[:120], "desc": _epic_description(m), "mode": "do",
                      "days": max(1, _days(int(m.get("est_turns") or 0), pace)),
                      "status": "proposed", "track": None, "due": ""})
    if not steps:
        return
    try:
        import processes
        p = processes.create(goal, client="", due="", actor="pm", steps=steps)
    except Exception as e:
        print("PM goal_process error:", e)
        return
    st["goal_process"] = {"goal": goal, "pid": p["id"]}
    _save_loopstate(st)
    msg = ("Ziel-Plan ist getriaged (Budget/Timeline/Scope grün) — ich hab ihn als Prozess (Epic) "
           "mit %d datierten Schritten aus dem geprüften Plan angelegt (Prozesse-Tab). Justiere/"
           "akzeptiere die Schritte, dann laufen die Ziel-Karten." % len(steps))
    _say(msg)


def _goal_process_status(st):
    """Compact goal-process view for analysis: (next_open_step_title, next_due,
    process_due, done, total) or None. Cheap read from processes.json."""
    gp = st.get("goal_process") or {}
    if gp.get("goal") != get_goal() or not gp.get("pid"):
        return None
    try:
        import processes
        p = processes.get(gp["pid"])
    except Exception:
        return None
    if not p:
        return None
    steps = p.get("steps") or []
    done = sum(1 for s in steps if s.get("status") == "done")
    nxt = next((s for s in steps if s.get("status") != "done"), None)
    return {"next": (nxt or {}).get("title"), "next_due": (nxt or {}).get("due"),
            "process_due": p.get("due"), "done": done, "total": len(steps),
            "status": p.get("status")}


def _stakeholder_update(st):
    """PMP core: reconcile GOAL vs BUDGET against the LIVE weekly quota and keep the
    stakeholder (owner) informed - a regular status once a day, plus an immediate
    escalation the moment the budget first puts the goal at risk this window. Managing
    goal-vs-budget and informing the stakeholder IS the PM's primary job."""
    goal = get_goal()
    if not goal:
        return
    try:
        import usage
        snap = usage.snapshot()
    except Exception:
        return
    weekly = None
    if snap.get("status") == "ok":
        weekly = next((w for w in snap.get("windows", []) if w.get("id") == "weekly"), None)
    budget = (latest_plan() or {}).get("budget") or {}
    est, eta, pace = budget.get("est_turns_to_goal"), budget.get("eta_days"), budget.get("pace_turns_per_day")
    pacing = (weekly or {}).get("pacing") or {}
    used = (weekly or {}).get("usedPct") or 0
    verdict = "at_risk" if pacing.get("flag") else ("tight" if used >= 80 else "on_track")
    risk_key = (weekly or {}).get("resetsAt") or ""
    risk_new = verdict == "at_risk" and st.get("stakeholder_risk") != risk_key
    if st.get("stakeholder_day") == _today() and not risk_new:
        return                                       # already updated today, nothing worse
    st["stakeholder_day"] = _today()
    if verdict == "at_risk":
        st["stakeholder_risk"] = risk_key
    _save_loopstate(st)
    msg = _goal_budget_text(goal, weekly, est, eta, pace, verdict)
    feas = (latest_plan() or {}).get("feasibility") or {}   # the brain's budget-fit judgement
    if feas.get("budget"):
        de = {"fits": "Budget reicht", "tight": "Budget knapp", "insufficient": "Budget reicht NICHT"}
        fl = de.get(feas["budget"], feas["budget"])
        if feas.get("earliest_done"):
            fl += " · frühestens fertig: %s" % feas["earliest_done"]
        if feas.get("note"):
            fl += " (%s)" % feas["note"]
        msg += " Machbarkeit: %s." % fl
    ps = _goal_process_status(st)         # timeline straight from the goal's process (epic)
    if ps and ps.get("total"):
        line = "Prozess: %d/%d Schritte fertig" % (ps["done"], ps["total"])
        if ps.get("next"):
            line += ", nächster Milestone „%s“%s" % (
                ps["next"][:50], (" bis %s" % ps["next_due"]) if ps.get("next_due") else "")
        if ps.get("process_due"):
            line += " · Ziel-Deadline %s" % ps["process_due"]
        msg += " " + line + "."
    _say(msg)


def _overview_stale(plan, tracks):
    """True if the plan's roadmap isn't reflected on the board yet: a card that
    belongs to a dated milestone still lacks that due date (Timeline), or the
    dashboard layout isn't set."""
    import events
    if not (events.settings().get("policy") or {}).get("dashboard", {}).get("tiles"):
        return True
    byid = {t["id"]: t for t in tracks}
    by_title = {(t.get("task") or "").strip().lower(): t for t in tracks}
    for ms in (plan.get("milestones") or []):
        d = ms.get("target_date")
        if not d:
            continue
        c = byid.get(ms.get("card")) or by_title.get((ms.get("name") or "").strip().lower())
        if not c:
            continue
        if c.get("lane") != "done" and (c.get("due") or "") != d:
            return True
    return False


def _build_overview(plan):
    """OVERVIEW state action: build Dashboard + Timeline FROM THE PLAN.
    - TIMELINE: give each board card its milestone's target date (due) -> the
      board Timeline lays out the roadmap.
    - DASHBOARD: ensure a sensible economics layout exists.
    Reversible edits only; this is a LOOP STATE, not bespoke capability code."""
    import sessions, events
    all_t = sessions.list_tracks()
    byid = {t["id"]: t for t in all_t}
    by_title = {(t.get("task") or "").strip().lower(): t for t in all_t}
    n = 0
    for ms in (plan.get("milestones") or []):
        d = ms.get("target_date")
        if not d:
            continue
        # match by the plan's card id first (reliable), then by title
        c = byid.get(ms.get("card")) or by_title.get((ms.get("name") or "").strip().lower())
        if not c:
            continue
        if c.get("lane") != "done" and (c.get("due") or "") != d:
            try:
                sessions.update_track(c["id"], {"due": d}, actor="pm"); n += 1
            except Exception:
                pass
    pol = dict(events.settings().get("policy") or {})
    if not (pol.get("dashboard") or {}).get("tiles"):
        pol["dashboard"] = {"tiles": ["value_delivered", "ai_spend", "margin", "yield", "automation", "leverage"],
                            "panels": ["capacity", "gates", "work"]}
        events.save_settings({"policy": pol})
    _activity("overview", "Uebersicht gebaut: %d Termine gesetzt (Timeline) + Dashboard-Layout." % n)
    return n


# The proactive loop is now a STATE MACHINE - same idea as tools/loop_state.py:
# the STATE is computed from REALITY (board + plan + config) each tick and drives
# the next action. A new capability = a new STATE (e.g. OVERVIEW), not new code.
def _state():
    """(STATE, plain reason). First actionable state wins. Surfaced to you so you
    can SEE what the PM is doing / about to do. WAIT = wants to act but you're here."""
    pm = _pm()
    if not pm.get("loop_enabled"):
        return ("OFF", "Proaktiv ist aus.")
    import sessions
    tracks = [t for t in sessions.list_tracks() if not t.get("archived")]
    st = _loopstate()
    day = st.get(_today(), {})
    disp = set(day.get("dispatched", []))
    notif = set(day.get("notified", []))
    res = set(day.get("resolved", []))
    auto0 = pm.get("autonomy", "act")
    if any(t["id"] not in notif and (
            (t.get("status") == "needs_you" and t["id"] in disp)
            or (t.get("status") == "bounced"
                and (t["id"] in res or (auto0 != "act" and t["id"] in disp))))
           for t in tracks):
        return ("NOTIFY", "Fertige/haengende Karten melden (mit Vorschlag).")
    acting = _in_window(pm) and _board_idle(pm)          # you're away -> may act
    if st.get("last_plan_day") != _today():
        return ("PLAN", "Tagesplanung steht aus.") if acting else ("WAIT", "Tagesplan faellig, aber du bist da.")
    plan = latest_plan()
    if plan and _overview_stale(plan, tracks):
        return ("OVERVIEW", "Dashboard + Timeline aus dem Plan bauen.") if acting else ("WAIT", "Uebersicht veraltet, aber du bist da.")
    # COORDINATOR: unblock what's stuck (delegate + re-submit, bis zu
    # _RESOLVE_MAX Anlaeufe mit anderem Ansatz) BEFORE starting new work
    if pm.get("autonomy", "act") == "act" and _bounced_to_resolve(tracks, pm, day):
        return ("RESOLVE", "Gebouncte Karte entstoeren (delegieren + neu einreichen).") if acting else ("WAIT", "Bounce zu fixen, aber du bist da.")
    # HARD GATE: a goal exists but its plan hasn't passed the golden triage
    # (Budget/Timeline/Scope green) -> hold ALL dispatch and surface the gate. Ranks
    # after PLAN (today's plan runs first) and RESOLVE (unblocking stuck work still runs).
    if get_goal() and not _triage_green(latest_plan()):
        return ("TRIAGE", "Gate rot: Budget/Timeline/Scope nicht gruen - kein Dispatch, ich kläre/frage.") \
            if acting else ("WAIT", "Plan-Gate rot, aber du bist da.")
    paused = day.get("paused_at") and time.time() - day["paused_at"] < 5 * 3600
    if not paused and len(day.get("dispatched", [])) < pm.get("max_dispatch_per_day", 3) and _backlog(tracks, pm, day):
        return ("DISPATCH", "Naechste Karte starten.") if acting else ("WAIT", "Arbeit da, aber du bist da.")
    return ("IDLE", "Alles im Griff - nichts zu tun.")


def _dispatch_next(pm, st, day):
    import sessions, events
    if sum(1 for t in sessions.list_tracks() if t.get("lane") == "working") >= events.settings()["capacity"]["wip_limit"]:
        return                                           # respect WIP headroom
    todo = _backlog(sessions.list_tracks(), pm, day)
    if not todo:
        return
    # BUDGET MANAGEMENT: if the weekly quota is burning ahead of pace, hold
    # non-urgent cards so the quota lasts to the reset - the PM spends the budget,
    # it doesn't just warn about it. Silent when it can still run high-prio work;
    # announces once per window only when it's actually holding everything back.
    floor = _quota_floor()
    if floor is not None:
        rank = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
        kept = [t for t in todo if rank.get(t.get("priority"), 2) <= floor]
        if not kept:
            key = ""
            try:
                import usage
                key = (usage.weekly_pacing_flag() or {}).get("resetsAt") or ""
            except Exception:
                pass
            if st.get("quota_held_reset") != key:
                st["quota_held_reset"] = key; _save_loopstate(st)
                only = "nur dringende" if floor == 0 else "nur dringende + hohe"
                msg = ("Quota-Management: das Wochenkontingent läuft voraus, deshalb halte ich "
                       "nicht-dringende Karten bis zum Reset zurück (%s Priorität wird noch "
                       "gestartet). Heb die Priorität an oder sag Bescheid, wenn eine trotzdem "
                       "sofort laufen soll." % only)
                _say(msg)
            return
        todo = kept
    t = todo[0]
    day["dispatched"].append(t["id"]); _save_loopstate(st)
    _activity("started", "Gestartet: " + (t.get("task", "")[:70]), card=t["id"])
    t = sessions.move_lane(t["id"], "working", actor="pm")
    if _limit_hit(t):
        day["paused_at"] = time.time(); _save_loopstate(st)
        _activity("blocked", "Quota erschoepft - pausiere ~5 Stunden.")


def _position(tracks, plan):
    """Phase 2+3 distilled: WHERE WE STAND, judged by the triangle. Its JSON
    digest is the delta key - communication fires only when THIS changes."""
    tri = (plan or {}).get("triage") or {}
    return {
        "goal": get_goal(),
        "done_pct": (plan or {}).get("done_pct"),
        "triage": {k: tri.get(k) for k in ("budget", "timeline", "scope")},
        "reasons": (plan or {}).get("triage_reasons") or {},
        "plan_status": (plan or {}).get("plan_status"),
        "needs_you": sorted(t["id"] for t in tracks if t.get("status") == "needs_you"),
        "bounced": sorted(t["id"] for t in tracks if t.get("status") == "bounced"),
        "open_q": (plan or {}).get("open_questions") or [],
    }


def _tick():
    """ONE loop, four phases (the owner's model):
        1 GATHER    all info: board, plan, economics/quota
        2 STAND     read the last plan + chat -> where we are
        3 TRIANGLE  judge Budget/Timeline/Scope (measured, in the plan)
        4 DELTA     communicate ONLY when the position changed
    then the acting states run - but only while you are away. Proactive on/off +
    the notify/ask/act ladder is a Settings control now, not a dashboard one."""
    # 1 - GATHER
    import cells
    if not cells.enabled_id("pm"):
        # ADDITIONAL early-return, not a replacement: loop_enabled (below) is
        # the owner's proactive on/off Settings control; cellEnabled is the
        # separate whole-cell kill switch (Phase 2 of the cell-registry decree).
        return
    pm = _pm()
    if not pm.get("loop_enabled"):
        return
    st = _loopstate()
    day = st.setdefault(_today(), {"dispatched": [], "paused_at": 0})
    import sessions
    tracks = sessions.list_tracks()
    plan = latest_plan()

    # deliveries are EVENT-driven (a card just finished/bounced), not a position
    # delta - always run, they dedup internally.
    _notify_deliveries(day, tracks, st, pm)

    # per-card burn watchdog: code thresholds, and like the deliveries NOT
    # behind the acting/idle gates below - the €843 card burned precisely
    # WHILE the owner was present and steering it.
    _cost_watch(st, tracks)

    # 2+3 - STAND, judged by the TRIANGLE
    pos = _position([t for t in tracks if not t.get("archived")], plan)
    _pkey = json.dumps(pos, sort_keys=True, ensure_ascii=False)

    # 4 - COMMUNICATE ONLY ON DELTA. Persist the new digest FIRST so a substep
    # that re-reads loopstate can't lose it, then run the (internally-deduped)
    # communication paths. Nothing changed -> the loop stays quiet.
    if st.get("pos_digest") != _pkey:
        st["pos_digest"] = _pkey
        _save_loopstate(st)
        _launch_checkin(pm, st)      # ask launch prereqs once
        _goal_process(pm, st)        # new goal -> process (epic) + intake
        _triangle_watch(st)          # escalate when a corner tilts
        _plan_gate_notice(st)        # honest "blocked" over a shallow estimate
        _needs_from_owner(st)        # surface missing-info questions
        _stakeholder_update(st)      # goal vs budget, keep the owner informed

    if not _in_window(pm) or not _board_idle(pm):
        return                                           # acting states need you away
    state, _reason = _state()
    auto = pm.get("autonomy", "act")
    try:
        if state == "PLAN":
            brief() if auto == "notify" else make_plan(actor="pm")
            st = _loopstate(); st["last_plan_ts"] = time.time()
            st["last_plan_day"] = _today()          # daily planning cadence
            st.pop("scope_baseline", None)          # today's plan re-baselines the triangle
            shape = _triage_shape(live_plan())      # re-baseline the flip detector too
            if shape:
                st["plan_triage_shape"] = shape
            _save_loopstate(st)
        elif state == "OVERVIEW":
            _build_overview(latest_plan() or {})         # build Dashboard + Timeline
        elif state == "RESOLVE" and auto == "act":
            _resolve_next(pm, st, day)                   # coordinator: delegate the fix
        elif state == "DISPATCH" and auto == "act":
            _dispatch_next(pm, st, day)
    except Exception as e:
        print("PM tick error [%s]:" % state, e)


def status():
    """Surfaced by /pm/* + /nightshift (alias) + /automation."""
    st = _loopstate()
    sname, sreason = _state()
    return {"config": _pm(), "plan": latest_plan(), "state": sname, "state_reason": sreason,
            "today": st.get(_today(), {"dispatched": [], "paused_at": 0}),
            "last_plan": st.get("last_plan")}


# -- the communication layer: plain-language "what am I doing" (DAU) ----------
# Computed from the REAL board (not LLM-guessed) so it's reliable, and phrased
# for a non-technical owner - no card ids, no jargon. This is how the PM keeps
# you in the loop without nagging: a status + an append-only activity feed.
_ACTIVITY = os.path.join(PLANS, "activity.jsonl")


def _activity(kind, msg, card=None):
    """Append one plain-language line the PM 'said' (planned/started/blocked)."""
    try:
        os.makedirs(PLANS, exist_ok=True)
        with open(_ACTIVITY, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M"), "kind": kind,
                                "msg": msg, "card": card}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _say(text):
    """The PM SPEAKS TO YOU: post a message into the owner's board chat so the
    chat MOVES on its own - real proactive communication, not just a silent feed.
    You can reply there and steer it. (cls 'pm' = a PM-authored message.)
    One voice: the shared writer in copilot.say, which the lane pipeline uses
    too - so everything non-interactive speaks in the same chat."""
    try:
        import copilot
        copilot.say(text, cls="pm")
    except Exception:
        pass


def _escalation_tid():
    """Presence anchor for GOAL-LEVEL escalations (triangle tilt, quota pacing):
    they have no card of their own, but presence.plan wants a card id to decide
    silent/in-app/push. Use the most recently touched working card - that is
    where the owner's attention would be; with none, "" still gives the correct
    present/absent split (nobody can be 'focused' on no card)."""
    try:
        import sessions
        working = [t for t in sessions.list_tracks()
                   if t.get("lane") == "working" and not t.get("archived")]
        if working:
            return max(working, key=lambda t: t.get("updated")
                       or t.get("created") or "")["id"]
    except Exception:
        pass
    return ""


def _escalate(text, tid="", title=""):
    """An ESCALATION, vs. _say (chat only): the chat line always lands, AND the
    alert goes through notify's presence-aware pipe so it reaches the phone as
    a sealed FCM push when the owner is actually AWAY - the route Burn Guard
    proved (_push_burn). _say alone let the €843 card burn for days: its
    warnings sat in a chat nobody had open. Dedup stays with the caller
    (content hash / level ladder); notify.escalate only decides delivery
    (silent / in-app / push)."""
    _say(text)
    try:
        import notify
        notify.escalate(title or _i18n.t("push.pmAlert"), text[:180],
                        tid or _escalation_tid())
    except Exception as e:
        print("pm: escalate push failed:", e)


def _read_activity(n=20):
    try:
        with open(_ACTIVITY, encoding="utf-8") as f:
            lines = f.readlines()[-n:]
        return [json.loads(x) for x in lines if x.strip()]
    except (OSError, ValueError):
        return []


def activity():
    """The DAU narrative: what's running now, what's next, what needs you, and
    the blockers - all from live card state, plus the recent activity feed."""
    import sessions
    # PRESENTED, not stored: "arbeitet gerade an X" was a lie for any card whose
    # turn had died - it reads `running` in the store until the reconciler heals
    # it, so the narrative claimed work was in flight AND left the card out of
    # "needs you". present() derives the truth at read time (invariant I2).
    tracks = [sessions.present(t) for t in sessions.list_tracks() if not t.get("archived")]
    st = _loopstate()

    def lbl(t):
        return (t.get("task") or "").replace("\n", " ")[:70]

    now = []
    for t in tracks:
        if t.get("lane") != "working":
            continue
        s = t.get("status")
        if s == "running":
            now.append("arbeitet gerade an: " + lbl(t))
        elif s == "needs_you":
            # Since Phase 2 the three reasons a card parks ARE distinguishable,
            # so say which one it is instead of lumping them together.
            if t.get("waiting_on") == "background":
                now.append("wartet auf einen Hintergrund-Task: " + lbl(t))
            elif t.get("question"):
                now.append("fragt dich etwas: " + lbl(t))
            else:
                now.append("wartet auf dich: " + lbl(t))
        elif s == "bounced":
            continue        # a bounced card is surfaced ONCE as a blocker below, not here
        else:
            now.append(lbl(t))
    # "waiting on you" = genuinely handed back (needs_you/submitted). A BOUNCED card is
    # NOT that - it's stuck/failed, listed only under blockers, never double-counted.
    # A card waiting on its own background task is nobody's move but the machine's,
    # so it must not pad the owner's to-do count either.
    #
    # Both buckets come out of the ONE derivation (sessions.owner_blockers),
    # split by reason: re-deriving "blocked on you" per surface is exactly what
    # let this narrative and the glasses feed answer the same question
    # differently. It also picks up the case neither of them had - a card whose
    # turn DIED, still stored as `running`, which no status test can see.
    _STUCK = ("gate", "conflict", "failed")
    needs, blockers = [], []
    for t, b in sessions.owner_blockers(tracks):
        (blockers if b["reason"] in _STUCK else needs).append(lbl(t))
    rank = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    todo = sorted((t for t in tracks if t.get("lane") == "backlog"
                   and t.get("mode") not in ("human", "teach", "cowork")),
                  key=lambda t: (rank.get(t.get("priority"), 2), t.get("created") or ""))
    sname, sreason = _state()
    return {
        "loop_enabled": _pm().get("loop_enabled"),
        "autonomy": _pm().get("autonomy"),
        "state": sname,
        "state_reason": sreason,
        "now": now,
        "next": lbl(todo[0]) if todo else None,
        "next_count": len(todo),
        "needs_you": needs,
        "blockers": blockers,
        "quota_paused": bool(st.get(_today(), {}).get("paused_at")),
        "last_plan": st.get("last_plan"),
        "feed": _read_activity(20),
    }


def start_loop():
    """Background ticker - a cheap no-op while loop_enabled is false."""
    def loop():
        while True:
            try:
                _tick()
            except Exception as e:
                try:
                    import events; events.log("pm", "tick error: %s" % e)
                except Exception:
                    pass
            time.sleep(120)
    threading.Thread(target=loop, daemon=True, name="pm-loop").start()
