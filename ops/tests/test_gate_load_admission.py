# -*- coding: utf-8 -*-
"""End-to-end pins for the load-aware-admission card's OTHER two halves that
ops/tests/test_gate_verdict.py and ops/tests/test_hook_idle.py don't cover:

  GATE SINGLETON (measured 2026-08-20, Display-Glasses card): a second _gate()
  call on the SAME worktree must never run concurrently with the first (two
  66-file suites starving each other on one tree's CPU/disk) - it BLOCKS until
  the first finishes, then runs its own fresh check.

  GATE IS SILENCE-BOUNDED, not the old fixed 600s wall-clock timeout: a gate
  command that keeps printing (just slowly, as under real box load) must
  survive past what a wall-clock cap would have killed; one that goes fully
  silent still gets killed, with the reason on the card - the same law
  test_hook_idle.py already pins for _repo_hook, now shared code
  (lanemachine._run_streamed) under _gate too.

  LOAD-AWARE ADMISSION is visible on the real card chat: with CPU faked high,
  _gate()'s ActionLog note names the wait, exactly as
  ops/tests/test_load_admission.py already pins against the primitive directly -
  this confirms the WIRING (a track WITH a run_dir, going through the real
  actionlog file), not just the primitive.

Self-sandboxing: throwaway git repos + a hand-written helmdeck.gate command
that invokes a real script file (test_hook_idle.py's `_py` technique - a
multi-line body embedded directly in a shell -c string breaks under cmd.exe),
spine.ops.resources.cpu_percent faked - no daemon, no network, no real
box load needed.

Run: py -3.12 ops/tests/test_gate_load_admission.py
"""
import json, os, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, DAEMON)

from spine.storage import events
from spine.ops import resources
from cells.engineer.cards import sessions
from spine.git.locks import _gate_lock_for

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


SETTINGS = {"policy": {"load_admission": {"enabled": True, "cpu_max_pct": 85,
                                          "wait_s": 1800, "poll_s": 1}}}
events.settings = lambda: SETTINGS
events.emit = lambda *a, **k: None

_CPU = [10.0]
resources.cpu_percent = lambda interval=0.2: _CPU[0]


def git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), r.stderr.strip()))
    return r.stdout.strip()


def clean_repo():
    d = tempfile.mkdtemp(prefix="hd-gateadmit-")
    git(d, "init")
    git(d, "symbolic-ref", "HEAD", "refs/heads/main")
    git(d, "config", "user.email", "t@t.t")
    git(d, "config", "user.name", "t")
    with open(os.path.join(d, "f.txt"), "w") as f:
        f.write("x\n")
    git(d, "add", "-A")
    git(d, "commit", "-m", "init")
    return d


def gate_track(repo, gate_body, tid="t-gate"):
    """gate_body is a real (possibly multi-line) Python program's source,
    written to its own script file and invoked as `"<python>" "<script>"` -
    NOT embedded in a `-c "..."` shell string, which mangles embedded
    newlines under cmd.exe. Committed (not left untracked) - _gate() bounces
    on any dirty worktree, which would mask what this test is actually
    checking."""
    script = os.path.join(repo, "gate_check.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write(gate_body)
    with open(os.path.join(repo, "helmdeck.gate"), "w", encoding="utf-8") as f:
        f.write('"%s" "%s"' % (sys.executable, script))
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "gate command")
    run_dir = os.path.join(repo, "_run_" + tid)
    os.makedirs(run_dir, exist_ok=True)
    return {"repo": repo, "worktree": repo, "id": tid, "run_dir": run_dir}


def notes(run_dir):
    path = os.path.join(run_dir, "actions.jsonl")
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d.get("kind") == "note":
                out.append(d.get("detail") or "")
    return out


