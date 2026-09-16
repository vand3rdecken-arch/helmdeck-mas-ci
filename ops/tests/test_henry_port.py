# -*- coding: utf-8 -*-
"""The always-on reader of Henry's warm chat process (cells/copilot/chat/port.py).

Owner 2026-09-16 19:04 "nur kurze Anweisung und er arbeitet fuer 20 min":
Henry's Explore sub-agent advanced ONE step per keepalive ping because the
CLI streams every sub-agent frame to stdout and nobody read the pipe between
turns - the child blocked on write. And after the task_notification the CLI
ran a turn of its own (measured with a real `claude -p` probe), whose
result frame sat in the pipe for the next ping to swallow.

Pinned here, without a model (fake process whose stdout is a blocking queue,
so timing is under the test's control):
 1. no consumer attached -> frames go to the idle handler: a launch registers,
    sub-agent chatter is ignored, the task_notification closes the task
 2. the CLI's own between-turns turn (result WITH usage) -> exactly one
    auto-continue, flagged seen=True (Henry must repeat for the OWNER)
 3. no CLI turn after the hand-back -> the fallback timer continues (seen=False)
 4. consumer attached (begin) -> frames go to the consumer's iterator, the
    idle handler sees none of them; detaching (break) hands stdout back
 5. the chat pump ignores sub-agent frames (parent_tool_use_id): their text
    never becomes Henry's reply
Run: py -3.12 ops/tests/test_henry_port.py
"""
import json, os, queue, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-port-")
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from cells.copilot.chat import copilot, henry_bg, port
copilot.ROOT = SANDBOX
from spine.agent import drivers
from spine.auth import auth
from spine.http import server

OWNER = "tien"
SK = copilot._skey(OWNER, None)
auth.list_users = lambda: [{"name": OWNER, "role": "owner"}]
drivers.argv_form_safe = lambda exe: False
copilot._schedule_compact = lambda user: None
copilot._schedule_prune = lambda user: None
server._bg = lambda name, fn: fn()
from spine.comms import notify
notify.push_fcm = lambda *a, **k: True

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


CONTINUES = []
copilot._schedule_bg_continue = lambda user, done, seen=False: CONTINUES.append((user, [d["uid"] for d in done], seen))


class _QStdout:
    """A blocking line source the test feeds - like a live pipe."""
    def __init__(self):
        self.q = queue.Queue()

    def __iter__(self):
        return self

    def __next__(self):
        line = self.q.get()
        if line is None:
            raise StopIteration
        return line

    def push(self, ev):
        self.q.put(json.dumps(ev) + "\n")


class _Proc:
    pid = 777

    def __init__(self):
        self.stdout = _QStdout()


