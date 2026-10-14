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
never cached as a stored flag (CLAUDE.md).

Titles: a process-born card's task text starts with the mode banner
processes.py prepends ("HUMAN STEP (tracked only): ...", "PREPARE (draft only
- ...): ..."), which is the WORKER's instruction, not a name the owner would
say out loud (his first screenshot of the list, 2026-09-13 13:11). For those
the STEP's own title is the name - matched through step["track"], the binding
processes.accept_step writes."""
import os
import time

ACTIVE_LANES = ("working", "review")

# Paseo's sidebar buckets (packages/protocol/src/agent-state-bucket.ts, display
# order hooks/sidebar-status-view-model.ts): needs_input, failed, attention
# ("Ready to review"), running ("Working"), done - plus `backlog`, which Paseo
# has no equivalent for (a HelmDeck card can exist before anyone works on it).
BUCKETS = ("needs_input", "failed", "attention", "running", "backlog", "done")


def _bucket(t):
    st, lane = t.get("status"), t.get("lane")
    # A turn that ends with a background task still running parks as
    # needs_you + waiting_on="background" (turnrunner) - the WORKER is waiting,
    # not the owner; blockers.py and pm.py already read it that way.
    # needs_input = a REAL open question; a turn that merely ended is not the
    # owner's move (lifecycle.card_phase).
    from cells.engineer.cards import lifecycle
    ph = lifecycle.card_phase(t)
    if ph == "asking":
        return "needs_input"
    if ph in ("delivered", "ready"):
        return "attention"
    if st in ("bounced", "failed", "canceled"):
        return "failed"
    if lane == "review":
        return "attention"
    if lane == "working":
        return "running"
    if lane == "backlog":
        return "backlog"
    return "done"


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
    from spine.ops.runs import run_id_of
    from spine.storage import db

    tail = db.chat_tail(user, 1)
    last = tail[-1] if tail else {}
    inbox = {"id": "inbox", "kind": "inbox", "title": "Henry",
             "preview": (last.get("text") or "")[:140].replace("\n", " "),
             "at": _epoch("%s %s:00" % (last.get("date") or "", last.get("ts") or ""))
             if last.get("ts") else 0.0}

    procs, step_title = {}, {}
    for p in processes.list_processes():
        steps = p.get("steps") or []
        procs[p["id"]] = {"id": p["id"], "title": (p.get("request") or "").split("\n")[0][:70],
                          "status": p.get("status"),
                          "total": len(steps),
                          # sync() owns step completion (state/done); a step's
                          # `status` is proposed/accepted and never "done"
                          "done": sum(1 for s in steps if s.get("state") == "done" or s.get("done"))}
        for s in steps:
            if s.get("track") and s.get("title"):
                step_title[s["track"]] = s["title"]

    rows = []
    for t in sessions.list_tracks():
        # board_hidden (owner decree 2026-09-14): a landing's own ship-decide
        # research runs as a real card underneath (dispatch.new_ship_task,
        # lanemachine.request_ship_decision) but must never become a thread/
        # process row the owner did not ask for - see that function's
        # docstring for the full history.
        if t.get("archived") or t.get("board_hidden"):
            continue
        run_dir = t.get("run_dir") or ""
        # ONE line per card, read from the table newest-first - never the whole
        # folded timeline (that filled timeline_store's cache with every card's
        # history: ~430 MB held by the daemon, measured 2026-10-14).
        lm = db.timeline_last_line(run_id_of(run_dir)) if run_dir else None
        at = float(lm.get("ta") or 0.0) if lm else 0.0
        bucket = _bucket(t)
        if not at:
            # No conversation line to date it by. For a FINISHED card `updated`
            # is not "when it last did something": it is the row's write stamp,
            # and a bulk write (the 2026-10-05 09:41 backfill touched 342 of 420
            # cards) put every old card in "Today / 2h". The turn's own end, then
            # its creation, are the card's real events. Live cards keep `updated`:
            # they are being written for real, and they sort by it.
            if bucket == "done":
                at = _epoch(t.get("turn_ended") or t.get("created") or "")
            else:
                at = _epoch(t.get("updated") or t.get("created") or "")
        lane = t.get("lane")
        status = t.get("status")
        rows.append({
            "id": t["id"], "kind": "card",
            "title": step_title.get(t["id"]) or card_mirror.short_name(t),
            "lane": lane, "status": status,
            # what the owner must know at a glance - the card's own signals
            "active": lane in ACTIVE_LANES or status == "needs_you",
            "bucket": bucket,
            "process": t.get("process") or None,
            "process_title": t.get("process_title") or None,
            # the PROJECT (repo folder name) and where the card came from
            "repo": os.path.basename((t.get("repo") or "").replace("\\", "/").rstrip("/")) or None,
            "origin_card": t.get("origin_card") or None,
            "isolated": bool(t.get("isolated_from")),
            "preview": ((lm.get("text") if lm else "") or "")[:140].replace("\n", " "),
            "by": (lm.get("byKind") if lm else None),
            "has_chat": lm is not None,
            "at": at,
        })
    rows.sort(key=lambda r: (not r["active"], -r["at"]))
    used = {r["process"] for r in rows if r.get("process")}
    return {"inbox": inbox,
            "threads": rows[:limit],
            # THE PLANS: every open process (the checklist under a goal) plus
            # any finished one a listed card still points at
            "processes": [procs[k] for k in procs
                          if k in used or procs[k]["status"] not in ("done", "cancelled")],
            "goals": _goals(),
            "needs": _needs()}


def _goals():
    """Ziel -> Prozess -> Karte, top level: each project's goal, and the
    workspace goal (repo None) when one is set."""
    out = []
    try:
        from cells.copilot.planning import pm
        g = pm.get_goal()
        if g:
            out.append({"repo": None, "goal": g})
    except Exception:                                    # noqa: BLE001
        pass
    try:
        from spine.storage import db
        for p in db.projects_all():
            if (p.get("goal") or "").strip():
                out.append({"repo": os.path.basename((p.get("repo") or "").replace("\\", "/").rstrip("/")) or p.get("name"),
                            "goal": p["goal"].strip()})
    except Exception:                                    # noqa: BLE001
        pass
    return out


def _needs():
    """What waits on the OWNER beyond card questions: ready human steps and
    long-parked cards outside any process - pm_push.derive is the one place
    that computes them (who="owner"); served, not re-derived. Everything an
    agent can decide is Henry's (process_drive) and never lands here."""
    try:
        from cells.copilot.planning import pm_push
        return [{k: it.get(k) for k in ("key", "kind", "label", "since", "process", "card")}
                for it in pm_push.derive() if it.get("who") == "owner"][:12]
    except Exception:                                    # noqa: BLE001
        return []
