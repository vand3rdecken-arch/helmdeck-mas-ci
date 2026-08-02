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
import json, math, os, re, subprocess, time

ROOT = os.path.dirname(os.path.abspath(__file__))
ROLE_FILE = os.path.join(ROOT, "pm.role.md")
PLANS = os.path.join(ROOT, "pm")

PM_DEFAULTS = {
    "goal": "",
    "plan": "max",              # "max" (flat quota) | "api" (per-token €) | "mixed"
    "monthly_eur": 200,
    "quota_turns_per_day": 0,   # 0 = derive pace from measured velocity
    "cadence_minutes": 0,       # 0 = only on demand / when the ticker plans
    "role_extra": "",           # house additions appended to the role charter
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
    return {
        "plan": pm.get("plan", "max"),
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


def _pace(econ):
    """Turns/day used for timelines: explicit quota cap, else measured velocity,
    else a conservative default so a fresh board still gets a timeline."""
    return econ.get("quota_turns_per_day") or econ.get("velocity_turns_per_day") or 3.0


def _days(turns, pace):
    return max(1, math.ceil(turns / pace)) if turns else 0


def _ask(prompt, model=""):
    import copilot
    cmd = ["cmd", "/c", copilot.CLAUDE, "-p", "--output-format", "json", "--permission-mode", "plan"]
    if model:
        cmd += ["--model", model]
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


def brief(goal=None, model=""):
    """The PM/CTO report: milestones with timelines, next actions, budget grounded
    in quota-time (Max plan) or € (API). `goal` overrides + persists the MVP goal."""
    import copilot, turnopts, events
    if goal is not None and goal.strip():
        set_goal(goal)
    goal = (goal or "").strip() or get_goal()
    econ = economics()
    cli_model, _ = turnopts.resolve_model(model or "auto", goal or "plan the mvp",
                                          False, signals={"priority": "high"})
    prompt = (_role()
              + "\n\nGOAL:\n" + (goal or "(no goal set - infer a reasonable MVP from the board and debt)")
              + "\n\nPOLICY:\n" + json.dumps(events.settings().get("policy") or {})
              + "\n\nECONOMICS (real, to date):\n" + json.dumps(econ)
              + "\n\nBOARD SNAPSHOT (%s):\n" % time.strftime("%Y-%m-%d %H:%M") + copilot._snapshot())
    out = _ask(prompt, cli_model)

    # price + time in CODE: LLM judged est_turns; we convert to days & shadow-€.
    pace = _pace(econ)
    cum = 0
    for ms in out.get("milestones", []):
        tt = sum(int(x.get("est_turns") or 0) for x in ms.get("tasks", [])
                 if str(x.get("status")) != "done" and str(x.get("est_turns") or "0").isdigit())
        cum += tt
        ms["est_turns"] = tt
        ms["eta_days"] = _days(tt, pace)
        ms["cumulative_eta_days"] = _days(cum, pace)
    est_turns = cum
    is_max = econ["plan"] == "max"
    out["budget"] = {
        "plan": econ["plan"],
        "fixed_monthly_eur": econ["monthly_eur"],
        "cash_to_goal_eur": 0.0 if is_max else round(est_turns * econ["avg_cost_per_turn"], 2),
        "shadow_eur_to_goal": round(est_turns * econ["avg_cost_per_turn"], 2),
        "spent_to_date_eur": econ["spend_to_date"],
        "est_turns_to_goal": est_turns,
        "velocity_turns_per_day": econ["velocity_turns_per_day"],
        "pace_turns_per_day": pace,
        "eta_days": _days(est_turns, pace),
        "note": ("Max-Abo: Engpass ist Quota/Zeit, nicht €. Schatten-€ = API-Äquivalent "
                 "(Leverage gegen €%s flat)." % econ["monthly_eur"]) if is_max
                else "API: gegen das €-Cap planen.",
    }
    out["economics"] = econ
    out["goal"] = goal
    out["model"] = cli_model or "default"
    out["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _write_artifact(out)
    return out


def plan_items(b=None):
    """The actionable NEW work from a brief (tasks not yet on the board), ordered
    by priority - what an executor (the night ticker) should file as cards.
    Returns (items, brief). Each item: {title, description, priority, repo}."""
    import events
    b = b or brief()
    order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
    default_repo = events.settings().get("default_repo") or ""
    items = []
    for ms in b.get("milestones", []):
        for t in ms.get("tasks", []):
            if str(t.get("status")) == "done" or t.get("card"):
                continue
            desc = "%s\n\nStream: %s · Milestone: %s\n[PM plan]" % (
                t.get("why") or t.get("title", ""), t.get("stream") or "-", ms.get("name") or "-")
            items.append({"title": t.get("title", "").strip(),
                          "description": desc,
                          "priority": t.get("priority", "medium"),
                          "repo": t.get("repo") or default_repo})
    items = [it for it in items if it["title"]]
    items.sort(key=lambda x: order.get(x.get("priority"), 2))
    return items, b
