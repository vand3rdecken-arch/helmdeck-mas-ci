# -*- coding: utf-8 -*-
"""Proactive PM / CTO briefing.

Reads the LIVE board + REAL economics + a GOAL (usually an MVP definition) and
produces a structured plan: what's left to the goal, what to do next, and a
token/cost projection. The split of labour is the honest part:

  the LLM JUDGES effort   (how many agent turns a task will take)
  the CODE PRICES it       (turns x the ACTUAL average cost/turn to date)

so the "how much until MVP" number is grounded in this board's own history, not
a model guess. Nothing here executes work - it only briefs. Turning a briefing
into cards stays an explicit action (the copilot's file_card / the human).
"""
import json, os, re, subprocess, time

ROOT = os.path.dirname(os.path.abspath(__file__))

PM_SYSTEM = """You are the HelmDeck PM/CTO. Given the live board, the REAL
economics to date, and a GOAL (usually an MVP definition), produce a crisp,
honest plan. Tie tasks to EXISTING cards by id where they already exist; only
invent a task when the board is genuinely missing it.

Reply with ONLY JSON:
{
 "summary": "2-4 sentence CTO briefing: where we are vs the goal and the single most important next move",
 "done_pct": <integer 0-100, your estimate of progress toward the goal>,
 "tasks": [   // EVERYTHING needed to reach the goal - existing cards + missing work
   {"title": "...", "why": "one line: why this is needed for the goal",
    "priority": "urgent|high|medium|low",
    "status": "done|in_progress|todo",
    "card": "<existing card id, or null if this work isn't on the board yet>",
    "est_turns": <rough agent turns to finish, integer 1-10>}
 ],
 "next": [ {"title": "...", "reason": "why do this now", "card": "<id or null>"} ],  // ORDERED, do-first at top, 3-5 items
 "risks": ["short blocker/risk", ...]
}

Rules: be concrete and specific to THIS board. Judge est_turns realistically
against the economics given (a task like the recently-finished ones costs about
the average). Do not restate the goal as a task. If the goal is unclear, say so
in summary and still give your best plan from the board. Output JSON only."""


def _currency():
    import events
    return events.settings().get("currency", "EUR")


def economics():
    """Real spend/token facts from this board, so estimates are grounded."""
    import sessions, events
    tracks = sessions.list_tracks()
    m = events.metrics(tracks)
    cards = m["cards"]
    spend = m["totals"]["ai_spend"]
    turns = sum(t.get("turns", 0) for t in tracks)
    toks = sum((t.get("tokens_in", 0) + t.get("tokens_out", 0)) for t in tracks)
    avg_cost_turn = round(spend / turns, 4) if turns else 0.0
    avg_tok_turn = round(toks / turns) if turns else 0
    done = [c for c in cards if c["lane"] == "done" and c["ai_cost"] > 0]
    avg_cost_card = (round(sum(c["ai_cost"] for c in done) / len(done), 4) if done
                     else round(avg_cost_turn * 3, 4))
    return {
        "spend_to_date": round(spend, 4),
        "turns_to_date": turns,
        "tokens_to_date": toks,
        "avg_cost_per_turn": avg_cost_turn,
        "avg_tokens_per_turn": avg_tok_turn,
        "avg_cost_per_finished_card": avg_cost_card,
        "value_delivered": m["totals"]["value_delivered"],
        "margin": m["totals"]["margin"],
        "capacity": m["capacity"],
        "spend_by_model": {k: v.get("cost", 0) for k, v in m["ai_by_model"].items()},
        "currency": _currency(),
    }


def _ask(prompt, model=""):
    """One stateless plan-mode turn (read-only); returns the parsed JSON object."""
    import copilot
    cmd = ["cmd", "/c", copilot.CLAUDE, "-p", "--output-format", "json",
           "--permission-mode", "plan"]
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
        return {"summary": txt.strip()[:400], "tasks": [], "next": [], "risks": []}
    try:
        return json.loads(m.group(0))
    except ValueError:
        return {"summary": txt.strip()[:400], "tasks": [], "next": [], "risks": []}


def get_goal():
    import events
    return ((events.settings().get("pm") or {}).get("goal") or "").strip()


def set_goal(goal):
    import events
    pm = dict(events.settings().get("pm") or {})
    pm["goal"] = (goal or "").strip()
    events.save_settings({"pm": pm})
    return pm["goal"]


def brief(goal=None, model=""):
    """The PM/CTO report. `goal` overrides (and is saved as) the stored MVP goal."""
    import copilot, turnopts
    if goal is not None and goal.strip():
        set_goal(goal)
    goal = (goal or "").strip() or get_goal()
    econ = economics()
    # PM analysis is real reasoning work -> route it to a strong model on Auto.
    cli_model, _ = turnopts.resolve_model(model or "auto", goal or "plan the mvp",
                                          False, signals={"priority": "high"})
    prompt = (PM_SYSTEM
              + "\n\nGOAL:\n" + (goal or "(no goal set - infer a reasonable MVP from the board and debt)")
              + "\n\nECONOMICS (real, to date):\n" + json.dumps(econ)
              + "\n\nBOARD SNAPSHOT (%s):\n" % time.strftime("%Y-%m-%d %H:%M") + copilot._snapshot())
    out = _ask(prompt, cli_model)

    # Price the plan in CODE: LLM judged est_turns, we cost it at the real rate.
    todo = [t for t in out.get("tasks", []) if str(t.get("status")) != "done"]
    est_turns = sum(int(t.get("est_turns") or 0) for t in todo if str(t.get("est_turns") or "").isdigit()
                    or isinstance(t.get("est_turns"), int))
    out["budget"] = {
        "currency": econ["currency"],
        "spent_to_date": econ["spend_to_date"],
        "avg_cost_per_turn": econ["avg_cost_per_turn"],
        "remaining_tasks": len(todo),
        "est_turns_to_goal": est_turns,
        "est_cost_to_goal": round(est_turns * econ["avg_cost_per_turn"], 2),
        "est_tokens_to_goal": est_turns * econ["avg_tokens_per_turn"],
    }
    out["economics"] = econ
    out["goal"] = goal
    out["model"] = cli_model or "default"
    out["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return out
