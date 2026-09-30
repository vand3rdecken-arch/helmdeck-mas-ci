# -*- coding: utf-8 -*-
"""THE drive: the one thing that wakes Henry FOR a piece of work (owner
2026-09-30: "Wieviel planning, process etc. gibt es schon - warum nicht als
eines", "alles zusammen legen").

Before, two wakes ran side by side - goal_drive for the ONE goal, and a
per-process wake beside it - and the PM brain planned a third time on the
Plan button. Now every piece of longer work is a PROCESS (the goal is one,
pm_goal.ensure_goal_process), and this module is the only wake for all of
them. It hands Henry evidence and an open question, never a checklist - the
earlier briefs were mostly restrictions, and restrictions are what stopped
the work.

Reasons, per open process:
  delivered - a step card reached done since the last look
  stalled   - no step card moved for STALL_S (the goal: also when none
              was ever filed)
  deadline  - DEADLINE_NEAR_DAYS or closer (the goal: its date in the goal
              text, pm_push.goal_deadline; a process: its `due`)
  next      - the process' recorded next move is due (processes.set_next -
              also what the Plan button writes, request_plan)
  decide    - pm_push.derive's who="henry" items for this process: steps
              nobody started, a dead chain, a step card parked on its question
  empty     - a new process without steps (there is no proposer any more:
              Henry files the first cards)

DERIVED, NOT STORED: every reason is computed from the process store, the
card store and the event log at tick time. The latches in the PM loopstate
(st["proc_wake"][pid]) are dedup only - one open escalation per process, each
timed reason once a day, a `next` once per recorded move."""
import time

STALL_S = 24 * 3600
DEADLINE_NEAR_DAYS = 3
MAX_WAKES_PER_TICK = 2           # a board full of old processes must not flood Henry
ESC_KIND = "process-move"

# Open on purpose: what he can do and the ONE line where the owner comes in.
_ASK = (
    "Was ist jetzt der naechste Zug? Du machst die Arbeit selbst - recherchieren, "
    "bauen, im Browser oder auf dem Desktop (direct_task / machine_task, text = der "
    "Auftrag; die Karte wird Schritt dieses Prozesses). Den Owner holst du nur fuer "
    "einen Login oder das letzte Go vor etwas, das nach aussen geht (posten, "
    "senden, bezahlen) - dann bereitest du alles so vor, dass ihm ein Tap bleibt "
    "(notify_owner, eine Frage). Weitere Verben: accept_steps, cancel_process, "
    "set_next (text = was, at = wann), steer/move, ignore (ein Satz warum).")


def _epoch(s):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return time.mktime(time.strptime((s or "")[:19], fmt))
        except ValueError:
            continue
    return 0.0


def _title(p):
    return " ".join(((p.get("request") or "").split("\n")[0]).split())[:120]


def _open_ids():
    from spine.registry import escalations
    return {e["id"] for e in escalations.list_open()}


def _enabled():
    try:
        from spine.registry import behavior
        return behavior.value("initiative.goal_drive", "pm") is not False
    except Exception:                                        # noqa: BLE001
        return True


def process_state(p, tracks_by_id, last_lane, now, days_left=None):
    """The evidence for one process: done step cards, last movement, days to
    the deadline, the recorded next move. `days_left` overrides the process
    `due` (the goal's date lives in the goal text)."""
    steps = p.get("steps") or []
    cards = [s.get("track") for s in steps if s.get("track")]
    done = sorted(c for c in cards if (tracks_by_id.get(c) or {}).get("lane") == "done")
    last = max([last_lane.get(c, 0.0) for c in cards]
               + [_epoch((tracks_by_id.get(c) or {}).get("created")) for c in cards]
               + [_epoch(p.get("created"))])
    days = days_left
    if days is None and p.get("due"):
        e = _epoch(p["due"])
        if e:
            today = _epoch(time.strftime("%Y-%m-%d", time.localtime(now)))
            days = int(round((e - today) / 86400))
    return {"steps": len(steps), "cards": cards, "done": done, "last_move": last,
            "days_left": days, "next": p.get("next") or None}


