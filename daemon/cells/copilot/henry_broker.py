# -*- coding: utf-8 -*-
"""Henry's judgement half of the escalation channel (owner decree 2026-08-21,
backlog/henry-exception-broker; cell placement corrected same day on owner
pushback: "respect the cell structure - communication between cells").

The split across the architecture:
  spine/registry/escalations.py - the CHANNEL. Append-only log + fold. Any
      cell may emit; nothing there judges. Same standing as events.jsonl.
  engineer cell                 - EMITS (aborted-by-restart, conflict-
      unresolved, deploy-red). Reports facts, never decides.
  THIS module (copilot cell)    - Henry CONSUMES. Full-context judgement via
      the same headless-claude seam the board chat uses, bounded verbs, the
      2-attempt RESOLVE cap, audit note per decision. Starts with the
      copilot cell, stops with it (copilotEnabled off = no broker).

Policy is DATA: settings.json `henry_policy` overrides DEFAULT_POLICY -
changing Henry's behaviour is editing prose, never shipping Python.
"""
import json
import os
import re
import subprocess
import threading
import time

from daemon.paths import DAEMON_ROOT as ROOT
from daemon.spine.registry import escalations

_MAX_ATTEMPTS = 2
_INTERVAL_S = 90

DEFAULT_POLICY = (
    "Du bist Henry, die einzige Instanz mit vollem Systemkontext ueber dem "
    "HelmDeck-Board. Du hast HAENDE (owner decree 2026-08-21): du darfst in "
    "diesem Turn selbst Dateien lesen/aendern und Kommandos ausfuehren, um das "
    "Problem DIREKT zu beheben - melde dann action \"did\" mit dem, was du "
    "getan hast. Delegiere nur, wenn die Reparatur echte Feature-Arbeit ist.\n"
    "Entscheide die Eskalation mit gesundem Urteil:\n"
    "- Bevorzuge WARTEN/WIEDERANLAUF vor Toeten; toete nie Arbeit, die noch "
    "lebt und Fortschritt macht.\n"
    "- Ein durch Daemon-Neustart abgebrochener DEPLOY/SHIP wird neu "
    "angestossen (rerun_deploy), ausser derselbe Stand wurde inzwischen "
    "ohnehin geshippt.\n"
    "- Ein ungeloester Konflikt: entscheide die Seite, wenn die Historie sie "
    "klar macht (steer mit konkreter Anweisung welche Seite gewinnt); sonst "
    "notify_owner mit EINER konkreten Frage.\n"
    "- Roter Deploy-Hook nach Kappe: notify_owner mit dem Fehlerkern, kein "
    "weiterer Blindversuch.\n"
    "- Wecke den Owner nur, wenn keine sichere Selbsthilfe existiert."
)


def _ask(prompt, model=""):
    """Headless one-shot judgement call - same spawn shape as the board
    copilot/PM (drivers._cmd_line, never a bare .cmd with quoted args).

    Runs in a WORKING permission mode, not plan (owner decree 2026-08-21:
    "Henry should start in normal mode... do stuff directly"): Henry may fix
    the exception himself in this turn - hands like a direct/machine card, on
    the live tree, cwd repo root. The bounded-verb JSON stays as the CLOSING
    report, not the only channel. Override via settings `henry_permission_mode`."""
    from daemon.cells.copilot import copilot
    from daemon.spine.agent import drivers
    from daemon.spine.storage import events
    pmode = (events.settings().get("henry_permission_mode") or "").strip() or "acceptEdits"
    argv = [copilot.CLAUDE, "-p", "--output-format", "json", "--permission-mode", pmode]
    if model:
        argv += ["--model", model]
    p = subprocess.Popen(drivers._cmd_line(argv), cwd=os.path.dirname(ROOT),
                         stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, encoding="utf-8", errors="replace")
    try:
        # 300s judged fine; a turn that ACTS (build retry, file fix) needs room.
        stdout, stderr = p.communicate(input=prompt, timeout=900)
    except subprocess.TimeoutExpired:
        p.kill()          # a timed-out judgement must not linger as a zombie
        p.communicate()
        raise
    if not (stdout or "").strip():
        raise RuntimeError("henry: no model output: " + (stderr or "").strip()[:200])
    txt = json.loads(stdout).get("result", "")
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        raise RuntimeError("henry: no JSON in reply: " + txt.strip()[:150])
    return json.loads(m.group(0))


