# -*- coding: utf-8 -*-
"""Self-sandboxing regression test for the events.jsonl RE-import bug (A4).

The bug: db._migrate() imported events.jsonl on EVERY db.init(), with a plain
`INSERT` and no key to dedupe on. events.emit() recreates that file constantly
(it appends there AND write-through inserts the same row), so every boot
re-imported the whole previous session. Counts over `events` grew without any
new events happening - which is why the dashboard's cost figures read high.
Second bug in the same lines: os.replace(p, p + ".imported") overwrote the
archive from the previous boot, breaking db.py's own "originals preserved"
promise from the second boot onward.

What this pins down:
  1. first start with a legacy file still imports it (migration still works)
  2. a SECOND init() does not re-import - the table only grows by real emits
  3. the legacy archive from boot 1 survives boot 2
  4. events.jsonl is NOT retired once the table is populated: it is the durable
     append-only record, not a leftover
  5. _archive() never eats an existing archive

Sandbox: db.ROOT/db.DBPATH AND events.EV/events.SET are redirected to a temp
dir. events.py keeps its own ROOT globals, never covered by the db.ROOT patch -
an earlier test in this repo appended to the production events.jsonl before
that was understood, so both halves are patched here deliberately.

Run: py -3.12 tests/test_events_no_reimport.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_fails = []
def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)


def count_events(db):
    return db.conn().execute("SELECT count(*) FROM events").fetchone()[0]


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-evreimport-test-")

    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from spine.storage import events
    events.EV = os.path.join(tmp, "events.jsonl")
    events.SET = os.path.join(tmp, "settings.json")

    ej = os.path.join(tmp, "events.jsonl")

    # --- a SYNTHETIC legacy events.jsonl, never the real one ----------------
    with open(ej, "w", encoding="utf-8") as f:
        for i in range(3):
            f.write(json.dumps({"ts": "2026-01-0%d 10:00:00" % (i + 1),
                                "kind": "legacy", "track": "t-old",
                                "note": "line %d" % i}) + "\n")

    print("boot 1 - first start, legacy file present")
    db.init()
    ok(count_events(db) == 3, "3 legacy events imported (got %d)" % count_events(db))
    ok(os.path.exists(ej + ".imported"), "legacy file archived as .imported")
    ok(not os.path.exists(ej), "legacy file no longer at its original name")

    print("operation - two real events, the way the daemon emits them")
    events.emit("gate", "t-new", ok=True)
    events.emit("done", "t-new", mode="clean")
    ok(count_events(db) == 5, "table at 5 after 2 emits (got %d)" % count_events(db))
    ok(os.path.exists(ej), "emit recreated events.jsonl - this is what came back")

    print("boot 2 - the restart that used to duplicate everything")
    db.init()
    ok(count_events(db) == 5,
       "STILL 5 after restart, no re-import (got %d)" % count_events(db))
    ok(os.path.exists(ej + ".imported"), "boot-1 archive survived boot 2")
    with open(ej + ".imported", encoding="utf-8") as f:
        archived = [l for l in f if l.strip()]
    ok(len(archived) == 3 and "legacy" in archived[0],
       "boot-1 archive still holds the ORIGINAL 3 legacy lines")
    ok(os.path.exists(ej),
       "events.jsonl left in place - durable record, not a leftover to retire")

    print("boot 3 - a third restart must be just as quiet")
    db.init()
    ok(count_events(db) == 5, "still 5 after a third start (got %d)" % count_events(db))

    print("_archive - never eats an existing archive")
    victim = os.path.join(tmp, "processes.json")
    with open(victim, "w", encoding="utf-8") as f:
        f.write("[]")
    first = db._archive(victim)
    with open(victim, "w", encoding="utf-8") as f:
        f.write("[]")
    second = db._archive(victim)
    ok(first != second, "second archive got a distinct name (%s vs %s)"
       % (os.path.basename(first), os.path.basename(second)))
    ok(os.path.exists(first) and os.path.exists(second), "both archives on disk")

    print()
    if _fails:
        print("FAILED (%d):" % len(_fails))
        for m in _fails:
            print("  - " + m)
        return 1
    print("all green - %s" % tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
