# -*- coding: utf-8 -*-
"""PM / CTO planning ROLE, run by the thin harness here.

The PM's brain is DATA (ops/harness/agents/pm.md + settings.pm), not code. This module only:
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

from spine.registry import i18n as _i18n

from daemon.paths import DAEMON_ROOT as ROOT
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
    from spine.storage import events
    c = dict(PM_DEFAULTS)
    c.update(events.settings().get("pm") or {})
    return c


def get_goal():
    return (_pm().get("goal") or "").strip()


def set_goal(goal):
    from spine.storage import events
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
    # The role is DATA in the harness layer (ops/harness/agents/pm.md - owner-
    # editable, versioned). brief() is total: a missing/mangled file degrades
    # to the short JSON-shape floor in harness._DEFAULTS, never breaks a plan.
    from spine.registry import harness
    role = harness.brief("pm")
    extra = (_pm().get("role_extra") or "").strip()
    return role + ("\n\n## House additions\n" + extra if extra else "")


def economics():
    """Real spend/token/velocity facts, so estimates are grounded in THIS board."""
    from cells.engineer import sessions
    from spine.storage import events
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
        from spine.auth import auth
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
        from spine.storage import events
        reg = events.settings().get("registration")
        if reg:
            lines.append("REGISTRATION: " + json.dumps(reg, ensure_ascii=False)[:200])
    except Exception:
        pass
    return "\n".join(lines) or "(keine gesonderten System-Fakten)"


from cells.copilot.pm_budget import (_pace, _days, _quota_signal, _budget_assess, _fmt_when,
                       _usage_flag_text, _quota_floor, _goal_budget_text, _triage_green)
from cells.copilot.pm_state import touch, _loopstate, _save_loopstate, _today, _in_window, _board_idle, LOOPSTATE


# -- golden-triangle gate: extracted to pm_triangle.py (god-file breakup). --
# Re-imported here so every existing pm.<name> caller (routes_pm.py,
# sessions.py's on_card_done hook) stays unchanged.
from cells.copilot.pm_triangle import (
    live_plan, _gate_triangle, _triage_shape, on_card_done, _on_card_done,
    RECONCILE_PROMPT, reconcile_corner)


def _ask(prompt, model=""):
    from cells.copilot import copilot
    from spine.agent import drivers
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

A decision the OWNER CLARIFICATIONS below already answer is RESOLVED, not open: never put
it in must_ask, not even reworded as a different question. An open question HOLDS EVERY
DISPATCH, so re-asking an answered one stalls the whole board.

Reply with ONLY this JSON:
{"ready": true|false,
 "gate": "if not ready: the ONE binding reason - MAX 2 short sentences, plain owner language, no essay",
 "issues": ["each a single short sentence (max ~12 words), max 4 items"],
 "must_ask": ["owner decisions/questions that must be answered before firm estimates - each ONE short question"]}
If the plan genuinely holds, ready=true with empty arrays."""


def _verify_plan(plan, econ, quota, prev=None):
    """The GATE's second opinion (paseo worker/verifier pattern): an independent, skeptical
    pass that can DOWNGRADE a plan to not-ready (it never upgrades). Catches the over-confident
    failure - a 14-day calendar test sized as 2 days, a not-yet-started recruiting long-pole,
    an unresolved decision. Fail-open: if the pass errors, don't block.

    INDEPENDENT of the planner, but NOT of the owner: this pass gets the same ground
    truth brief()'s own prompt gets - the owner's chat clarifications and any reconciled
    corner evidence. Without them it re-derived must_asks the owner had already answered
    (a resolved question came back in different words), and since an open question is a
    hard dispatch gate (_state's "ASK"), that answered question held the whole board."""
    try:
        from spine.agent import turnopts
        cli_model, _ = turnopts.resolve_model("auto", "verify plan", False, signals={"priority": "high"})
        keep = {k: plan.get(k) for k in ("goal", "summary", "milestones", "feasibility",
                                         "assumptions", "open_questions", "budget")}
        prompt = (VERIFY_PROMPT + "\n\nPLAN:\n" + json.dumps(keep)
                  + "\n\nECONOMICS:\n" + json.dumps(econ)
                  + "\n\nQUOTA/BUDGET (live):\n" + json.dumps(quota)
                  + _reconcile_block(prev)
                  + _clarifications_block())
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


