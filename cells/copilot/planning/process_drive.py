# -*- coding: utf-8 -*-
"""Henry drives every PROCESS, not only the goal (owner 2026-09-30: "was
auch fehlt ist der Drive fuer die threads - man bespricht etwas, es legt
vlt einen Prozess an um lang zu planen, aber es gibt kein Follow-up").

Before this, the only thing that ever woke Henry FOR a piece of work was
goal_drive, hard-wired to the ONE goal. Every other process could only
reach the OWNER (pm_push: "Starten?", "Streichen?"), so a process filed
from a conversation sat until he noticed - and he was asked decisions an
agent can take. This module is goal_drive's wake generalised to every open
process, aimed at Henry:

  delivered - a step card reached done since the last look
  stalled   - a running process whose cards did not move for STALL_S
  deadline  - the process due date is DEADLINE_NEAR_DAYS or closer
  next      - the process' recorded next move (processes.set_next) is due
  decide    - pm_push.derive's who="henry" items for this process: a
              proposal nobody started, a dead chain, a step card parked on
              its question

The goal's own process keeps its delivered/stalled/deadline wake in
goal_drive (with the goal line as evidence); here it only gets `next` and
`decide`, so the goal never wakes twice for one event.

DERIVED, NOT STORED: every reason is computed from the process store, the
card store and the event log at tick time. The latches in the PM loopstate
(st["proc_wake"][pid]) are dedup only - one open escalation per process,
each timed reason once a day, a `next` once per recorded move."""
import time

STALL_S = 24 * 3600
DEADLINE_NEAR_DAYS = 3
MAX_WAKES_PER_TICK = 2           # a board full of old processes must not flood Henry
ESC_KIND = "process-move"

_ASK = (
    "Frage: Was ist JETZT der naechste Zug fuer diesen Prozess? Du entscheidest "
    "selbst, der Owner wird nur fuer das gefragt, was nur er kann (unterschreiben, "
    "anrufen, Menschen treffen, bezahlen, veroeffentlichen). Deine Verben hier: "
    "\"accept_steps\" (alle vorgeschlagenen Schritte werden Karten), "
    "\"cancel_process\" (ueberholt/tot - why sagt warum), "
    "\"direct_task\" (text = Auftrag der naechsten Karte, sie wird Schritt dieses "
    "Prozesses), \"set_next\" (text = was als Naechstes, at = wann, "
    "YYYY-MM-DD[ HH:MM] - dann weckt dich der Prozess genau dann wieder), "
    "\"steer\"/\"move\" auf eine Schritt-Karte, \"notify_owner\" nur fuer einen "
    "echten Owner-Schritt mit EINER konkreten Frage. Nichts Sinnvolles: ignore "
    "mit einem Satz Grund.")


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


def process_state(p, tracks_by_id, last_lane, now):
    """The evidence for one process: done step cards, last movement, days to
    due, the recorded next move."""
    steps = p.get("steps") or []
    cards = [s.get("track") for s in steps if s.get("track")]
    done = sorted(c for c in cards if (tracks_by_id.get(c) or {}).get("lane") == "done")
    last = max([last_lane.get(c, 0.0) for c in cards]
               + [_epoch((tracks_by_id.get(c) or {}).get("created")) for c in cards]
               + [_epoch(p.get("created"))])
    days = None
    if p.get("due"):
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
    for i, s in enumerate((p.get("steps") or [])[:10]):
        lines.append("  %d. [%s/%s] %s%s" % (
            i + 1, s.get("state") or s.get("status") or "?", s.get("mode") or "do",
            (s.get("title") or "")[:90], (" -> " + s["track"]) if s.get("track") else ""))
    if ps["next"]:
        lines.append("  NAECHSTER ZUG (vermerkt %s): %s - faellig %s" % (
            ps["next"].get("set", ""), ps["next"].get("what", ""), ps["next"].get("at", "")))
    if ps["days_left"] is not None:
        lines.append("  Frist: %s (%d Tage)" % (p.get("due"), ps["days_left"]))
    return "\n".join(lines)


def reasons_for(p, ps, lat, day, now, decide, is_goal):
    """(reasons, new latch) for one process - pure, for tests."""
    fired = dict(lat.get("fired") or {}) if lat.get("day") == day else {}
    out = []
    if not is_goal:
        seen = lat.get("seen_done")
        new_done = [c for c in ps["done"] if seen is not None and c not in seen]
        if new_done:
            out.append("delivered: Schritt-Karte fertig (%s)" % ", ".join(new_done[:3]))
        open_steps = ps["steps"] and len(ps["done"]) < ps["steps"]
        if (p.get("status") == "running" and ps["cards"] and open_steps
                and now - ps["last_move"] >= STALL_S and not fired.get("stalled")):
            out.append("stalled: seit %d h keine Bewegung" % ((now - ps["last_move"]) // 3600))
            fired["stalled"] = True
        d = ps["days_left"]
        if d is not None and 0 <= d <= DEADLINE_NEAR_DAYS and not fired.get("deadline"):
            out.append("deadline: noch %d Tage" % d)
            fired["deadline"] = True
    nx = ps["next"]
    if nx and nx.get("at") and _epoch(nx["at"]) <= now and lat.get("next_fired") != nx.get("set"):
        out.append("next: faellig seit %s - %s" % (nx["at"], nx.get("what", "")))
    dk = sorted(x["key"] for x in decide)
    if dk and set(dk) - set(lat.get("decide_seen") or []):
        out.append("decide: " + "; ".join(x["label"] for x in decide[:3]))
    new = dict(lat)
    new["seen_done"] = list(ps["done"])
    new["decide_seen"] = dk
    if out:
        new.update({"day": day, "fired": fired})
        if nx and any(r.startswith("next:") for r in out):
            new["next_fired"] = nx.get("set")
    return out, new


def wake(st, now=None, processes=None, tracks=None, ev=None, emit=None, save=None,
         open_ids=None, goal_pid=None, decide_items=None):
    """One pass over every open process. Returns the escalation ids emitted.
    Everything injectable for tests; the daemon passes only `st`."""
    now = now or time.time()
    if processes is None:
        from cells.engineer.chains import processes as _p
        processes = _p.list_processes()
    live = [p for p in processes
            if p.get("status") not in ("done", "cancelled", "failed", "proposing")]
    wl = st.setdefault("proc_wake", {})
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
    if goal_pid is None:
        from cells.copilot.planning import pm_push
        goal_pid = pm_push.goal_process_id()
    if decide_items is None:
        from cells.copilot.planning import pm_push
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
    for p in sorted(live, key=lambda q: q.get("created") or ""):
        pid = p["id"]
        lat = wl.get(pid) or {}
        if lat.get("last") in open_ids:
            continue                     # Henry is still on the last one
        ps = process_state(p, tmap, last_lane, now)
        decide = [x for x in decide_items
                  if x.get("process") == pid
                  or (x.get("card") and (tmap.get(x["card"]) or {}).get("process") == pid)]
        reasons, new = reasons_for(p, ps, lat, day, now, decide, pid == goal_pid)
        if reasons and len(out) >= MAX_WAKES_PER_TICK:
            continue                     # next tick; latch untouched so nothing is lost
        if not reasons:
            if new != lat:
                wl[pid] = new
                changed = True
            continue
        detail = "%s\n\nWARUM JETZT: %s\n\n%s" % (summary(p, ps, now), "; ".join(reasons), _ASK)
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
