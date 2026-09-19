# -*- coding: utf-8 -*-
"""events_all() must not re-read and re-parse the whole event log on every
call (root cause of the 2026-09-19 dashboard hang: /dashboard/data and
/pm/plan took up to 115s under card load, the phone reported "Relay nicht
erreichbar"). Runs the REAL read path (events.read_events -> db.events_all)
against a sandboxed db and counts the SQL the connection actually executes.

Proven to FAIL on the pre-fix db.py (two full SELECTs for two reads).
Run: py -3.12 ops/tests/test_events_cache.py
"""
import os, sqlite3, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from spine.storage import db
SANDBOX = tempfile.mkdtemp(prefix="hd-evcache-")
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
db.init()
from spine.storage import events

FULL_SCANS = []
def _trace(stmt):
    if "FROM events ORDER BY seq" in stmt:
        FULL_SCANS.append(stmt)
db.conn().set_trace_callback(_trace)

fails = 0
def check(cond, msg):
    global fails
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails += 1

for i in range(50):
    events.emit("touch", "t-%d" % (i % 5), touch="steer", n=i)

a = events.read_events()
b = events.read_events()
check(len(a) == 50 and a == b, "two reads return the same 50 events")
check(len(FULL_SCANS) == 1, "second read of an unchanged log did NOT re-scan (scans=%d)" % len(FULL_SCANS))

a[0]["n"] = "poisoned"; a.append({"kind": "fake"})
c = events.read_events()
check(c[0]["n"] == 0 and len(c) == 50, "a caller mutating its result never leaks into another's")

events.emit("done", "t-1", msg="new row")
d = events.read_events()
check(len(d) == 51 and d[-1]["kind"] == "done", "an in-process append is seen on the next read")
check(len(FULL_SCANS) == 2, "and it cost exactly one re-scan (scans=%d)" % len(FULL_SCANS))

# A writer in ANOTHER process (ops/tools/*.py open their own connection) must
# invalidate too - the key is the table's own max(seq), not process state.
other = sqlite3.connect(db.DBPATH)
other.execute("INSERT INTO events(id,ts,kind,track,data) VALUES(?,?,?,?,?)",
              ("ext1", "2026-09-19 12:00:00", "relay", "-", '{"msg": "from another process"}'))
other.commit(); other.close()
e = events.read_events()
check(len(e) == 52 and e[-1]["msg"] == "from another process", "a foreign-connection append is seen")
check(len(FULL_SCANS) == 3, "and re-scanned exactly once (scans=%d)" % len(FULL_SCANS))

f = events.read_events()
check(len(FULL_SCANS) == 3, "quiet log: still no re-scan (scans=%d)" % len(FULL_SCANS))

print("RESULT:", "PASS" if not fails else "FAIL (%d)" % fails)
sys.exit(1 if fails else 0)
