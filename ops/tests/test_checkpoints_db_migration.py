# -*- coding: utf-8 -*-
"""Checkpoints snapshot the CONFIG ROWS, not a dead file (state-into-db
phase G, 2026-09-12).

The defect this pins: checkpoints.create() copied daemon/settings.json, which
config-consolidation phase 2 stopped writing on 2026-09-03 - so every
checkpoint since held NO config, and diff()/restore() rolled back nothing
but connectors. The old version of this test hid that by writing a
settings.json into its temp ROOT. Proven to FAIL on the old code: case 2
changes a workspace_config ROW between two checkpoints and expects diff()
to see it - the old code diffed the (absent) file and reported nothing.

The directory shape stays (debt order 32: half of a checkpoint is a copytree
of connectors/ - code, not a record); only the config half reads and writes
its real store.

  1. create() snapshots the live workspace_config + policy_doc into
     <checkpoint>/config.json and copies connectors/
  2. diff() reports a row change between two checkpoints, and against the
     LIVE rows for the newest one
  3. restore() writes the rows back and is itself checkpointed
  4. connectors added/removed are still reported and restored

SANDBOXED: db.DBPATH, checkpoints.CPDIR and checkpoints.ROOT all point into
one temp dir; the test refuses to run otherwise.

Run: py -3.12 ops/tests/test_checkpoints_db_migration.py
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
    tmp = tempfile.mkdtemp(prefix="helmdeck-cpdb-test-")
    from spine.storage import db, events
    db.DBPATH = os.path.join(tmp, "test.db")
    events.SET = os.path.join(tmp, "settings.json")
    db.init()
    from spine.ops import checkpoints
    cpdir = os.path.join(tmp, "checkpoints")
    os.makedirs(cpdir, exist_ok=True)
    checkpoints.CPDIR = cpdir
    checkpoints.ROOT = tmp          # connectors/ derives from ROOT
    assert db.DBPATH.startswith(tmp) and checkpoints.CPDIR.startswith(tmp), "REFUSING TO RUN: not sandboxed"
    conn_dir = os.path.join(tmp, "connectors")
    os.makedirs(conn_dir, exist_ok=True)
    with open(os.path.join(conn_dir, "demo.py"), "w", encoding="utf-8") as f:
        f.write("NAME='demo'\n")

    print("1. create() snapshots the config rows")
    db.workspace_config_replace({"appearance": {"backdrop": "a"}, "policy": {"auto_accept_green": False}})
    cid1 = checkpoints.create(actor="test", reason="synthetic snapshot one")
    ok(bool(cid1), "create() returns a checkpoint id")
    ok(os.path.isdir(os.path.join(cpdir, cid1)), "checkpoint dir landed in sandboxed CPDIR")
    snap = json.load(open(os.path.join(cpdir, cid1, "config.json"), encoding="utf-8"))
    ok(snap["workspace_config"]["appearance"]["backdrop"] == "a", "config.json holds the workspace rows")
    ok("policy_doc" in snap, "…and the policy document")
    ok(os.path.exists(os.path.join(cpdir, cid1, "connectors", "demo.py")), "connectors/ copied")
    lst = checkpoints.list_checkpoints()
    ok(len(lst) == 1 and lst[0]["id"] == cid1, "list_checkpoints() sees it")

    print("2. diff() sees a ROW change")
    db.workspace_config_put({"appearance": {"backdrop": "b"}})
    cid2 = checkpoints.create(actor="test", reason="synthetic snapshot two")
    d = checkpoints.diff(cid1)
    fields = {f["key"]: (f["before"], f["after"]) for f in d["settings"]}
    ok(fields.get("appearance.backdrop") == ("a", "b"),
       "diff(cid1) reports the backdrop change between the two snapshots (%s)" % fields)
    db.workspace_config_put({"appearance": {"backdrop": "c"}})
    d2 = checkpoints.diff(cid2)
    f2 = {f["key"]: (f["before"], f["after"]) for f in d2["settings"]}
    ok(f2.get("appearance.backdrop") == ("b", "c"), "diff(newest) compares against the LIVE rows")

    print("3. restore() writes the rows back, and is itself checkpointed")
    n_before = len(checkpoints.list_checkpoints())
    restored = checkpoints.restore(cid1, actor="test")
    ok(restored == cid1, "restore() returns the checkpoint id")
    ok(db.workspace_config_all()["appearance"]["backdrop"] == "a", "the live row rolled back to snapshot one")
    ok(len(checkpoints.list_checkpoints()) == n_before + 1, "the pre-restore state was checkpointed first")

    print("4. connectors still tracked")
    with open(os.path.join(conn_dir, "extra.py"), "w", encoding="utf-8") as f:
        f.write("NAME='extra'\n")
    cid4 = checkpoints.create(actor="test", reason="with extra")
    os.remove(os.path.join(conn_dir, "extra.py"))
    d4 = checkpoints.diff(cid4)
    ok("extra.py" in d4["connectors"]["removed"], "a removed connector shows in diff (%s)" % d4["connectors"])
    checkpoints.restore(cid4, actor="test")
    ok(os.path.exists(os.path.join(conn_dir, "extra.py")), "restore brings the connector file back")

    print(("\n%d FAILURE(S)" % len(_fails)) if _fails else "\nALL PASS")
    sys.exit(1 if _fails else 0)


if __name__ == "__main__":
    main()
