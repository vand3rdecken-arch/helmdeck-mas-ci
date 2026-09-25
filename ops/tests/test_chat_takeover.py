# -*- coding: utf-8 -*-
"""A NEW OWNER MESSAGE TAKES OVER HENRY'S RUNNING TURN, and his sub-agents are
own processes that survive it (owner 2026-09-25: "ich sehe nur Tool-Calls und
nicht meine Nachricht ... was bringt es, wenn er mir spaeter antwortet" /
"wie Paseo - Thread oder Subprocess").

MEASURED the same day (claude -p stream-json, haiku): a soft `interrupt`
control request ends the running turn (result error_during_execution) and the
process answers the next user frame at once - but it also STOPS every CLI
background agent of that process. Hence: takeover by interrupt, sub-agents as
daemon processes (hands.spawn kind="agent"), CLI Agent/Task refused in chat.

Drives the REAL chat() pump on the warm-port path + the real route + the
real action runner + the guard hook as a subprocess:
 1. POST /chat steer_only while a turn runs -> absorbed, an interrupt control
    request reaches the SAME process, the owner's row is persisted at once
 2. the interrupted turn ends quietly: no bot row, no error row
 3. the new message runs as its own turn right behind it; its prompt carries
    the harness note UNTERBROCHEN with what was cut off; its answer lands
 4. the `agent` action starts an own process with no desktop queue, its act
    row carries run=<id> (agent tile), it lands kind "agent", wakes Henry
    (bg-continue) and writes no second "Haende" box
 5. the guard refuses the CLI Agent/Task in Henry's chat, even in background
Run: py -3.12 ops/tests/test_chat_takeover.py
"""
import json, os, queue, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-takeover-")
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from cells.copilot.chat import copilot, hands
from cells.copilot.chat import copilot_actions
copilot.ROOT = SANDBOX
os.makedirs(os.path.join(SANDBOX, "state"), exist_ok=True)
from spine.agent import drivers, proctable
from spine.auth import auth
from spine.http import server
from spine.comms import notify

OWNER = "tien"
auth.list_users = lambda: [{"name": OWNER, "role": "owner"}]
drivers.argv_form_safe = lambda exe: True          # the warm persistent-port path
copilot._schedule_compact = lambda user: None
copilot._schedule_prune = lambda user: None
server._bg = lambda name, fn: fn()
notify.push_fcm = lambda *a, **k: True
notify.chat_reply = lambda *a, **k: None
proctable._forget_pid = lambda pid: None
proctable._record_pid = lambda pid, t: None

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
    pid = 4343
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


