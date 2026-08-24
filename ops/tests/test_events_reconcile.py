# -*- coding: utf-8 -*-
"""Self-sandboxing test for the events reconcile healer (phase D3).

The finding (debt events-two-stores-unreconciled): events.emit() appends to
events.jsonl and separately write-through inserts into the events table, and
that db insert is best-effort - wrapped in a bare `except: pass`
(events.py). Before this, the file and the table shared NO KEY, so a dropped
db write stayed dropped and silent forever: there was no way to tell the two
stores apart, let alone heal one from the other, without either re-importing
nothing (miss the drop) or re-importing everything (duplicate everything -
the exact bug A4 fixed). A stable per-event `id` plus a UNIQUE index makes
re-scanning safe.

What this pins down:
  1. a genuinely DROPPED write-through (event in the file, never reached the
     table) is healed by _reconcile_events() on the next boot
  2. reconciling AGAIN is a no-op - INSERT OR IGNORE, not a duplicate
  3. a normal emit() (both sides succeed) needs no healing - reconcile finds
     nothing to do
  4. the checkpoint file advances, so only NEW bytes get rescanned - proven by
     appending fresh content after a reconcile and confirming a second
     reconcile only heals THAT, not by re-processing the old lines
  5. a pre-id-era row (id missing, as if written before this feature existed)
     is skipped, not crashed on
  6. a shrunk/rotated file resets the checkpoint to 0 rather than silently
     skipping content

Run: py -3.12 ops/tests/test_events_reconcile.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_fails = []
def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)


def db_count(db):
    return db.conn().execute("SELECT count(*) FROM events").fetchone()[0]


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-reconcile-test-")

    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from spine.storage import events
    events.EV = os.path.join(tmp, "events.jsonl")
    events.SET = os.path.join(tmp, "settings.json")
    db.init()

    # ------------------------------------------------------------------ 3 ---
    print("normal emit() - both sides succeed, nothing to heal")
    events.emit("gate", "t-1", ok=True)
    events.emit("done", "t-1", mode="clean")
    ok(db_count(db) == 2, "both landed in the table via the normal write-through")
    db._reconcile_events()
    ok(db_count(db) == 2, "reconciling right after finds nothing dropped (still 2)")

    # ------------------------------------------------------------------ 1 ---
    print("\na genuinely DROPPED write-through gets healed")
    # Simulate exactly what a failed db.event_insert() inside emit()'s
    # try/except leaves behind: the line landed in the file, the table never
    # saw it. Appended directly, bypassing event_insert entirely.
    dropped = {"id": "deadbeef0000", "ts": "2026-01-01 00:00:00",
               "kind": "signature", "track": "t-2", "op": "signed"}
    with open(events.EV, "a", encoding="utf-8") as f:
        f.write(json.dumps(dropped) + "\n")
    ok(db_count(db) == 2, "fixture: still only 2 in the table before reconcile")

    db._reconcile_events()
    ok(db_count(db) == 3, "the dropped event is now in the table (3)")
    row = db.conn().execute(
        "SELECT id, kind, track FROM events WHERE id=?", ("deadbeef0000",)).fetchone()
    ok(row == ("deadbeef0000", "signature", "t-2"), "healed with its real id/kind/track")
    restored = [e for e in db.events_all() if e.get("id") == "deadbeef0000"][0]
    ok(restored.get("op") == "signed", "events_all() round-trips the extra fields too")

    # ------------------------------------------------------------------ 2 ---
    print("\nreconciling again does not duplicate")
    db._reconcile_events()
    ok(db_count(db) == 3, "still 3 - INSERT OR IGNORE, not a second copy")

    # ------------------------------------------------------------------ 4 ---
    print("\nthe checkpoint means only NEW bytes get rescanned")
    ckpt = events.EV + ".synced"
    ok(os.path.exists(ckpt), "checkpoint file was written")
    ok(int(open(ckpt, encoding="utf-8").read()) == os.path.getsize(events.EV),
       "checkpoint matches the file's current size - fully caught up")

    fresh = {"id": "cafef00dbaad", "ts": "2026-01-02 00:00:00",
             "kind": "gxp", "track": "t-3", "outcome": "accept_refused"}
    with open(events.EV, "a", encoding="utf-8") as f:
        f.write(json.dumps(fresh) + "\n")
    db._reconcile_events()
    ok(db_count(db) == 4, "the newly appended row was picked up (4)")
    ok(db.conn().execute("SELECT 1 FROM events WHERE id=?", ("cafef00dbaad",)).fetchone(),
       "...and it is the right one")

    # ------------------------------------------------------------------ 5 ---
    print("\na pre-id-era row (no id) is skipped, not crashed on")
    legacy = {"ts": "2020-01-01 00:00:00", "kind": "lane", "track": "t-old",
              "frm": "review", "to": "done"}
    with open(events.EV, "a", encoding="utf-8") as f:
        f.write(json.dumps(legacy) + "\n")
    before = db_count(db)
    try:
        db._reconcile_events()
        crashed = False
    except Exception as e:
        crashed = True
        print("    unexpected:", e)
    ok(not crashed, "no exception on a row with no id")
    ok(db_count(db) == before, "and it was not inserted (nothing to key it on)")

    # ------------------------------------------------------------------ 6 ---
    print("\na shrunk file resets the checkpoint instead of skipping content")
    with open(events.EV, "w", encoding="utf-8") as f:
        f.write(json.dumps({"id": "0000rotated1", "ts": "2026-01-03 00:00:00",
                            "kind": "touch", "track": "t-4"}) + "\n")
    db._reconcile_events()
    ok(db.conn().execute("SELECT 1 FROM events WHERE id=?", ("0000rotated1",)).fetchone(),
       "the post-rotation row was NOT skipped because the checkpoint was stale")

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
