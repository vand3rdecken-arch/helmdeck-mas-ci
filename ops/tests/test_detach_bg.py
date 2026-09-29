# -*- coding: utf-8 -*-
"""ops/tools/detach.py + the daemon's detached sweep, on the REAL path: a detached
process ends -> the card is auto-continued with the log tail; a daemon restart
mid-run (sweep_zombies at startup) neither drops the entry nor the wake; a
recycled PID (same pid, other creation time) never reads as 'still running'."""
import os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, DAEMON)

SANDBOX = tempfile.mkdtemp(prefix="hd-det-")
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()
from spine.ops import runs, procwatch
runs.REC = os.path.join(SANDBOX, "runs"); os.makedirs(runs.REC, exist_ok=True)
from cells.engineer.cards import sessions, sessions_bg, lifecycle
sessions.REC = runs.REC
SPOOL = os.path.join(SANDBOX, "spool")
os.environ["HELMDECK_DETACH_DIR"] = SPOOL

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _track(tid):
    return sessions._find(sessions._load(), tid)


def _card(tid):
    rd = os.path.join(runs.REC, tid); os.makedirs(rd, exist_ok=True)
    sessions._save([{"id": tid, "task": "t", "status": "needs_you", "lane": "working",
                     "run_dir": rd, "waiting_on": "you"}])


steered = []
sessions.steer = lambda tid, text, **kw: steered.append((tid, text))


def _wait_steer(n=1, s=5):
    end = time.time() + s
    while len(steered) < n and time.time() < end:
        time.sleep(0.1)


# --- 1) a detached job ends -> the card is woken with the log tail -----------
_card("det1")
log = os.path.join(SANDBOX, "job.log")
env = dict(os.environ, HELMDECK_CARD="det1")
job = "import time; time.sleep(3); print('CHAIN-FINISHED-OK'); raise SystemExit(3)"
r = subprocess.run([sys.executable, os.path.join(DAEMON, "ops", "tools", "detach.py"), log,
                    "--title", "chain", "--", sys.executable, "-c", job],
                   env=env, capture_output=True, text=True, timeout=30)
check(r.returncode == 0, "detach.py returns at once: " + r.stdout.strip())

sessions_bg._sweep_background()
t = _track("det1")
d = [v for v in (t.get("bg_tasks") or {}).values() if v.get("detached")]
check(len(d) == 1 and d[0]["status"] == "running", "sweep registers it as a running background task")
check(t.get("waiting_on") == "background", "card is parked on it (waiting_on=background)")
check(not steered, "no wake while it still runs")

# --- 2) daemon restart mid-run: entry + wait survive ---------------------------
lifecycle.sweep_zombies(0)
t = _track("det1")
d = [v for v in t["bg_tasks"].values() if v.get("detached")]
check(d[0]["status"] == "running" and t.get("waiting_on") == "background",
      "startup sweep leaves a live detached job alone")
check(sessions_bg.running_bg(t) and not sessions_bg.running_bg(t, killable_only=True),
      "it is visible as running but does not block a restart")

time.sleep(4)   # the job sleeps 3s
sessions_bg._sweep_background()
_wait_steer()
t = _track("det1")
d = [v for v in t["bg_tasks"].values() if v.get("detached")]
check(d[0]["status"] == "failed" and "exit 3" in d[0]["result"] and "CHAIN-FINISHED-OK" in d[0]["result"],
      "ended job folds to failed with exit code + log tail")
check(len(steered) == 1 and steered[0][0] == "det1" and "CHAIN-FINISHED-OK" in steered[0][1],
      "card is auto-continued with the log tail (existing auto-continue path)")
check(not [n for n in os.listdir(SPOOL)], "spool record cleaned up")

# --- 3) PID reuse: same pid, different creation time = gone ---------------------
ct = procwatch.create_time(os.getpid())
check(procwatch.alive(os.getpid(), ct), "own pid+ctime reads alive")
check(not procwatch.alive(os.getpid(), ct + 10_000_000), "recycled pid (other ctime) reads gone")

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails)); sys.exit(1)
print("detach-bg: all pinned - PASS")
