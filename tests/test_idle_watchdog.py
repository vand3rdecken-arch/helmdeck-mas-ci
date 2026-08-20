# -*- coding: utf-8 -*-
"""run_turn bounds SILENCE, not wall-clock (Paseo bounds the TOOL, not the turn).
A long-but-PRODUCTIVE turn - one that keeps emitting stream frames - must run to
completion even past the idle window; only a genuinely wedged turn (no frame for
the whole idle window) is killed. Pins the "killed during run" regression: a
fixed 1800s wall-clock cap killed a machine card mid-gradle-build."""
import os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(HERE)
sys.path.insert(0, DAEMON)

SANDBOX = tempfile.mkdtemp(prefix="hd-idle-")
from daemon.spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from daemon.spine.storage import events
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()
from daemon.spine.agent import drivers

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


def _sess(idle):
    run_dir = os.path.join(SANDBOX, "run-%d" % (idle * 1000)); os.makedirs(run_dir, exist_ok=True)
    t = {"id": "idle-%d" % (idle * 1000), "worktree": SANDBOX, "run_dir": run_dir, "machine": True}
    return drivers._ClaudeSession({"perm": "acceptEdits", "idle_timeout": idle}, t), run_dir


# 1) PRODUCTIVE turn: 8 deltas @0.4s (~3.2s of activity) with idle=2s. Every
#    delta resets the watchdog, so it must NOT be killed - it completes.
s, rd = _sess(idle=2)
t0 = time.time()
sid, out, meta = s.run_turn("__SLOW__:8", rd)
dur = time.time() - t0
check(out == "slow-done", "productive turn survived past the idle window (out=%r)" % out)
check(dur > 3.0, "it really ran the full ~3.2s of streaming, not cut short (%.1fs)" % dur)
check(not meta.get("is_error"), "productive turn is not an error")
s.kill()

# 2) WEDGED turn: init then total silence, idle=2s -> killed as stalled.
s2, rd2 = _sess(idle=2)
t0 = time.time()
raised = ""
try:
    s2.run_turn("__HANG__", rd2)
except RuntimeError as e:
    raised = str(e)
dur = time.time() - t0
check("stalled" in raised and "no output" in raised, "wedged turn killed as stalled (%r)" % raised[:60])
check(2.0 <= dur < 8.0, "killed near the idle window, not a 30-min wall-clock wait (%.1fs)" % dur)
s2.kill()

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails)); sys.exit(1)
print("idle-watchdog: all pinned - PASS")