def _snapshot():
    """One screenful of system truth - derived live at read time, never a
    stored flag (the no-monkey-patch law)."""
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
    lines.append(_ship_lock_line())
    lines.append(_heavy_procs_line())
    return "\n".join(lines[:40])


def _ship_lock_line():
    pid = _ship_lock_pid()
    if pid is None:
        return "ship.lock: frei"
    return "ship.lock: pid %s (%s)" % (pid, "LIVE" if _pid_alive(pid) else "dead/stale")


def _ship_lock_pid():
    lock = os.path.join(os.path.dirname(ROOT), ".loop", "ship.lock", "pid")
    try:
        return open(lock).read().strip()
    except OSError:
        return None


def _pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def _heavy_procs_line():
    """Box-load proxy without psutil/powershell (absent from this box's PATH):
    count the classic build hogs via tasklist. Coarse on purpose - Henry needs
    'a build is running', not percentages."""
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV"], capture_output=True,
                             text=True, timeout=15).stdout.lower()
        counts = {n: out.count('"%s"' % n) for n in
                  ("java.exe", "node.exe", "qemu-system-x86_64.exe", "clang++.exe")}
        busy = ", ".join("%s x%d" % (k, v) for k, v in counts.items() if v)
        return "build-prozesse: " + (busy or "keine")
    except Exception:
        return "build-prozesse: (nicht lesbar)"


def check_stale_ship_lock():
    """Boot check: a ship.lock whose pid is DEAD means a deploy died with the
    previous daemon (exactly the 04:19 incident - the APK build vanished and
    nobody knew). Report it; whether to re-run is Henry's call."""
    pid = _ship_lock_pid()
    if pid is not None and not _pid_alive(pid):
        escalations.emit("ship-aborted", card=None,
                         detail="ship.lock pid %s ist tot - ein Deploy starb mit dem "
                                "vorigen Daemon; Tree-Stand ggf. ungeshippt." % pid)


def _card_log_tail(card, n=35):
    """The card's own recent history (gate/merge/deploy notes, steers, hook
    output) - read live from its actionlog. Henry's first conflict decision
    (2026-08-21 05:15) had to answer 'kein Kontext (Diff/Historie) verfuegbar'
    because the prompt carried only the board snapshot: full-context judgement
    was judging blind on the one card it was about."""
    if not card:
        return ""
    try:
        from daemon.spine.storage.trackstore import _load, _find
        t = _find(_load(), card)
        if not t:
            return ""
        path = os.path.join(t["run_dir"], "actions.jsonl")
        with open(path, encoding="utf-8") as f:
            recs = [json.loads(x) for x in f.read().splitlines()[-n:] if x.strip()]
        return "\n".join("%s %s: %s" % (r.get("ts", "?"), r.get("kind", "?"),
                                        str(r.get("detail", ""))[:220]) for r in recs)
    except Exception as e:
        return "(actionlog unreadable: %s)" % e


