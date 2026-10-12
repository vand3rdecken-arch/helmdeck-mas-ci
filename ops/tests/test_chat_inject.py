# -*- coding: utf-8 -*-
"""STEER INTO HENRY'S RUNNING TURN (copilot.try_inject + POST /chat steer_only).

Owner 2026-09-25: "Henry main chat kann direkte tool calls machen, aber das
blockiert diesen Chat." MEASURED the same day against the real CLI (claude -p
--input-format stream-json, haiku): a user frame written to stdin while a
Bash tool runs is folded into THAT turn and the turn ends with ONE result
("DONE1 MANGO"). So a message typed mid-turn rides into the running turn
instead of waiting on the turn lock.

Drives the REAL chat() pump on the persistent-port path, with a fake warm
process whose stdout the test feeds line by line (timing under control):
 1. before any tool call -> not absorbable (a frame during the final answer
    would open a second CLI turn nobody pumps)
 2. while a tool call is open -> absorbed: the frame reaches the SAME
    process's stdin with the owner's text, the 'you' row is persisted now
 3. after the tool result -> not absorbable again
 4. after the turn -> not absorbable, registry empty
 5. POST /chat steer_only answers at once: absorbed false when idle, and
    runs NO turn (no bot row, no process write)
Run: py -3.12 ops/tests/test_chat_inject.py
"""
import json, os, queue, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-inject-")
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from cells.copilot.chat import copilot
copilot.ROOT = SANDBOX
os.makedirs(os.path.join(SANDBOX, "state"), exist_ok=True)
from spine.agent import drivers
from spine.auth import auth
from spine.http import server

OWNER = "tien"
auth.list_users = lambda: [{"name": OWNER, "role": "owner"}]
drivers.argv_form_safe = lambda exe: True          # the warm persistent-port path
copilot._schedule_compact = lambda user, agent=False, immediate=False: None
copilot._schedule_prune = lambda user: None
server._bg = lambda name, fn: fn()
from spine.comms import notify
notify.push_fcm = lambda *a, **k: True

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


class _Stdin:
    def __init__(self):
        self.sent = []
    def write(self, s):
        self.sent.append(s)
        return len(s)
    def flush(self):
        pass
    def close(self):
        pass


class _QStdout:
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


class _WarmProc:
    pid = 4242
    def __init__(self):
        self.stdin = _Stdin()
        self.stdout = _QStdout()
    def poll(self):
        return None
    def kill(self):
        pass
    def wait(self, timeout=None):
        return 0


P = _WarmProc()
copilot._persist_get = lambda skey, cli_model, sid, system: (P, False)


def _settle(cond, timeout=3.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def msgs():
    return (copilot.history(OWNER) or {}).get("messages") or []


print("steer into the running turn")
db.chat_clear()
out = {}
th = threading.Thread(target=lambda: out.update(copilot.chat(OWNER, "pruef den Build", role="owner")),
                      daemon=True)
th.start()
check(_settle(lambda: OWNER in copilot._inject), "running board turn registers as injectable")
P.stdout.push({"type": "system", "subtype": "init", "session_id": "s1"})
P.stdout.push({"type": "stream_event", "event": {"type": "content_block_delta",
               "delta": {"type": "text_delta", "text": "Moment."}}})
time.sleep(0.2)
check(copilot.try_inject(OWNER, "zu frueh") is False, "1. no open tool call -> not absorbed")

P.stdout.push({"type": "assistant", "message": {"content": [
    {"type": "tool_use", "id": "tA", "name": "Bash", "input": {"command": "sleep 12"}}],
    "usage": {"input_tokens": 10, "output_tokens": 2}}})
check(_settle(lambda: "tA" in copilot._inject.get(OWNER, {}).get("tools", ())),
      "tool_use folded as an open tool window")
n_before = len(P.stdin.sent)
ok = copilot.try_inject(OWNER, "und nimm MANGO mit", client_msg_id="mid-7")
check(ok is True, "2. open tool call -> absorbed")
frames = [json.loads(s) for s in P.stdin.sent[n_before:]]
check(len(frames) == 1 and frames[0]["type"] == "user"
      and "und nimm MANGO mit" in frames[0]["message"]["content"],
      "the owner's text went into the SAME warm process as a user frame")
yous = [m for m in msgs() if m.get("cls") == "you"]
check(any(m.get("text") == "und nimm MANGO mit" and m.get("client_msg_id") == "mid-7" for m in yous),
      "the absorbed message is persisted at submission with its client id")

P.stdout.push({"type": "user", "message": {"content": [
    {"type": "tool_result", "tool_use_id": "tA", "content": "ok"}]}})
check(_settle(lambda: not copilot._inject.get(OWNER, {}).get("tools")), "tool_result closes the window")
check(copilot.try_inject(OWNER, "zu spaet") is False, "3. after the tool result -> not absorbed")

P.stdout.push({"type": "stream_event", "event": {"type": "content_block_delta",
               "delta": {"type": "text_delta", "text": "Build gruen. MANGO."}}})
P.stdout.push({"type": "assistant", "message": {"content": [{"type": "text", "text": "Build gruen. MANGO."}],
    "usage": {"input_tokens": 10, "output_tokens": 3}}})
P.stdout.push({"type": "result", "result": "Build gruen. MANGO.", "session_id": "s1",
               "usage": {"input_tokens": 10, "output_tokens": 3}, "total_cost_usd": 0.001})
th.join(10)
check(not th.is_alive(), "the turn ended on its ONE result")
check("MANGO" in (out.get("reply") or ""), "the one reply answers both messages (got %r)" % out.get("reply"))
check(OWNER not in copilot._inject, "4. registry cleared at turn end")
check(copilot.try_inject(OWNER, "nachher") is False, "4. idle -> not absorbed")

# 5) the route: steer_only never runs a turn
from cells.copilot.routes import routes_copilot


class _H:
    def __init__(self):
        self.sent = None
    def _send(self, code, body, *a, **k):
        self.sent = (code, json.loads(body))


h = _H()
n_before = len(P.stdin.sent)
bots_before = len([m for m in msgs() if m.get("cls") == "bot"])
routes_copilot.chat_post(h, {"name": OWNER, "role": "owner"},
                         {"text": "noch was", "steer_only": True, "mid": "m9"})
check(h.sent and h.sent[0] == 200 and h.sent[1].get("absorbed") is False,
      "5. steer_only on an idle chat answers absorbed=false at once (got %r)" % (h.sent,))
check(len(P.stdin.sent) == n_before and
      len([m for m in msgs() if m.get("cls") == "bot"]) == bots_before,
      "5. steer_only ran no turn")

print("PASS test_chat_inject" if not _fails else "FAIL test_chat_inject (%d)" % len(_fails))
sys.exit(1 if _fails else 0)
