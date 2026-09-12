# -*- coding: utf-8 -*-
"""Schema ledger + audit fixes (state-into-db phase A, 2026-09-12).

Proven to FAIL on the pre-ledger code: case 2 builds a db in the OLD shape
(user_version 0, no schema_migrations, tracks as bare (id, data), the dead
workspace_config `users` row with a plaintext token) and asserts the upgrade -
on old code user_version stays 0 and the token row survives.

  1. a fresh db reaches user_version == schema_head() and records one ledger
     row per step; a second init() applies nothing
  2. an OLD-shape db upgrades in place: every card/event/memory row kept,
     generated scope columns exist and are indexed, the dead `users` row is gone
  3. every table carries a scope column or is on the explicit workspace-level
     allowlist (the data-model rule from the card, enforced)
  4. append-only tables have no UPDATE/DELETE path in db.py (static check)
  5. a failing step is rolled back AND left unrecorded (retried next boot)
  6. db_export masks secrets at any depth, keeps counts, skips generated
     columns; db_import round-trips into an empty db with identical counts and
     never writes a masked value

SANDBOXED like test_boards.py: daemon.paths is repointed BEFORE the storage
import and the test refuses to run if that did not take.

Run:  py -3.12 ops/tests/test_db_schema.py
"""
import json
import os
import re
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

_SANDBOX = tempfile.mkdtemp(prefix="hd-schema-")
import daemon.paths                      # noqa: E402
daemon.paths.DAEMON_ROOT = _SANDBOX

from spine.storage import db             # noqa: E402
assert db.DBPATH.startswith(_SANDBOX), "REFUSING TO RUN: db points at %s" % db.DBPATH

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def fresh(name):
    """Repoint db at a new file inside the sandbox and drop the thread-local
    connection so init() opens it."""
    db.DBPATH = os.path.join(_SANDBOX, name)
    db._local.c = None
    return db.DBPATH


def old_shape(path):
    """The db exactly as an install from before the ledger had it."""
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE tracks(id TEXT PRIMARY KEY, data TEXT NOT NULL)")
    c.execute("CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, track TEXT, data TEXT)")
    c.execute("CREATE TABLE memory(name TEXT PRIMARY KEY, content TEXT NOT NULL, updated_at TEXT NOT NULL, actor TEXT NOT NULL)")
    c.execute("CREATE TABLE workspace_config(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)")
    for i in range(5):
        c.execute("INSERT INTO tracks VALUES(?,?)", ("t%d" % i, json.dumps(
            {"id": "t%d" % i, "lane": "done" if i < 3 else "backlog", "status": "accepted",
             "project_id": "p1", "repo": "r", "task": "x", "archived": i == 4})))
    c.execute("INSERT INTO events(ts,kind,track,data) VALUES(?,?,?,?)",
              ("2026-01-01 00:00:00", "lane", "t0", json.dumps({"actor": "owner"})))
    c.execute("INSERT INTO memory VALUES(?,?,?,?)", ("n1", "note", "2026-01-01", "henry"))
    c.execute("INSERT INTO workspace_config VALUES(?,?,?)",
              ("users", json.dumps([{"name": "owner", "token": "PLAINTEXT"}]), "2026-01-01"))
    c.execute("INSERT INTO workspace_config VALUES(?,?,?)",
              ("relay", json.dumps({"url": "https://r", "sk": "SECRETKEY", "nested": {"api_token": "T"}}), "2026-01-01"))
    c.commit()
    c.close()


print("1. fresh db")
fresh("fresh.db")
db.init()
c = db.conn()
head = db.schema_head()
check(c.execute("PRAGMA user_version").fetchone()[0] == head, "user_version == schema_head (%d)" % head)
check(len(db.schema_applied()) == head, "one ledger row per step")
before = db.schema_applied()
db.init()
check(db.schema_applied() == before, "second init applies nothing")

print("2. old-shape db upgrades in place")
p = fresh("old.db")
old_shape(p)
db.init()
c = db.conn()
check(c.execute("PRAGMA user_version").fetchone()[0] == head, "old db reaches user_version %d" % head)
check(c.execute("SELECT count(*) FROM tracks").fetchone()[0] == 5, "all 5 cards kept")
check(c.execute("SELECT count(*) FROM events").fetchone()[0] == 1, "event kept")
check(c.execute("SELECT count(*) FROM memory").fetchone()[0] == 1, "memory kept")
check(c.execute("SELECT count(*) FROM workspace_config WHERE key='users'").fetchone()[0] == 0,
      "dead `users` row with the plaintext token is gone")