# -- owner questions: one question, ONE identity ------------------------------
# The verifier's must_ask list joins the planner's open_questions, and an open
# question is a HARD dispatch gate (_state's "ASK"). A question asked twice in
# two wordings therefore doesn't just read as noise - it holds the board, and
# answering one copy leaves the other standing. The PRIMARY fix is that the
# verifier now sees the owner's clarifications (_verify_plan above); this is the
# second net, for when the two independent passes phrase the same ask
# differently - which the `q not in oq` exact match at the merge never caught.
_Q_STOP = {
    # pure function words only, DE + EN. Quantifiers ("viele"), negations and
    # topic nouns deliberately stay: an over-eager stoplist collapses two
    # different questions into one and silently swallows the real one.
    "wie", "was", "wann", "wer", "wo", "warum", "wieso", "welche", "welcher", "welches",
    "welchen", "welchem", "ist", "sind", "war", "waren", "soll", "sollen", "muss",
    "muessen", "müssen", "kann", "koennen", "können", "hat", "hast", "haben", "wird",
    "werden", "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einer",
    "eines", "und", "oder", "fuer", "für", "mit", "von", "vom", "zum", "zur", "auf",
    "aus", "bei", "nach", "ueber", "über", "dir", "dich", "ich", "wir", "sie", "ihr",
    "dass", "dann", "denn", "sich", "auch", "als", "beim", "wenn",
    "what", "when", "who", "whom", "where", "why", "which", "how", "are", "was", "were",
    "does", "did", "the", "and", "for", "with", "from", "into", "that", "this", "there",
    "will", "would", "shall", "should", "can", "could", "has", "have", "had", "been",
    "you", "your", "our", "its", "any", "about",
}


def _q_tokens(q):
    """The CONTENT words of a question: casefolded, punctuation gone, pure
    function words dropped. Two wordings of the same ask land on the same set."""
    return {w for w in re.findall(r"\w+", (q or "").casefold())
            if len(w) >= 3 and w not in _Q_STOP}


# MEASURED, not reasoned (ops/tests/test_pm_clarifications.py pins both sides):
# on real PM question pairs the same ask reworded scores >= 0.571 Jaccard on its
# content words, while two DIFFERENT asks about the same object ("Budget fuer den
# Closed Test?" vs "Deadline fuer den Closed Test?") top out at 0.500. 0.55 is
# that gap. It is a narrow one - which is why this is only the second net and
# _verify_plan seeing the clarifications is the real fix.
_Q_SAME = 0.55


def _same_question(a, b):
    """True when two owner questions ask the SAME thing. Equal after
    normalisation, or a near-duplicate: one's content words fully contained in
    the other's (>= 3 words, i.e. a more specific restatement of the same ask),
    or a _Q_SAME+ Jaccard overlap. Conservative on purpose - a false merge loses
    a question the owner never gets asked, which is worse than a duplicate line."""
    ta, tb = _q_tokens(a), _q_tokens(b)
    if not ta or not tb:                      # nothing but function words: fall back
        return (a or "").strip().casefold() == (b or "").strip().casefold()
    if ta == tb:
        return True
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(small) >= 3 and small <= big:
        return True
    return len(ta & tb) / float(len(ta | tb)) >= _Q_SAME


def _merge_questions(open_qs, must_ask):
    """The planner's open_questions + the verifier's must_asks as ONE list with
    one entry per DISTINCT question. First wording wins (the planner's, which
    carries the plan's own context); order is preserved so _needs_from_owner
    still asks the top question first."""
    out = []
    for q in list(open_qs or []) + list(must_ask or []):
        if not isinstance(q, str) or not q.strip():
            continue
        q = q.strip()
        if not any(_same_question(q, k) for k in out):
            out.append(q)
    return out


