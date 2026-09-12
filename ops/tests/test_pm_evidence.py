# -*- coding: utf-8 -*-
"""Headless test: planner-with-hands (fetch-as-needed) + question discipline
(2026-09-12, owner: "it should fetch as needed, and be intelligent").

Root cause it pins: the PM plan of 2026-09-12 asked whether a Google-Play
developer account exists while eight FINISHED cards, a live card and a memory
note documented the submission - because brief() inlined only the live board,
gave the turn no tools, and let an unchecked question block the Scope gate.

Under test (the REAL brief() prompt-assembly path, _ask stubbed at the
process boundary - no daemon, no model):
  1. brief() runs the planner WITH HANDS: the role rides as the system prompt
     (stable prefix), the turn carries the memory INDEX + the EVIDENCE TOOLS
     block + the hidden-history count, and _ask is called with hands=True.
     (Fails on the old code: no `system`, no hands, no tools in the prompt.)
  2. board_state.find_cards / henry_memory_get.find_notes find a finished
     card / a note by content words - archived and done included, titles
     alone not required (the Play-Store lesson).
  3. _dispose_questions keeps a question ONLY with a non-empty `checked`
     trail; a bare string or empty trail is dropped and reported.
  4. _stale_question_guard hands a question repeated in 3 consecutive plans
     to Henry once (escalation kind pm-question-stale), never removes it.
  5. The steer fold skips daemon hand-backs so clarifications stay owner
     ground truth (sessions.steer, actor="daemon").

Self-sandboxing: pm's plan dir + loopstate go to a temp dir; sessions.list_tracks,
_snapshot, economics/quota and the memory digest are stubbed."""
import json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "ops", "tools"))

SANDBOX = tempfile.mkdtemp()

from cells.copilot.planning import pm, pm_state, pm_comm
from cells.copilot.chat import copilot, copilot_memory
from cells.engineer.cards import sessions
import board_state, henry_memory_get

# plans, loop state and the activity feed are db rows (state-into-db phase
# D): sandbox the store
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "test.db")
db.init()

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


TRACKS = [
    {"id": "20260831-071411-machine", "task": "Play Console: Produktionsrelease einreichen",
     "lane": "done", "status": "accepted", "archived": False, "created": "2026-08-31",
     "updated": "2026-09-01", "outcome": "Alle drei Schritte ausgefuehrt, Einreichung laeuft.",
     "last_reply": "Eingereicht. Konto projectkaiser, 4 Aenderungen zur Ueberpruefung gesendet."},
    {"id": "20260826-212403-machine", "task": "Chrome: Internal-Testing-Status pruefen",
     "lane": "done", "status": "accepted", "archived": True, "created": "2026-08-26",
     "updated": "2026-08-27", "outcome": "Antrag raus", "last_reply": "Produktionszugriff beantragt."},
    {"id": "20260912-063252-machine", "task": "Status-Check Play Console", "lane": "working",
     "status": "needs_you", "archived": False, "created": "2026-09-12", "updated": "2026-09-12",
     "last_reply": "Wird ueberprueft"},
    {"id": "ex", "task": "Example card", "lane": "backlog", "example": True, "archived": False,
     "last_reply": "play konto example"},
]
sessions.list_tracks = lambda: [dict(t) for t in TRACKS]
copilot._snapshot = lambda full=False: "CARDS: (live slice)"
pm.economics = lambda: {"turns_to_date": 10, "cost_per_turn": 1.0}
pm._quota_signal = lambda: {"plan": "max"}
pm._system_state = lambda: "USERS: 1"
copilot_memory.digest = lambda: "\n\nDEIN GEDAECHTNIS (Index):\nplaystore-produktionszugriff-genehmigt - granted"

seen = []


def fake_ask(prompt, model="", system="", hands=False, timeout=300):
    seen.append({"prompt": prompt, "system": system, "hands": hands, "model": model})
    return {"summary": "s", "done_pct": 50, "milestones": [], "next": [], "risks": [],
            "open_questions": [
                {"question": "Zaehlt gelauncht erst mit dem Produktionsrelease?",
                 "checked": "memory find gelauncht: offen laut helmdeck-launch-planung"},
                "Hat der Owner ein Google Play Developer-Konto?",
                {"question": "Ohne Trail", "checked": ""}],
            "_meta": {"num_turns": 4, "usage": {"input_tokens": 12}, "cost_usd": 0.1}}


pm._ask = fake_ask
henry_calls = []
pm._to_henry = lambda kind, detail, card=None, feed="": henry_calls.append((kind, detail)) or "e1"

