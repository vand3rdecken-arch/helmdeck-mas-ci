# -*- coding: utf-8 -*-
"""One session = one card (the Paseo invariant), CHAIN included: a rotated-away
session is its card's own history (the transcript renders it via session_chain),
so adopting it would spawn a second card writing into the middle of another
card's conversation. The guard used to check only the live session_id - the
chain was adoptable through the API. lane=done stays exempt (deliberate escape
hatch, documented at the guard)."""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, DAEMON)

SANDBOX = tempfile.mkdtemp(prefix="hd-adopt-")
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()
from spine.ops import runs
runs.REC = os.path.join(SANDBOX, "runs"); os.makedirs(runs.REC, exist_ok=True)
from cells.engineer import sessions
sessions.REC = runs.REC

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def expect_bounce(sid, msg):
    try:
        sessions.adopt_session(sid, SANDBOX, mode="continue")
        check(False, msg + " (no error raised)")
    except RuntimeError as e:
        check("already on the board" in str(e), msg + " (%s)" % str(e)[:50])


t = {"id": "card-1", "task": "t", "status": "needs_you", "lane": "working",
     "session_id": "live-sess", "session_chain": ["old-a", "old-b"],
     "run_dir": os.path.join(runs.REC, "card-1")}
sessions._save([t])

expect_bounce("live-sess", "live session id is guarded")
expect_bounce("old-a", "a CHAIN member is guarded too")
expect_bounce("old-b", "every chain member, not just the first")

# an unrelated session must not bounce on the guard (it fails later on the
# missing transcript / repo machinery, or succeeds - either way NOT this error)
try:
    sessions.adopt_session("totally-new", SANDBOX, mode="continue")
    check(True, "unbound session passes the guard")
except RuntimeError as e:
    check("already on the board" not in str(e),
          "unbound session passes the guard (failed later: %s)" % str(e)[:40])

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails)); sys.exit(1)
print("adopt-guard: all pinned - PASS")
