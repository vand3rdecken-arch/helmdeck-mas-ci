# -*- coding: utf-8 -*-
"""db.events_all reads the append-only event log INCREMENTALLY (measured 2026-10-18: GET /dashboard/data
took 14-29 s on the live daemon because every new event threw the cache away and ~30,000 rows were
re-parsed).

  1. after new events, the result equals a full fresh read (same rows, same order);
  2. only the NEW rows are parsed, not the whole log;
  3. an unchanged log is answered from the cache with no parse at all.

Sandboxed db.  Run: py -3.12 ops/tests/test_events_all_incremental.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from spine.storage import db                                  # noqa: E402

db.DBPATH = os.path.join(tempfile.mkdtemp(prefix="hd-ev-"), "test.db")
db.init()
from spine.storage import events                              # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


class Counting:
    """Stands in for db.json: counts the row parses events_all does."""
    def __init__(self):
        self.n = 0

    def loads(self, s, *a, **k):
        self.n += 1
        return json.loads(s, *a, **k)

    def __getattr__(self, name):
        return getattr(json, name)


def main():
    for i in range(500):
        events.emit("note", "T%d" % (i % 7), msg="m%d" % i)
    first = db.events_all()
    count = Counting()
    real = db.json
    db.json = count
    try:
        for i in range(500, 520):
            events.emit("note", "T%d" % (i % 7), msg="m%d" % i)
        inc = db.events_all()
        parsed = count.n
        count.n = 0
        again = db.events_all()
        cached = count.n
    finally:
        db.json = real
    db._events_cache = (None, b"")
    full = db.events_all()
    check([e.get("msg") for e in inc] == [e.get("msg") for e in full] and len(inc) == len(first) + 20,
          "incremental result == a full fresh read (%d rows)" % len(inc))
    check(parsed == 20, "only the 20 NEW rows were parsed, not the log (%d)" % parsed)
    check(cached == 0 and len(again) == len(inc), "an unchanged log is answered from the cache, no parse")
    print()
    if _fails:
        print("=== %d FAILED ===" % len(_fails))
        return 1
    print("events_all incremental: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
