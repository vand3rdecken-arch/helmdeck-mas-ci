# -*- coding: utf-8 -*-
"""PM budget/quota math - extracted from pm.py. Code-computed, plan-aware
budget verdict (Max: subscription usage windows w/ pacing; API: € vs cap)
+ pace/eta helpers + the quota-notice text builders (_fmt_when/_usage_flag_text/
_goal_budget_text) and the two hard gates (_quota_floor/_triage_green). Pure
over the econ dict + usage.snapshot(); pm.py re-imports the names. Not
monkeypatched.
"""
import math

_DE_DOW = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def _fmt_when(iso):
    """ISO -> 'Mi 05.08. 03:47' (local time) for a human-readable quota date."""
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
        return "%s %02d.%02d. %02d:%02d" % (_DE_DOW[dt.weekday()], dt.day, dt.month, dt.hour, dt.minute)
    except Exception:
        return iso or "?"


def _usage_flag_text(f):
    used = f.get("usedPct"); elapsed = f.get("elapsed_pct"); proj = f.get("projected_pct")
    parts = ["⚠ Quota-Warnung: Wochenlimit zu %s%% verbraucht, aber erst %s%% der "
             "Woche vorbei." % (round(used), round(elapsed))]
    if proj is not None:
        parts.append("Bei diesem Tempo landest du bei ~%s%% zum Reset." % round(proj))
    if f.get("exhaust_before_reset") and f.get("exhaust_at"):
        parts.append("Das Wochenlimit ist dann ~%s erschöpft — also VOR dem Reset am %s."
                     % (_fmt_when(f["exhaust_at"]), _fmt_when(f.get("resetsAt"))))
    parts.append("Vorschlag: Auto-Dispatch drosseln oder Routine-Karten auf ein günstigeres "
                 "Modell setzen, damit das Kontingent bis zum Reset reicht. Sag Bescheid, "
                 "dann passe ich die Policy an.")
    return " ".join(parts)


def _quota_floor():
    """The weekly quota IS the budget the PM manages (on a Max plan the bottleneck
    is quota, not euros). When the current pace runs the window OVER its limit before
    it resets, the PM spends the remaining budget only on the work that's worth it:
    this returns the lowest-priority rank still allowed to dispatch (0=urgent .. 3=low),
    or None when there's headroom to dispatch everything. Cheap (cached snapshot)."""
    try:
        from spine.ops import usage
        f = usage.weekly_pacing_flag()
    except Exception:
        return None
    if not f:
        return None
    proj = f.get("projected_pct") or 0
    return 0 if proj >= 130 else 1     # badly over -> urgent only; ahead -> urgent + high


def _goal_budget_text(goal, weekly, est, eta, pace, verdict):
    g = goal if len(goal) <= 90 else goal[:88] + "…"
    parts = ["📊 Ziel vs. Budget — Ziel: %s." % g]
    if weekly is not None:
        used = weekly.get("usedPct")
        pac = weekly.get("pacing") or {}
        proj = pac.get("projected_pct")
        line = "Budget (Woche): %s%% verbraucht" % round(used) if isinstance(used, (int, float)) else "Budget (Woche): —"
        if proj is not None:
            line += ", projiziert %s%% zum Reset (%s)" % (round(proj), _fmt_when(weekly.get("resetsAt")))
        parts.append(line + ".")
    if est:
        parts.append("Zielpfad: Restaufwand ~%s Schritte, ETA ~%s Tage (Velocity %s/Tag)." % (est, eta, pace))
    else:
        parts.append("Noch kein bepreister Plan — sag 'plane', dann rechne ich Zielpfad + ETA.")
    if verdict == "at_risk":
        pac = (weekly or {}).get("pacing") or {}
        parts.append("⚠ Risiko: bei diesem Tempo ist das Wochenkontingent ~%s erschöpft — VOR dem "
                     "Reset. Dann stockt die Arbeit bis zum Reset und die Ziel-ETA rutscht. "
                     "Ich fokussiere das Kontingent in DISPATCH schon auf dringende/hohe Karten; "
                     "sag Bescheid, ob ich Nicht-Ziel-Arbeit härter zurückstelle oder den Slip "
                     "akzeptieren soll." % _fmt_when(pac.get("exhaust_at")))
    elif verdict == "tight":
        parts.append("Budget wird knapp — noch tragbar, aber ich behalte das Tempo im Auge.")
    else:
        parts.append("Auf Kurs — das Budget trägt das Tempo bis zum Reset.")
    return " ".join(parts)


def _triage_green(plan):
    """The HARD gate: goal work may proceed only when the golden triage is green -
    plan_status 'ready' AND all three iron-triangle corners (budget/timeline/scope) 'ok'.
    No plan yet -> not green (a goal can't be dispatched without a vetted plan). A legacy
    plan without a triage block falls back to plan_status alone."""
    if not plan:
        return False
    if (plan.get("plan_status") or "ready") != "ready":
        return False
    tri = plan.get("triage") or {}
    if tri:
        return all(tri.get(k) == "ok" for k in ("budget", "timeline", "scope"))
    return True


def _pace(econ):
    """Turns/day used for timelines: explicit quota cap, else measured velocity,
    else a conservative default so a fresh board still gets a timeline."""
    return econ.get("quota_turns_per_day") or econ.get("velocity_turns_per_day") or 3.0


def _days(turns, pace):
    return max(1, math.ceil(turns / pace)) if turns else 0


