# -*- coding: utf-8 -*-
"""Henry's hands run ONE AT A TIME, and the browser they share outlives them.

Owner 2026-09-15 18:48 "Warum Hände Prozess so buggy": Henry had fanned round
2 of the X outreach out as THREE hands actions in one turn. All three drove
the same persistent HelmDeck Chrome and the same mouse; the first run's end
took Chrome down (it was that run's child process), the other two died with
"no close frame received or sent", the next start showed "Chrome didn't shut
down correctly", and eight empty console windows (one per hands spawn of the
day) sat on the desktop.

Pinned here through the REAL hands.spawn/_kick/_run path (a fake process
stands in for claude; no model, no MCP, no browser):
 1. two hands spawned back to back: the second waits, its descriptor says so,
    and it starts only after the first has landed
 2. the running hands holds locks._desktop_lock for its whole life, and
    releases it when done (a card's desktop tool sees "busy", not a race)
 3. both land in order, the queue drains, nothing is left active
 4. a spawn failure lands as FAILED and still frees the desktop
 5. browsercap._spawn_orphan starts a process whose parent is NOT us
Run: py -3.12 ops/tests/test_hands_queue.py
"""
import json, os, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-handsq-")
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from cells.copilot.chat import copilot, hands
from spine.agent import proctable
from spine.git import locks

hands.DAEMON_ROOT = SANDBOX
proctable._PIDFILE = os.path.join(SANDBOX, "driver_pids.json")
LANDED = []
copilot._append_log = lambda user, rows: LANDED.append(rows[0]["text"])

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


class _Stdin:
    def write(self, s): return len(s)
    def close(self): pass


class _Stderr:
    def read(self): return ""


class _FakeProc:
    """Emits one tool_use, sleeps `hold` seconds, then the result - like a
    hands run that takes a while on the desktop."""
    _n = [40000]

    def __init__(self, hold, result="DONE\n- did it", fail=False):
        _FakeProc._n[0] += 1
        self.pid = _FakeProc._n[0]
        self.hold, self.result, self.fail = hold, result, fail
        self.stdin, self.stderr = _Stdin(), _Stderr()
        self.stdout = self._lines()

    def _lines(self):
        yield json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "t", "name": "mcp__helmdeck-browser__navigate", "input": {}}]}}) + "\n"
        time.sleep(self.hold)
        yield json.dumps({"type": "result", "result": self.result, "is_error": self.fail}) + "\n"

    def wait(self): return 0
    def poll(self): return 0


TIMELINE = []          # (event, hid, t)


def _fake_popen(argv, cwd, env):
    hid = os.path.basename(cwd)
    TIMELINE.append(("start", hid, time.time(), locks._desktop_lock.locked()))
    return _FakeProc(hold=1.0)


hands._popen = _fake_popen

print("hands queue")
SKEY = copilot._skey("owner", None)
a = hands.spawn("owner", "erste Aufgabe", SKEY, why="test")
b = hands.spawn("owner", "zweite Aufgabe", SKEY, why="test")
time.sleep(0.3)
ta, tb = hands.tasks()[a], hands.tasks()[b]
check(hands._active == a, "first spawn owns the desktop (%r)" % hands._active)
check(b in hands._queue, "second spawn is queued, not started")
check(tb["status"] == "running" and tb["result"].startswith("wartet: 1"),
      "queued descriptor says it waits behind 1 (%r)" % tb["result"])
check(ta["result"].startswith("1 Schritte"), "running descriptor shows live steps (%r)" % ta["result"])
check(locks._desktop_lock.locked(), "the running hands HOLDS the desktop lock")
check(not locks._desktop_lock.acquire(blocking=False), "...so a card's desktop tool would see busy")

for _ in range(80):
    if hands._active is None and not hands._queue:
        break
    time.sleep(0.1)
starts = [x for x in TIMELINE if x[0] == "start"]
check([x[1] for x in starts] == [a, b], "runs started in spawn order, one after the other")
check(len(starts) == 2 and starts[1][2] >= starts[0][2] + 1.0,
      "second started only after the first finished (%.2fs apart)" % (starts[1][2] - starts[0][2]))
check(all(x[3] for x in starts), "every run started while holding the desktop lock")
check(hands.tasks()[a]["status"] == "completed" and hands.tasks()[b]["status"] == "completed",
      "both completed")
check(len(LANDED) == 2 and "erste" in LANDED[0] and "zweite" in LANDED[1], "both landed, in order")
check(hands._active is None and not hands._queue, "queue drained, nothing active")
check(not locks._desktop_lock.locked(), "desktop lock released at the end")

print("\nspawn failure frees the desktop")
def _broken_popen(argv, cwd, env):
    raise RuntimeError("no claude here")
hands._popen = _broken_popen          # BEFORE the spawn - _kick starts the run at once
c = hands.spawn("owner", "boom", SKEY)
for _ in range(50):
    if hands._active is None:
        break
    time.sleep(0.1)
check(hands.tasks()[c]["status"] == "failed" and "spawn" in hands.tasks()[c]["result"],
      "spawn error lands as FAILED (%r)" % hands.tasks()[c]["result"][:60])
check(not locks._desktop_lock.locked(), "...and the desktop lock is free again")

print("\nbrowser launcher: the browser is nobody's child")
from spine.media import browsercap
mark = os.path.join(SANDBOX, "ppid.txt")
browsercap._spawn_orphan([sys.executable, "-c",
                          "import os; open(%r, 'w').write(str(os.getppid()))" % mark])
for _ in range(50):
    if os.path.exists(mark) and open(mark).read().strip():
        break
    time.sleep(0.1)
ppid = int(open(mark).read().strip() or 0)
check(ppid and ppid != os.getpid(), "spawned process' parent is not this process (ppid=%s, us=%s)" % (ppid, os.getpid()))
try:
    alive = {p for p, _pp, _exe in proctable._pid_table()}
    check(ppid not in alive, "...and that parent (the launcher) is already gone")
except Exception as e:
    print("  skip  pid table unavailable: %s" % e)

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails)); sys.exit(1)
print("hands queue: all pinned - PASS")
