# -*- coding: utf-8 -*-
"""Pin: a card that finishes a turn right AFTER Henry decided on it reaches Henry again.

Root cause (measured 2026-10-08, cards 193748 + 212340): _emit_delivered_parked
skipped the report when Henry had decided the same card < 15 min ago. Henry's
steer / the owner's reopen starts a new turn, that turn IS the answer, and it
was swallowed -> the card sat in working until the owner dragged it. RED on the
old code (decided_recently guard), GREEN without it.

Self-sandboxing: temp db, real escalations module, real _emit_delivered_parked.
Run: py -3.12 ops/tests/test_delivered_after_decision.py
"""
import os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SANDBOX = tempfile.mkdtemp(prefix="hd-deliv-after-dec-")
from spine.storage import db as _db
_db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
_db.init()
from spine.registry import escalations
from cells.engineer.cards import turnrunner

fails = []
def check(name, ok):
    print(("  ok    " if ok else "  FAIL  ") + name)
    if not ok:
        fails.append(name)

card = {"id": "c-after", "lane": "working", "status": "needs_you", "task": "x"}

# 1st delivery -> Henry steers (decision recorded just now)
turnrunner._emit_delivered_parked(card, "needs_you", "done", {})
first = [e for e in escalations.list_open() if e.get("card") == "c-after"]
check("first delivery opens an escalation", len(first) == 1)
escalations.record_decision(first[0]["id"], "steer", card="c-after", why="nachbessern")
check("decision closes it", not [e for e in escalations.list_open() if e.get("card") == "c-after"])

# the steer's turn ends minutes later -> must reach Henry again
turnrunner._emit_delivered_parked(card, "needs_you", "done", {})
again = [e for e in escalations.list_open() if e.get("card") == "c-after"]
check("delivery right after Henry's decision reaches him again", len(again) == 1)

# still deduped while the open one is unjudged
turnrunner._emit_delivered_parked(card, "needs_you", "done", {})
check("an unjudged open report is not doubled",
      len([e for e in escalations.list_open() if e.get("card") == "c-after"]) == 1)

sys.exit(1 if fails else 0)
