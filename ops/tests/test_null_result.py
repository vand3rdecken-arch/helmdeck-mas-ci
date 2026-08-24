# -*- coding: utf-8 -*-
"""Null-result guard: resuming a session whose prior turn was HARD-KILLED makes
the CLI flush the dead turn's leftover result first - empty text, zero usage,
no error. Taking that as the new turn's result ended the turn after seconds
with an empty reply while the real work ran on ownerless ("Broke up in the
middle", 2026-08-10 18:35). The driver must DROP the substance-free frame (a
real model turn always carries input_tokens > 0) and return the real result.
The guard is scoped to the first turn after a --resume spawn - a fresh spawn
takes frames at face value."""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, DAEMON)

SANDBOX = tempfile.mkdtemp(prefix="hd-null-")
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()
from spine.agent import claude_sessions
from spine.agent import drivers

# the resumed session's transcript "exists" (else _spawn degrades to FRESH and
# the guard correctly stays off - that path is asserted too)
_real_find = claude_sessions._find_transcript
claude_sessions._find_transcript = lambda sid: "exists" if sid == "prev-sess" else _real_find(sid)

_WRAP = os.path.join(tempfile.mkdtemp(), "fake_claude.cmd")
with open(_WRAP, "w", encoding="utf-8") as f:
    f.write('@echo off\r\n"%s" "%s" %%*\r\n' % (sys.executable, os.path.join(HERE, "fake_claude.py")))
drivers.CLAUDE = _WRAP
drivers._PIDFILE = os.path.join(tempfile.mkdtemp(), "driver_pids.json")

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


rd = os.path.join(SANDBOX, "run"); os.makedirs(rd, exist_ok=True)

# 1) resume spawn: the null frame is dropped, the REAL result lands
s = drivers._ClaudeSession({"perm": "acceptEdits", "idle_timeout": 30},
                           {"id": "n1", "worktree": SANDBOX, "run_dir": rd,
                            "machine": True, "session_id": "prev-sess"})
sid, out, meta = s.run_turn("__NULLRESULT__", rd)
check(out == "real-answer", "resume: null frame dropped, real result returned (out=%r)" % out)
check((meta.get("usage") or {}).get("input_tokens") == 9, "real result's usage kept")
s.kill()

# 2) fresh spawn: guard off - frames taken at face value (first result counts)
s2 = drivers._ClaudeSession({"perm": "acceptEdits", "idle_timeout": 30},
                            {"id": "n2", "worktree": SANDBOX, "run_dir": rd, "machine": True})
sid2, out2, _ = s2.run_turn("__NULLRESULT__", rd)
check(out2 == "", "fresh spawn: guard scoped to resume only (out=%r)" % out2)
s2.kill()

# 3) an ERROR result right after resume is NOT swallowed (it carries evidence)
s3 = drivers._ClaudeSession({"perm": "acceptEdits", "idle_timeout": 30},
                            {"id": "n3", "worktree": SANDBOX, "run_dir": rd,
                             "machine": True, "session_id": "prev-sess"})
sid3, out3, meta3 = s3.run_turn("__ERR__", rd)
check(meta3.get("is_error"), "resume: a real error result still lands (not dropped)")
s3.kill()

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails)); sys.exit(1)
print("null-result: all pinned - PASS")
