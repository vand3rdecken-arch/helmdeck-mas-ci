# -*- coding: utf-8 -*-
"""Sandboxed daemon for JUDGING the lane-visibility UI (CLAUDE.md: UI changes
must be screenshotted and judged, not just confirmed to render).

Boots the real daemon on :8199 - the app's web default baseUrl - against a
throwaway sandbox with its OWN users.json/settings.json/helmdeck.db, and seeds
cards in exactly the states this branch changed:

  gating   - the new "Gate läuft…" pulse + subline (status published before the
             slow work, so the board is no longer frozen during an accept)
  bounced  - a red gate that STAYS on Review, carrying gate_report
  backlog  - a PM epic card whose description is the new PMP template
             (user story / done_when / why_now / steps)
  running  - unchanged, as a visual control
  review   - submitted + review_report, the merge preview

Prints TOKEN=<device token> so the Playwright driver can authenticate in
direct mode. Never touches the owner's real files. Ctrl-C to stop.

STOP THIS BEFORE RUNNING tools/run_gate.py: while it is listening on :8199,
test_machine_task.py resolves card references against THIS live board and fails
with "'machine' passt auf 2 Karten". The gate is green once it is stopped.
"""
import json, os, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.join(os.path.dirname(HERE), "daemon")
sys.path.insert(0, DAEMON)

SANDBOX = os.environ.get("HELMDECK_UI_SANDBOX") or tempfile.mkdtemp(prefix="helmdeck-ui-")
os.makedirs(SANDBOX, exist_ok=True)   # an explicit sandbox path may not exist yet

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

EPIC_DESC = (
    "NUTZERGESCHICHTE\n"
    "Als Owner möchte ich die App im Play Store haben, damit echte Nutzer sie "
    "installieren können.\n\n"
    "FERTIG, WENN\n"
    "- Die App ist im Play Store sichtbar\n"
    "- Ein Testnutzer kann sie installieren und öffnen\n\n"
    "WARUM JETZT\n"
    "Ohne Store-Eintrag kann niemand die App bekommen.\n\n"
    "ENTHÄLT\n"
    "- Play-Console-Eintrag anlegen\n"
    "- Signing-Key einrichten\n"
    "- Store-Listing ausfüllen\n"
    "- Build hochladen"
)


def card(tid, task, lane, status, **kw):
    t = {"id": tid, "repo": SANDBOX, "branch": "b-" + tid, "worktree": SANDBOX,
         "task": task, "description": "", "client": "", "session_id": None,
         "perm": "acceptEdits", "lane": lane, "status": status, "turns": 4,
         "run_dir": RUN, "last_reply": "", "value": 100.0, "driver": "claude",
         "priority": "high", "due": "", "rank": None, "model": "", "attachments": [],
         "project_id": None, "billing": "fixed", "rate": None, "ai_cost": 1.25,
         "tokens_in": 1200, "tokens_out": 800, "models": ["claude-opus-5"],
         "mode": "auto", "created": time.strftime("%Y-%m-%d %H:%M:%S"),
         "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
    t.update(kw)
    sessions._save_track(t)
    return t


# THE state this branch adds: the board used to show nothing at all here.
card("c-gating", "Silent OTA: Kanäle + Rollback-Pfad", "review", "gating")
# a red gate that stays on Review, with the reason on the card
card("c-bounced", "Pay debt: single-secret transport", "review", "bounced",
     gate_report=["gate command failed (py -3.12 tools/run_gate.py):\n"
                  "FAIL test_transport_tls.py\nAssertionError: expected https"],
     gate_failed=True)
# the merge preview verdict
card("c-review", "PM: Epic-Karten statt Ticket-Flut", "review", "submitted",
     merge_kind="mergeable", review_report="sauber mergebar - zum Landen auf Done ziehen")
# a PM epic card carrying the new PMP description template
card("c-epic", "M2: Launch im Play Store", "backlog", "queued",
     description=EPIC_DESC, priority="urgent")
# controls
card("c-running", "Desktop-Tray: Supervisor + Autostart", "working", "running")
card("c-done", "HelmDeck Rebrand + Apple-Redesign", "done", "accepted")

print("SANDBOX=" + SANDBOX)
print("TOKEN=" + str(TOKEN))
sys.stdout.flush()

threading.Thread(target=lambda: server.serve(8199), daemon=True).start()
while True:
    time.sleep(1)
