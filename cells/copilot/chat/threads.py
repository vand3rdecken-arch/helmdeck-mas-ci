# -*- coding: utf-8 -*-
"""CONVERSATIONS = CARD THREADS, grouped by process (owner decree 2026-09-13:
"es macht eine Conversation und eine Karte, so übersichtlicher - jetzt nur ein
sehr sehr langer Chat").

Nothing new is stored. A conversation IS a card: its transcript already lives
in the card's own timeline (copilot.chat(card=...) folds owner + Henry lines
there), its session is already isolated per (user, card) (copilot._skey), and
the app already has the card chat tab. The board chat is the INBOX - the one
flat conversation for quick questions, card tiles and roll-ups. The process
(the PMBOK epic, cells/engineer/chains/processes.py) is the FOLDER: cards born
from a process carry `process`/`process_title`, so the list can group them
without a fourth object. Derived on every call from the runtime's own records,
never cached as a stored flag (CLAUDE.md)."""
import time


def _epoch(s):
    try:
        return time.mktime(time.strptime(s, "%Y-%m-%d %H:%M:%S"))
    except Exception:                                    # noqa: BLE001
        return 0.0


def _last_line(steps):
    """The newest CONVERSATION line of a card timeline: owner or Henry prose
    (kind text/note by human/henry) - tool rows and worker steps do not count
    as 'the last thing said'."""
    for s in reversed(steps or []):
        if not isinstance(s, dict):
            continue
        if s.get("kind") in ("text", "note") and s.get("byKind") in ("human", "henry"):
            txt = (s.get("text") or "").strip()
            if txt:
                return s
    return None


def threads(user, limit=200):
    from cells.engineer.cards import sessions
    from cells.engineer.chains import processes
    from cells.copilot.chat import card_mirror
    from spine.agent import timeline_store
    from spine.storage import db

    tail = db.chat_tail(user, 1)
    last = tail[-1] if tail else {}
    inbox = {"id": "inbox", "kind": "inbox", "title": "Henry",
             "preview": (last.get("text") or "")[:140].replace("\n", " "),
             "at": _epoch("%s %s:00" % (last.get("date") or "", last.get("ts") or ""))
             if last.get("ts") else 0.0}

    procs = {}
    for p in processes.list_processes():
        steps = p.get("steps") or []
        procs[p["id"]] = {"id": p["id"], "title": (p.get("request") or "")[:60],
                          "status": p.get("status"),
                          "total": len(steps),
                          "done": sum(1 for s in steps if s.get("status") == "done" or s.get("done"))}

    rows = []
    for t in sessions.list_tracks():
        if t.get("archived"):
            continue
        run_dir = t.get("run_dir") or ""
        steps = timeline_store.read(run_dir) if run_dir else []
        lm = _last_line(steps)
        at = float(lm.get("ta") or 0.0) if lm else 0.0
        if not at:
            at = _epoch(t.get("updated") or t.get("created") or "")
        rows.append({
            "id": t["id"], "kind": "card",
            "title": card_mirror.short_name(t),
            "lane": t.get("lane"), "status": t.get("status"),
            "process": t.get("process") or None,
            "process_title": t.get("process_title") or None,
            "preview": ((lm.get("text") if lm else "") or "")[:140].replace("\n", " "),
            "by": (lm.get("byKind") if lm else None),
            "has_chat": lm is not None,
            "at": at,
        })
    rows.sort(key=lambda r: r["at"], reverse=True)
    used = {r["process"] for r in rows if r.get("process")}
    return {"inbox": inbox,
            "threads": rows[:limit],
            "processes": [procs[k] for k in procs if k in used]}
