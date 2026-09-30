# -*- coding: utf-8 -*-
"""PM goal->process (PMP epic) management - extracted from pm.py (god-file
breakup, see spine/registry/debt.py daemon-god-files).

A goal has exactly one process: an EMPTY folder, created on first need
(ensure_goal_process), whose steps are the goal cards Henry files
(goal_drive.link_card -> processes.attach_card). Until 2026-09-30 this was
PMP initiation - proposed steps the owner had to accept - which ran beside
Henry's goal cards as a second, never-started plan.

pm.py's own functions (get_goal) are
imported LAZILY inside the function bodies that need them - pm.py imports
THIS module at module level to re-export these names unchanged for existing
callers, so a top-level import back would cycle."""
from cells.copilot.planning.pm_state import _save_loopstate
from cells.copilot.planning.pm_comm import _say


def _goal_has_process(st):
    """True when the current goal is already tracked as a process (the epic)."""
    from cells.copilot.planning.pm import get_goal
    gp = st.get("goal_process") or {}
    return bool(gp.get("pid")) and gp.get("goal") == get_goal()


def ensure_goal_process(st=None):
    """The goal's process id, created EMPTY when there is none yet (owner
    2026-09-30: goal and process were two parallel records - Henry's goal
    cards carried a `goal` tag, the PM's goal process held 7 proposed steps
    nobody accepted, and neither knew the other: 10 goal cards, process 0/7,
    and the owner asked to start work that was already done). ONE link now:
    a card is goal work iff it is a step of this process (attach_card). The
    process is a folder the work fills, not a plan waiting for a sign-off -
    so no proposer and nothing to accept. Returns "" without a goal."""
    from cells.copilot.planning.pm import get_goal
    from cells.copilot.planning.pm_state import _loopstate
    if st is None:
        st = _loopstate()
    goal = get_goal()
    if not goal:
        return ""
    if _goal_has_process(st):
        return st["goal_process"]["pid"]
    from cells.engineer.chains import processes
    p = processes.create(goal, client="", due="", actor="pm", propose=False)
    st["goal_process"] = {"goal": goal, "pid": p["id"]}
    _save_loopstate(st)
    return p["id"]


def _goal_process(pm, st):
    """A new goal gets its (empty) process - see ensure_goal_process. The old
    PMP initiation (proposer or vetted milestones as `proposed` steps the
    owner had to accept) is gone: it produced exactly the parallel track the
    owner found on 2026-09-30. Henry drives the goal (goal_drive) and files
    the steps as cards; the process only collects them."""
    if _goal_has_process(st):
        return
    try:
        pid = ensure_goal_process(st)
    except Exception as e:
        print("PM goal_process error:", e)
        return
    if pid:
        _say("Ziel notiert. Henry treibt es, seine Ziel-Karten sammeln sich als Plan.")


def _goal_process_status(st):
    """Compact goal-process view for analysis: (next_open_step_title, next_due,
    process_due, done, total) or None. Cheap read from processes.json."""
    from cells.copilot.planning.pm import get_goal
    gp = st.get("goal_process") or {}
    if gp.get("goal") != get_goal() or not gp.get("pid"):
        return None
    try:
        from cells.engineer.chains import processes
        p = processes.get(gp["pid"])
    except Exception:
        return None
    if not p:
        return None
    steps = p.get("steps") or []
    # sync() owns completion (state/done); a step's `status` is only
    # proposed/accepted and never "done" - counting it said 0/N forever
    done = sum(1 for s in steps if s.get("state") == "done" or s.get("done"))
    nxt = next((s for s in steps if not (s.get("state") == "done" or s.get("done"))), None)
    return {"next": (nxt or {}).get("title"), "next_due": (nxt or {}).get("due"),
            "process_due": p.get("due"), "done": done, "total": len(steps),
            "status": p.get("status")}
