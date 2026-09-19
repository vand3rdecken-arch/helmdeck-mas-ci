# -*- coding: utf-8 -*-
"""metrics() must not be re-derived for every poller within METRICS_TTL, and
must re-derive once the store moved. Runs the REAL events.metrics against a
sandboxed db, counting the compute passes. Proven red on the pre-fix code
(two computes for two calls). Run: py -3.12 ops/tests/test_metrics_cache.py
"""
import os, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from spine.storage import db
SANDBOX = tempfile.mkdtemp(prefix="hd-mcache-")
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
db.init()
from spine.storage import events

COMPUTES = []
_compute = getattr(events, "_metrics_compute", None)
if _compute is None:           # pre-fix shape: metrics IS the compute
    _real = events.metrics
    def counting(tracks):
        COMPUTES.append(1); return _real(tracks)
    events.metrics = counting
else:
    def counting(tracks):
        COMPUTES.append(1); return _compute(tracks)
    events._metrics_compute = counting

fails = 0
def check(cond, msg):
    global fails
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails += 1

t = {"id": "20260919-120000-direct", "task": "x", "lane": "working", "status": "running",
     "branch": "main", "repo": SANDBOX, "client": "owner", "priority": "normal", "mode": "auto",
     "created": "2026-09-19 12:00:00", "turns": 1, "tokens_in": 10, "tokens_out": 5}
db.track_put(t)
events.emit("lane", t["id"], to="working")
tracks = [t]
from spine.auth import policy
policy.load()          # first-run seed writes the policy doc - warm it so the count below is the cache's, not the seed's
a = events.metrics(tracks); b = events.metrics(tracks)
check(a == b, "two polls within the TTL see the same figures")
check(len(COMPUTES) == 1, "and cost ONE compute (computes=%d)" % len(COMPUTES))
a["totals"] = "poisoned"
c = events.metrics(tracks)
check(c.get("totals") != "poisoned", "a caller mutating its copy never leaks into the next")
events.emit("touch", t["id"], touch="steer")            # the store moved
d = events.metrics(tracks)
check(len(COMPUTES) == 2, "a new event re-derives exactly once (computes=%d)" % len(COMPUTES))
print("RESULT:", "PASS" if not fails else "FAIL (%d)" % fails)
sys.exit(1 if fails else 0)
