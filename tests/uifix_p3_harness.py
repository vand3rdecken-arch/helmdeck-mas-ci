# -*- coding: utf-8 -*-
"""Sandboxed daemon for JUDGING the P3 transcript model (CLAUDE.md: UI changes
must be screenshotted and judged, not just confirmed to render).

Boots the real daemon on :8199 against a throwaway sandbox and seeds ONE card
whose feed exercises everything this branch changed:

  - all FOUR tool-call states: completed, failed (error!=null), canceled
    (interrupt sentinel), running (no result yet; card status=running)
  - the turn lifecycle as its OWN events: started / completed+usage+cost /
    canceled / failed+error+usage (actionlog kind="turn", woven by `ta`)
  - compaction as a first-class marker (isCompactSummary record)

The session .jsonl is synthetic: claude_sessions.PROJECTS is pointed at the
sandbox so _find_transcript resolves it without touching ~/.claude.

Prints TOKEN=<device token> for the Playwright driver. Ctrl-C to stop.
STOP THIS BEFORE RUNNING tools/run_gate.py (it listens on :8199)."""
import json, os, sys, tempfile, threading, time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.join(os.path.dirname(HERE), "daemon")
sys.path.insert(0, DAEMON)

SANDBOX = os.environ.get("HELMDECK_UI_SANDBOX") or tempfile.mkdtemp(prefix="helmdeck-p3-")
os.makedirs(SANDBOX, exist_ok=True)

import auth, db, events

auth.USERS = os.path.join(SANDBOX, "users.json")
auth.SESS = os.path.join(SANDBOX, "sessions.json")
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
db._LEGACY_DB = os.path.join(SANDBOX, "legacy.db")
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")

import claude_sessions, copilot, sessions, server

claude_sessions.PROJECTS = os.path.join(SANDBOX, "projects")
copilot.CHATLOG = os.path.join(SANDBOX, "copilot_log.json")
copilot.SESS = os.path.join(SANDBOX, "copilot_sessions.json")
db.init()

auth.create_user("owner1", "test-pw-12345", "owner")
TOKEN = auth.issue_token("owner1", "ui-judge")

RUN = os.path.join(SANDBOX, "run")
os.makedirs(RUN, exist_ok=True)
SID = "p3-session-0001"

# --- the synthetic session transcript (the card's agent view) ---------------
BASE = time.time() - 900          # the conversation happened ~15 min ago


def _iso(off):
    return datetime.fromtimestamp(BASE + off, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _rec(off, typ, content):
    return {"type": typ, "timestamp": _iso(off), "cwd": SANDBOX,
            "message": {"role": typ, "content": content}}


def _tool(tid, name, inp):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


def _result(off, tid, text, is_error=False):
    return {"type": "user", "timestamp": _iso(off), "cwd": SANDBOX,
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tid, "is_error": is_error,
                 "content": [{"type": "text", "text": text}]}]}}


records = [
    _rec(0, "user", "Bau das Transcript-Modell um: 4 Tool-Zustände, Turn-Events, Compaction."),
    _rec(4, "assistant", [
        {"type": "thinking", "thinking": "Erst der grüne Pfad, dann die Fehlerfälle."},
        {"type": "text", "text": "Ich fange mit den Tests an und baue dann die vier Zustände durch."},
        _tool("tu-ok", "Bash", {"command": "py -3.12 tools/run_gate.py"}),
    ]),
    _result(48, "tu-ok", "gate: PASS (20 checks)"),
    _rec(52, "assistant", [
        _tool("tu-fail", "Bash", {"command": "npm run bogus-script"}),
    ]),
    _result(55, "tu-fail", "npm ERR! Missing script: \"bogus-script\"\nnpm ERR! To see a list of scripts, run: npm run",
            is_error=True),
    _rec(60, "assistant", [
        {"type": "text", "text": "Der npm-Lauf schlägt fehl - ich korrigiere das Skript und probiere den langen Build."},
        _tool("tu-cancel", "Edit", {"file_path": "app/package.json",
                                    "old_string": "\"bogus-script\"", "new_string": "\"web\""}),
    ]),
    _result(63, "tu-cancel", "[Request interrupted by user for tool use]", is_error=True),
    # the Stop is also recorded as the harness' user message -> typed turn_canceled item
    {"type": "user", "timestamp": _iso(64), "cwd": SANDBOX,
     "message": {"role": "user", "content": "[Request interrupted by user for tool use]"}},
    # context compaction happened here (first-class marker, never the summary text)
    {"type": "user", "timestamp": _iso(120), "cwd": SANDBOX, "isCompactSummary": True,
     "message": {"role": "user", "content": "This session is being continued from a previous conversation..."}},
    _rec(130, "user", "Weiter - starte den Web-Export im Hintergrund."),
    _rec(135, "assistant", [
        {"type": "text", "text": "Export läuft - das dauert ein paar Minuten."},
        _tool("tu-run", "Bash", {"command": "npx expo export --platform web", "run_in_background": False}),
    ]),
    # tu-run has NO result: with the card status=running this is the live
    # "running" state (ticking clock), the fourth of the four.
]