def _settle(cond, timeout=10.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def msgs():
    return (copilot.history(OWNER) or {}).get("messages") or []


def frames(since=0):
    out = []
    for s in P.stdin.sent[since:]:
        try:
            out.append(json.loads(s))
        except ValueError:
            pass
    return out


print("new message takes over")
db.chat_clear()
out_a = {}
th = threading.Thread(target=lambda: out_a.update(copilot.chat(OWNER, "recherchier die Website", role="owner")),
                      daemon=True)
th.start()
check(_settle(lambda: OWNER in copilot._inject), "turn A runs")
P.stdout.push({"type": "system", "subtype": "init", "session_id": "s1"})
P.stdout.push({"type": "assistant", "message": {"content": [
    {"type": "tool_use", "id": "tA", "name": "Bash", "input": {"command": "curl -s https://helmdeck.de"}}],
    "usage": {"input_tokens": 10, "output_tokens": 2}}})
time.sleep(0.2)

from cells.copilot.routes import routes_copilot


class _H:
    def __init__(self):
        self.sent = None
    def _send(self, code, body, *a, **k):
        self.sent = (code, json.loads(body))


h = _H()
n0 = len(P.stdin.sent)
routes_copilot.chat_post(h, {"name": OWNER, "role": "owner"},
                         {"text": "Check Posthog", "steer_only": True, "mid": "m2"})
check(h.sent and h.sent[1].get("absorbed") is True, "1. steer_only while running -> absorbed (%r)" % (h.sent,))
ints = [f for f in frames(n0) if f.get("type") == "control_request"
        and (f.get("request") or {}).get("subtype") == "interrupt"]
check(len(ints) == 1, "1. an interrupt control request reached Henry's process")
check(_settle(lambda: any(m.get("cls") == "you" and m.get("text") == "Check Posthog"
                          and m.get("client_msg_id") == "m2" for m in msgs())),
      "1. the owner's message is in the chat at once")

# the CLI's answer to the interrupt (measured shape)
P.stdout.push({"type": "user", "message": {"content": [
    {"type": "tool_result", "tool_use_id": "tA", "is_error": True,
     "content": "The user doesn't want to proceed with this tool use."}]}})
P.stdout.push({"type": "control_response", "response": {"subtype": "success", "request_id": "x"}})
P.stdout.push({"type": "result", "subtype": "error_during_execution", "is_error": True, "result": None,
               "session_id": "s1", "usage": {"input_tokens": 10, "output_tokens": 2}})
th.join(10)
check(not th.is_alive() and out_a.get("superseded") is True, "2. turn A ended as superseded (%r)" % out_a)
check(not any(m.get("cls") in ("bot", "error") for m in msgs()), "2. no bot row, no error row for turn A")

# turn B = the takeover thread; its prompt is written once turn A released the lock
check(_settle(lambda: any(f.get("type") == "user" and "Check Posthog" in json.dumps(f) for f in frames(n0))),
      "3. the new message ran as its own turn in the same process")
fb = [f for f in frames(n0) if f.get("type") == "user" and "Check Posthog" in json.dumps(f)][-1]
body = fb["message"]["content"] if isinstance(fb["message"]["content"], str) else json.dumps(fb)
check("UNTERBROCHEN" in body and "recherchier die Website" in body,
      "3. it tells Henry what was cut off")
P.stdout.push({"type": "assistant", "message": {"content": [{"type": "text", "text": "PostHog: 42 Besuche heute."}],
    "usage": {"input_tokens": 10, "output_tokens": 3}}})
P.stdout.push({"type": "result", "result": "PostHog: 42 Besuche heute.", "session_id": "s1",
               "usage": {"input_tokens": 10, "output_tokens": 3}, "total_cost_usd": 0.001})
check(_settle(lambda: any(m.get("cls") == "bot" and "42" in (m.get("text") or "") for m in msgs())),
      "3. the new message got its answer")

# 4) the agent action: own process, no desktop queue, tile, wake
print("agent action")
woke = []
copilot._schedule_bg_continue = lambda user, done, seen=False: woke.append(done)


class _AgentProc:
    pid = 5353
    def __init__(self):
        self.stdin = _Stdin()
        self.stdout = iter([json.dumps(e) + "\n" for e in [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "g1", "name": "Grep", "input": {"pattern": "posthog"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "g1", "content": "x"}]}},
            {"type": "result", "result": "DONE - PostHog-Token steht in analytics.ts:12"}]])
        class _E:
            def read(self): return ""
        self.stderr = _E()
    def wait(self, timeout=None):
        return 0
    def poll(self):
        return 0


spawned = []
hands._popen = lambda argv, cwd, env: (spawned.append(argv), _AgentProc())[1]
active_before = hands._active
a = {"type": "agent", "task": "wo steht der PostHog-Token", "why": "Owner fragt"}
res = copilot_actions._run_action(a, OWNER, "owner")
rid = a.get("_run") or ""
check(res.startswith("Hintergrund-Agent:") and "-agent-" in rid, "4. agent action started a run (%r)" % res)
check(_settle(lambda: (hands.tasks(OWNER).get(rid) or {}).get("status") == "completed"),
      "4. it ran and landed")
check(hands._active is active_before and rid not in hands._queue, "4. it never touched the desktop queue")
argv = " ".join(spawned[-1]) if spawned else ""
check("windows-mcp" not in argv and "--strict-mcp-config" in argv, "4. lean: no machine MCP servers")
d = hands.tasks(OWNER).get(rid) or {}
check(d.get("kind") == "agent" and "analytics.ts" in (d.get("result") or ""), "4. descriptor kind agent + report")
check(woke and woke[-1][0].get("uid") == rid, "4. its report woke Henry")
check(not any(m.get("hands") == rid and m.get("cls") == "hands" for m in msgs()), "4. no second 'Haende' box")
check((db.runs_get([rid]).get(rid) or {}).get("status") == "completed", "4. persisted for the tile")


# 5) the guard
def guard(tool, ti):
    env = dict(os.environ)
    for k in ("HELMDECK_WORKTREE", "HELMDECK_CHAT_USER"):
        env.pop(k, None)
    env["HELMDECK_SURFACE"] = "copilot"
    p = subprocess.run([sys.executable, os.path.join(ROOT, "ops", "tools", "card_tool_guard.py")],
                       input=json.dumps({"tool_name": tool, "tool_input": ti}), capture_output=True,
                       text=True, env=env, timeout=60)
    try:
        return (json.loads((p.stdout or "").strip()).get("hookSpecificOutput") or {}).get("permissionDecision")
    except ValueError:
        return None


check(guard("Agent", {"description": "x", "prompt": "y", "run_in_background": True}) == "deny",
      "5. background CLI Agent in Henry's chat is refused")
check(guard("Task", {"description": "x", "prompt": "y"}) == "deny", "5. Task too")

print("PASS test_chat_takeover" if not _fails else "FAIL test_chat_takeover (%d)" % len(_fails))
sys.exit(1 if _fails else 0)
