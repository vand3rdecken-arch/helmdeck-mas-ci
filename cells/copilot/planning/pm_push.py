# -*- coding: utf-8 -*-
"""The PUSH sweep - the part of a PM that moves things (owner decree
2026-09-23: "Henry ist kein PM, er pusht nichts. Er muss keine Entscheidung
treffen, aber das Ganze pushen: den User fragen, ob was gemacht werden soll,
damit das Ziel erreicht wird.").

Measured the same day, before this existed: 16 processes, 6 of them with
NOT ONE step accepted (two since 2026-08-05, one of them "HIGHEST PRIO"), 3
more parked on a human step nobody was reminded of (one since August), 2
with step cards deleted or archived while the process still said `running`.
The old PM tick watched cost and context windows (78 of its 99 notices in a
week) and wrote a nightly plan the owner does not read - it never once looked
at whether the work it had filed was actually moving.

DERIVED, NOT STORED (CLAUDE.md law): every stall below is computed from the
process steps and the card store at sweep time. `status=ready` on a process
means "proposal waiting for a human", `state=working` on a step whose card
is archived means nothing - this module checks the card, never the word.
sync() still trusts the word (debt chain-counts-archived-card-as-live);
that debt stays open and is listed, not silently paid here.

ONE writer of the ask latch (st["push_asked"]), one owner-facing shape: the
existing tap-with-options channel (_ask_owner). A tapped option becomes the
owner's next chat message to Henry, whose brief (VORANTREIBEN-ANTWORT)
turns "Starten: X" / "Erledigt: X" / "Streichen: X" / "Zeig mir: X" into the
verb he already has (accept_steps / move done / cancel_process / show the
card's question). No new autonomy anywhere."""
import hashlib
import re
import time

STALL_AGE_S = 24 * 3600          # a needs_you card counts as parked after this
MAX_ITEMS = 5                    # ask.MAX_OPTIONS is 6: five items + "Nichts davon"


def _epoch(s):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return time.mktime(time.strptime((s or "")[:19], fmt))
        except ValueError:
            continue
    return 0.0


