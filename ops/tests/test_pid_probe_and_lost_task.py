# -*- coding: utf-8 -*-
"""Pins the 2026-10-20 incident (card jira-subkomponenten, Henry deaf 41 min):

  1. Probing a pid read from a lock file must NOT kill it. On Windows CPython's
     os.kill(pid, 0) is TerminateProcess + SystemError - Henry's ship.lock line
     killed the process it reported on, and an analysis call took the live
     daemon down. Runs the REAL probe against a REAL foreign process.
  2. start_broker starts Henry's loop even when the stale-ship.lock boot check
     raises (it raised, the thread never started, escalations sat unread).
  3. A worker whose --resume found no transcript gets the card's task in its
     first prompt, not just "do the task as described".

Self-sandboxing: temp db, the loop and the boot check are stubbed - nothing
touches the live board, a real model or the phone.

Run: py -3.12 ops/tests/test_pid_probe_and_lost_task.py
"""
import os, subprocess, sys, tempfile, threading, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from spine.storage import db
db.DBPATH = os.path.join(tempfile.mkdtemp(prefix="hd-pidprobe-"), "test.db")
db._local.c = None
db.init()
from spine.ops import procwatch
from spine.agent import drivers
from cells.copilot.broker import henry_broker as hb


def check(desc, ok):
    assert ok, desc
    print("  ok: " + desc)


def _foreign_sleeper():
    """A sleeper that is NOT our child (its launcher exits) - the shape of a
    lock holder or the daemon as seen from another process."""
    flags = (0x00000008 | 0x00000200) if os.name == "nt" else 0
    code = ("import subprocess,sys; p=subprocess.Popen([sys.executable,'-c',"
            "'import time; time.sleep(60)'], creationflags=%d); print(p.pid)" % flags)
    return int(subprocess.check_output([sys.executable, "-c", code]).strip())


def _gone(pid):
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"],
                             capture_output=True, text=True).stdout
        return str(pid) not in out
    try:
        os.kill(pid, 0)
        return False
    except OSError:
        return True


# -- 1) the probe ---------------------------------------------------------------
pid = _foreign_sleeper()
time.sleep(0.5)
try:
    check("1. a live foreign pid reads alive", procwatch.exists(pid))
    check("1. henry's lock probe reads it alive", hb._pid_alive(pid) is True)
    time.sleep(1.0)
    check("1. ...and the probe did NOT kill it", not _gone(pid))
finally:
    subprocess.run(["taskkill", "/F", "/PID", str(pid)] if os.name == "nt" else ["kill", "-9", str(pid)],
                   capture_output=True)
time.sleep(0.5)
check("1. a dead pid reads dead", not procwatch.exists(pid))
check("1. garbage reads dead, never raises", not procwatch.exists("x") and not procwatch.exists(None)
      and not procwatch.exists(0))

# -- 2) the broker starts even when its boot check raises ------------------------
ran = threading.Event()
saved = (hb._loop, hb.check_stale_ship_lock, hb._started)
try:
    hb._loop = ran.set
    def _boom():
        raise SystemError("<built-in function kill> returned a result with an exception set")
    hb.check_stale_ship_lock = _boom
    hb._started = False
    hb.start_broker()
    check("2. the loop runs although the boot check raised", ran.wait(5))
finally:
    hb._loop, hb.check_stale_ship_lock, hb._started = saved

# -- 3) lost session -> the task rides along -------------------------------------
p = drivers._with_lost_task("Review vorbereiten fuer jira-subkomponenten.", "Bitte von vorn ausfuehren.")
check("3. the task comes first, the instruction after it",
      p.index("Review vorbereiten") < p.index("Bitte von vorn"))
check("3. no task -> the prompt is untouched", drivers._with_lost_task("", "x") == "x")

print("test_pid_probe_and_lost_task: PASS")
