# -*- coding: utf-8 -*-
"""Pins 2026-10-20 22:30: restart_daemon.py read "nothing running" while the
broker's judge run was filing a process's step cards, and the restart killed it
half way. The tool reads driver_pids.json (another process); proctable.own()
lives in the daemon's memory only. A judge run is now recorded there too
(own_turn) and removed when it ends (forget_turn). RED on the old code: no
own_turn - and the old own() left driver_pids.json empty.

Self-sandboxing: proctable's pidfile redirected to a temp dir. Run:
  py -3.12 ops/tests/test_restart_guard_sees_judge.py
"""
import os, subprocess, sys, tempfile, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from spine.agent import proctable

tmp = tempfile.mkdtemp(prefix="hd-guard-")
proctable._PIDFILE = os.path.join(tmp, "driver_pids.json")
fails = []


def check(c, m):
    print(("  ok   " if c else "  FAIL ") + m)
    if not c:
        fails.append(m)


# a stand-in agent process: the guard only trusts pids whose image looks like an agent
p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
try:
    proctable.own_turn(p)
    check(str(p.pid) in proctable._read_pids(), "a judge run shows up in driver_pids.json (what restart_daemon reads)")
    proctable.forget_turn(p)
    check(str(p.pid) not in proctable._read_pids(), "forget_turn removes it when the run ends")
finally:
    p.kill()
print("PASS test_restart_guard_sees_judge" if not fails else "FAIL (%d)" % len(fails))
sys.exit(1 if fails else 0)
