# -*- coding: utf-8 -*-
"""Escalation CHANNEL between cells (owner decree 2026-08-21, backlog/
henry-exception-broker; placement corrected on owner pushback: "respect the
cell structure - communication between cells"). This module is the shared
BUS only, same standing as the events table:

  any cell  -> emit(kind, card, detail)          report a fact, never decide
  copilot   -> cells/copilot/henry_broker.py     Henry judges + acts

Append-only (audit law): open/attempt/note/decision records are appended;
current state is FOLDED from the records at read time - never a mutated
flag. No judgement, no threads, no policy in here.

STORE (state-into-db phase C, 2026-09-12): the `escalations` table in
helmdeck.db, ledger step 6 - which also imported and archived the old
daemon/state/escalations.jsonl (1292 lines, count-verified). The file was
folded IN FULL on every list_open(): once per lane tick, per Henry pass, per
PM question. Same records, same fold, one indexed query. The table has no
UPDATE/DELETE path (ops/tests/test_db_schema.py pins that)."""
import time


def _append(rec):
    from spine.storage import db
    rec = dict(rec, ts=time.strftime("%Y-%m-%dT%H:%M:%S"))
    db.escalation_append(rec)
    return rec


def emit(kind, card=None, detail=""):
    """Reporting seam for ANY cell: record the exception, note it on the card,
    never decide anything here."""
    eid = "%s-%d" % (kind, int(time.time() * 1000))
    _append({"event": "open", "id": eid, "kind": kind, "card": card,
             "detail": str(detail)[:1500]})
    try:
        from spine.storage import events
        events.emit("escalation", card or "-", kind=kind, esc=eid)
    except Exception:
        pass
    if card:
        try:
            from spine.storage.trackstore import _load, _find
            from spine.ops.actionlog import ActionLog
            t = _find(_load(), card)
            if t:
                ActionLog(t["run_dir"]).log(
                    "note", "ESKALATION an Henry (%s): %s" % (kind, str(detail)[:200]))
        except Exception:
            pass
    return eid


def record_attempt(eid):
    _append({"event": "attempt", "id": eid})


def record_note(eid, detail):
    _append({"event": "note", "id": eid, "detail": str(detail)[:400]})


def record_decision(eid, action, card="", why=""):
    _append({"event": "decision", "id": eid, "action": action,
             "card": card, "why": why})


def records():
    """Every bus record in order - the raw log, for tests and audit views."""
    from spine.storage import db
    return db.escalations_rows()


def fold():
    """Current state, derived from the append-only records: {id: rec} with
    rec['attempts'] and rec['closed'] folded in."""
    out = {}
    for r in records():
        ev = r.get("event")
        if ev == "open":
            out[r["id"]] = dict(r, attempts=0, closed=False)
        elif r.get("id") in out:
            e = out[r["id"]]
            if ev == "attempt":
                e["attempts"] += 1
            elif ev == "note":
                e["last_note"] = r.get("detail") or ""
            elif ev == "decision":
                e["closed"] = True
                e["action"] = r.get("action")
                e["why"] = r.get("why")
                e["decided_ts"] = r.get("ts")
    return out


def list_open():
    return [e for e in fold().values() if not e["closed"]]


def decided_recently(kind, card, within_s):
    """True when an escalation of `kind` for `card` was DECIDED within the
    last `within_s` seconds - derived from the append-only decision records
    at read time, never a stored flag (the no-monkey-patch law).

    Why (owner report 2026-09-12, "viele Meldungen doppelt"): drivers' turn-
    burn tripwire latches per TURN (cur['burn_soft_fired']). Henry's answer to
    a turn-burn is a `steer`, and a steer-while-running is interrupt-and-
    replace - a NEW turn on the same bloated session, which re-crosses the
    threshold within minutes and re-emits (measured 18:57 + 19:03 for one
    card). _to_henry's open-dedup cannot see it: Henry had already closed the
    first. The signal that a re-emit is noise is the decision itself."""
    now = time.time()
    for r in records():
        if r.get("event") != "decision":
            continue
        rid = r.get("id") or ""
        if not rid.startswith(kind + "-") or (r.get("card") or "") != (card or ""):
            continue
        try:                     # _append stamps LOCAL time -> mktime, not timegm
            t = time.mktime(time.strptime(r.get("ts") or "", "%Y-%m-%dT%H:%M:%S"))
        except Exception:
            continue
        if now - t <= within_s:
            return True
    return False


def list_all(limit=50):
    """Newest-first full view for the UI/route."""
    rows = sorted(fold().values(), key=lambda e: e.get("ts") or "", reverse=True)
    return rows[:limit]