def poll_until(pred, timeout=3.0, step=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(step)
    return pred()


SIMPLE_PASS = "print('ok    x')\nprint('gate: PASS (1 checks)')\n"

# --- 1) load-aware admission is wired into the REAL _gate() call, visible in
#        the card's own actionlog file --------------------------------------
_CPU[0] = 95.0
SETTINGS["policy"]["load_admission"].update(cpu_max_pct=85, wait_s=1.5, poll_s=1)
repo1 = clean_repo()
t1 = gate_track(repo1, SIMPLE_PASS, "t-admit")
t0 = time.time()
ok1, problems1 = sessions._gate(t1)
dur1 = time.time() - t0
check(ok1 and not problems1, "the gate itself still passes once admitted (problems=%r)" % problems1)
check(dur1 > 0.5, "high fake CPU actually delayed the gate start (%.2fs)" % dur1)
check(any("wartet: Box ausgelastet" in n or "starte trotzdem" in n for n in notes(t1["run_dir"])),
      "the admission wait is a visible note in the card's OWN actionlog: %r" % notes(t1["run_dir"]))
_CPU[0] = 10.0
SETTINGS["policy"]["load_admission"].update(wait_s=1800)


# --- 2) GATE SINGLETON: two gates on the SAME tree serialize, never overlap -
repo2 = clean_repo()
slow_body = ("import time\n"
             "print('start', flush=True)\n"
             "time.sleep(1.0)\n"
             "print('gate: PASS (1 checks)', flush=True)\n")
t2a = gate_track(repo2, slow_body, "t-first")
results = {}

def _run_first():
    results["first"] = sessions._gate(t2a)

th_first = threading.Thread(target=_run_first, daemon=True)
th_first.start()
lock = _gate_lock_for(repo2)
check(poll_until(lock.locked), "the gate lock for this tree is held while the first gate runs")

t0 = time.time()
t2b = gate_track(repo2, SIMPLE_PASS, "t-second")
ok2b, problems2b = sessions._gate(t2b)
dur2b = time.time() - t0
th_first.join(10)
check("first" in results and results["first"][0], "the first gate completed successfully")
check(ok2b and not problems2b, "the second gate (blocked, then run fresh) also passes (problems=%r)" % problems2b)
check(dur2b > 0.3, "the second call BLOCKED for roughly the first gate's remaining runtime, "
                    "not a race (%.2fs)" % dur2b)
check(not lock.locked(), "the tree's gate lock is free again after both finish")


# --- 3) SILENCE-bounded execution: a gate that keeps printing (slowly, as
#        under real load) survives past a duration an old wall-clock cap
#        would have killed; total silence still gets killed, reason on the
#        card ----------------------------------------------------------------
SETTINGS["gate_idle_s"] = 2
repo3 = clean_repo()
productive = ("import time\n"
              "for i in range(6):\n"
              "    print('step %d' % i, flush=True)\n"
              "    time.sleep(0.4)\n"
              "print('gate: PASS (1 checks)', flush=True)\n")
t3 = gate_track(repo3, productive, "t-productive")
t0 = time.time()
ok3, problems3 = sessions._gate(t3)
dur3 = time.time() - t0
check(ok3 and not problems3, "a slow-but-productive gate (never silent) completes clean (problems=%r)" % problems3)
check(dur3 > 2.0, "it really ran its full ~2.4s, past the 2s idle window that would have "
                  "killed a SILENT process (%.2fs)" % dur3)

repo4 = clean_repo()
wedged = ("import time\n"
          "print('starting', flush=True)\n"
          "time.sleep(30)\n")
t4 = gate_track(repo4, wedged, "t-wedged")
t0 = time.time()
ok4, problems4 = sessions._gate(t4)
dur4 = time.time() - t0
check(not ok4 and problems4, "a truly silent/wedged gate command still fails the gate")
check(any("no output for" in p for p in problems4),
      "killed for SILENCE, with the reason in the punch list: %r" % problems4)
check(2.0 <= dur4 < 20.0, "killed near the idle window, not a long wait (%.2fs)" % dur4)
del SETTINGS["gate_idle_s"]

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails))
    sys.exit(1)
print("gate-load-admission: all pinned - PASS")
