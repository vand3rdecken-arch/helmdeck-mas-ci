# -*- coding: utf-8 -*-
"""Self-sandboxing test for the connectors/_state.json -> db.py
connector_state table migration. Mirrors test_processes_db_migration.py.

Scope note (see daemon/debt.py order 32): only the last-run STATE dict
(connectors/_state.json) moves into db.py. The connector CODE files
(connectors/<name>.py) and their version backups (connectors/_versions/*.py)
stay on disk on purpose - connectors.install_from_worktree/_load/_run_sandboxed
treat CDIR as a directory of real importable python modules run in a
sandboxed SEPARATE process (connectors._run_sandboxed spawns sys.executable
against CDIR), not JSON records; there is no "data TEXT" row shape that fits
an executable module without breaking that isolation. This test therefore
ALSO sandboxes connectors.CDIR/VDIR to a temp dir (not just db.ROOT) so that
list_connectors()/run_connector() calls in this test can never touch the real
daemon/connectors/ directory - the same class of leak the processes.json
incident caught, just via a different global.

Run: py -3.12 test_connectors_db_migration.py
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


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-conndb-test-")

    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from spine.storage import events
    events.EV = os.path.join(tmp, "events.jsonl")
    events.SET = os.path.join(tmp, "settings.json")

    # sandbox connectors.py's own directory globals too - CDIR/VDIR are NOT
    # under db.ROOT's umbrella, they are module-level paths computed at import
    # time from connectors.py's own __file__.
    from cells.engineer import connectors
    cdir = os.path.join(tmp, "connectors")
    vdir = os.path.join(cdir, "_versions")
    os.makedirs(vdir, exist_ok=True)
    connectors.CDIR = cdir
    connectors.VDIR = vdir

    # a SYNTHETIC legacy connectors/_state.json - never touches the real one.
    legacy = {"hn-top": "2026-01-01 00:00:01", "rss-demo": "2026-01-02 00:00:02"}
    legacy_path = os.path.join(tmp, "connectors", "_state.json")
    with open(legacy_path, "w", encoding="utf-8") as f:
        json.dump(legacy, f)

    # db._migrate() reads connectors/_state.json relative to db.ROOT (=tmp),
    # which matches where we just wrote the synthetic file.
    db.init(role="tool")

    ok(not os.path.exists(legacy_path), "_state.json renamed away after migration")
    ok(os.path.exists(legacy_path + ".imported"), "_state.json.imported now exists (nothing lost)")

    st = connectors._state()
    ok(st == legacy, "migrated state dict round-trips exactly")

    # -- a fresh write goes straight to the db, not back to a file -----------
    st["new-conn"] = "2026-01-03 00:00:03"
    connectors._save_state(st)
    ok(not os.path.exists(legacy_path), "_save_state never recreates the flat file")
    st2 = connectors._state()
    ok(st2.get("new-conn") == "2026-01-03 00:00:03", "fresh state persisted through db")

    # -- a second init() (simulating a daemon restart) is a no-op -----------
    db.init(role="tool")
    ok(connectors._state() == st2, "re-running init() does not duplicate or lose connector state")

    # -- list_connectors() only touches the sandboxed CDIR, never the real one
    got = connectors.list_connectors()
    ok(got == [], "empty sandboxed CDIR yields no connectors (real ones never leaked in)")

    print(("\n%d FAILURE(S)" % len(_fails)) if _fails else "\nALL PASS")
    sys.exit(1 if _fails else 0)


if __name__ == "__main__":
    main()