print("1. brief() runs the planner with hands, role as system, tools + index in the turn")
out = pm.brief(goal="HelmDeck launchen")
check(len(seen) == 1, "exactly one planner turn")
call = seen[0]
check(call["hands"] is True, "_ask called with hands=True (permission default + pm.json allowlist)")
check("PM / CTO role" in call["system"] or "PM/CTO" in call["system"], "role rides as the SYSTEM prompt")
check("PM / CTO role" not in call["prompt"], "role is NOT duplicated in the turn text")
check("EVIDENCE TOOLS" in call["prompt"] and "board_state.py --find" in call["prompt"]
      and "henry_memory_get.py find" in call["prompt"], "turn carries the evidence tools block")
check("DEIN GEDAECHTNIS" in call["prompt"], "turn carries the memory INDEX (progressive disclosure)")
check("2 finished/archived cards" in call["prompt"], "turn states the measured hidden-history count")
check("GOAL:\nHelmDeck launchen" in call["prompt"], "goal + volatile facts stay in the turn")

print("2. question discipline: only questions with a checked trail survive")
check(out["open_questions"] == ["Zaehlt gelauncht erst mit dem Produktionsrelease?"],
      "bare-string and empty-trail questions dropped: %r" % out["open_questions"])
check(set(out["dropped_questions"]) == {"Hat der Owner ein Google Play Developer-Konto?", "Ohne Trail"},
      "dropped questions stay visible in the artifact")
check(out["question_evidence"].get("Zaehlt gelauncht erst mit dem Produktionsrelease?", "").startswith("memory find"),
      "the kept question carries its evidence trail")
check(out["evidence"].get("num_turns") == 4 and "_meta" not in out,
      "CLI accounting lands under `evidence`, _meta stripped")
check(out["triage"]["scope"] == "blocked", "a checked question still blocks Scope (decree kept)")
act = " ".join(a["msg"] for a in pm_comm._read_activity(50))
check("ohne Belegsuche verworfen" in act, "dropping is reported in the activity feed")

print("3. evidence tools find by content, done + archived included, examples excluded")
hits = board_state.find_cards(["play", "konto"], TRACKS)
check([h["id"] for h in hits] == ["20260831-071411-machine"],
      "--find matches ALL terms across task+reply, skips the example card: %r" % [h["id"] for h in hits])
hits = board_state.find_cards(["produktionszugriff"], TRACKS)
check(hits and hits[0]["archived"], "archived history is searchable")
txt = board_state.format_hit(hits[0])
check("ARCHIVED" in txt and "last_reply=" in txt, "hit shows archived flag + reply")
notes = {"MEMORY": {"content": "index"},
         "helmdeck-launch-planung": {"content": "KEIN festes Zieldatum", "updated_at": "2026-09-11"},
         "other": {"content": "nothing", "updated_at": "2026-09-01"}}
found = henry_memory_get.find_notes(notes, ["zieldatum"])
check([n for n, _ in found] == ["helmdeck-launch-planung"], "memory find matches content, skips the index")

print("4. a question repeated in 3 consecutive plans is handed to Henry once, never removed")
# step 1 wrote today's artifact - the guard runs BEFORE the write in brief(),
# so clear the plans table and seed three consecutive days (pm_plans rows)
with db.conn() as _c:
    _c.execute("DELETE FROM pm_plans")
for d in ("20260909", "20260910", "20260911"):
    db.pm_plan_put(d, {"open_questions": ["Wie viel vom Wochenkontingent soll das Launch-Ziel bekommen?"]})
qs = ["Wie viel vom Wochenkontingent soll das Launch-Ziel bekommen?"]
pm._stale_question_guard(qs, None)
check(len(henry_calls) == 1 and henry_calls[0][0] == "pm-question-stale",
      "stale question escalated to Henry as pm-question-stale")
check(qs == ["Wie viel vom Wochenkontingent soll das Launch-Ziel bekommen?"], "the question itself stays in the plan")
henry_calls.clear()
pm._stale_question_guard(["Ganz neue Frage?"], None)
check(not henry_calls, "a fresh question is not escalated")

print("5. steer fold ignores daemon hand-backs")
src = open(os.path.join(ROOT, "cells", "engineer", "cards", "sessions.py"), encoding="utf-8").read()
check('actor != "daemon"' in src and 'startswith("[[")' in src,
      "sessions.steer folds a clarification only for non-daemon, non-sentinel answers")

print("\n%s" % ("ALL OK" if not _fails else "FAILED: %d" % len(_fails)))
sys.exit(1 if _fails else 0)
