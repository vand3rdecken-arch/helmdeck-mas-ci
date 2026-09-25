# -*- coding: utf-8 -*-
"""Henry's hand-offs are VISIBLE RUNS (owner 2026-09-25: "Am besten wenn er das
als Subagent-Prozess macht, damit man es sehen kann").

Pinned through the real code paths (chat() pump, hands._pump, history()):
 1. a background Agent launched in a board turn puts an act row with
    run="bg:<uid>" into the chat AT LAUNCH (under the owner's message)
 2. the sub-agent's own tool calls (frames with parent_tool_use_id) become
    the run's steps in history()["followups"]["bg:<uid>"] (kind "agent")
 3. a hands run's tool calls become its steps (kind "hands", its card),
    folded by hands._pump from the child's own stream
 4. followups are per user: another user's hands run is not in mine
Run: py -3.12 ops/tests/test_run_tiles.py
"""
import json, os, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
SANDBOX = tempfile.mkdtemp(prefix="hd-runtiles-")
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()
from cells.copilot.chat import copilot, hands, henry_bg
copilot.ROOT = SANDBOX
os.makedirs(os.path.join(SANDBOX, "state"), exist_ok=True)
from spine.agent import drivers, proctable
from spine.auth import auth
from spine.http import server
from spine.comms import notify

OWNER = "tien"
auth.list_users = lambda: [{"name": OWNER, "role": "owner"}, {"name": "gast", "role": "operator"}]
drivers.argv_form_safe = lambda exe: False
copilot._schedule_compact = copilot._schedule_prune = lambda user: None
copilot._schedule_bg_continue = lambda *a, **k: None
server._bg = lambda name, fn: fn()
notify.push_fcm = lambda *a, **k: True
notify.chat_reply = lambda *a, **k: None

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


class _In:
    def write(self, s): return len(s)
    def flush(self): pass
    def close(self): pass


class _P:
    pid = 5151
    def __init__(self, lines):
        self.stdin = _In()
        self.stdout = iter([json.dumps(e) + "\n" for e in lines])
        self.returncode = 0
        class _E:
            def read(self): return ""
        self.stderr = _E()
    def poll(self): return 0
    def wait(self, timeout=None): return 0
    def kill(self): pass


LINES = []


class _Sub:
    PIPE, DEVNULL = -1, -3
    Popen = staticmethod(lambda *a, **k: _P(LINES))


copilot.subprocess = _Sub

UID = "toolu_agent1"
LINES[:] = [
    {"type": "system", "subtype": "init", "session_id": "s1"},
    {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": UID, "name": "Agent",
         "input": {"description": "Gate-Logs lesen", "prompt": "lies die Logs", "run_in_background": True}}],
        "usage": {"input_tokens": 5, "output_tokens": 5}}},
    {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": UID, "content": "Async agent launched successfully. agentId: a1"}]}},
    # the sub-agent's own frames
    {"type": "assistant", "parent_tool_use_id": UID, "message": {"content": [
        {"type": "tool_use", "id": "sub1", "name": "Grep", "input": {"pattern": "FAILED"}}]}},
    {"type": "user", "parent_tool_use_id": UID, "message": {"content": [
        {"type": "tool_result", "tool_use_id": "sub1", "content": "3 hits"}]}},
    {"type": "stream_event", "event": {"type": "content_block_delta",
                                       "delta": {"type": "text_delta", "text": "Laeuft im Hintergrund."}}},
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "Laeuft im Hintergrund."}],
                                      "usage": {"input_tokens": 5, "output_tokens": 5}}},
    {"type": "result", "result": "Laeuft im Hintergrund.", "session_id": "s1",
     "usage": {"input_tokens": 5, "output_tokens": 5}, "total_cost_usd": 0.0},
]

print("run tiles")
db.chat_clear()
copilot.chat(OWNER, "warum ist das Gate rot", role="owner")
msgs = copilot.history(OWNER)["messages"]
clss = [(m.get("cls"), m.get("run")) for m in msgs]
i_you = next(i for i, m in enumerate(msgs) if m.get("cls") == "you")
i_run = next((i for i, m in enumerate(msgs) if m.get("run") == "bg:" + UID), None)
i_bot = next((i for i, m in enumerate(msgs) if m.get("cls") == "bot"), None)
check(i_run is not None, "1. launch put a run row into the chat (%r)" % clss)
check(i_run is not None and i_you < i_run < (i_bot or 99), "1. ... between the owner's message and the reply")
f = copilot.history(OWNER)["followups"].get("bg:" + UID) or {}
check(f.get("kind") == "agent" and f.get("status") == "running", "2. followups carry the agent run (%r)" % f.get("kind"))
check([(s["label"], s["status"]) for s in f.get("steps", [])][:1] and f["steps"][0]["status"] == "completed",
      "2. the sub-agent's tool call is a completed step (%r)" % f.get("steps"))

# 3) hands steps through the real _pump
hid = "h-test-1"
with hands._lock:
    hands._tasks[hid] = {"title": "Screenshot", "status": "running", "since": time.time(), "updated": time.time(),
                         "detail": "x", "pid": None, "user": OWNER, "skey": copilot._skey(OWNER, None),
                         "card": "card-42", "result": ""}
proctable._forget_pid = lambda pid: None
hp = _P([{"type": "assistant", "message": {"content": [
             {"type": "tool_use", "id": "hs1", "name": "mcp__windows-mcp__Screenshot", "input": {}}]}},
         {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "hs1", "content": "img"}]}},
         {"type": "assistant", "message": {"content": [
             {"type": "tool_use", "id": "hs2", "name": "Bash", "input": {"command": "dir"}}]}},
         {"type": "result", "result": "DONE - screenshot taken"}])
hands._pump(hid, hp)
ht = hands.tasks(OWNER).get(hid) or {}
check(ht.get("kind") == "hands" and ht.get("card") == "card-42", "3. hands descriptor carries kind + card")
check([s["status"] for s in ht.get("steps", [])] == ["completed", "running"],
      "3. hands steps folded from its own stream (%r)" % ht.get("steps"))

# 4) per user
check(hid not in hands.tasks("gast"), "4. another user's hands run is not in their followups")

print("PASS test_run_tiles" if not _fails else "FAIL test_run_tiles (%d)" % len(_fails))
sys.exit(1 if _fails else 0)
