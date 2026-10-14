# -*- coding: utf-8 -*-
"""The inbox must not hold every card's history in RAM (measured 2026-10-14:
the daemon's timeline fold cache grew to ~430 MB, 186k steps, because
threads() folded each listed card's WHOLE timeline just to read its last
conversation line).

Pins three things, each against the REAL path:
  1. db.timeline_last_line returns exactly what the old fold + _last_line did
     (tool rows ignored, later patches folded, empty text skipped).
  2. threads()'s per-card read leaves timeline_store's cache EMPTY.
  3. timeline_store's cache is LRU-bounded.

Run: py -3.12 ops/tests/test_timeline_memory.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

SANDBOX = tempfile.mkdtemp()
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")      # never the live db
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from spine.agent import timeline_store
from cells.copilot.chat import threads

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _put(run, sid, **patch):
    db.timeline_append(run, sid, patch)


def _old_way(run):
    """What threads() did before: fold the whole run, take the last line."""
    order, folded = [], {}
    for _seq, sid, rec in db.timeline_since(run, 0):
        if sid not in folded:
            order.append(sid)
            folded[sid] = {}
        folded[sid].update(rec)
    return threads._last_line([folded[s] for s in order])


def test_matches_the_old_fold():
    run = "r-main"
    _put(run, "a", kind="text", byKind="human", text="first question", ta=1.0)
    _put(run, "b", kind="tool", name="Bash", ta=2.0)
    _put(run, "c", kind="text", byKind="henry", text="the answer", ta=3.0)
    _put(run, "d", kind="tool", name="Read", ta=4.0)                 # newer, but a tool row
    _put(run, "e", kind="text", byKind="worker", text="worker chatter", ta=5.0)
    _put(run, "c", result="later patch on the same step")            # folds into c
    got, want = db.timeline_last_line(run), _old_way(run)
    check(got is not None and got["text"] == "the answer", "newest HUMAN/HENRY prose wins over newer tool/worker rows")
    check(got == want, "identical to the old whole-timeline fold")
    check(got.get("result") == "later patch on the same step", "a later patch on that step is folded in")

    _put(run, "f", kind="note", byKind="human", text="   ", ta=6.0)   # blank: not a line
    check(db.timeline_last_line(run) == _old_way(run), "a blank line does not count, same as before")

    check(db.timeline_last_line("r-none") is None, "a run with no conversation has none")
    _put("r-tools", "x", kind="tool", name="Bash", ta=1.0)
    check(db.timeline_last_line("r-tools") is None, "tool-only run has none")


def test_memo_follows_writes():
    run = "r-memo"
    _put(run, "a", kind="text", byKind="human", text="one", ta=1.0)
    check(db.timeline_last_line(run)["text"] == "one", "first read")
    _put(run, "b", kind="text", byKind="henry", text="two", ta=2.0)
    check(db.timeline_last_line(run)["text"] == "two", "a write is seen at once - the memo is keyed on the table's own max(seq)")
    got = db.timeline_last_line(run)
    got["text"] = "mutated by a caller"
    check(db.timeline_last_line(run)["text"] == "two", "callers get a copy, not the memo itself")


def test_listing_does_not_fill_the_fold_cache():
    for i in range(60):
        _put("r-card-%d" % i, "a", kind="text", byKind="human", text="hi %d" % i, ta=float(i))
    timeline_store._cache.clear()
    for i in range(60):
        db.timeline_last_line("r-card-%d" % i)
    check(len(timeline_store._cache) == 0, "reading 60 cards' last line folds NONE of them into the cache")


def test_fold_cache_is_bounded():
    timeline_store._cache.clear()
    for i in range(60):
        run_dir = os.path.join(SANDBOX, "r-card-%d" % i)
        timeline_store.read(run_dir)
    check(len(timeline_store._cache) == timeline_store.CACHE_MAX,
          "60 runs read -> cache holds only the %d most recent" % timeline_store.CACHE_MAX)
    check("r-card-59" in timeline_store._cache and "r-card-0" not in timeline_store._cache,
          "the oldest fell out, the newest stayed")
    steps = timeline_store.read(os.path.join(SANDBOX, "r-card-0"))
    check(len(steps) == 1 and steps[0]["text"] == "hi 0", "an evicted run simply re-folds on its next read")


def test_connections_use_the_small_page_cache():
    """One connection per thread: the default 2000 KiB cache x ~70 threads was
    ~140 MB of the daemon. Checked on a NEW thread's connection, the way the
    daemon's request/relay workers get theirs."""
    import threading
    out = {}

    def w():
        out["kib"] = db.conn().execute("PRAGMA cache_size").fetchone()[0]
    th = threading.Thread(target=w)
    th.start()
    th.join()
    check(out.get("kib") == -db.CACHE_KIB, "a thread's connection gets the %d KiB page cache" % db.CACHE_KIB)
    check(db.CACHE_KIB >= 512, "never below 512 KiB: 256 KiB measured slower on hot reads")


if __name__ == "__main__":
    test_connections_use_the_small_page_cache()
    test_matches_the_old_fold()
    test_memo_follows_writes()
    test_listing_does_not_fill_the_fold_cache()
    test_fold_cache_is_bounded()
    print()
    if _fails:
        print("FAILED: %d check(s)" % len(_fails))
        sys.exit(1)
    print("ALL GREEN - the inbox no longer holds card history in memory")
