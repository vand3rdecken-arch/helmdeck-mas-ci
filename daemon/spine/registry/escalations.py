# -*- coding: utf-8 -*-
"""Henry exception broker - the full-context judgement layer (owner decree
2026-08-21, backlog/henry-exception-broker, memory helmdeck-henry-exception-
broker). The dual architecture: card workers stay context-poor; anything
DISCRETIONARY escalates HERE instead of growing a judgement branch in hook
code ("sonst hast du tausende Regeln"). Code keeps only hard invariants.

Mechanism, kept thin:
  emit(kind, card, detail)   - harness points report, they never decide.
  broker loop                - folds open escalations, hands each to Henry
                               (the same headless-claude seam pm._ask uses)
                               together with a SYSTEM SNAPSHOT, executes his
                               bounded verb, writes an audit note on the card.
  policy                     - prose in settings.json (henry_policy), NOT
                               code: changing behaviour = editing data.
  bound                      - 2 decision attempts per escalation (the PM
                               RESOLVE ladder's shape), then notify owner +
                               close as 'escalated'.

Storage is an append-only JSONL (audit law): open/attempt/decision records
are appended, current state is FOLDED from the file - never a mutated flag.
"""
import json
import os
import threading
import time

from daemon.paths import DAEMON_ROOT as ROOT

ESC_PATH = os.path.join(ROOT, "escalations.jsonl")
_LOCK = threading.Lock()
_MAX_ATTEMPTS = 2
_INTERVAL_S = 90

DEFAULT_POLICY = (
    "Du bist Henry, die einzige Instanz mit vollem Systemkontext ueber dem "
    "HelmDeck-Board. Entscheide die Eskalation mit gesundem Urteil:\n"
    "- Bevorzuge WARTEN/WIEDERANLAUF vor Toeten; toete nie Arbeit, die noch "
    "lebt und Fortschritt macht.\n"
    "- Ein durch Daemon-Neustart abgebrochener DEPLOY wird neu angestossen "
    "(rerun_deploy), ausser derselbe Stand wurde inzwischen ohnehin geshippt.\n"
    "- Ein ungeloester Konflikt: entscheide die Seite, wenn die Historie sie "
    "klar macht (steer mit konkreter Anweisung welche Seite gewinnt); sonst "
    "notify_owner mit EINER konkreten Frage.\n"
    "- Roter Deploy-Hook nach Kappe: notify_owner mit dem Fehlerkern, kein "
    "weiterer Blindversuch.\n"
    "- Wecke den Owner nur, wenn keine sichere Selbsthilfe existiert."
)