check(c.execute("SELECT count(*) FROM workspace_config").fetchone()[0] == 1, "other config rows kept")
check(len(db.tracks_where(lane="done", status="accepted")) == 3, "tracks_where(lane, status) over generated columns")
plan = " ".join(r[3] for r in c.execute("EXPLAIN QUERY PLAN SELECT data FROM tracks WHERE lane=? AND status=?", ("done", "accepted")))
check("tracks_lane_status" in plan, "and it uses the index: %s" % plan)
check(c.execute("SELECT count(*) FROM tracks WHERE archived=1").fetchone()[0] == 1, "archived boolean queryable")
check(c.execute("SELECT actor FROM events").fetchone()[0] == "owner", "events.actor generated from the blob")
check("account" in {r[1] for r in c.execute("PRAGMA table_info(memory)")}, "memory.account exists")
check(c.execute("SELECT account FROM memory").fetchone()[0] == "owner", "existing note defaults to account owner")
db.memory_put("n2", "x", account="acme")
check(c.execute("SELECT account FROM memory WHERE name='n2'").fetchone()[0] == "acme", "memory_put stores account")
# the writer is untouched: a plain (id, data) upsert still works with the generated columns present
db.track_put({"id": "t9", "lane": "review", "status": "gating", "project_id": "p1"})
check(len(db.tracks_where(lane="review")) == 1, "track_put unchanged, new row visible through the index")
bad = False
try:
    db.tracks_where(nope="x")
except ValueError:
    bad = True
check(bad, "tracks_where rejects an unknown scope column")

print("3. every table declares its scope (data-model rule)")
# entity ROOTS (the row IS the scope: projects.id is the project) and
# workspace-level tables need no scope column
WORKSPACE_LEVEL = {"workspace_config", "policy_doc", "process_template", "connector_state",
                   "schema_migrations", "processes", "events", "sqlite_sequence", "projects",
                   # workspace-level records per the data model (card section 2.1)
                   "pm_plans", "pm_activity", "runtime_doc"}
SCOPE_COLS = {"account", "user", "owner", "project", "project_id", "track", "run_id"}
for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
    if t in WORKSPACE_LEVEL:
        continue
    cols = {r[1] for r in c.execute("PRAGMA table_xinfo(%s)" % t)}
    check(bool(cols & SCOPE_COLS), "table %s has a scope column (%s)" % (t, ", ".join(sorted(cols & SCOPE_COLS))))

print("4. append-only tables have no UPDATE/DELETE path")
src = open(os.path.join(ROOT, "spine", "storage", "db.py"), encoding="utf-8").read()
for t in ("events", "schema_migrations"):
    hits = re.findall(r"(UPDATE|DELETE FROM)\s+%s\b" % t, src)
    check(not hits, "db.py never mutates %s (%s)" % (t, hits or "clean"))

print("5. a failing step rolls back and stays unrecorded")
fresh("fail.db")
db.init()
saved = list(db._MIGRATIONS)
def boom(c):
    c.execute("CREATE TABLE half_done(x)")
    raise RuntimeError("simulated")
db._MIGRATIONS.append((head + 1, "boom", boom))
raised = False
try:
    db._apply_migrations()
except RuntimeError:
    raised = True
c = db.conn()
check(raised, "the failure propagates (never swallowed)")
check(c.execute("PRAGMA user_version").fetchone()[0] == head, "user_version unchanged")
check(not c.execute("SELECT name FROM sqlite_master WHERE name='half_done'").fetchone(), "partial DDL rolled back")
check(len(db.schema_applied()) == head, "no ledger row for the failed step")
db._MIGRATIONS[:] = saved

print("6. export masks, import round-trips")
p = fresh("exp.db")
old_shape(p)
db.init()
from ops.tools import db_export, db_import   # noqa: E402
doc = db_export.export()
flat = json.dumps(doc)
check("PLAINTEXT" not in flat and "SECRETKEY" not in flat and '"T"' not in flat, "no secret survives a default export")
check(doc["workspace_config"][0]["value"]["sk"] == "***", "sk masked at depth 1")
check(doc["workspace_config"][0]["value"]["nested"]["api_token"] == "***", "api_token masked at depth 2")
check(doc["workspace_config"][0]["value"]["url"] == "https://r", "non-secret kept")
check(len(doc["tracks"]) == 5 and "lane" not in doc["tracks"][0], "5 cards exported, generated columns skipped")
check("SECRETKEY" in json.dumps(db_export.export(secrets=True)), "--with-secrets keeps them")
scoped = db_export.export(account="acme")
check("tracks" not in scoped and "workspace_config" in scoped, "account export drops project tables, keeps workspace config")
counts_src = {t: len(v) for t, v in doc.items() if isinstance(v, list)}
fresh("imp.db")
counts = db_import.import_doc(doc)
c = db.conn()
check(counts.get("tracks") == 5, "import wrote 5 cards")
check(c.execute("SELECT count(*) FROM memory").fetchone()[0] == counts_src["memory"], "memory count identical")
relay = json.loads(c.execute("SELECT value FROM workspace_config WHERE key='relay'").fetchone()[0])
check("sk" not in relay and relay.get("url") == "https://r", "masked key dropped on import, real value kept")
check(len(db.tracks_where(lane="done")) == 3, "generated columns recomputed after import")
refused = False
try:
    db_import.import_doc(doc)
except SystemExit:
    refused = True
check(refused, "import into a non-empty db refuses without --merge")
counts2 = db_import.import_doc(doc, merge=True)
check(c.execute("SELECT count(*) FROM tracks").fetchone()[0] == 5, "--merge is INSERT OR IGNORE, no duplicates")

print()
if _fails:
    print("FAILED: %d" % len(_fails))
    for f in _fails:
        print("  - " + f)
    sys.exit(1)
print("ALL OK")
