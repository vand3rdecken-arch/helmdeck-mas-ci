# -*- coding: utf-8 -*-
"""Headless test: goal_check + duplicate_titles + the suggestion cooldown
(ops/docs/backlog/pm-lean-advisor/README.md phases 2-3, 2026-09-04).

Under test:
  1. goal_check() runs ONE cheap-model turn (never brief()'s auto/strong tier)
     with the goal + ACTIVE card TITLES ONLY - no card body, no full snapshot.
  2. goal_check runs ON REQUEST only (chat action, 2026-09-13) - no automatic
     nagger after a goal edit / clarify_goal exists any more.
  3. duplicate_titles() is PURE CODE (zero _ask calls) and only pairs cards
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
pm._ask_owner = lambda text, options, header="", card=None, title="": asked.append(
    {"text": text, "options": options, "header": header, "card": card}) or True


print("\n[1] goal_check: one cheap turn, titles only, no full snapshot")
r = pm.goal_check(GOAL)
check(len(seen_prompts) == 1, "exactly one _ask call")
check(seen_models[0] in ("claude-haiku-4-5",), "resolved to the CHEAP model, not auto/strong (%r)" % seen_models[0])
check(GOAL in seen_prompts[0], "prompt carries the goal")
check("Play-Store-Release-Karte" in seen_prompts[0], "prompt carries an ACTIVE card title")
check("Archivierte Altlast" not in seen_prompts[0], "archived cards are NOT in the prompt")
check("Fertige Sache" not in seen_prompts[0], "done cards are NOT in the prompt")
check(r.get("missing") == ["E2E-Smoke vor Release einrichten"], "missing list comes back")

print("\n[2] goal_check is ON REQUEST only (2026-09-13): no async nagger exists any more")
check(not hasattr(pm, "goal_check_async"), "goal_check_async is gone - the owner asks, Henry answers")
check(not asked, "goal_check itself never asks the owner (no _ask_owner call)")
import time as _time
from cells.copilot.chat import copilot_actions as _ca
src = open(_ca.__file__, encoding="utf-8").read()
check('if kind == "goal_check":' in src, "chat action goal_check exists for the on-request path")
check("goal_check_async" not in src, "clarify_goal no longer chains an automatic goal check")

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

print("\n[4] duplicate_check_async asks once per pair, then cools down")
pm.duplicate_check_async()
for _ in range(20):
    if asked:
        break
    _time.sleep(0.05)
check(len(asked) == 1, "asked exactly once for the c1/c2 pair")
check(asked[0]["options"] == ["Anzeigen", "Ignorieren"], "the duplicate-flow options are present")
asked.clear()
pm.duplicate_check_async()
for _ in range(20):
    _time.sleep(0.05)
check(not asked, "the SAME pair is not re-asked inside the cooldown window")

print("\n%s (%d failure(s))" % ("FAILED" if _fails else "PASS", len(_fails)))
sys.exit(1 if _fails else 0)
