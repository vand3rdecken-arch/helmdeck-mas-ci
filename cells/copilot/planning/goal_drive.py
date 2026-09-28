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
membership is a RECORD, never a guess from task text: a card is goal work when
its `goal` field names the CURRENT goal (filed with "goal": true or marked via
mark_goal - copilot_actions / the broker's direct_task verb write the goal
sentence at event time, current_tag) or when it is a step of the goal's own
process (pm_goal records that pid, pm_push checks it is still this goal's). Cards filed before 2026-09-28 carry no flag - the
share says so ("noch keine Ziel-Karten markiert") instead of guessing.

The wake latches in the PM loopstate (st["goal_wake"]) are DEDUP, not truth:
they only stop the same reason from firing twice a day.
"""
import time

GOAL_STALL_S = 24 * 3600       # no goal movement for this long -> wake
DEADLINE_NEAR_DAYS = 3         # T-3 and closer -> wake once a day
SHARE_WINDOW_S = 7 * 24 * 3600
ESC_KIND = "goal-move"

# The question the broker hands Henry. The broker's DEFAULT_POLICY must not
# grow a bullet per escalation kind (its own law), so the kind-specific ask
# rides in the escalation detail, where the emitter owns it.
_ASK = (
    "Frage: Was ist JETZT der naechste Zug fuer das Ziel? Du treibst das Ziel "
    "(Regel initiative.goal_drive). Innerhalb des Ziels handelst du selbst: "
    "eine Karte starten (action \"direct_task\", text = der Auftrag in einem "
    "Absatz), recherchieren, Entwuerfe vorbereiten, einen Owner-Schritt so "
    "vorbereiten, dass ihm ein Tap bleibt, und ihn dann mit EINER konkreten "
    "Frage melden (notify_owner). Nie ohne den Owner: veroeffentlichen/posten, "
    "Geld ausgeben, neue Accounts, Unumkehrbares, Deploys. Laeuft bereits eine "
    "Ziel-Karte, die das abdeckt, oder gibt es gerade nichts Sinnvolles: "
    "ignore mit einem Satz Grund.")


def _epoch(s):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return time.mktime(time.strptime((s or "")[:19], fmt))
        except ValueError:
            continue
    return 0.0


def norm(goal):
    return " ".join((goal or "").split())


def current_tag():
    """What a card's `goal` field holds when it serves the CURRENT goal: the
    goal sentence itself, whitespace-normalized. A bare True would outlive
    the goal it was set for - after a set_goal the old goal's cards kept
    counting as work for the new one (found 2026-09-28 in the adversarial
    pass, before any goal change happened live)."""
    from cells.copilot.planning.pm import get_goal
    return norm(get_goal())


def _goal_ids(tracks, goal_pid, goal):
    return {t["id"] for t in tracks
            if not t.get("example") and (
                (goal and norm(t.get("goal") if isinstance(t.get("goal"), str) else "") == goal)
                or (goal_pid and t.get("process") == goal_pid))}


def goal_state(now=None, tracks=None, processes=None, ev=None, goal=None, goal_pid=None):
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
             if (goal_pid and x.get("process") == goal_pid) or x.get("card") in ids]
    done = sorted(t["id"] for t in tracks if t["id"] in ids and t.get("lane") == "done")
    live = [t for t in tracks if t["id"] in ids and not t.get("archived")
            and t.get("lane") in ("backlog", "working", "review")]
    return {
        "goal": goal,
        "days_left": pm_push.goal_deadline(goal, now),
        "goal_pid": goal_pid or "",
        "goal_cards": len(ids),
        "live": [t["id"] for t in live],
        "done": done,
        "share": (tok_goal / float(tok_all)) if tok_all and ids else None,
        "last_move": last_move or None,
        "needs": needs,
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
        parts.append("Ziel-Anteil 7T: noch keine Ziel-Karten markiert (goal=true beim Anlegen)")
    else:
        parts.append("Ziel-Anteil 7T: %d%% der Kartenarbeit" % round(100 * gs["share"]))
    parts.append("%d Ziel-Karte%s laufen" % (len(gs["live"]), "" if len(gs["live"]) == 1 else "n"))
    parts.append(("letzte Ziel-Bewegung " + _ago(gs["last_move"], now))
                 if gs["last_move"] else "noch keine Ziel-Bewegung")
    out = "GOAL: %s\n  %s" % (head, " | ".join(parts))
    if gs["needs"]:
        out += "\n  wartet auf den Owner: " + "; ".join(x["label"] for x in gs["needs"][:3])
    return out


def _enabled():
    try:
        from spine.registry import behavior
        return behavior.value("initiative.goal_drive", "pm") is not False
    except Exception:                                        # noqa: BLE001
        return True


def _open_goal_move():
    from spine.registry import escalations
    return any(e.get("kind") == ESC_KIND for e in escalations.list_open())


def wake(st, now=None, gs=None, emit=None, save=None, enabled=None, open_exists=None):
    """At most one open goal-move escalation; each reason at most once a day.
    Reasons:
      delivered - a goal card reached done since the last look (first look
                  only records what is already done - history never fires)
      stalled   - no goal movement for GOAL_STALL_S
      deadline  - DEADLINE_NEAR_DAYS or fewer calendar days left
    Returns the escalation id, or None. Everything injectable for tests."""
    now = now or time.time()
    if not (_enabled() if enabled is None else enabled):
        return None
    if gs is None:
        gs = goal_state(now)
    if not gs:
        return None
    lat = st.setdefault("goal_wake", {})
    day = time.strftime("%Y%m%d", time.localtime(now))
    fired = lat.get("fired") if lat.get("day") == day else {}
    fired = dict(fired or {})
    reasons = []
    seen = lat.get("seen_done")
    new_done = [c for c in gs["done"] if seen is not None and c not in seen]
    if new_done:
        reasons.append("delivered: Ziel-Karte fertig (%s)" % ", ".join(new_done[:3]))
    lm = gs["last_move"]
    if (not lm or now - lm >= GOAL_STALL_S) and not fired.get("stalled"):
        reasons.append("stalled: " + ("keine Ziel-Bewegung seit %s" % _ago(lm, now)
                                      if lm else "noch nie eine Ziel-Karte bewegt"))
        fired["stalled"] = True
    d = gs["days_left"]
    if d is not None and 0 <= d <= DEADLINE_NEAR_DAYS and not fired.get("deadline"):
        reasons.append("deadline: noch %d Tage" % d)
        fired["deadline"] = True
    if reasons and (_open_goal_move() if open_exists is None else open_exists):
        # Henry is still on the last one: change nothing, so a delivery that
        # happened meanwhile still fires once he is done
        return None
    changed = seen != list(gs["done"])
    lat["seen_done"] = list(gs["done"])
    if not reasons:
        if changed:                        # the PM ticks every 120 s - no idle writes
            (save or _save)(st)
        return None
    detail = "%s\n\nWARUM JETZT: %s\n\n%s" % (goal_line(gs, now), "; ".join(reasons), _ASK)
    if emit is None:
        from spine.registry import escalations
        emit = escalations.emit
    eid = emit(ESC_KIND, None, detail)
    lat.update({"day": day, "fired": fired, "last": eid, "at": now})
    (save or _save)(st)
    return eid


def _save(st):
    from cells.copilot.planning.pm_state import _save_loopstate
    _save_loopstate(st)