def _decide(esc):
    """One judgement round. Returns True if the escalation was closed."""
    from daemon.spine.storage import events
    policy = (events.settings().get("henry_policy") or "").strip() or DEFAULT_POLICY
    escalations.record_attempt(esc["id"])
    card_log = _card_log_tail(esc.get("card"))
    prompt = (
        policy
        + "\n\n== ESKALATION ==\nkind: %s\ncard: %s\ndetail:\n%s\n" % (
            esc["kind"], esc.get("card") or "-", esc.get("detail") or "")
        + ("\n== KARTE (actionlog, juengste zuerst unten) ==\n" + card_log + "\n" if card_log else "")
        + "\n== SYSTEM ==\n" + _snapshot()
        + "\n\nDu darfst vor der Antwort selbst handeln (Dateien, Kommandos). "
          "Antworte am ENDE NUR mit diesem JSON:\n"
          '{"action": "did|rerun_deploy|steer|notify_owner|ignore",\n'
          ' "card": "karten-id oder leer",\n'
          ' "text": "bei did: was du getan hast; sonst steer-anweisung bzw. owner-nachricht",\n'
          ' "why": "ein satz begruendung"}')
    try:
        d = _ask(prompt)
    except Exception as e:
        escalations.record_note(esc["id"], "ask failed: %s" % str(e)[:200])
        return False
    action = (d.get("action") or "").strip()
    card = (d.get("card") or esc.get("card") or "").strip()
    text = (d.get("text") or "").strip()
    why = (d.get("why") or "").strip()
    if not _execute(action, card, text, esc):
        return False   # malformed verb - stays open for the next attempt
    escalations.record_decision(esc["id"], action, card=card, why=why)
    _audit(card, "HENRY entschieden (%s): %s - %s" % (
        esc["kind"], action,
        (text[:200] + (" | " + why if why else "")) if action == "did" else (why or text[:120])))
    return True


def _execute(action, card, text, esc):
    from daemon.spine.storage.trackstore import _load, _find
    t = _find(_load(), card) if card else None
    if action == "ignore":
        return True
    if action == "did":
        # Henry already acted with his own hands inside the judgement turn
        # (owner decree 2026-08-21) - the work is done, this verb just closes
        # the escalation; `text` (what he did) lands in the audit note.
        return True
    if action == "steer" and t and text:
        from daemon.cells.engineer import sessions
        threading.Thread(target=sessions.steer, args=(t["id"], text),
                         kwargs={"actor": "henry", "source": "henry-escalation"},
                         daemon=True).start()
        return True
    if action == "rerun_deploy":
        from daemon.cells.engineer.lanemachine import _repo_hook
        if t is None:
            # card-less ship abort: rebuild the hook target from the default
            # repo - the hook only needs repo/run_dir-shaped fields.
            from daemon.spine.storage import events
            repo = events.settings().get("default_repo") or ""
            if not repo:
                return False
            t = {"id": "-", "repo": repo, "run_dir": os.path.join(ROOT, "recordings", "_henry"),
                 "worktree": repo}
            os.makedirs(t["run_dir"], exist_ok=True)
        threading.Thread(target=_repo_hook, args=(dict(t), "deploy"), daemon=True).start()
        return True
    if action == "notify_owner":
        _notify_owner("Henry (%s): %s" % (esc["kind"], text or (esc.get("detail") or "")[:200]), t)
        return True
    return False


def _give_up(esc):
    escalations.record_decision(esc["id"], "escalated",
                                why="no safe automatic decision after %d attempts" % _MAX_ATTEMPTS)
    _notify_owner("Henry gibt ab (%s): %s" % (esc["kind"], (esc.get("detail") or "")[:200]), None)


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
        from daemon.spine.registry import i18n as _i18n
        notify.push_fcm(_i18n.t("push.henry"), text[:230])
    except Exception:
        pass
    if t:
        _audit(t["id"], text)


def _loop():
    while True:
        try:
            for esc in escalations.list_open():
                if esc["attempts"] >= _MAX_ATTEMPTS:
                    _give_up(esc)
                    continue
                _decide(esc)
        except Exception as e:
            # never die, but never be SILENT either - an invisible broken broker
            # is exactly the class of failure Henry exists to end.
            print("henry: loop error:", str(e)[:200])
        time.sleep(_INTERVAL_S)


_started = False


def start_broker():
    """Copilot cell lifecycle hook (cells.py start=). Idempotent."""
    global _started
    if _started:
        return
    _started = True
    check_stale_ship_lock()
    threading.Thread(target=_loop, daemon=True).start()
