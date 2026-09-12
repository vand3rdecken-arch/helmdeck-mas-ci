# -*- coding: utf-8 -*-
"""The events table is the record (state-into-db phase H, owner decision
2026-09-12). Replaces test_events_reconcile.py / test_events_no_reimport.py,
which pinned the file era (jsonl first, best-effort write-through, boot-time
reconcile, "the file is the durable record").

Proven to FAIL on the old code: case 2 makes db.event_insert raise and
asserts emit() RAISES - on the old code emit() swallowed it (`except: pass`)
and appended to the file instead, the exact silent drop this closes.

  1. emit() lands ONE row in the table, nothing on disk
  2. a failed insert is an ERROR at the emitter, never a silent drop
  3. ledger step 11 folds a leftover events.jsonl in: id-keyed rows the
     write-through already stored are no-ops, rows it missed are added, the
     file is archived, .synced removed - and a second init() changes nothing
  4. export_events renders the trail in table order, filterable
  5. the table has no UPDATE/DELETE path in the storage layer

Run:  py -3.12 ops/tests/test_events_db_first.py
"""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "ops", "tools"))

_SANDBOX = tempfile.mkdtemp(prefix="hd-events-")
import daemon.paths                      # noqa: E402
daemon.paths.DAEMON_ROOT = _SANDBOX
from spine.storage import db, events     # noqa: E402
assert db.DBPATH.startswith(_SANDBOX), "REFUSING TO RUN: db points at %s" % db.DBPATH

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def count():
    return db.conn().execute("SELECT count(*) FROM events").fetchone()[0]


print("1. emit lands in the table, nothing on disk")
db.init()
n0 = count()
row = events.emit("lane", "t-1", actor="owner", to="review")
check(count() == n0 + 1, "one row per emit")
check(not os.path.exists(os.path.join(_SANDBOX, "events.jsonl")), "no events.jsonl is written")
got = [r for r in events.read_events() if r.get("id") == row["id"]]
check(len(got) == 1 and got[0]["to"] == "review" and got[0]["actor"] == "owner",
      "read_events serves the row with its fields")
check(db.conn().execute("SELECT actor FROM events WHERE id=?", (row["id"],)).fetchone()[0] == "owner",
      "the generated actor column sees it")

print("2. a failed insert is an error, never a silent drop")
real = db.event_insert
db.event_insert = lambda r: (_ for _ in ()).throw(RuntimeError("disk full"))
raised = False
try:
    events.emit("lane", "t-1", actor="owner")
except RuntimeError:
    raised = True
finally:
    db.event_insert = real
check(raised, "emit() raises when the table cannot take the row")
check(count() == n0 + 1, "and nothing was half-written")

print("3. ledger step 11 folds a leftover file in, once")
# cases 1-2 already ran on sandbox/helmdeck.db (ROOT == dirname(DBPATH), so
# file steps are allowed there): start this case from an EMPTY store
_c = getattr(db._local, "c", None)
if _c is not None:
    _c.close()          # Windows keeps an open db undeletable
db._local.c = None
for ext in ("", "-wal", "-shm"):
    try:
        os.remove(os.path.join(_SANDBOX, "helmdeck.db" + ext))
    except OSError:
        pass
db.DBPATH = os.path.join(_SANDBOX, "helmdeck.db")
stored = {"id": "aaaa11", "ts": "2026-09-01 10:00:00", "kind": "gate", "track": "t-9", "ok": True}
missed = {"id": "bbbb22", "ts": "2026-09-01 10:00:01", "kind": "merge", "track": "t-9", "ok": False}
legacy = {"ts": "2026-08-01 09:00:00", "kind": "touch", "track": "t-0"}   # pre-id era, no key
with open(os.path.join(_SANDBOX, "events.jsonl"), "w", encoding="utf-8") as f:
    for r in (stored, missed, legacy):
        f.write(json.dumps(r) + "\n")
with open(os.path.join(_SANDBOX, "events.jsonl.synced"), "w") as f:
    f.write("0")
# pretend the write-through had stored `stored` and this table is populated
c = db.conn()
c.execute("CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT, ts TEXT, kind TEXT, track TEXT, data TEXT)")
c.execute("CREATE UNIQUE INDEX IF NOT EXISTS ev_id ON events(id)")
c.execute("INSERT INTO events(id,ts,kind,track,data) VALUES(?,?,?,?,?)",
          (stored["id"], stored["ts"], stored["kind"], stored["track"], json.dumps({"ok": True})))
c.commit()
db.init()
ids = [r[0] for r in c.execute("SELECT id FROM events ORDER BY seq")]
check(ids.count("aaaa11") == 1, "the row the write-through had stored is not duplicated")
check("bbbb22" in ids, "the row it had missed is folded in")
check(c.execute("SELECT count(*) FROM events WHERE kind='touch'").fetchone()[0] == 0,
      "an id-less pre-id-era row is NOT re-imported into a populated table")
check(not os.path.exists(os.path.join(_SANDBOX, "events.jsonl")), "events.jsonl archived")
check(os.path.exists(os.path.join(_SANDBOX, "backups", "events.jsonl.imported")), "…into backups/")
check(not os.path.exists(os.path.join(_SANDBOX, "events.jsonl.synced")), ".synced removed")
n1 = count()
db.init()
check(count() == n1, "a second init() changes nothing")
check(db.conn().execute("PRAGMA user_version").fetchone()[0] == db.schema_head(), "ledger at head")

print("4. export renders the trail")
import export_events                     # noqa: E402
lines = list(export_events.rows())
check([l["id"] for l in lines if l.get("id")][:2] == ["aaaa11", "bbbb22"], "table order, ids kept")
check(all("ts" in l and "kind" in l for l in lines), "row shape = ts/kind/track + fields")
check([l["kind"] for l in export_events.rows(kind="merge")] == ["merge"], "--kind filters")
check(all(l["ts"] >= "2026-09-01" for l in export_events.rows(since="2026-09-01")), "--since filters")
r = subprocess.run([sys.executable, os.path.join(ROOT, "ops", "tools", "export_events.py"), "--kind", "gate"],
                   capture_output=True, text=True, encoding="utf-8",
                   env=dict(os.environ, HELMDECK_ALLOW_LIVE_DB="1"))
check(r.returncode == 0 and "event(s)" in r.stderr, "the CLI runs (against the live db, read-only)")

print("5. no mutation path in the storage layer")
src = open(os.path.join(ROOT, "spine", "storage", "db.py"), encoding="utf-8").read()
check(not re.search(r"(UPDATE|DELETE FROM)\s+events\b", src), "db.py never mutates events")
check("def _reconcile_events" not in src, "the reconcile machinery is gone")

print()
if _fails:
    print("FAILED: %d" % len(_fails))
    for f in _fails:
        print("  - " + f)
    sys.exit(1)
print("ALL OK")
