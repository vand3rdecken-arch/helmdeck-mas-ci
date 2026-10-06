# -*- coding: utf-8 -*-
"""Henry drives the goal (owner 2026-09-28, "Ok, do it" - reverses the
2026-09-23 decree "Henry ist kein PM, er pusht nichts": Henry owns MOVING the
goal, the owner owns the trade-offs).

Measured the week before (2026-09-21..27): 98% of card work was accepted, but
only 13% of it served the goal "erster fremder User bis 2026-09-30". Three
causes, all structural, none about model intelligence:
  - the goal was not in Henry's view (the only plan he could read was frozen
    on 2026-09-23 and said "triage ok"),
  - nothing ever woke him FOR the goal - every escalation was card health
    (parked, idle, context size), 36 of 73 judgements ended in "ignore",
  - his brief said "only act when the owner clearly asks".
This module is the first two: the goal as EVIDENCE (goal_state / goal_line,
rendered into both board snapshots) and the WAKE (a goal-move escalation the
broker judges like any other). The third is the brief rule
initiative.goal_drive.

DERIVED, NOT STORED (CLAUDE.md law): every number here is computed at read
time from the card store, the process store and the event log. Goal
membership is a RECORD, never a guess from task text, and there is exactly
ONE: a card is goal work iff it is a step of the goal's own process
(card.process == goal pid; pm_goal.ensure_goal_process owns the pid,
pm_push checks it is still this goal's). Filing with "goal": true, mark_goal
and the broker's direct_task on a goal-move all go through link_card ->
processes.attach_card at event time. Until 2026-09-30 there was a second
record, a `goal` sentence on the card, that the goal process never saw - 10
goal cards, process 0/7, the owner asked to start finished work. That tag is
no longer written or read.

The WAKE that used to live here (goal-move escalations) is merged into
process_drive since 2026-09-30 - the goal is a process, and one drive wakes
Henry for every process. This module keeps the goal's EVIDENCE (goal_state /
goal_line, rendered into both board snapshots) and its one link (link_card).
"""
import time

SHARE_WINDOW_S = 7 * 24 * 3600


def _epoch(s):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return time.mktime(time.strptime((s or "")[:19], fmt))
        except ValueError:
            continue
    return 0.0


def norm(goal):
    return " ".join((goal or "").split())


def link_card(tid, actor="henry", on=True):
    """Make card `tid` goal work (or stop it being): a step of the goal's
    process. Creates the (empty) goal process on first use. Returns the goal
    pid, or "" when no goal is set. The ONE entry every goal-marking path
    uses (copilot_actions file/direct/mark_goal, henry_broker direct_task)."""
    from cells.copilot.planning.pm_goal import ensure_goal_process
    from cells.engineer.chains import processes
    pid = ensure_goal_process()
    if not pid:
        return ""
    if on:
        processes.attach_card(pid, tid, actor=actor)
    else:
        processes.detach_card(pid, tid, actor=actor)
    return pid


def _goal_ids(tracks, goal_pid, goal=None):
    if not goal_pid:
        return set()
    return {t["id"] for t in tracks
            if not t.get("example") and t.get("process") == goal_pid}


def _facts_evicted(goal):
    """How many clarifications of THIS goal the PM's fixed-size ring has dropped
    (pm.add_clarification counts them at write time, per goal text)."""
    try:
        from cells.copilot.planning.pm_state import _loopstate
        ev = _loopstate().get("clarifications_evicted") or {}
        return int(ev.get(norm(goal)) or 0) if isinstance(ev, dict) else 0
    except Exception:                                        # noqa: BLE001
        return 0


def _facts(goal):
    """The owner's clarifications recorded against THIS goal text (clarify_goal
    -> pm.add_clarification). Until 2026-09-30 only the PM brain's plan prompt
    read them; with Henry as the one planner they ride in the goal evidence."""
    try:
        from cells.copilot.planning.pm_state import _loopstate
        return [c.get("text", "") for c in (_loopstate().get("clarifications") or [])
                if norm(c.get("goal")) == goal and c.get("text")]
    except Exception:                                        # noqa: BLE001
        return []