def _append(rec):
    rec = dict(rec, ts=time.strftime("%Y-%m-%dT%H:%M:%S"))
    with _LOCK:
        with open(ESC_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def emit(kind, card=None, detail=""):
    """Harness reporting seam: record the exception, note it on the card,
    NEVER decide anything here."""
    eid = "%s-%d" % (kind, int(time.time() * 1000))
    _append({"event": "open", "id": eid, "kind": kind, "card": card,
             "detail": str(detail)[:1500]})
    try:
        from daemon.spine.storage import events
        events.emit("escalation", card or "-", kind=kind, esc=eid)
    except Exception:
        pass
    if card:
        try:
            from daemon.spine.storage.trackstore import _load, _find
            from daemon.spine.ops.actionlog import ActionLog
            t = _find(_load(), card)
            if t:
                ActionLog(t["run_dir"]).log(
                    "note", "ESKALATION an Henry (%s): %s" % (kind, str(detail)[:200]))
        except Exception:
            pass
    return eid


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


def _snapshot():
    """One screenful of system truth for Henry - derived live, never stored."""
    lines = []
    try:
        from daemon.spine.storage.trackstore import _load
        from daemon.spine.agent import drivers
        for t in _load():
            if t.get("archived") or t.get("lane") == "done":
                continue
            lines.append("card %s | %s/%s | ft=%s direct=%s turn_active=%s | %s" % (
                t["id"], t.get("lane"), t.get("status"), bool(t.get("fast_track")),
                bool(t.get("direct")), drivers.turn_active(t["id"]),
                (t.get("task") or "")[:60]))
    except Exception as e:
        lines.append("(board unreadable: %s)" % e)
    lock = os.path.join(os.path.dirname(ROOT), ".loop", "ship.lock", "pid")
    try:
        pid = open(lock).read().strip()
        alive = False
        try:
            os.kill(int(pid), 0)
            alive = True
        except (OSError, ValueError):
            pass
        lines.append("ship.lock: pid %s (%s)" % (pid, "LIVE" if alive else "dead/stale"))
    except OSError:
        lines.append("ship.lock: frei")
    return "\n".join(lines[:40])


def _decide(esc):
    """One Henry decision round for one escalation. Returns True if closed."""
    from daemon.cells.pm import pm
    from daemon.spine.storage import events
    policy = (events.settings().get("henry_policy") or "").strip() or DEFAULT_POLICY
    _append({"event": "attempt", "id": esc["id"]})
    prompt = (
        policy
        + "\n\n== ESKALATION ==\nkind: %s\ncard: %s\ndetail:\n%s\n" % (
            esc["kind"], esc.get("card") or "-", esc.get("detail") or "")
        + "\n== SYSTEM ==\n" + _snapshot()
        + "\n\nAntworte NUR mit diesem JSON:\n"
          '{"action": "rerun_deploy|steer|notify_owner|ignore",\n'
          ' "card": "karten-id oder leer",\n'
          ' "text": "steer-anweisung bzw. owner-nachricht",\n'
          ' "why": "ein satz begruendung"}')
    try:
        d = pm._ask(prompt)
    except Exception as e:
        _append({"event": "note", "id": esc["id"], "detail": "ask failed: %s" % str(e)[:200]})
        return False
    action = (d.get("action") or "").strip()
    card = (d.get("card") or esc.get("card") or "").strip()
    text = (d.get("text") or "").strip()
    why = (d.get("why") or "").strip()
    ok = _execute(action, card, text, esc)
    if ok:
        _append({"event": "decision", "id": esc["id"], "action": action,
                 "card": card, "why": why})
        _audit(card, "HENRY entschieden (%s): %s - %s" % (esc["kind"], action, why or text[:120]))
    return ok


def _execute(action, card, text, esc):
    from daemon.spine.storage.trackstore import _load, _find
    t = _find(_load(), card) if card else None
    if action == "ignore":
        return True
    if action == "steer" and t and text:
        from daemon.cells.engineer import sessions
        threading.Thread(target=sessions.steer, args=(t["id"], text),
                         kwargs={"actor": "henry", "source": "henry-escalation"},
                         daemon=True).start()
        return True
    if action == "rerun_deploy" and t:
        from daemon.cells.engineer.lanemachine import _repo_hook
        threading.Thread(target=_repo_hook, args=(dict(t), "deploy"), daemon=True).start()
        return True
    if action == "notify_owner":
        _notify_owner("Henry (%s): %s" % (esc["kind"], text or esc.get("detail", "")[:200]), t)
        return True
    return False   # malformed decision - stays open for the next attempt


def _give_up(esc):
    _append({"event": "decision", "id": esc["id"], "action": "escalated",
             "why": "no safe automatic decision after %d attempts" % _MAX_ATTEMPTS})
    _notify_owner("Henry gibt ab (%s): %s" % (esc["kind"], (esc.get("detail") or "")[:200]),
                  None)


def _audit(card, note):
    if not card:
        return
    try:
        from daemon.spine.storage.trackstore import _load, _find
        from daemon.spine.ops.actionlog import ActionLog
        t = _find(_load(), card)
        if t:
            ActionLog(t["run_dir"]).log("note", note)
    except Exception:
        pass


def _notify_owner(text, t):
    try:
        from daemon.spine.comms import notify
        notify.push_fcm("Henry", text[:230])
    except Exception:
        pass
    if t:
        _audit(t["id"], text)


def _loop():
    while True:
        try:
            for esc in list_open():
                if esc["attempts"] >= _MAX_ATTEMPTS:
                    _give_up(esc)
                    continue
                _decide(esc)
        except Exception:
            pass
        time.sleep(_INTERVAL_S)


_started = False


def start_broker():
    """Idempotent; called from the engineer cell's start alongside the zombie
    reconciler."""
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True).start()
