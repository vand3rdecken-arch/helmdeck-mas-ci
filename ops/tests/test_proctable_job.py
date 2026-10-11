# -*- coding: utf-8 -*-
"""Pins PROCESS OWNERSHIP (owner 2026-10-11: "Prozesse verwaisen, werden nicht
richtig beendet" - three `npm install` of 450 MB each, two `opencode serve` of
59 h and a bash with ten children, all with a DEAD parent, on a box that was
swapping).

Windows has no reparenting: once an intermediate process dies, taskkill /T and
_descendants cannot reach what is below it. proctable now owns every spawn
through a kill-on-close Job Object, taken at the SAME seam every driver already
calls (_record_pid), so the OS - not a reconstructed tree - decides who belongs
to a worker. Runs the REAL seam (Popen -> _record_pid -> _tree_kill), no fakes
for the process layer; on the old code the grandchild below survives.

Pins:
  1. worker -> middle -> grandchild, the middle EXITS (the grandchild's parent
     is dead), _tree_kill(worker): the grandchild dies too;
  2. a worker that DIES ON ITS OWN takes its family with it at once - no kill
     call, no next turn (the leak that ran until the next turn, or forever);
  3. popen_breakaway escapes the job on purpose (persistent Chrome, detach.py,
     the restart helper) and survives the worker's death;
  4. close_job on a pid that never had a job is a harmless False.

Run: py -3.12 ops/tests/test_proctable_job.py
"""
import os, subprocess, sys, tempfile, textwrap, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
SANDBOX = tempfile.mkdtemp(prefix="hd-job-sb-")
from spine.agent import proctable
proctable._PIDFILE = os.path.join(SANDBOX, "driver_pids.json")     # never the live file

CHILD = os.path.join(SANDBOX, "child.py")
with open(CHILD, "w", encoding="utf-8") as f:
    f.write(textwrap.dedent('''
        import os, subprocess, sys, time
        role, out = sys.argv[1], sys.argv[2]
        def note(name):
            with open(os.path.join(out, name), "w") as fh: fh.write(str(os.getpid()))
        me = [sys.executable, __file__]
        if role == "worker":            # worker -> middle -> grandchild; the middle exits
            note("worker"); subprocess.Popen(me + ["middle", out]); time.sleep(300)
        elif role == "mortal":          # a worker that dies on its own, grandchild still running
            note("worker"); subprocess.Popen(me + ["grandchild", out]); time.sleep(2.5)
        elif role == "middle":
            subprocess.Popen(me + ["grandchild", out]); time.sleep(1)
        elif role == "escaper":         # worker that starts a deliberately detached process
            sys.path.insert(0, %r)
            from spine.agent.proctable import popen_breakaway
            note("worker"); popen_breakaway(me + ["survivor", out]); time.sleep(300)
        else:                           # grandchild / survivor
            note(role); time.sleep(300)
    ''' % ROOT))

fails = []


def check(label, ok, extra=""):
    print(("  ok    " if ok else "  FAIL  ") + label + (("  " + extra) if (extra and not ok) else ""))
    if not ok:
        fails.append(label)


def alive(pid):
    return any(p == pid for p, _pp, _exe in proctable._pid_table())


def wait_for(path, secs=15):
    end = time.time() + secs
    while time.time() < end:
        try:
            with open(path) as f:
                return int(f.read())
        except (OSError, ValueError):
            time.sleep(0.1)
    return None


def wait_gone(pid, secs=8):
    end = time.time() + secs
    while time.time() < end:
        if not alive(pid):
            return True
        time.sleep(0.2)
    return False


def spawn(role):
    out = tempfile.mkdtemp(prefix=role + "-", dir=SANDBOX)
    p = subprocess.Popen([sys.executable, CHILD, role, out], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    proctable._record_pid(p.pid, time.time())        # THE seam every driver calls right after Popen
    return p, out


cleanup = []

# 1 -- the measured leak: the grandchild's parent is dead, taskkill /T cannot see it
w, out = spawn("worker")
gc = wait_for(os.path.join(out, "grandchild"))
check("grandchild started", gc is not None)
time.sleep(1.8)                                      # the middle has exited by now
check("precondition: grandchild is orphaned (its parent is dead, its job is its only owner)",
      gc is not None and alive(gc) and not any(p == gc and alive(pp) for p, pp, _e in proctable._pid_table()))
proctable._tree_kill(w)
check("_tree_kill(worker) also ends the orphaned grandchild", gc is not None and wait_gone(gc),
      "grandchild %s still alive" % gc)
if gc and alive(gc):
    cleanup.append(gc)

# 2 -- a worker dying on its own takes its family at once
w, out = spawn("mortal")
gc = wait_for(os.path.join(out, "grandchild"))
check("mortal: grandchild started", gc is not None)
try:
    w.wait(timeout=10)                               # the worker exits by itself, nobody calls a kill
except subprocess.TimeoutExpired:
    pass
check("worker exiting by itself ends its grandchild (event-driven, no kill call)",
      gc is not None and wait_gone(gc), "grandchild %s still alive" % gc)
if gc and alive(gc):
    cleanup.append(gc)

# 3 -- an intentional escape survives
w, out = spawn("escaper")
sv = wait_for(os.path.join(out, "survivor"))
check("escaper: breakaway process started", sv is not None)
# close_job, not _tree_kill: taskkill /T would walk the still-LIVE parent link to the survivor.
# Real escapers also end their starter at once (detach.py, the Chrome launcher, restart_daemon.py),
# which is what hides them from /T - the JOB boundary is what this pin is about.
check("escaper's job closed", proctable.close_job(w.pid) is True)
time.sleep(1.0)
check("worker is gone", wait_gone(w.pid))
check("popen_breakaway survives the job's death", sv is not None and alive(sv))
if sv:
    cleanup.append(sv)

# 4 -- no job: harmless
check("close_job on a pid that never had a job -> False", proctable.close_job(2 ** 22 - 4) is False)

for pid in cleanup:
    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)

if fails:
    print("\n%d FAILED" % len(fails))
    sys.exit(1)
print("\nall passed")
