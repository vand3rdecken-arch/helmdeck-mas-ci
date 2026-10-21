# -*- coding: utf-8 -*-
"""Headless test: duplicate_titles + the suggestion cooldown (goal_check struck)
(ops/docs/backlog/pm-lean-advisor/README.md phases 2-3, 2026-09-04).

Under test:
  1. goal_check is GONE (2026-09-13): the title-only check re-proposed shipped
     work as missing; Henry sees the whole board and answers that himself.
  2. duplicate_titles() is PURE CODE (zero _ask calls) and only pairs cards
     whose titles are a genuine near-duplicate (the same Jaccard machinery
     _same_question already pins), never two cards that merely share a topic.

Self-sandboxing: pm's loopstate goes to a temp dir, sessions.list_tracks is
stubbed with fixture cards, _ask is a scripted double - no daemon, no board,
no network, no model."""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp()

from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "test.db")   # loopstate lives in the db since state-into-db
db.init()

from cells.copilot.planning import pm
from cells.copilot.planning import pm_state

PLANS = os.path.join(SANDBOX, "pm")
pm.PLANS = PLANS
pm_state.PLANS = PLANS
pm_state.LOOPSTATE = os.path.join(PLANS, "loop.json")
os.makedirs(PLANS, exist_ok=True)

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


GOAL = "Play-Store-Launch der App"
TRACKS = [
    {"id": "c1", "task": "Play-Store-Release-Karte", "lane": "working", "archived": False},
    {"id": "c2", "task": "Play-Store-Release-Karte 2", "lane": "backlog", "archived": False},  # near-dup of c1
    {"id": "c3", "task": "Voice-Modus stabilisieren", "lane": "backlog", "archived": False},
    {"id": "c4", "task": "Archivierte Altlast", "lane": "backlog", "archived": True},           # must be ignored
    {"id": "c5", "task": "Fertige Sache", "lane": "done", "archived": False},                   # must be ignored
]

from cells.engineer.cards import sessions
sessions.list_tracks = lambda: [dict(t) for t in TRACKS]

seen_prompts = []
seen_models = []


def fake_ask(prompt, model=""):
    seen_prompts.append(prompt)
    seen_models.append(model)
    return {"fits": ["Play-Store-Release-Karte"], "missing": ["E2E-Smoke vor Release einrichten"]}


pm._ask = fake_ask

asked = []
pm._ask_owner = lambda text, options, header="", card=None, title="", context="": asked.append(
    {"text": text, "options": options, "header": header, "card": card, "context": context}) or True


print("\n[1] goal_check is GONE (struck 2026-09-13): Henry answers 'was fehlt' himself")
check(not hasattr(pm, "goal_check"), "no goal_check in pm")
check(not hasattr(pm, "goal_check_async"), "no goal_check_async in pm")
from cells.copilot.chat import copilot_actions as _ca
src = open(_ca.__file__, encoding="utf-8").read()
check('"goal_check"' not in src, "no goal_check chat action")
check(not asked, "nothing asked the owner so far")
import time as _time

print("\n[3] duplicate_titles: pure code, near-duplicate titles pair up, real ones don't")
# duplicate_titles adds NO _ask call of its own - that's what this assertion
# is actually about.
before = len(seen_prompts)
pm.duplicate_titles()
check(len(seen_prompts) == before, "duplicate_titles made NO _ask calls at all (%d before, %d after)"
      % (before, len(seen_prompts)))
pairs = pm.duplicate_titles()
ids = sorted(tuple(sorted([a["id"], b["id"]])) for a, b in pairs)
check(ids == [("c1", "c2")], "only the genuine near-duplicate pair is found (%r)" % (ids,))
check(not any(("c3" in p) for p in ids), "a merely-related title (Voice-Modus) is NOT flagged")

print("\n[3b] one template, different named apps: NOT a duplicate; a re-filed twin still is")
_T = ("Neue Atlassian-Forge-Einzelapp '%s' (Jira) als eigener Ordner direkt neben den "
      "bestehenden Apps. Vorlagen fuer Struktur und Stand: jira-label-doktor, "
      "confluence-lesenachweis, jsm-ticket-merge im selben Verzeichnis, Forge-Manifest, Tests.")
check(not pm._same_card(_T % "Vorgangs-Historie als Bericht", _T % "Delegierte Projektanlage"),
      "two different quoted app names off one template are not flagged")
check(pm._same_card(_T % "Delegierte Projektanlage", _T % "Delegierte Projektanlage"),
      "the same app filed twice still is")
_F = "Projekt X, Ordner C:/Users/u/Documents/Private Project/%s. Listing-Entwurf docs/listing.md DE und EN, Preis, Fragebogen."
check(not pm._same_card(_F % "jsm-ticket-merge", _F % "confluence-seiten-review"),
      "different project folders are not flagged")
check(pm._same_card(_F % "jsm-ticket-merge", _F % "jsm-ticket-merge"), "same folder twice still is")

print("\n[3c] one plan step filed for three apps (2026-10-21): other folder / other process = not a twin")
_S = "HUMAN STEP (tracked only): Vergleich und Preis (Owner-Ja)\n\nTabelle gleich / besser / fehlt gegen die Konkurrenz."
_a = {"id": "s1", "task": _S, "repo": "C:/P/space-kopie", "process": "p1"}
check(pm._owns_apart(_a, dict(_a, id="s2", repo="C:/P/jsm-ticket-merge", process="p2")), "different app folders")
check(pm._owns_apart(_a, dict(_a, id="s2", process="p2")), "same folder, different process")
check(not pm._owns_apart(_a, dict(_a, id="s2")), "same folder + process: the title check decides")
check(not pm._owns_apart({"id": "x"}, dict(_a)), "a card owning nothing is not vetoed")

print("\n[3d] a tapped answer to a PM question carries the question's context to Henry")
from cells.copilot.routes import routes_copilot
from cells.copilot.chat import copilot as _cp
from spine.ops import ask as _ask_mod
_q, _ = _ask_mod.parse('<helmdeck-ask>{"questions":[{"question":"Zusammenlegen?","header":"Dup",'
                       '"options":["Zusammenlegen","Beide behalten"]}]}</helmdeck-ask>')
_q["context"] = "Gemeint: Karten s1 und s2."
_orig_oq = _cp.open_question
_cp.open_question = lambda u: _q
try:
    _txt, _err, _ = routes_copilot._answer_text({"name": "o"}, _q.get("id") or "", {"Dup": "Zusammenlegen"})
finally:
    _cp.open_question = _orig_oq
check(not _err and _txt.startswith("Zusammenlegen") and "s1 und s2" in _txt and "Zusammenlegen?" in _txt,
      "answer = label + question + context (%r %r)" % (_txt, _err))

print("\n[4] duplicate_check_async asks once per pair, then cools down")
pm.duplicate_check_async()
for _ in range(20):
    if asked:
        break
    _time.sleep(0.05)
check(len(asked) == 1, "asked exactly once for the c1/c2 pair")
check(asked[0]["options"] == ["Zusammenlegen", "Beide behalten"], "the options answer the question asked")
check("c1" in asked[0]["context"] and "c2" in asked[0]["context"],
      "Henry gets WHICH cards the tapped answer is about")
asked.clear()
pm.duplicate_check_async()
for _ in range(20):
    _time.sleep(0.05)
check(not asked, "the SAME pair is not re-asked inside the cooldown window")

print("\n%s (%d failure(s))" % ("FAILED" if _fails else "PASS", len(_fails)))
sys.exit(1 if _fails else 0)