def _settle(cond, timeout=2.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def _launch(uid, title):
    return [{"type": "assistant", "parent_tool_use_id": None, "message": {"content": [
                 {"type": "tool_use", "id": uid, "name": "Agent",
                  "input": {"description": title, "run_in_background": True, "prompt": "x"}}],
             "usage": {"input_tokens": 9, "output_tokens": 9}}},
            {"type": "user", "parent_tool_use_id": None, "message": {"content": [
                 {"type": "tool_result", "tool_use_id": uid, "content": "Async agent launched successfully. agentId: a1"}]}}]


print("henry port")
p = _Proc()
port.attach(p, lambda line: copilot._idle_frame(SK, OWNER, line))
check(getattr(p, "_hd_port", None) is not None and port.attach(p, None) is p._hd_port, "attach is idempotent")

# 1) idle: launch, chatter, notification
for ev in _launch("tu_a", "Explore onboarding"):
    p.stdout.push(ev)
check(_settle(lambda: (henry_bg.tasks(OWNER).get("bg:tu_a") or {}).get("status") == "running"),
      "idle launch frames register the agent as running")
p.stdout.push({"type": "assistant", "parent_tool_use_id": "tu_a", "message": {"content": [
    {"type": "text", "text": "SUBAGENT PROSE - must never surface"}], "usage": {"input_tokens": 1, "output_tokens": 1}}})
p.stdout.push({"type": "system", "subtype": "task_progress", "tool_use_id": "tu_a"})
p.stdout.push({"type": "system", "subtype": "task_notification", "tool_use_id": "tu_a", "status": "completed",
               "summary": "3 facts found"})
check(_settle(lambda: (henry_bg.tasks(OWNER).get("bg:tu_a") or {}).get("status") == "completed"),
      "the between-turns task_notification closes it (no ping needed)")
check(CONTINUES == [], "no continue yet - the CLI may run its own turn first")

# 2) the CLI's own turn -> one continue, seen=True
p.stdout.push({"type": "system", "subtype": "init", "session_id": "s"})
p.stdout.push({"type": "assistant", "parent_tool_use_id": None, "message": {"content": [
    {"type": "text", "text": "Recherche da, meine Fragen: ..."}], "usage": {"input_tokens": 5, "output_tokens": 5}}})
p.stdout.push({"type": "result", "result": "Recherche da", "usage": {"input_tokens": 5, "output_tokens": 5}})
check(_settle(lambda: len(CONTINUES) == 1), "the CLI's own between-turns turn triggers exactly one auto-continue")
check(CONTINUES and CONTINUES[0][1] == ["tu_a"] and CONTINUES[0][2] is True,
      "...flagged seen=True: Henry already answered into the void and must repeat for the owner (got %r)" % CONTINUES)
copilot._IDLE_FALLBACK_S = 0.3
time.sleep(0.5)
check(len(CONTINUES) == 1, "the fallback timer does not fire a second continue for a hand-back already served")

# 3) no CLI turn -> fallback continue, seen=False
del CONTINUES[:]
for ev in _launch("tu_b", "Second"):
    p.stdout.push(ev)
p.stdout.push({"type": "system", "subtype": "task_notification", "tool_use_id": "tu_b", "status": "failed",
               "summary": "boom"})
check(_settle(lambda: len(CONTINUES) == 1, timeout=2.0), "no CLI turn within the fallback window -> harness continue")
check(CONTINUES and CONTINUES[0][1] == ["tu_b"] and CONTINUES[0][2] is False, "...flagged seen=False (got %r)" % CONTINUES)

# 4) consumer attached: frames go to the consumer, not idle
del CONTINUES[:]
port.begin(p)
got = []
it = port.lines(p)
p.stdout.push({"type": "assistant", "parent_tool_use_id": None, "message": {"content": [{"type": "text", "text": "turn text"}]}})
got.append(json.loads(next(it)))
check(got[0]["message"]["content"][0]["text"] == "turn text", "with a consumer attached the frame reaches the consumer")
p.stdout.push({"type": "result", "result": "ok", "usage": {"input_tokens": 3}})
got.append(json.loads(next(it)))
check(got[1]["type"] == "result" and CONTINUES == [], "...and the idle handler never saw the consumer's result")
it.close()
check(p._hd_port.active is False, "closing the iterator detaches the consumer")
for ev in _launch("tu_c", "Third"):
    p.stdout.push(ev)
check(_settle(lambda: (henry_bg.tasks(OWNER).get("bg:tu_c") or {}).get("status") == "running"),
      "after detaching, stdout is idle-folded again")
p.stdout.q.put(None)
check(_settle(lambda: p._hd_port.eof), "EOF closes the reader")

# 5) the chat pump drops sub-agent frames
from cells.copilot.chat import copilot as _cp


class _FakeStdin:
    def write(self, s):
        return len(s)

    def flush(self):
        pass

    def close(self):
        pass


class _FakeProc:
    def __init__(self, lines):
        self.stdin = _FakeStdin(); self.stdout = iter(lines); self.returncode = 0

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return 0

    def kill(self):
        pass


SCRIPT = {"lines": []}


class _FakeSubprocess:
    PIPE = -1
    DEVNULL = -3

    @staticmethod
    def Popen(*a, **k):
        lines = [{"type": "system", "subtype": "init", "session_id": "sess-test"}] + SCRIPT["lines"]
        return _FakeProc([json.dumps(e) + "\n" for e in lines])


_cp.subprocess = _FakeSubprocess
db.chat_clear()
SCRIPT["lines"] = [
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "Echte Antwort."}],
                                      "usage": {"input_tokens": 100, "output_tokens": 5}}},
    {"type": "assistant", "parent_tool_use_id": "tu_x", "message": {"content": [{"type": "text", "text": "SUBAGENT PROSE"}],
                                                                     "usage": {"input_tokens": 1, "output_tokens": 1}}},
    {"type": "assistant", "parent_tool_use_id": "tu_x", "message": {"content": [
        {"type": "tool_use", "id": "sub1", "name": "Read", "input": {"file_path": "x"}}],
        "usage": {"input_tokens": 1, "output_tokens": 1}}},
    {"type": "result", "result": "Echte Antwort.", "session_id": "sess-test",
     "usage": {"input_tokens": 100, "output_tokens": 8}, "total_cost_usd": 0.001}]
out = _cp.chat(OWNER, "hi", role="owner")
check(out.get("reply") == "Echte Antwort.", "sub-agent prose in the stream never becomes Henry's reply (got %r)" % out.get("reply"))

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails)); sys.exit(1)
print("henry port: all pinned - PASS")
