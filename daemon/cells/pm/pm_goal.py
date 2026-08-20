# -*- coding: utf-8 -*-
"""PM goal->process (PMP epic) management - extracted from pm.py (god-file
breakup, see daemon/spine/registry/debt.py daemon-god-files).

PMP initiation: a new goal becomes a PROCESS (the epic) so goal <-> timeline
<-> cost are analysable through the existing process/SoW machinery instead of
a flat card list, built from the BRAIN's plan once it passes the golden
triage (Budget/Timeline/Scope green) - the steps ARE the vetted, dated
milestones, not a context-blind checklist.

pm.py's own functions (get_goal, latest_plan, _epic_description) are
imported LAZILY inside the function bodies that need them - pm.py imports
THIS module at module level to re-export these names unchanged for existing
callers, so a top-level import back would cycle."""
import re

from daemon.cells.pm.pm_budget import _pace, _days, _triage_green
from daemon.cells.pm.pm_state import _save_loopstate
from daemon.cells.pm.pm_comm import _say


def _goal_has_process(st):
    """True when the current goal is already tracked as a process (the epic)."""
    from daemon.cells.pm.pm import get_goal
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
    from daemon.cells.pm.pm import get_goal, latest_plan, _epic_description
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
        from daemon.cells.process import processes
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
    from daemon.cells.pm.pm import get_goal
    gp = st.get("goal_process") or {}
    if gp.get("goal") != get_goal() or not gp.get("pid"):
        return None
    try:
        from daemon.cells.process import processes
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