def _quota_signal():
    """Compact LIVE budget for the planning brain: the weekly + 5h quota windows so
    the PM can judge budget-FIT (not just scope). Empty/failsafe when unavailable."""
    try:
        from spine.ops import usage
        s = usage.snapshot()
    except Exception:
        return {}
    if s.get("status") != "ok":
        return {"status": s.get("status", "unavailable")}
    out = {"plan": s.get("plan")}
    for w in s.get("windows", []):
        if w.get("id") in ("weekly", "five_hour"):
            e = {"usedPct": w.get("usedPct"), "resetsAt": w.get("resetsAt")}
            if w.get("id") == "weekly" and w.get("pacing"):
                e["projectedPct"] = w["pacing"].get("projected_pct")
                e["exhaustBeforeReset"] = w["pacing"].get("exhaust_before_reset")
            out[w["id"]] = e
    return out


def _budget_assess(econ, est_turns, pace):
    """The PM's CODE-COMPUTED, plan-aware budget verdict + the panel data the
    board renders. It CHECKS the real bottleneck and BUILDS the block - measured,
    not the LLM's narrative guess (which said "green" while the weekly quota was
    pacing to 111%). Stays flexible: the constraint that matters is the plan's:

      Max plan  -> the SUBSCRIPTION USAGE is the budget. kind="usage" carries the
                   real rate-limit windows (5h + weekly, with pacing), and the
                   verdict comes from pacing: a window pacing to exhaust before
                   its reset BLOCKS, near-full WARNS. No euros anywhere.
      API plan  -> € spend vs the monthly cap is the budget. kind="cash" carries
                   spent / projected / cap, verdict from projected-vs-cap.

    Returns (budget_dict, state) where state in {"ok","warn","blocked"} - the
    caller overrides triage.budget with it (measured economics beats the guess)."""
    plan = econ.get("plan", "max")
    if plan == "api":
        cap = econ.get("monthly_eur") or 0
        spent = econ.get("spend_to_date", 0.0)
        to_goal = round(est_turns * econ.get("avg_cost_per_turn", 0.0), 2)
        projected = round(spent + to_goal, 2)
        state = "ok"
        if cap:
            if projected >= cap:
                state = "blocked"
            elif projected >= 0.8 * cap:
                state = "warn"
        b = {"plan": "api", "kind": "cash", "monthly_eur": cap,
             "spent_to_date_eur": spent, "cash_to_goal_eur": to_goal,
             "projected_eur": projected, "est_turns_to_goal": est_turns,
             "velocity_turns_per_day": econ.get("velocity_turns_per_day"),
             "pace_turns_per_day": pace, "eta_days": _days(est_turns, pace),
             "state": state,
             "note": "API: Projektion €%.2f gegen Cap €%s (Restaufwand × Ø-Kosten)."
                     % (projected, cap or "—")}
        return b, state
    # -- Max / flat plan: the usage allowance IS the budget --------------------
    try:
        from spine.ops import usage as _usage
        snap = _usage.snapshot()
    except Exception:
        snap = {}
    wins = snap.get("windows") or []
    state = "ok"
    weekly = next((w for w in wins if w.get("id") == "weekly"), None)
    for w in wins:                       # derive the verdict from the real windows
        pac = w.get("pacing") or {}
        up = w.get("usedPct") or 0
        if up >= 95 or pac.get("exhaust_before_reset") or pac.get("flag"):
            state = "blocked"
            break
        if up >= 80 or (pac.get("projected_pct") or 0) >= 100:
            state = "warn"
    # PM-grade note: reason in VELOCITY x QUOTA, not a flat figure. Name the pace,
    # the weekly projection at that pace, and the reset - so the verdict reads
    # like a PM's ("at 9.6/day the weekly quota projects 110% -> exhausts before
    # the Sun reset"), which is the bottleneck on a flat plan, not euros.
    vel = econ.get("velocity_turns_per_day") or 0
    wp = (weekly or {}).get("pacing") or {}
    proj = wp.get("projected_pct")
    reset = _fmt_when((weekly or {}).get("resetsAt")) if weekly else ""
    used = (weekly or {}).get("usedPct")
    if not wins:                         # no Claude login / usage unreachable
        note = "Max-Abo: Budget = Plan-Kapazität (kein €). Nutzungsdaten gerade nicht verfügbar."
    elif weekly is None:
        note = "Max-Abo: Budget = Plan-Kapazität (kein €)."
    else:
        head = {"ok": "reicht bis zum Reset.",
                "warn": "wird eng vor dem Reset.",
                "blocked": "reicht NICHT bis zum Reset - vorher erschöpft."}[state]
        # Owner vocabulary (2026-09-04, same rule as pm.md's style law):
        # "Velocity", not the internal "Turns/Tag" - the owner reads PM
        # language, not our unit names.
        note = ("Max-Abo: Kontingent ist der Engpass (kein €). Bei Velocity %.1f/Tag ist die "
                "Woche bei %d%%%s, Reset %s - %s%s"
                % (vel, round(used or 0),
                   (" → projiziert %d%%" % round(proj)) if proj is not None else "",
                   reset or "—", head,
                   " Tempo drosseln oder Reset abwarten." if state == "blocked" else ""))
    b = {"plan": "max", "kind": "usage", "usage_plan": snap.get("plan"),
         "windows": wins,               # full UsageWindow shape - board reuses UsageRow
         "est_turns_to_goal": est_turns,
         "velocity_turns_per_day": econ.get("velocity_turns_per_day"),
         "pace_turns_per_day": pace, "eta_days": _days(est_turns, pace),
         "state": state, "note": note}
    return b, state
