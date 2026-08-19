# -*- coding: utf-8 -*-
"""Self-sandboxing test for the processes.json -> db.py processes table
migration. Verifies the SAME import-and-rename-to-.imported mechanism db.py
already uses for tracks.json/events.jsonl (db._migrate), applied to a
SYNTHETIC processes.json in a temp dir - never the real daemon/processes.json.

This is the regression test that should have existed before routes_misc.py's
/processes routes were smoke-tested: a prior test run (and a debug script)
wrote fake entries into the REAL processes.json because processes.py used its
own flat-file storage, untouched by the db.ROOT/db.DBPATH sandbox other tests
rely on. Recovered by hand (removed the 3 fake entries, verified real data
intact) and by this migration: processes.py now delegates to db.py, so it is
sandboxed by the SAME db.ROOT patch every other test already uses.

Run: py -3.12 test_processes_db_migration.py
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


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-procdb-test-")

    from daemon.spine import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    # processes.create()/sync() call events.emit() directly - events.py has its
    # OWN independent ROOT/EV globals, never covered by db.ROOT (measured the
    # hard way: an earlier run of this exact test appended real lines to the
    # production events.jsonl before this sandbox line existed).
    from daemon.spine import events
    events.EV = os.path.join(tmp, "events.jsonl")
    events.SET = os.path.join(tmp, "settings.json")

    # a SYNTHETIC legacy processes.json, shaped like the real one but with
    # obviously-fake content - never touches daemon/processes.json.
    legacy = [
        {"id": "20260101-000001-proc", "request": "synthetic legacy process one",
         "client": "", "due": "", "status": "ready", "steps": [], "cost": 0.0,
         "created": "2026-01-01 00:00:01", "actor": "test"},
        {"id": "20260101-000002-proc", "request": "synthetic legacy process two",
         "client": "acme", "due": "", "status": "proposing", "steps": [], "cost": 0.0,
         "created": "2026-01-01 00:00:02", "actor": "test"},
    ]
    legacy_path = os.path.join(tmp, "processes.json")
    with open(legacy_path, "w", encoding="utf-8") as f:
        json.dump(legacy, f)

    db.init(role="tool")

    # -- migration ran: imported into the db, legacy file renamed ------------
    ok(not os.path.exists(legacy_path), "processes.json renamed away after migration")
    ok(os.path.exists(legacy_path + ".imported"), "processes.json.imported now exists (nothing lost)")

    from daemon.cells.process import processes
    got = processes.list_processes()
    ok(len(got) == 2, "both synthetic legacy processes migrated into the db")
    ids = {p["id"] for p in got}
    ok(ids == {"20260101-000001-proc", "20260101-000002-proc"},
       "migrated ids match exactly")
    got2 = {p["id"]: p for p in got}
    ok(got2["20260101-000002-proc"]["client"] == "acme",
       "migrated process content preserved (client field round-trips)")

    # -- ordering: newest-first, same as the old insert(0, ...) contract -----
    p3 = processes.create("a third, freshly-created process", actor="test")
    ok(bool(p3.get("id")), "create() returns a process with an id")
    after = processes.list_processes()
    ok(len(after) == 3, "create() persisted through the db-backed _save()")
    ok(after[0]["id"] == p3["id"], "newest process sorts first (id DESC == chronological)")

    # -- a second init() (simulating a daemon restart) is a no-op on the -----
    # already-migrated data, not a re-import or a duplicate.
    db.init(role="tool")
    ok(len(processes.list_processes()) == 3, "re-running init() does not duplicate or lose data")

    # -- get() by id still works through the new backing store ---------------
    fetched = processes.get(p3["id"])
    ok(fetched is not None and fetched["id"] == p3["id"], "processes.get(id) resolves through db")

    print(("\n%d FAILURE(S)" % len(_fails)) if _fails else "\nALL PASS")
    sys.exit(1 if _fails else 0)


if __name__ == "__main__":
    main()