def goal_state(now=None, tracks=None, processes=None, ev=None, goal=None, goal_pid=None,
               facts=None):
    """The goal, as evidence. None when no goal is set. Every input is
    injectable for tests; the daemon passes nothing."""
    now = now or time.time()
    from cells.copilot.planning import pm_push
    if goal is None:
        from cells.copilot.planning.pm import get_goal
        goal = get_goal() or ""
    goal = norm(goal)
    if not goal:
        return None
    if tracks is None:
        from cells.engineer.cards import sessions
        tracks = sessions._load()
    if goal_pid is None:
        goal_pid = pm_push.goal_process_id()
    if ev is None:
        from spine.storage import events
        ev = events.read_events()
    from spine.storage.events import turn_tokens
    ids = _goal_ids(tracks, goal_pid, goal)
    since = now - SHARE_WINDOW_S
    tok_all = tok_goal = 0
    last_move = 0.0
    for e in ev:
        k = e.get("kind")
        if k == "turn":
            ts = _epoch(e.get("ts"))
            if ts < since:
                continue
            n = turn_tokens(e)
            tok_all += n
            if e.get("track") in ids:
                tok_goal += n
        elif k == "lane" and e.get("track") in ids:
            last_move = max(last_move, _epoch(e.get("ts")))
    for t in tracks:                       # a goal card filed, never moved yet
        if t["id"] in ids:
            last_move = max(last_move, _epoch(t.get("created")))
    needs = [x for x in pm_push.derive(now, processes, tracks, goal_pid)
             if x.get("who") == "owner"
             and ((goal_pid and x.get("process") == goal_pid) or x.get("card") in ids)]
    done = sorted(t["id"] for t in tracks if t["id"] in ids and t.get("lane") == "done")
    live = [t for t in tracks if t["id"] in ids and not t.get("archived")
            and t.get("lane") in ("backlog", "working", "review")]
    return {
        "goal": goal,
        "days_left": pm_push.goal_deadline(goal, now),
        "goal_pid": goal_pid or "",
        "goal_cards": len(ids),
        "live": [t["id"] for t in live],
        "working": sum(1 for t in live if t.get("lane") == "working"),
        "done": done,
        "share": (tok_goal / float(tok_all)) if tok_all and ids else None,
        "last_move": last_move or None,
        "needs": needs,
        "facts": _facts(goal) if facts is None else list(facts),
        "facts_evicted": _facts_evicted(goal) if facts is None else 0,
    }


def _ago(epoch, now):
    h = int(max(0.0, now - epoch) // 3600)
    return ("vor %d h" % h) if h < 48 else ("vor %d Tagen" % (h // 24))


def goal_line(gs, now=None):
    """One or two lines for the board snapshots. '' without a goal."""
    if not gs:
        return ""
    now = now or time.time()
    head = gs["goal"] if len(gs["goal"]) <= 110 else gs["goal"][:109].rstrip() + "…"
    parts = []
    d = gs["days_left"]
    if d is not None:
        parts.append(("noch %d Tage" % d) if d >= 0 else ("Frist seit %d Tagen vorbei" % -d))
    if gs["share"] is None:
        parts.append("Ziel-Anteil 7T: noch keine Ziel-Karten (goal=true beim Anlegen haengt sie an den Ziel-Prozess)")
    else:
        parts.append("Ziel-Anteil 7T: %d%% der Kartenarbeit" % round(100 * gs["share"]))
    # "live" = lanes backlog+working+review: say OPEN, not "laufen" (a card
    # parked in backlog or review is not running)
    nl = len(gs["live"])
    parts.append("%d Ziel-Karte%s offen%s" % (
        nl, "" if nl == 1 else "n",
        (" (davon %d in Arbeit)" % gs["working"]) if gs.get("working") is not None else ""))
    parts.append(("letzte Ziel-Bewegung " + _ago(gs["last_move"], now))
                 if gs["last_move"] else "noch keine Ziel-Bewegung")
    out = "GOAL: %s\n  %s" % (head, " | ".join(parts))
    if gs["needs"]:
        out += "\n  wartet auf den Owner: " + "; ".join(x["label"] for x in gs["needs"][:3])
        if len(gs["needs"]) > 3:
            out += " (+%d weitere)" % (len(gs["needs"]) - 3)
    if gs.get("facts_evicted"):
        out += ("\n  (%d aeltere Owner-Fakten wurden aus dem begrenzten Speicher verdraengt "
                "und sind nicht mehr hier - frag den Owner, falls ein Fakt fehlt)" % gs["facts_evicted"])
    allf = gs.get("facts") or []
    if len(allf) > 8:
        out += "\n  (%d von %d Owner-Fakten gezeigt, aeltere nicht gezeigt)" % (8, len(allf))
    for f in allf[-8:]:
        ft = " ".join(f.split())
        out += "\n  Owner-Fakt: " + ft[:200] + ("… (gekuerzt)" if len(ft) > 200 else "")
    return out
