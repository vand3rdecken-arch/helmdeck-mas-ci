# -*- coding: utf-8 -*-
"""Sandboxed daemon for JUDGING the Phase 2 UI (CLAUDE.md: UI changes must be
screenshotted and judged, not just confirmed to render).

Boots the real daemon on :8199 against a throwaway sandbox and seeds the card
states this branch adds:

  c-question  - a worker's typed question: ONE question, 4 options with
                descriptions (the common case, and the longest text)
  c-multi     - two questions, the second multi-select (the wizard + checkboxes)
  c-short     - a two-option yes/no style question (the compact case)
  c-bg        - parked on a BACKGROUND task, not on the owner (the new cue)
  c-needsyou  - the ordinary "waiting for you" cue, as a visual control

Prints TOKEN=<device token> for the Playwright driver. Never touches the
owner's real files. Ctrl-C to stop.

STOP THIS BEFORE RUNNING ops/tools/run_gate.py: while it listens on :8199,
test_machine_task.py resolves card references against THIS live board.
"""
import os, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.join(os.path.dirname(os.path.dirname(HERE)), "daemon")
sys.path.insert(0, DAEMON)

SANDBOX = os.environ.get("HELMDECK_UI_SANDBOX") or tempfile.mkdtemp(prefix="helmdeck-q-")
os.makedirs(SANDBOX, exist_ok=True)

import auth, db, events

auth.USERS = os.path.join(SANDBOX, "users.json")
auth.SESS = os.path.join(SANDBOX, "sessions.json")
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
db._LEGACY_DB = os.path.join(SANDBOX, "legacy.db")
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")

import copilot, sessions, server

copilot.CHATLOG = os.path.join(SANDBOX, "copilot_log.json")
copilot.SESS = os.path.join(SANDBOX, "copilot_sessions.json")
db.init()

auth.create_user("owner1", "test-pw-12345", "owner")
TOKEN = auth.issue_token("owner1", "ui-judge")

RUN = os.path.join(SANDBOX, "run")
os.makedirs(RUN, exist_ok=True)


def card(tid, task, **kw):
    t = {"id": tid, "repo": SANDBOX, "branch": "b-" + tid, "worktree": SANDBOX,
         "task": task, "description": "", "client": "", "session_id": "s-" + tid,
         "perm": "acceptEdits", "lane": "working", "status": "needs_you", "turns": 4,
         "run_dir": RUN, "last_reply": "", "value": 100.0, "driver": "claude",
         "priority": "high", "due": "", "rank": None, "model": "", "attachments": [],
         "project_id": None, "billing": "fixed", "rate": None, "ai_cost": 1.25,
         "tokens_in": 1200, "tokens_out": 800, "models": ["claude-opus-5"],
         "mode": "auto", "created": time.strftime("%Y-%m-%d %H:%M:%S"),
         "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
    t.update(kw)
    sessions._save_track(t)
    return t


def q(qid, questions):
    return {"id": qid, "kind": "question", "asked": "2026-08-07 09:00:00",
            "ta": time.time(), "questions": questions}


# The real shape, taken verbatim from a live worker turn (ops/tests/e2e_question_live.py)
card("c-question",
     "Login-Maske bauen",
     last_reply="Bevor ich baue, brauche ich eine Produktentscheidung von dir. "
                "Meine Empfehlung waere E-Mail + Passwort, weil der Daemon lokal "
                "laeuft und ein Magic-Link zwingend Mail-Versand braucht.",
     question=q("q-1", [{
         "question": "Wie soll die Anmeldung in der Login-Maske laufen: per "
                     "E-Mail + Passwort, per Magic-Link, oder beides?",
         "header": "Auth-Verfahren", "multiSelect": False, "idx": 0,
         "options": [
             {"label": "E-Mail + Passwort",
              "description": "Klassischer Login; braucht Passwort-Hashing und einen Reset-Flow. Funktioniert ohne Mail-Infrastruktur."},
             {"label": "Magic-Link",
              "description": "Passwortloser Login per E-Mail-Link; braucht zwingend zuverlaessigen Mail-Versand."},
             {"label": "Beides",
              "description": "Passwort-Login plus Magic-Link als Alternative; hoechste Flexibilitaet, meiste Arbeit."},
             {"label": "Erst Passwort, Link spaeter",
              "description": "Jetzt E-Mail + Passwort umsetzen, Magic-Link als spaeteren Ausbau vormerken."},
         ]}]))

card("c-multi", "Release-Pipeline aufsetzen",
     last_reply="Zwei Dinge muss ich von dir wissen, bevor die Pipeline steht.",
     question=q("q-2", [
         {"question": "Auf welchen Kanal soll der Release standardmaessig gehen?",
          "header": "Kanal", "multiSelect": False, "idx": 0,
          "options": [
              {"label": "Internal", "description": "Nur das Testteam, sofort verfuegbar."},
              {"label": "Closed Beta", "description": "Eingeladene Tester, Review dauert ~1 Tag."},
              {"label": "Production", "description": "Alle Nutzer; Rollout in Stufen."}]},
         {"question": "Welche Checks sollen den Release blockieren?",
          "header": "Blocker", "multiSelect": True, "idx": 1,
          "options": [
              {"label": "Unit-Tests", "description": "Schnell, laufen in ~2 min."},
              {"label": "E2E auf dem Emulator", "description": "Langsam (~12 min), faengt Integrationsfehler."},
              {"label": "Lint + Typen", "description": "Sekunden; verhindert Trivialfehler."},
              {"label": "Manuelle Abnahme", "description": "Du schaust drauf, bevor es rausgeht."}]},
     ]))

card("c-short", "Datenbank migrieren",
     last_reply="Kurze Rueckfrage, dann laufe ich durch.",
     question=q("q-3", [{
         "question": "Soll ich die alte Tabelle nach der Migration loeschen?",
         "header": "Alte Tabelle", "multiSelect": False, "idx": 0,
         "options": [
             {"label": "Loeschen", "description": "Sauber, aber nicht umkehrbar."},
             {"label": "Behalten", "description": "Kostet Platz, laesst sich zurueckrollen."}]}]))

# the NEW cue: parked on its own background task, not on the owner
card("c-bg", "Signiertes Release-AAB bauen",
     last_reply="Der Gradle-Build laeuft im Hintergrund, ich melde mich mit dem Ergebnis.",
     waiting_on="background",
     background={"n": 1, "names": ["Build signed release AAB with gradle bundleRelease"],
                 "since": time.time() - 240})

# visual control: the ordinary "your move" cue
card("c-needsyou", "Debt-Register aufraeumen",
     waiting_on="you",
     last_reply="DELIVERED - Register ist wohlgeformt. Ready for Review.")

print("SANDBOX=" + SANDBOX)
print("TOKEN=" + str(TOKEN))
sys.stdout.flush()

threading.Thread(target=lambda: server.serve(8199), daemon=True).start()
while True:
    time.sleep(1)
