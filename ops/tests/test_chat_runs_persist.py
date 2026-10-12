# -*- coding: utf-8 -*-
"""Henry's delegated runs outlive the in-memory registry, and his chat never
waits on a sub-agent (owner 2026-09-25: "Henry blockiert den Chat ... als
Subagent-Prozess, damit man es sehen kann").

Pinned through the real code paths (chat() pump, henry_bg.fold, hands._pump,
history(), the guard hook as a real subprocess):
 1. a background Agent's launch writes its run row to db.chat_runs
 2. its task_notification closes that row with the summary
 3. registry forgotten (hour window / daemon restart): history() still serves
    the run for the tile in the chat, from the db - status + report + steps
 4. a hands run's landing writes its final descriptor; same history() path
 5. rows are per account
 6. boot reconcile closes only runs a PREVIOUS daemon left running, with why
 7. finish_all (Henry's process died) persists the failed state
 8. the guard hook denies the CLI Agent/Task in Henry's chat surface
    (foreground AND background), and leaves worker cards alone
 9. the inline budget: 6 inline calls per board turn (turn = the daemon's
    chat_turns.json stamp), the 7th refused; none after 90 s
Run: py -3.12 ops/tests/test_chat_runs_persist.py
"""
import json, os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
SANDBOX = tempfile.mkdtemp(prefix="hd-chatruns-")
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
copilot._schedule_compact = copilot._schedule_prune = lambda user, agent=False, immediate=False: None
copilot._schedule_bg_continue = lambda *a, **k: None
server._bg = lambda name, fn: fn()
notify.push_fcm = lambda *a, **k: True
notify.chat_reply = lambda *a, **k: None
proctable._forget_pid = lambda pid: None

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
    pid = 5252
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

UID = "toolu_persist1"
LINES[:] = [
    {"type": "system", "subtype": "init", "session_id": "s1"},
    {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": UID, "name": "Agent",
         "input": {"description": "Gate-Logs lesen", "prompt": "lies die Logs", "run_in_background": True}}],
        "usage": {"input_tokens": 5, "output_tokens": 5}}},
    {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": UID, "content": "Async agent launched successfully. agentId: a1"}]}},
    {"type": "assistant", "parent_tool_use_id": UID, "message": {"content": [
        {"type": "tool_use", "id": "sub1", "name": "Grep", "input": {"pattern": "FAILED"}}]}},
    {"type": "user", "parent_tool_use_id": UID, "message": {"content": [
        {"type": "tool_result", "tool_use_id": "sub1", "content": "3 hits"}]}},
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "Laeuft im Hintergrund."}],
                                      "usage": {"input_tokens": 5, "output_tokens": 5}}},
    {"type": "result", "result": "Laeuft im Hintergrund.", "session_id": "s1",
     "usage": {"input_tokens": 5, "output_tokens": 5}, "total_cost_usd": 0.0},
]

print("chat runs persist")
db.chat_clear()
copilot.chat(OWNER, "warum ist das Gate rot", role="owner")
row = db.runs_get(["bg:" + UID]).get("bg:" + UID) or {}
check(row.get("status") == "running" and row.get("title") == "Gate-Logs lesen",
      "1. launch wrote the run row (%r)" % row.get("status"))

skey = copilot._skey(OWNER, None)
henry_bg.fold(skey, {"type": "system", "subtype": "task_notification", "tool_use_id": UID,
                     "status": "completed", "summary": "3 FAILED-Zeilen im Gate-Log, Ursache: Timeout"})
row = db.runs_get(["bg:" + UID]).get("bg:" + UID) or {}
check(row.get("status") == "completed" and "Timeout" in (row.get("result") or ""),
      "2. task_notification closed the row with the summary (%r)" % row.get("status"))
check(any(s.get("label") for s in row.get("steps") or []), "2. ... and its steps (%r)" % row.get("steps"))

# 3) the registry forgets (restart / hour window) - the tile must not
with henry_bg._lock:
    henry_bg._tasks.clear()
f = copilot.history(OWNER)["followups"].get("bg:" + UID) or {}
check(f.get("status") == "completed" and "Timeout" in (f.get("result") or ""),
      "3. history() serves the forgotten run from the db (%r)" % f.get("status"))

# 4) hands: its landing persists the final state
hid = "h-persist-1"
with hands._lock:
    hands._tasks[hid] = {"title": "Screenshot", "status": "running", "since": time.time(), "updated": time.time(),
                         "detail": "x", "pid": None, "user": OWNER, "skey": skey, "card": None, "result": ""}
hands._pump(hid, _P([
    {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "hs1", "name": "Bash", "input": {"command": "dir"}}]}},
    {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "hs1", "content": "ok"}]}},
    {"type": "result", "result": "DONE - Screenshot liegt auf dem Desktop"}]))
with hands._lock:
    hands._tasks.clear()
msgs = copilot.history(OWNER)["messages"]
check(any(m.get("hands") == hid for m in msgs), "4. the hands report row is in the chat")
f = copilot.history(OWNER)["followups"].get(hid) or {}
check(f.get("status") == "completed" and f.get("kind") == "hands" and "Desktop" in (f.get("result") or ""),
      "4. history() serves the landed hands run from the db (%r)" % f.get("status"))