def _short_title(s, n=34):
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def _days(epoch, now):
    return int(max(0.0, now - epoch) // 86400) if epoch else 0


def goal_deadline(goal, now=None):
    """Days until the first YYYY-MM-DD in the goal text, or None."""
    m = re.search(r"(20\d\d-\d\d-\d\d)", goal or "")
    if not m:
        return None
    e = _epoch(m.group(1))
    if not e:
        return None
    today = _epoch(time.strftime("%Y-%m-%d", time.localtime(now or time.time())))
    return int(round((e - today) / 86400))          # calendar days, not 24h blocks


# Ask order: what moves the GOAL first, then what only needs a tap from the
# owner, then proposals never started, then chains that are dead, then cards
# parked on him. Within a group oldest first. Measured live 2026-09-23 before
# this ranking existed: the five oldest stalls were all August leftovers and
# the goal's own process (7 days to its deadline) did not make the buttons.
_RANK = {"human": 1, "proposal": 2, "dead": 3, "parked": 4}


def goal_process_id(st=None):
    """The goal's own process, as the PM RECORDED it (pm_goal._goal_process
    writes st["goal_process"] = {pid, goal}) - never guessed from text."""
    try:
        if st is None:
            from cells.copilot.planning.pm_state import _loopstate
            st = _loopstate()
        return ((st or {}).get("goal_process") or {}).get("pid") or ""
    except Exception:                                        # noqa: BLE001
        return ""


def derive(now=None, processes=None, tracks=None, goal_pid=None):
    """Every stalled thing on the board, goal first, then oldest. Each item:
        {key, kind, label, option, desc, since, process, step, card}
    kind: proposal   - a process whose steps were proposed and never accepted
          human      - a human step that is ready and waiting on the owner
          dead       - a process whose chain cannot move: a step's card is
                       gone or was archived unfinished (ONE item per process)
          parked     - a card on needs_you for longer than STALL_AGE_S
    `processes`/`tracks`/`goal_pid` are injectable for tests; the daemon
    passes nothing and reads the goal pid from the PM's loopstate."""
    now = now or time.time()
    if processes is None:
        from cells.engineer.chains import processes as _p
        processes = _p.list_processes()
    if tracks is None:
        from cells.engineer.cards import sessions
        tracks = sessions._load()
    if goal_pid is None:
        goal_pid = goal_process_id()
    tmap = {t["id"]: t for t in tracks}
    items = []
    for p in processes:
        if p.get("status") in ("done", "cancelled", "failed", "proposing"):
            continue
        steps = p.get("steps") or []
        if not steps:
            continue
        head = _short_title((p.get("request") or "").split("\n")[0])
        if not any(s.get("track") for s in steps):
            since = _epoch(p.get("created"))
            items.append({
                "key": "proposal:" + p["id"], "kind": "proposal",
                "label": "%s: %d Schritte vorgeschlagen, nie gestartet" % (head, len(steps)),
                "option": "Starten: " + head,
                "desc": "%d Schritte annehmen, die Kette laeuft an" % len(steps),
                "since": since, "process": p["id"], "step": None, "card": None})
            continue
        prev_done = True
        dead = []
        for i, s in enumerate(steps):
            t = tmap.get(s.get("track")) if s.get("track") else None
            done = bool(t and t.get("lane") == "done")
            if s.get("track") and (t is None or (t.get("archived") and not done)):
                dead.append((i, _epoch((t or {}).get("updated") or p.get("created"))))
                prev_done = False
                continue
            if (t and not done and s.get("mode") == "human" and prev_done
                    and t.get("lane") == "backlog"):
                since = _epoch(t.get("created") or p.get("created"))
                items.append({
                    "key": "human:%s:%d" % (p["id"], i), "kind": "human",
                    "label": "%s: wartet auf dich" % _short_title(s.get("title"), 40),
                    "option": "Erledigt: " + _short_title(s.get("title"), 26),
                    "desc": "Schritt abhaken, die naechsten Schritte starten",
                    "since": since, "process": p["id"], "step": i, "card": t["id"]})
            prev_done = prev_done and done
        if dead:
            items.append({
                "key": "dead:" + p["id"], "kind": "dead",
                "label": "%s: %d Schritt-Karte%s weg, Kette steht" % (
                    head, len(dead), "" if len(dead) == 1 else "n"),
                "option": "Streichen: " + head,
                "desc": "Prozess abbrechen - laufende Karten bleiben unberuehrt",
                "since": min(e for _, e in dead) or _epoch(p.get("created")),
                "process": p["id"], "step": dead[0][0], "card": steps[dead[0][0]].get("track")})
    for t in tracks:
        if t.get("archived") or t.get("example") or t.get("lane") == "done":
            continue
        if t.get("status") == "needs_you":
            since = _epoch(t.get("updated") or t.get("created"))
            if since and now - since >= STALL_AGE_S:
                items.append({
                    "key": "parked:" + t["id"], "kind": "parked",
                    "label": "%s: wartet auf dich" % _short_title(t.get("task"), 40),
                    "option": "Zeig mir: " + _short_title(t.get("task"), 26),
                    "desc": "die offene Frage dieser Karte im Chat",
                    "since": since, "process": t.get("process"), "step": None, "card": t["id"]})
    items.sort(key=lambda x: (0 if goal_pid and x.get("process") == goal_pid else 1,
                              _RANK.get(x["kind"], 9), x["since"] or 0))
    return items


def _digest(items):
    return hashlib.sha1("|".join(sorted(x["key"] for x in items)).encode("utf-8")).hexdigest()[:12]


def question(items, goal="", now=None):
    """(line, header, options) for _ask_owner - two sentences, the items as
    buttons. Text length obeys spine.comms.notice.short by construction."""
    now = now or time.time()
    top = items[:MAX_ITEMS]
    oldest = max((_days(x["since"], now) for x in items if x["since"]), default=0)
    dl = goal_deadline(goal, now)
    head = ("Ziel in %d Tagen, " % dl) if dl is not None and dl >= 0 else ""
    line = "%s%d Sache%s steh%s still%s." % (
        head, len(items), "" if len(items) == 1 else "n",
        "t" if len(items) == 1 else "en",
        (", die aelteste seit %d Tagen" % oldest) if oldest else "")
    line += " Was soll ich starten, was streichst du?"
    options = [{"label": x["option"], "description": x["desc"]} for x in top]
    options.append({"label": "Nichts davon", "description": "heute nicht - ich frage morgen wieder"})
    return line, "Vorantreiben", options


def sweep(st, now=None, ask=None, feed=None, save=None):
    """At most ONE question per day, earlier only when a NEW stall appears.
    Returns True when a question went out. `ask`/`feed`/`save` are injectable
    for tests; the daemon wires pm_comm._ask_owner / _activity and the
    loopstate writer."""
    now = now or time.time()
    items = derive(now)
    if not items:
        if st.get("push_asked"):
            st.pop("push_asked", None)
            (save or _save)(st)
        return False
    dig = _digest(items)
    last = st.get("push_asked") or {}
    day = time.strftime("%Y%m%d", time.localtime(now))
    if last.get("day") == day and set(last.get("keys") or []) >= {x["key"] for x in items}:
        return False                      # asked today, nothing new since
    goal = ""
    try:
        from cells.copilot.planning.pm import get_goal
        goal = get_goal() or ""
    except Exception:                                        # noqa: BLE001
        pass
    line, header, options = question(items, goal, now)
    (feed or _feed)("blocked", "Vorantreiben: %d Stillstaende - %s" % (
        len(items), "; ".join(x["label"] for x in items[:MAX_ITEMS])))
    sent = (ask or _ask)(line, options, header)
    st["push_asked"] = {"day": day, "digest": dig, "keys": [x["key"] for x in items],
                        "at": now, "sent": bool(sent)}
    (save or _save)(st)
    return bool(sent)


def _ask(line, options, header):
    from cells.copilot.planning.pm_comm import _ask_owner
    return _ask_owner(line, options, header=header, title="Vorantreiben")


def _feed(kind, msg):
    from cells.copilot.planning.pm_comm import _activity
    _activity(kind, msg)


def _save(st):
    from cells.copilot.planning.pm_state import _save_loopstate
    _save_loopstate(st)
