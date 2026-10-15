# -*- coding: utf-8 -*-
"""The boot sweep must touch only the cards that have something to settle.

Measured 2026-10-15 with py-spy on a real restart: ~45 of the daemon's ~60 boot
seconds went into sessions.sweep_zombies. Its background-task branch fired for
every card that HAS a bg_tasks dict - and finished tasks stay there as 'canceled'
history on purpose, so that was 595 of 729 cards - and then `_mutate`'d each one
with a function that returned None (= "save") even when nothing changed. Every
card was rewritten at every boot (all 595 `updated` stamps sat in the two minutes
of the last restart), and every write invalidated the card cache, so the next
read re-parsed all 729 cards.

Pinned, against the real sweep:
  1. a card with only FINISHED task history is not written and keeps its `updated`;
  2. a card with a descriptor still "running" and no live session IS reconciled
     (the descriptor ends 'canceled', the card is handed back);
  3. a card gated on waiting_on=background with nothing running is handed back to
     the owner;
  4. the number of card WRITES equals the number of cards that needed one.

Run: py -3.12 ops/tests/test_boot_sweep_cost.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

SANDBOX = tempfile.mkdtemp()
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")           # never the live db
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from cells.engineer.cards import sessions

_fails = []
OLD = "2026-07-28 22:00:00"


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def card(tid, status="needs_you", **extra):
    run_dir = os.path.join(SANDBOX, tid)
    os.makedirs(run_dir, exist_ok=True)
    t = {"id": tid, "status": status, "lane": "working", "task": "t", "branch": tid,
         "run_dir": run_dir, "turns": 1, "updated": OLD}
    t.update(extra)
    return t


HISTORY = {"b1": {"status": "canceled", "title": "an old build", "result": "daemon restart"},
           "b2": {"status": "done", "title": "a finished task"}}

N_HISTORY = 120
for i in range(N_HISTORY):
    db.track_put(card("h-%03d" % i, bg_tasks={k: dict(v) for k, v in HISTORY.items()}))
db.track_put(card("zz-running", bg_tasks={"r1": {"status": "running", "title": "a build that died with the daemon"}},
                  waiting_on="background"))
db.track_put(card("zz-gated", bg_tasks={"b1": dict(HISTORY["b1"])}, waiting_on="background"))
db.track_put(card("zz-plain"))                                # never had a background task

writes = []
_orig_put = db.track_put


def counting_put(t, *a, **k):
    writes.append(t["id"])
    return _orig_put(t, *a, **k)


db.track_put = counting_put
try:
    sessions.sweep_zombies()                                   # min_idle_s=0: the boot sweep
finally:
    db.track_put = _orig_put

untouched = [t for t in db.tracks_all() if t["id"].startswith("h-")]
check(len(untouched) == N_HISTORY and all(t["updated"] == OLD for t in untouched),
      "%d cards with only finished task history keep their `updated` stamp" % N_HISTORY)
check(not [w for w in writes if w.startswith("h-")] and "zz-plain" not in writes,
      "...and are not written at all")

r = db.track_get("zz-running")
check(r["bg_tasks"]["r1"]["status"] == "canceled", "a descriptor still 'running' with no live session is reconciled to 'canceled'")
check(r.get("waiting_on") == "you", "...and the card is handed back to the owner")
g = db.track_get("zz-gated")
check(g.get("waiting_on") == "you", "a card gated on waiting_on=background with nothing running is handed back")

check(sorted(set(writes)) == ["zz-gated", "zz-running"],
      "the sweep WROTE exactly the cards that needed it (%s), not the other %d" % (sorted(set(writes)), N_HISTORY + 1))

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails))
    sys.exit(1)
print("boot-sweep-cost: all pinned - PASS")