# 5) per account
check(db.runs_get([hid], account="gast") == {} and hid in db.runs_get([hid], account=OWNER),
      "5. another account does not get my run")

# 6) boot reconcile
now = time.time()
db.chat_run_put("bg:old", OWNER, {"title": "alt", "status": "running", "since": now - 900, "updated": now - 900,
                             "detail": "", "result": "", "kind": "agent", "steps": []})
db.chat_run_put("bg:new", OWNER, {"title": "neu", "status": "running", "since": now + 1, "updated": now + 1,
                             "detail": "", "result": "", "kind": "agent", "steps": []})
n = db.runs_close_running(now, "der Daemon wurde neu gestartet")
got = db.runs_get(["bg:old", "bg:new"])
check(n == 1 and got["bg:old"]["status"] == "failed" and "neu gestartet" in got["bg:old"]["result"],
      "6. a prior daemon's running run is closed with the reason (n=%d)" % n)
check(got["bg:new"]["status"] == "running", "6. a run of THIS daemon life is left alone")

# 7) finish_all persists
henry_bg.fold(skey, {"type": "assistant", "message": {"content": [
    {"type": "tool_use", "id": "toolu_fa", "name": "Agent",
     "input": {"description": "lang", "prompt": "x", "run_in_background": True}}]}}, user=OWNER)
henry_bg.fold(skey, {"type": "user", "message": {"content": [
    {"type": "tool_result", "tool_use_id": "toolu_fa", "content": "Async agent launched"}]}}, user=OWNER)
henry_bg.finish_all(skey, "Henrys Chat-Prozess wurde beendet")
r = db.runs_get(["bg:toolu_fa"]).get("bg:toolu_fa") or {}
check(r.get("status") == "failed" and "beendet" in (r.get("result") or ""),
      "7. finish_all persisted the failed run (%r)" % r.get("status"))


# 8) the guard hook, as the CLI runs it
def guard(tool, ti, surface, user=None, state=None):
    env = dict(os.environ)
    for k in ("HELMDECK_WORKTREE", "HELMDECK_SURFACE", "HELMDECK_CHAT_USER", "HELMDECK_STATE_DIR"):
        env.pop(k, None)
    if surface:
        env["HELMDECK_SURFACE"] = surface
    if user:
        env["HELMDECK_CHAT_USER"] = user
    env["HELMDECK_STATE_DIR"] = state or SANDBOX
    p = subprocess.run([sys.executable, os.path.join(ROOT, "ops", "tools", "card_tool_guard.py")],
                       input=json.dumps({"tool_name": tool, "tool_input": ti}), capture_output=True,
                       text=True, env=env, timeout=60)
    out = (p.stdout or "").strip()
    try:
        return (json.loads(out).get("hookSpecificOutput") or {}).get("permissionDecision") or "none"
    except ValueError:
        return "none"


check(guard("Agent", {"description": "x", "prompt": "y"}, "copilot") == "deny",
      "8. foreground Agent in Henry's chat is denied")
check(guard("Task", {"description": "x", "prompt": "y"}, "copilot") == "deny",
      "8. foreground Task in Henry's chat is denied")
check(guard("Agent", {"description": "x", "prompt": "y", "run_in_background": True}, "copilot") == "deny",
      "8. background CLI Agent in Henry's chat is refused too (it dies on an interrupt - use `agent`)")
check(guard("Agent", {"description": "x", "prompt": "y"}, "") != "deny",
      "8. a worker card's foreground Agent is not this rule's business")

# 9) the inline budget: a board turn gets 6 inline calls, then hands off
STATE = os.path.join(SANDBOX, "budget-state")
os.makedirs(STATE, exist_ok=True)


def turn(stamp):
    with open(os.path.join(STATE, "chat_turns.json"), "w", encoding="utf-8") as f:
        json.dump({OWNER: stamp} if stamp else {}, f)


turn(time.time())
got = [guard("Bash", {"command": "git status"}, "copilot", OWNER, STATE) for _ in range(6)]
check("deny" not in got, "9. six inline calls in one turn pass (%r)" % got)
check(guard("Bash", {"command": "git log"}, "copilot", OWNER, STATE) == "deny",
      "9. the seventh inline call is refused")
turn(time.time() + 1)
check(guard("Bash", {"command": "git status"}, "copilot", OWNER, STATE) != "deny",
      "9. a NEW turn starts a fresh budget")
turn(time.time() - 120)
check(guard("Bash", {"command": "git status"}, "copilot", OWNER, STATE) == "deny",
      "9. no inline call starts later than 90 s into the turn (time window)")
turn(None)
for _ in range(8):
    last = guard("Bash", {"command": "git status"}, "copilot", OWNER, STATE)
check(last != "deny", "9. no turn witness (not a board turn) = no budget")
turn(time.time() + 2)
for _ in range(8):
    last = guard("Bash", {"command": "git status"}, "", None, STATE)
check(last != "deny", "9. a worker card (no chat surface) is never budgeted")

print("PASS test_chat_runs_persist" if not _fails else "FAIL test_chat_runs_persist (%d)" % len(_fails))
sys.exit(1 if _fails else 0)
