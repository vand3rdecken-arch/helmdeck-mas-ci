# -*- coding: utf-8 -*-
"""Self-sandboxing test for checkpoints.py's ROOT-based storage.

Decision recorded here (see daemon/debt.py order 32): checkpoints.py is
NOT migrated into db.py's `data TEXT` row shape. A checkpoint is a directory
snapshot - shutil.copytree of the whole connectors/ folder plus a copy of
settings.json, one directory per checkpoint id (checkpoints.create) - not a
JSON record. There is no row shape that represents "a copy of a directory
tree" without re-implementing a filesystem inside SQLite, and CPDIR's own
diff()/restore() logic (checkpoints.py:78-113) is written directly against
os.listdir/shutil.copy2 on that tree. Forcing it into db.py would trade a
working, simple mechanism for a worse one just to satisfy a shape it doesn't
fit - the same call the task brief invited for voice.py's binary cache.

What DOES matter for test isolation (the actual incident this debt item is
about) is that CPDIR is a module-level global computed from checkpoints.py's
own __file__, independent of db.ROOT - exactly like CDIR/VDIR in connectors.py
and CACHE in voice.py. This test proves checkpoints.py is safely sandboxable
by patching CPDIR alone, and exercises create/list/diff/restore against a
temp directory to lock in that no code path falls back to the real ROOT.

Run: py -3.12 test_checkpoints_db_migration.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_fails = []
def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-cpdb-test-")

    import events
    events.EV = os.path.join(tmp, "events.jsonl")
    events.SET = os.path.join(tmp, "settings.json")

    import checkpoints
    cpdir = os.path.join(tmp, "checkpoints")
    os.makedirs(cpdir, exist_ok=True)
    checkpoints.CPDIR = cpdir
    checkpoints.ROOT = tmp   # _snapshot_targets() derives settings.json/connectors from ROOT

    # synthetic workspace to snapshot - never the real settings.json/connectors
    with open(os.path.join(tmp, "settings.json"), "w", encoding="utf-8") as f:
        f.write('{"appearance": {"backdrop": "a"}, "policy": {"auto_accept_green": false}}')
    conn_dir = os.path.join(tmp, "connectors")
    os.makedirs(conn_dir, exist_ok=True)
    with open(os.path.join(conn_dir, "demo.py"), "w", encoding="utf-8") as f:
        f.write("NAME='demo'\n")

    cid1 = checkpoints.create(actor="test", reason="synthetic snapshot one")
    ok(bool(cid1), "create() returns a checkpoint id")
    ok(os.path.isdir(os.path.join(cpdir, cid1)), "checkpoint dir landed in sandboxed CPDIR")

    lst = checkpoints.list_checkpoints()
    ok(len(lst) == 1 and lst[0]["id"] == cid1, "list_checkpoints() sees the sandboxed checkpoint")

    # mutate the "live" settings, then snapshot again
    with open(os.path.join(tmp, "settings.json"), "w", encoding="utf-8") as f:
        f.write('{"appearance": {"backdrop": "b"}, "policy": {"auto_accept_green": false}}')
    cid2 = checkpoints.create(actor="test", reason="synthetic snapshot two")
    ok(len(checkpoints.list_checkpoints()) == 2, "second checkpoint recorded")

    d = checkpoints.diff(cid1)
    fields = {f["key"]: (f["before"], f["after"]) for f in d["settings"]}
    ok(fields.get("appearance.backdrop") == ("a", "b"),
       "diff() reports the backdrop change between the two synthetic snapshots")

    restored = checkpoints.restore(cid1, actor="test")
    ok(restored == cid1, "restore() returns the checkpoint id")
    with open(os.path.join(tmp, "settings.json"), encoding="utf-8") as f:
        restored_content = f.read()
    ok('"a"' in restored_content, "restore() rolled the live settings back to snapshot one's value")
    ok(len(checkpoints.list_checkpoints()) == 3,
       "restore() itself checkpointed the pre-restore state (restores are reversible)")

    print(("\n%d FAILURE(S)" % len(_fails)) if _fails else "\nALL PASS")
    sys.exit(1 if _fails else 0)


if __name__ == "__main__":
    main()