def brief(goal=None, model=""):
    """The PM/CTO report: milestones with timelines, next actions, budget grounded
    in quota-time (Max plan) or € (API). `goal` overrides + persists the MVP goal."""
    from cells.copilot import copilot
    from spine.agent import turnopts
    from spine.storage import events
    if goal is not None and goal.strip():
        set_goal(goal)
    goal = (goal or "").strip() or get_goal()
    econ = economics()
    quota = _quota_signal()   # live budget, fed to the planner AND the verifier
    prev = latest_plan()      # MEMORY: read the last plan BEFORE we overwrite it
    cli_model, _ = turnopts.resolve_model(model or "auto", goal or "plan the mvp",
                                          False, signals={"priority": "high"})
    prompt = (_role()
              + "\n\nDATE RULE: never write calendar dates into milestone names/notes - "
                "code derives each target date from your est_turns and the measured pace. "
                "A fixed EXTERNAL wait (a review period, a trial window) is its own "
                "milestone noted as wait time, never effort you can compress; if its "
                "length is unknown, set that milestone's calendar_wait: true - code then "
                "leaves its date (and every date after it) unknown instead of guessing, "
                "until you flip it to status: done."
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

    def _date_milestones(o):
        cum = 0
        wait_hit = False   # once an open calendar_wait milestone is hit, every date
                            # from here on is unknown - cascades until it's done
        for ms in o.get("milestones", []):
            done = str(ms.get("status")) == "done"
            tt = int(ms.get("est_turns") or 0) if not done else 0
            cum += tt
            ms["est_turns"] = tt
            if ms.get("calendar_wait") and not done:
                wait_hit = True
            if wait_hit and not done:
                ms["eta_days"] = None
                ms["cumulative_eta_days"] = None
                ms["target_date"] = None
            else:
                ms["eta_days"] = _days(tt, pace)
                ms["cumulative_eta_days"] = _days(cum, pace)
                # a concrete TARGET DATE, so the board Timeline lays the roadmap out and
                # the milestone reads "by Thu" not just "~3d".
                ms["target_date"] = (today + timedelta(days=ms["cumulative_eta_days"])).strftime("%Y-%m-%d")
        return cum

    est_turns = _date_milestones(out)
    # GATE with SELF-REPAIR first (owner decree 2026-08-22: "Agent setzt die
    # Timeline selbst fest und meckert dann, dass sie nicht passt"): findings
    # the PLANNER itself caused - invented calendar dates, milestones that
    # contradict the plan's own prose, a long-pole not put first - are the
    # planner's to FIX, not the owner's to hear about. One repair round: feed
    # the verifier's issues back, re-plan, re-verify. Only what still fails
    # (or genuinely needs an owner decision via must_ask) reaches the gate.
    ver = _verify_plan(out, econ, quota, prev)
    if not ver.get("ready", True) and ver.get("issues"):
        keep = {k: out.get(k) for k in ("goal", "summary", "milestones", "feasibility",
                                        "assumptions", "open_questions", "budget")}
        repair = (prompt
                  + "\n\nYOUR PREVIOUS DRAFT:\n" + json.dumps(keep, ensure_ascii=False)
                  + "\n\nSKEPTICAL REVIEWER FINDINGS on that draft - these are YOUR OWN "
                    "inconsistencies; REPAIR them yourself, do NOT bounce them to the owner:\n"
                  + json.dumps({"issues": ver.get("issues"), "gate": ver.get("gate")}, ensure_ascii=False)
                  + "\n\nRepair rules: never write calendar dates into milestone names/notes - "
                    "code derives target dates from est_turns; a fixed external wait (a review "
                    "period, a trial window) is its own milestone with the wait as est note, not "
                    "effort; a not-yet-started human long-pole goes FIRST; only a question the "
                    "OWNER alone can answer belongs in open_questions.")
        try:
            out2 = _ask(repair, cli_model)
            if out2.get("milestones"):
                # carry over what the repair pass doesn't restate
                for k in ("goal", "summary"):
                    out2.setdefault(k, out.get(k))
                out = out2
                est_turns = _date_milestones(out)
                ver = _verify_plan(out, econ, quota, prev)
        except Exception as e:
            ver.setdefault("issues", []).append("self-repair failed: %s" % str(e)[:120])
    out["economics"] = econ
    # carry forward any owner-run corner reconciliations so the evidence persists
    # across re-plans (and stays visible to the NEXT brief's _reconcile_block).
    if (prev or {}).get("reconcile"):
        out["reconcile"] = prev["reconcile"]
    out["goal"] = goal
    out["model"] = cli_model or "default"
    out["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    # GATE: an independent verifier can only DOWNGRADE readiness, never upgrade
    # it - `ver` is the verdict on the FINAL (possibly repaired) plan above.
    # Style law: clip LLM prose at the SOURCE so every surface (board box,
    # chat notice, push) inherits the cap.
    ver["gate"] = _clip_prose((ver.get("gate") or "").strip(), 240)
    ver["issues"] = [_clip_prose(i.strip(), 140) for i in (ver.get("issues") or [])
                     if isinstance(i, str) and i.strip()][:4]
    out["gate"] = _clip_prose((out.get("gate") or "").strip(), 240)
    out["summary"] = _clip_prose((out.get("summary") or "").strip(), 300)
    out["verify"] = ver
    if not ver.get("ready", True):
        out["plan_status"] = "blocked"
        if not (out.get("gate") or "").strip():
            out["gate"] = ver.get("gate", "")
    # the verifier's must-asks join the planner's questions - deduped by MEANING,
    # not by exact string. The two passes are independent and practically never
    # word the same ask identically, so `q not in oq` let a re-derived duplicate
    # through and the board sat on "ASK" with a question the owner had answered.
    out["open_questions"] = _merge_questions(out.get("open_questions"), ver.get("must_ask"))
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
    from spine.storage import events
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
    from cells.copilot import copilot
    from spine.agent import turnopts
    cli_model, _ = turnopts.resolve_model(model or "auto", "consolidate the board",
                                          False, signals={"priority": "high"})
    prompt = _CONSOLIDATE_ASK + "\n\nBOARD SNAPSHOT:\n" + copilot._snapshot()
    out = _ask(prompt, cli_model)
    return {"repos": out.get("repos", []) if isinstance(out, dict) else [],
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S")}


def apply_consolidation(repos, actor="owner"):
    """Non-destructive: create each stream card, then REVERSIBLY archive its
    BACKLOG members (their titles roll into the stream card's description).
    Members that are not in backlog are refused and reported, never archived -
    a roll-up may not sweep a card somebody is actually working. Returns what
    changed so the caller can show/undo it."""
    from cells.engineer import sessions
    tracks = {t["id"]: t for t in sessions.list_tracks()}
    created, archived, refused = [], [], []
    for rp in repos or []:
        repo = rp.get("repo") or ""
        if not repo:
            continue
        for st in rp.get("streams", []):
            # _CONSOLIDATE_ASK says "Leave working/review/done cards alone" -
            # but that was only ever a PROMPT, and this loop archived whatever
            # ids came back. One slipped active card is invisible afterwards:
            # archiving hides it from every board view but the Archive scope,
            # and it stays needs_you forever because nothing works an archived
            # card (turn/blockers.py skips them). The rule the proposal is
            # asked to follow is enforced here instead of hoped for.
            wanted = [m for m in (st.get("members") or []) if m in tracks]
            members = [m for m in wanted
                       if (tracks[m].get("lane") or "backlog") == "backlog"
                       and not tracks[m].get("archived")]
            refused += [m for m in wanted if m not in members]
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
    # `refused` is reported, never silently dropped - a roll-up that quietly
    # left cards out would read as "all of it landed".
    return {"created": created, "archived": archived, "refused": refused}


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
    from cells.engineer import sessions
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
    summary = (brief.get("summary") or "").strip()
    _activity("planned", (("Geplant: %d neue Aufgabe(n) angelegt." % filed)
                          + ((" " + summary[:350]) if summary else "")) if filed
              else "Plan geprüft – nichts Neues nötig.")
    # DASHBOARD ONLY (owner decree 2026-08-30): filing cards is the PM doing its
    # job, not a decision for the owner - the new cards are on the board and the
    # line above is in the activity feed. The chat version carried 350 chars of
    # LLM plan summary on top, which is the "zu viel info" shape exactly.
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
        from spine.comms import notify
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
            from spine.ops import ask
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
         and not t.get("example")
         and (not allow or os.path.normcase(t.get("repo") or "") in allow)),
        key=lambda t: (rank.get(t.get("priority"), 2), t.get("created") or ""))


# -- RESOLVE + BURN GUARD: extracted to pm_resolve.py (god-file breakup). ----
# Re-imported here so every existing pm.<name> caller (routes_pm.py,
# processes.py's autopilot, sessions.flag_burn) stays unchanged.
from cells.copilot.pm_resolve import (
    _RESOLVE_MAX, _resolving, _resolving_lock, _bounce_kind, _unblock_proposal,
    _bump_attempt, _give_up, _bounced_to_resolve, _resolve_next, mark_notified,
    _burn_lock, _burn_active, review_burn, _burn_judge, _push_burn,
    _review_burn, resolve_card_now, _resolve_card)


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
    meter carries the running numbers.

    TO HENRY, not to the owner (owner decree 2026-08-30). Managing AI usage is
    the FIRST bullet of Henry's own mandate ("Turns, Quota, Kosten. Verschwende
    sie nicht"), and he can act on it - throttle dispatch, move routine cards to
    a cheaper model, hold non-goal work. The owner's chat version was a chain of
    four projections ending in "sag Bescheid, dann passe ich die Policy an": a
    number wall whose only ask was permission for something the harness is
    already allowed to do. The live numbers stay one tap away in the usage
    meter, which is the surface built for them."""
    try:
        from spine.ops import usage
        flag = usage.weekly_pacing_flag()
    except Exception:
        return
    if not flag:
        return
    if st.get("usage_flagged_reset") == (flag.get("resetsAt") or ""):
        return
    st["usage_flagged_reset"] = flag.get("resetsAt") or ""
    _save_loopstate(st)
    _to_henry("quota-pacing", _usage_flag_text(flag),
              feed="Wochenkontingent laeuft voraus (%s%% bei %s%% der Woche) - an Henry"
                   % (round(flag.get("usedPct") or 0), round(flag.get("elapsed_pct") or 0)))


def _clip_prose(text, n):
    """Length NET under the style law (owner decree 2026-08-22 "sehr langer
    Text immer"): LLM-authored prose surfaced to the phone gets clipped at the
    last sentence boundary within n chars - the prompt asks for brevity, this
    guarantees it even when the model rambles."""
    if len(text) <= n:
        return text
    cut = text[:n]
    for stop in (". ", "! ", "? "):
        i = cut.rfind(stop)
        if i > n * 0.3:
            return cut[:i + 1]
    return cut.rsplit(" ", 1)[0] + " …"


_NOTICE_COOLDOWN_S = 24 * 3600


def _notice_due(st, name, key):
    """Anti-repeat gate for proactive notices (owner 2026-08-22 "wiederkehrende
    Nachrichten" + NN/g state-change-only law): speak when the SEMANTIC state
    changes (stable key, never LLM wording - a re-plan that rewords the same
    problem stays silent) or as a once-a-day heartbeat while it persists.
    key=None clears the episode so the NEXT occurrence speaks immediately."""
    slot = st.get("notice_" + name) or {}
    if key is None:
        if slot:
            st.pop("notice_" + name, None)
            _save_loopstate(st)
        return False
    if slot.get("key") == key and time.time() - (slot.get("at") or 0) < _NOTICE_COOLDOWN_S:
        return False
    st["notice_" + name] = {"key": key, "at": time.time()}
    _save_loopstate(st)
    return True


def _plan_gate_notice(st):
    """The planning GATE speaks: when the plan isn't 'ready' - a decision, a spike, or a
    prerequisite blocks a confident estimate - the PM says so plainly and holds, instead of
    pretending with a shallow schedule. Deduped on the STABLE state (which corners are
    red), not the wording - a re-plan that re-describes the same red stays silent.

    TO HENRY, not to the owner (owner decree 2026-08-30). The message's own
    closing move - "sag „prüfe Budget", dann hole ich die echte Evidenz zu der
    roten Ecke nach" - is work the harness can do without being asked, so
    routing it through the owner only added a hop and a bulleted issue list to
    a chat that wanted neither. The hold itself stays visible where a hold
    belongs: the dashboard's state/state_reason and the feed line below."""
    plan = latest_plan() or {}
    if not get_goal() or _triage_green(plan):     # gate is GREEN (or no goal) -> nothing to say
        _notice_due(st, "plan_gate", None)
        return
    tri = plan.get("triage") or {}
    red = [k for k in ("budget", "timeline", "scope") if tri.get(k) == "blocked"]
    gate = _clip_prose((plan.get("gate") or "").strip(), 240)
    ver = plan.get("verify") or {}
    issues = [_clip_prose(i.strip(), 140) for i in (ver.get("issues") or [])
              if isinstance(i, str) and i.strip()]
    if not _notice_due(st, "plan_gate", "|".join(sorted(red)) or "noestimate"):
        return
    corner = {"budget": "Budget", "timeline": "Timeline", "scope": "Scope"}
    head = ("Ziel-Plan-Gate ROT — die Triage hält (%s). Kein Dispatch, bis das grün ist."
            % ", ".join(corner[c] for c in red) if red else
            "Ziel-Plan-Gate ROT — ich kann noch nicht seriös schätzen. Kein Dispatch, bis geklärt.")
    msg = head + ((" Gate: %s" % gate) if gate else "")
    if issues:
        msg += "\n" + "\n".join("• " + i for i in issues[:4])
    if red:
        # never dead-end: a red corner is ACTIONABLE - name the evidence check
        # that can re-derive it (reconcile_corner), so Henry has the move and
        # does not have to infer it.
        msg += ("\nHenry: „prüfe %s“ holt die echte Evidenz zu der roten Ecke nach "
                "und plant damit neu." % corner[red[0]])
    _to_henry("plan-gate-red", msg,
              feed="Plan-Gate ROT (%s) - kein Dispatch, an Henry"
                   % (", ".join(corner[c] for c in red) or "keine Schätzung"))


def _needs_from_owner(st):
    """The PM ASKS instead of silently guessing: surface the plan's open_questions
    (material info the PM is missing) to the owner. Best-effort planning still needs
    answers a good PM chases. Deduped by content, so the same set isn't re-asked every
    plan - it re-asks only when the questions actually change, and stays silent when
    the plan has none."""
    plan = latest_plan() or {}
    qs = [q.strip() for q in (plan.get("open_questions") or []) if isinstance(q, str) and q.strip()]
    # STABLE key: goal + how many questions - a re-plan that merely REWORDS the
    # same asks stays silent; a genuinely new question (count grows) speaks.
    if not _notice_due(st, "questions", ("%s|%d" % (get_goal(), len(qs))) if qs else None):
        return
    # ONE question, not a bulleted five (owner decree 2026-08-30). This notice
    # STAYS in the chat - a missing answer is by definition the owner's move and
    # nothing else on the board can supply it - but a list of five asks is a form,
    # not a question, and the owner answered none of them. Asking the first and
    # re-asking as the set changes (the _notice_due key counts them) walks the
    # same list one answerable step at a time; the full set stays on the plan.
    # The question goes in WHOLE - the [:180] that stood here was a raw slice
    # that could land inside a word, and the chat has no length budget to
    # justify it (2026-08-30; spine/comms/notice.short's docstring says where a
    # clip does belong). Brevity here comes from asking ONE question - the line
    # above - not from cutting it in half.
    more = (" (%d weitere im Plan.)" % (len(qs) - 1)) if len(qs) > 1 else ""
    _say("Mir fehlt Info: %s%s" % (qs[0], more))


def _triangle_watch(st):
    """Management by exception: between the DAILY plans, inspect the iron triangle
    (Budget / Timeline / Scope) against today's baseline and ESCALATE to the owner the
    moment a corner tilts. Daily planning sets the baseline; this is the ongoing monitor.
    Deduped by the tilt's content; clears itself when the triangle is level again."""
    corners = []
    # BUDGET — the weekly quota is burning ahead of pace
    try:
        from spine.ops import usage
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
            from cells.engineer import processes
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
    # STABLE key: WHICH corners tilt (the prefix before ':'), never the numbers
    # in the text - a projection drifting 108%->111% is the same escalation.
    kinds = "|".join(sorted(c.split(":", 1)[0] for c in corners)) if corners else None
    if not _notice_due(st, "triangle", kinds):
        return
    # TO HENRY (owner decree 2026-08-30). "Welche Ecke ist dir heilig
    # (Zeit/Budget/Scope)?" is not a decision the owner can make from a bullet
    # list of drifts - it is the question a PM answers himself from context and
    # only escalates once he has a concrete trade to propose. Henry has that
    # context and the hands; if he concludes the owner really must choose, he
    # wakes him with ONE question, which is what his mandate already says.
    msg = ("Dreieck schief - Abweichung von der Tages-Baseline:\n"
           + "\n".join("• " + c for c in corners)
           + "\nGegensteuern (Prioritäten, Dispatch, Scope) oder dem Owner EINE konkrete "
             "Trade-off-Frage stellen - keine Statistik weiterreichen.")
    _to_henry("triangle-tilt", msg,
              feed="Dreieck schief (%s) - an Henry" % kinds.replace("|", ", "))


# -- per-card budget watchdog: extracted to pm_watchdog.py (god-file breakup).
# Re-imported here so every existing pm.<name> caller stays unchanged.
from cells.copilot.pm_watchdog import (
    _WATCH_PRIO, _watch_budget_ctx, _watch_bac_pct, _cost_watch)


# -- goal->process (PMP epic): extracted to pm_goal.py (god-file breakup). --
# Re-imported here so every existing pm.<name> caller stays unchanged.
from cells.copilot.pm_goal import (
    _goal_has_process, _goal_process, _goal_process_status)


def _stakeholder_update(st):
    """PMP core: reconcile GOAL vs BUDGET against the LIVE weekly quota. Managing
    goal-vs-budget IS the PM's primary job - but INFORMING is not the same as
    INTERRUPTING, and this notice is the one the owner quoted back (2026-08-30):

      "Diese Karte sollte in der Form nicht mehr im Chat sein. Zu viel info..
       bzw ich weiss nicht was ich dazu machen soll."

    He was right about the whole class. The daily "Ziel vs. Budget" block was
    five sentences of projections - used%, projected%, reset time, turns open,
    ETA, pace, feasibility, milestone counts - and on-track or tight there is
    no move in any of them. So:

      on_track / tight -> the DASHBOARD (activity feed + the PM panel, which
                          already renders the same numbers as a panel rather
                          than as prose). Silent in the chat.
      at_risk          -> ONE line and two BUTTONS. This one IS his call: the
                          quota runs out before the reset, and only he can say
                          whether non-goal work gets held or the goal slips.

    The daily/risk dedup below is unchanged - what changed is the CHANNEL, not
    when the PM considers this news."""
    goal = get_goal()
    if not goal:
        return
    try:
        from spine.ops import usage
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
    # the full block still gets WRITTEN - just to the dashboard feed, where a
    # status report with no move belongs and where the owner reads it when he
    # wants it instead of being handed it.
    _activity("status", msg)
    if verdict != "at_risk":
        return
    if not risk_new:
        return                       # same risk_key already asked - Henry has it
    # no timestamp in the ASK, deliberately: "~So 30.08. 22:00" is a number the
    # owner cannot act on differently depending on its value, and a chain of
    # those is the shape the decree bans. The exact exhaust time is in the
    # dashboard block written just above, where a number belongs.
    _ask_owner("⚠ Das Wochenkontingent ist vor dem Reset leer — dann steht „%s“ still. "
               "Nicht-Ziel-Arbeit bis zum Reset zurückstellen?" % goal[:60],
               [{"label": "Zurückstellen",
                 "description": "Nur Ziel-Karten laufen bis zum Reset"},
                {"label": "Slip akzeptieren",
                 "description": "Alles läuft weiter, die Ziel-ETA rutscht"}],
               header="Budget vs. Ziel", title=_i18n.t("push.pmQuota"))


def _overview_stale(plan, tracks):
    """True if the plan's roadmap isn't reflected on the board yet: a card that
    belongs to a dated milestone still lacks that due date (Timeline), or the
    dashboard layout isn't set."""
    from spine.storage import events
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
    from cells.engineer import sessions
    from spine.storage import events
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


# The proactive loop is now a STATE MACHINE - same idea as ops/tools/loop_state.py:
# the STATE is computed from REALITY (board + plan + config) each tick and drives
# the next action. A new capability = a new STATE (e.g. OVERVIEW), not new code.
def _state():
    """(STATE, plain reason). First actionable state wins. Surfaced to you so you
    can SEE what the PM is doing / about to do. WAIT = wants to act but you're here."""
    pm = _pm()
    if not pm.get("loop_enabled"):
        return ("OFF", "Proaktiv ist aus.")
    from cells.engineer import sessions
    tracks = [t for t in sessions.list_tracks()
              if not t.get("archived") and not t.get("example")]
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
    # HARD GATE 2 (owner decree 2026-08-22: "ohne die Haupt-Info sollte er
    # nicht arbeiten"): the plan still carries OPEN QUESTIONS to the owner ->
    # no new dispatch on assumptions. Answering in chat (clarify_goal) folds
    # the answer in and re-plans immediately, which clears this hold.
    if get_goal() and any(isinstance(q, str) and q.strip()
                          for q in ((latest_plan() or {}).get("open_questions") or [])):
        return ("ASK", "Offene Schlüsselfragen an dich - kein Dispatch auf Annahmen, "
                       "bitte kurz im Chat beantworten.") \
            if acting else ("WAIT", "Fragen an dich offen, aber du bist da.")
    paused = day.get("paused_at") and time.time() - day["paused_at"] < 5 * 3600
    if not paused and len(day.get("dispatched", [])) < pm.get("max_dispatch_per_day", 3) and _backlog(tracks, pm, day):
        return ("DISPATCH", "Naechste Karte starten.") if acting else ("WAIT", "Arbeit da, aber du bist da.")
    return ("IDLE", "Alles im Griff - nichts zu tun.")


def _dispatch_next(pm, st, day):
    from cells.engineer import sessions
    from spine.storage import events
    if sum(1 for t in sessions.list_tracks() if t.get("lane") == "working") >= events.wip_limit_of():
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
                from spine.ops import usage
                key = (usage.weekly_pacing_flag() or {}).get("resetsAt") or ""
            except Exception:
                pass
            if st.get("quota_held_reset") != key:
                st["quota_held_reset"] = key; _save_loopstate(st)
                only = "nur dringende" if floor == 0 else "nur dringende + hohe"
                # DASHBOARD ONLY (owner decree 2026-08-30): the PM already DID the
                # thing. Raising a card's priority is a board action he takes when
                # he wants that card, not an answer this message needs - and the
                # hold is on the dashboard as quota_paused / the feed line.
                _activity("blocked", "Quota-Management: nicht-dringende Karten bis zum "
                          "Reset zurueckgestellt (%s Prioritaet startet noch)." % only)
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
    from spine.registry import cells
    # "copilot", NOT "pm": the pm cell merged into copilot (2026-09-03) and
    # enabled_id fails OPEN for an unknown id - left reading "pm", this guard
    # would have silently stopped guarding anything.
    if not cells.enabled_id("copilot"):
        # ADDITIONAL early-return, not a replacement: loop_enabled (below) is
        # the owner's proactive on/off Settings control; cellEnabled is the
        # separate whole-cell kill switch (Phase 2 of the cell-registry decree).
        return
    pm = _pm()
    if not pm.get("loop_enabled"):
        return
    st = _loopstate()
    day = st.setdefault(_today(), {"dispatched": [], "paused_at": 0})
    from cells.engineer import sessions
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
    pos = _position([t for t in tracks if not t.get("archived") and not t.get("example")], plan)
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
# Extracted to pm_comm.py (god-file breakup). Re-imported here so every
# existing pm.<name> caller (routes_pm.py, this file's own many callers)
# stays unchanged.
from cells.copilot.pm_comm import (
    PLANS as _COMM_PLANS, _ACTIVITY, _activity, _say, _escalation_tid,
    _escalate, _ask_owner, _to_henry, _short, _read_activity)
assert _COMM_PLANS == PLANS, "pm_comm.PLANS drifted from pm.PLANS"


def activity():
    """The DAU narrative: what's running now, what's next, what needs you, and
    the blockers - all from live card state, plus the recent activity feed."""
    from cells.engineer import sessions
    # PRESENTED, not stored: "arbeitet gerade an X" was a lie for any card whose
    # turn had died - it reads `running` in the store until the reconciler heals
    # it, so the narrative claimed work was in flight AND left the card out of
    # "needs you". present() derives the truth at read time (invariant I2).
    tracks = [sessions.present(t) for t in sessions.list_tracks()
              if not t.get("archived") and not t.get("example")]
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
                    from spine.storage import events
                    events.log("pm", "tick error: %s" % e)
                except Exception:
                    pass
            time.sleep(120)
    threading.Thread(target=loop, daemon=True, name="pm-loop").start()
