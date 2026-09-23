# -*- coding: utf-8 -*-
"""The daemon must outrank the work it spawns.

2026-09-23: while a card built the Android AAB (14:36-15:12) the daemon
answered /pm/plan and /dashboard/data in 20-115s and the phone showed "Relay
unreachable". 143 slow answers since 2026-09-19, every one inside a heavy
build window, zero in the 3.5 quiet hours after. The endpoints cost ~2.5s of
CPU, so it was starvation. Agent workers (and everything they start, the
Gradle daemon included) now spawn BELOW_NORMAL; the daemon and Henry's chat
stay at NORMAL.

This pins the flag AND the seam: a new driver that hand-rolls its own
creationflags is the regression this test exists to catch."""
import io
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from spine.agent import spawnenv

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


flags = spawnenv.worker_creationflags()

# 1) the flag itself
if os.name == "nt":
    check(flags & subprocess.CREATE_NO_WINDOW, "keeps CREATE_NO_WINDOW (no focus-stealing console)")
    check(flags & subprocess.BELOW_NORMAL_PRIORITY_CLASS, "adds BELOW_NORMAL_PRIORITY_CLASS")
    check(not (flags & getattr(subprocess, "IDLE_PRIORITY_CLASS", 0x40)),
          "NOT idle priority - a worker must still run on a busy box, just not ahead of the daemon")
else:
    check(flags == 0, "no Windows flags off Windows")

# 2) THE SEAM: every agent driver spawns through it, none hand-rolls its own
DRIVERS = ["drivers.py", "codex_driver.py", "omp_driver.py", "opencode_driver.py", "pi_driver.py"]
for name in DRIVERS:
    src = io.open(os.path.join(ROOT, "spine", "agent", name), encoding="utf-8").read()
    # the Popen that starts the agent process: from the call to its closing
    # paren is not worth a parser - the argument list is well under 800 chars
    # in every driver, and the two assertions below are about what IS and is
    # NOT in it.
    at = src.find("self.proc = subprocess.Popen(")
    check(at >= 0, "%s: found the worker spawn" % name)
    body = src[at:at + 800] if at >= 0 else ""
    check("spawnenv.worker_creationflags()" in body,
          "%s: spawns with worker_creationflags()" % name)
    check('creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)' not in body,
          "%s: no hand-rolled creationflags left" % name)

# 3) the interactive processes stay at NORMAL - the owner waits on them
cop = io.open(os.path.join(ROOT, "cells", "copilot", "chat", "copilot.py"), encoding="utf-8").read()
check("worker_creationflags" not in cop,
      "Henry's chat/hands port is NOT lowered (the owner is waiting on it)")

# 4) it really is inheritable: a child spawned with the flag reports the class
if os.name == "nt":
    import ctypes
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3)"],
                         creationflags=flags, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    try:
        PROCESS_QUERY_LIMITED = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False, p.pid)
        prio = ctypes.windll.kernel32.GetPriorityClass(h) if h else 0
        if h:
            ctypes.windll.kernel32.CloseHandle(h)
        check(prio == subprocess.BELOW_NORMAL_PRIORITY_CLASS,
              "a process spawned with the flag really runs BELOW_NORMAL (got 0x%x)" % prio)
    finally:
        p.kill()
        p.wait(timeout=10)

print("\n%d FAIL" % len(_fails) if _fails else "\nall ok")
sys.exit(1 if _fails else 0)