proj = os.path.join(claude_sessions.PROJECTS, "p3-demo")
os.makedirs(proj, exist_ok=True)
with open(os.path.join(proj, SID + ".jsonl"), "w", encoding="utf-8") as f:
    for r in records:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

# --- the turn lifecycle events (daemon knowledge, woven in by ta) -----------
turns = [
    {"kind": "turn", "detail": "Turn gestartet", "event": "started", "off": 1},
    {"kind": "turn", "detail": "Turn abgebrochen", "event": "canceled", "off": 65},
    {"kind": "turn", "detail": "Turn fehlgeschlagen", "event": "failed", "off": 90,
     "error": "claude turn exceeded 1800s - session killed; steer again to resume.",
     "usage": {"input_tokens": 41000, "output_tokens": 380,
               "cache_creation_input_tokens": 2100, "cache_read_input_tokens": 88000},
     "cost": 0.0388},
    {"kind": "turn", "detail": "Turn gestartet", "event": "started", "off": 131},
    {"kind": "turn", "detail": "Turn abgeschlossen", "event": "completed", "off": 210,
     "usage": {"input_tokens": 52400, "output_tokens": 1290,
               "cache_creation_input_tokens": 900, "cache_read_input_tokens": 96000},
     "cost": 0.0421},
]
with open(os.path.join(RUN, "actions.jsonl"), "w", encoding="utf-8") as f:
    for i, r in enumerate(turns):
        off = r.pop("off")
        row = {"i": i, "t": float(off), "ta": BASE + off,
               "ts": time.strftime("%H:%M:%S", time.localtime(BASE + off))}
        row.update(r)
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

# --- the card --------------------------------------------------------------
t = {"id": "c-p3", "repo": SANDBOX, "branch": "paseo-p3-transcript-model",
     "worktree": SANDBOX, "task": "P3: Transcript-Datenmodell aufräumen",
     "description": "", "client": "", "session_id": SID, "perm": "acceptEdits",
     "lane": "working", "status": "running", "turns": 3, "run_dir": RUN,
     "last_reply": "", "value": 200.0, "driver": "claude", "priority": "high",
     "due": "", "rank": None, "model": "", "attachments": [], "project_id": None,
     "billing": "fixed", "rate": None, "ai_cost": 0.081, "tokens_in": 190000,
     "tokens_out": 2400, "models": ["claude-fable-5"], "ctx_tokens": 149000,
     "created": time.strftime("%Y-%m-%d %H:%M:%S"),
     "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
print("SANDBOX=" + SANDBOX)
print("TOKEN=" + str(TOKEN))
sys.stdout.flush()

threading.Thread(target=lambda: server.serve(8199), daemon=True).start()
# Seed AFTER boot: serve()'s db.init(role="daemon") structurally devalues any
# persisted 'running' (exactly what this branch adds) - a pre-seeded running
# card would be reaped before the screenshot. Seeding post-boot puts the card
# inside the live spawn/idle window, which is the honest 'running' state.
time.sleep(3)
sessions._save_track(t)
print("SEEDED c-p3 (running)")
sys.stdout.flush()
# Keep the card inside the live window while it is being judged: the periodic
# reconciler + the read coercion both (rightly) refuse to show 'running' once
# the card sits idle >45s with no turn - freshen the flight recorder's mtime
# so the seeded running state stays visible for the screenshots.
while True:
    time.sleep(20)
    os.utime(os.path.join(RUN, "actions.jsonl"), None)