def summary(p, ps, now):
    lines = ["PROZESS %s: %s" % (p["id"], _title(p)),
             "  Status %s | %d Schritte, %d mit Karte, %d fertig" % (
                 p.get("status"), ps["steps"], len(ps["cards"]), len(ps["done"]))]
    for i, s in enumerate((p.get("steps") or [])[-12:]):
        lines.append("  - [%s/%s] %s%s" % (
            s.get("state") or s.get("status") or "?", s.get("mode") or "do",
            (s.get("title") or "")[:90], (" -> " + s["track"]) if s.get("track") else ""))
    if ps["next"]:
        lines.append("  NAECHSTER ZUG (vermerkt %s): %s - faellig %s" % (
            ps["next"].get("set", ""), ps["next"].get("what", ""), ps["next"].get("at", "")))
    if ps["days_left"] is not None:
        lines.append("  Frist: noch %d Tage" % ps["days_left"])
    return "\n".join(lines)


def reasons_for(p, ps, lat, day, now, decide, is_goal=False):
    """(reasons, new latch) for one process - pure, for tests."""
    fired = dict(lat.get("fired") or {}) if lat.get("day") == day else {}
    out = []
    seen = lat.get("seen_done")
    new_done = [c for c in ps["done"] if seen is not None and c not in seen]
    if new_done:
        out.append("delivered: Schritt-Karte fertig (%s)" % ", ".join(new_done[:3]))
    open_work = (ps["steps"] and len(ps["done"]) < ps["steps"]) or is_goal
    if (p.get("status") in ("running", "ready") and (ps["cards"] or is_goal) and open_work
            and now - ps["last_move"] >= STALL_S and not fired.get("stalled")):
        out.append("stalled: seit %d h keine Bewegung" % ((now - ps["last_move"]) // 3600)
                   if ps["cards"] else "stalled: noch keine Karte fuer das Ziel")
        fired["stalled"] = True
    d = ps["days_left"]
    if d is not None and 0 <= d <= DEADLINE_NEAR_DAYS and not fired.get("deadline"):
        out.append("deadline: noch %d Tage" % d)
        fired["deadline"] = True
    if not ps["steps"] and not is_goal and not lat.get("empty_seen"):
        out.append("empty: noch keine Schritte - leg die ersten Karten an (direct_task / "
                   "machine_task mit diesem Prozess)")
    nx = ps["next"]
    if nx and nx.get("at") and _epoch(nx["at"]) <= now and lat.get("next_fired") != nx.get("set"):
        out.append("next: faellig seit %s - %s" % (nx["at"], nx.get("what", "")))
    dk = sorted(x["key"] for x in decide)
    if dk and set(dk) - set(lat.get("decide_seen") or []):
        out.append("decide: " + "; ".join(x["label"] for x in decide[:3]))
    new = dict(lat)
    new["seen_done"] = list(ps["done"])
    new["decide_seen"] = dk
    if not ps["steps"] and not is_goal:
        new["empty_seen"] = True
    if out:
        new.update({"day": day, "fired": fired})
        if nx and any(r.startswith("next:") for r in out):
            new["next_fired"] = nx.get("set")
    return out, new


def request_plan(actor="owner", note=""):
    """The Plan button and a goal clarification: ONE planner, Henry, woken
    through this drive - no second planner. Records a `next` on the goal's
    process due now; the next PM tick hands it to him. Returns the pid or ""."""
    from cells.copilot.planning.pm_goal import ensure_goal_process
    from cells.engineer.chains import processes
    pid = ensure_goal_process()
    if not pid:
        return ""
    what = "Plan fuer das Ziel machen" + ((": " + note) if note else "") + \
        " - Stand pruefen, die naechsten Karten starten oder set_next setzen."
    processes.set_next(pid, what, time.strftime("%Y-%m-%d %H:%M"), actor=actor)
    return pid


def wake(st, now=None, processes=None, tracks=None, ev=None, emit=None, save=None,
         open_ids=None, goal_pid=None, decide_items=None, goal=None, enabled=None):
    """One pass over every open process. Returns the escalation ids emitted.
    Everything injectable for tests; the daemon passes only `st`."""
    now = now or time.time()
    if not (_enabled() if enabled is None else enabled):
        return []
    if processes is None:
        from cells.engineer.chains import processes as _p
        processes = _p.list_processes()
    live = [p for p in processes
            if p.get("status") not in ("done", "cancelled", "failed", "proposing")]
    wl = st.setdefault("proc_wake", {})
    st.pop("goal_wake", None)             # the old goal-only latch, merged in here
    gone = [k for k in wl if k not in {p["id"] for p in live}]
    for pid in gone:
        wl.pop(pid, None)                 # finished processes leave the latch
    if not live:
        if gone:
            (save or _save)(st)
        return []
    if tracks is None:
        from cells.engineer.cards import sessions
        tracks = sessions._load()
    if ev is None:
        from spine.storage import events
        ev = events.read_events()
    from cells.copilot.planning import pm_push
    if goal_pid is None:
        goal_pid = pm_push.goal_process_id()
    if goal is None and goal_pid:
        from cells.copilot.planning.pm import get_goal
        goal = get_goal() or ""
    if decide_items is None:
        decide_items = [x for x in pm_push.derive(now, processes, tracks, goal_pid)
                        if x.get("who") == "henry"]
    if open_ids is None:
        open_ids = _open_ids()
    tmap = {t["id"]: t for t in tracks}
    last_lane = {}
    for e in ev:
        if e.get("kind") == "lane" and e.get("track"):
            last_lane[e["track"]] = max(last_lane.get(e["track"], 0.0), _epoch(e.get("ts")))
    day = time.strftime("%Y%m%d", time.localtime(now))
    out, changed = [], bool(gone)
    # the goal first, then oldest
    for p in sorted(live, key=lambda q: (q["id"] != goal_pid, q.get("created") or "")):
        pid = p["id"]
        is_goal = bool(goal_pid) and pid == goal_pid
        lat = wl.get(pid) or {}
        if lat.get("last") in open_ids:
            continue                     # Henry is still on the last one
        ps = process_state(p, tmap, last_lane, now,
                           days_left=pm_push.goal_deadline(goal, now) if is_goal else None)
        decide = [x for x in decide_items
                  if x.get("process") == pid
                  or (x.get("card") and (tmap.get(x["card"]) or {}).get("process") == pid)]
        reasons, new = reasons_for(p, ps, lat, day, now, decide, is_goal)
        if reasons and len(out) >= MAX_WAKES_PER_TICK:
            continue                     # next tick; latch untouched so nothing is lost
        if not reasons:
            if new != lat:
                wl[pid] = new
                changed = True
            continue
        head = summary(p, ps, now)
        if is_goal:
            from cells.copilot.planning import goal_drive
            gl = ""
            try:
                gl = goal_drive.goal_line(goal_drive.goal_state(
                    now, tracks=tracks, processes=processes, ev=ev, goal=goal,
                    goal_pid=goal_pid), now)
            except Exception:                                # noqa: BLE001
                pass
            head = "%s\n%s" % (gl or "ZIEL: " + " ".join((goal or "").split())[:300], head)
        detail = "%s\n\nWARUM JETZT: %s\n\n%s" % (head, "; ".join(reasons), _ASK)
        if emit is None:
            from spine.registry import escalations
            emit = escalations.emit
        eid = emit(ESC_KIND, None, detail, process=pid)
        new.update({"last": eid, "at": now})
        wl[pid] = new
        changed = True
        out.append(eid)
    if changed:
        (save or _save)(st)
    return out


def _save(st):
    from cells.copilot.planning.pm_state import _save_loopstate
    _save_loopstate(st)
