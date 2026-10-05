# -*- coding: utf-8 -*-
"""A thread's `at` (last activity) must come from the card's own events.

Owner report 2026-10-05: the Henry list showed ~20 threads under "Today", all "2h".
Cause: a card with no conversation line was dated by `updated`, and `updated` is the
row's write stamp - a bulk write at 09:41 touched 342 of 420 cards, so every old
finished card looked like it had just happened.

Pinned through the real /chat/threads builder on a sandbox db:
 1. a FINISHED card with no chat line is dated by its turn end, not by `updated`
 2. without a turn end it falls back to its creation, still not `updated`
 3. a LIVE card (running) keeps `updated` - it is really being written
Run: py -3.12 ops/tests/test_thread_activity_time.py
"""
import os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
SANDBOX = tempfile.mkdtemp(prefix="hd-threadtime-")
from spine.storage import db
db.ROOT = SANDBOX   # BOTH, not just DBPATH - see test_hook_idle.py's preamble
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()
from cells.copilot.chat import threads

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


def epoch(s):
    return time.mktime(time.strptime(s, "%Y-%m-%d %H:%M:%S"))


BULK = "2026-10-05 09:41:26"          # the backfill stamp every card carries
base = {"repo": SANDBOX, "title": "x", "task": "x", "updated": BULK}
db.track_put({**base, "id": "20260803-aaaa", "lane": "done", "status": "accepted",
              "created": "2026-10-03 20:35:43", "turn_ended": "2026-10-03 20:44:12"})
db.track_put({**base, "id": "20260803-bbbb", "lane": "done", "status": "accepted",
              "created": "2026-08-13 08:55:00"})
db.track_put({**base, "id": "20260803-cccc", "lane": "working", "status": "running",
              "created": "2026-10-05 08:00:00", "updated": "2026-10-05 12:36:58"})

rows = {r["id"]: r for r in threads.threads("tien")["threads"]}
print("thread activity time")
check(set(rows) >= {"20260803-aaaa", "20260803-bbbb", "20260803-cccc"}, "setup: all three cards are listed")
check(rows["20260803-aaaa"]["at"] == epoch("2026-10-03 20:44:12"),
      "finished card is dated by its turn end, not the bulk `updated`")
check(rows["20260803-bbbb"]["at"] == epoch("2026-08-13 08:55:00"),
      "finished card without a turn end is dated by its creation")
check(rows["20260803-cccc"]["at"] == epoch("2026-10-05 12:36:58"),
      "a live card keeps `updated`")
check(rows["20260803-aaaa"]["at"] != epoch(BULK), "no finished card carries the bulk stamp")

print("\nFAILED: %s" % _fails if _fails else "\nall ok")
sys.exit(1 if _fails else 0)
