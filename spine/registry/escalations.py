# -*- coding: utf-8 -*-
"""Escalation CHANNEL between cells (owner decree 2026-08-21, backlog/
henry-exception-broker; placement corrected on owner pushback: "respect the
cell structure - communication between cells"). This module is the shared
BUS only, same standing as events.jsonl:

  any cell  -> emit(kind, card, detail)          report a fact, never decide
  copilot   -> cells/copilot/henry_broker.py     Henry judges + acts

Append-only JSONL (audit law): open/attempt/note/decision records are
appended; current state is FOLDED from the file at read time - never a
mutated flag. No judgement, no threads, no policy in here."""
import json
import os
import threading
import time

from daemon.paths import DAEMON_ROOT as ROOT

ESC_PATH = os.path.join(ROOT, "escalations.jsonl")
_LOCK = threading.Lock()


def _append(rec):
    rec = dict(rec, ts=time.strftime("%Y-%m-%dT%H:%M:%S"))
    with _LOCK:
        with open(ESC_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
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


def fold():
    """Current state, derived from the append-only log: {id: rec} with
    rec['attempts'] and rec['closed'] folded in."""
    out = {}
    try:
        with open(ESC_PATH, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                ev = r.get("event")
                if ev == "open":
                    out[r["id"]] = dict(r, attempts=0, closed=False)
                elif r.get("id") in out:
                    e = out[r["id"]]
                    if ev == "attempt":
                        e["attempts"] += 1
                    elif ev == "decision":
                        e["closed"] = True
                        e["action"] = r.get("action")
                        e["why"] = r.get("why")
    except OSError:
        pass
    return out


def list_open():
    return [e for e in fold().values() if not e["closed"]]


def list_all(limit=50):
    """Newest-first full view for the UI/route."""
    rows = sorted(fold().values(), key=lambda e: e.get("ts") or "", reverse=True)
    return rows[:limit]
