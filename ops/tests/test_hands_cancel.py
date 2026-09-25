# -*- coding: utf-8 -*-
"""A hands/agent run can be STOPPED by the daemon that owns it.

Owner 2026-09-25 21:44: "Stop" reached Henry while a hands run was posting on
X. Henry's only verb was a card steer - it missed ("keine Karte passt auf
'...-hands-bb3f82'"), the guard refused a kill, and the post went out four
minutes later. Paseo parity: any agent may stop any agent (cancel_agent).

Pinned through the REAL hands.spawn -> _run -> _pump -> _land path with a
real child process (and a grandchild, so the TREE kill is what is tested),
and through the real action layer:
 1. `stop` on a running run kills the whole tree, ends it "canceled",
    and tells Henry so in his next turn
 2. a QUEUED hands run is stopped before it ever starts
 3. a card verb aimed at a run id answers with the stop verb, not a card list
Run: py -3.12 ops/tests/test_hands_cancel.py
"""
import os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-handscancel-")
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from cells.copilot.chat import copilot, hands, copilot_actions
from spine.agent import proctable
from spine.http import server
copilot.ROOT = SANDBOX
hands.DAEMON_ROOT = SANDBOX                            # scratch folders stay in the sandbox
server._bg = lambda name, fn: fn()
from spine.comms import notify
notify.chat_reply = lambda *a, **k: None
copilot._schedule_bg_continue = lambda *a, **k: None
proctable._record_pid = lambda *a, **k: None        # never touch the live daemon's pid table
proctable._forget_pid = lambda *a, **k: None

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


# a child that starts a grandchild, reports it, emits one tool step, then hangs
GRANDKID = os.path.join(SANDBOX, "grandkid.pid")
CHILD = r'''
import json, subprocess, sys, time
g = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
open(%r, "w").write(str(g.pid))
print(json.dumps({"type": "assistant", "message": {"content": [
    {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "py cdp.py compose"}}]}}), flush=True)
time.sleep(120)
''' % GRANDKID
hands._popen = lambda argv, cwd, env: subprocess.Popen(
    [sys.executable, "-c", CHILD], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    stderr=subprocess.PIPE, text=True, encoding="utf-8",
    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def alive(pid):
    return any(p == pid for p, _, _ in (proctable._pid_table() or []))


def wait(pred, s=20):
    end = time.time() + s
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.2)
    return False


OWNER = "tien"
SK = copilot._skey(OWNER, None)

# 1) stop a RUNNING hands run through the action layer
hid = hands.spawn(OWNER, "Publish ONE post on X", SK)
check(wait(lambda: (hands._tasks[hid].get("steps") or []) and os.path.exists(GRANDKID)),
      "the fake run is live and has taken a step")
child = hands._tasks[hid]["pid"]
gk = int(open(GRANDKID).read())
check(alive(child) and alive(gk), "child and grandchild are running")
msg = copilot_actions._run_action({"type": "stop", "target": hid}, OWNER, "owner")
check(msg.startswith("GESTOPPT"), "stop answers with the truth: %r" % msg)
check(wait(lambda: hands._tasks[hid]["status"] == "canceled"), "run ends as canceled (got %r)" % hands._tasks[hid]["status"])
check(wait(lambda: not alive(child) and not alive(gk)), "the whole TREE is gone, grandchild included")
with copilot._pending_lock:
    pend = " ".join(copilot._pending_actions.get(SK) or [])
check("CANCELED" in pend and "CANCELLED by tien" in pend, "Henry's next turn hears it was stopped")
check(hands._active is None, "the desktop slot is free again")
again = copilot_actions._run_action({"type": "stop", "target": hid}, OWNER, "owner")
check(again.startswith("NICHT gestoppt"), "stopping a finished run says so: %r" % again)

# 2) a QUEUED hands run never starts
os.remove(GRANDKID)
first = hands.spawn(OWNER, "first job", SK)
second = hands.spawn(OWNER, "second job", SK)
check(second in hands._queue, "the second hands run waits for the desktop")
r = hands.cancel(second, actor="henry")
check(r["ok"] and hands._tasks[second]["status"] == "canceled", "queued run canceled: %r" % r)
check(second not in hands._queue, "and removed from the queue")
hands.cancel(first)
check(wait(lambda: hands._tasks[first]["status"] == "canceled"), "first run stopped too")
time.sleep(1)
check(hands._tasks[second].get("pid") is None, "the canceled queued run never got a process")

# 3) a card verb aimed at a run id points at `stop`
m = copilot_actions._run_action({"type": "steer", "card": hid, "text": "stop"}, OWNER, "owner")
check('"type": "stop"' in m and "keine Karte" in m, "steer on a run id names the stop verb: %r" % m[:120])

print("\n%d failure(s)" % len(_fails) if _fails else "\nall hands-cancel checks passed")
sys.exit(1 if _fails else 0)
