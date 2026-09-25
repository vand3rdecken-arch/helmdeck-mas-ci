# -*- coding: utf-8 -*-
"""THE OWNER'S MESSAGE OUTRANKS A BACKGROUND JUDGEMENT (owner 2026-09-25
22:21, screenshot "Warum eingereiht": a follow_up judgement - copilot.judge,
a turn in Henry's own session - held the chat's turn lock, and "Klaere das
jetzt" sat under "Wartet auf den laufenden Turn").

Real code paths, fake processes:
 1. chat() while judge() holds the lock stops the judge process at once and
    runs the owner's turn (it does not wait out the judgement)
 2. judge() raises JudgePreempted and does NOT advance the session pointer
 3. the broker counts a preempted round as NO attempt (2-attempt cap is for
    judgements), a real failure still counts
Run: py -3.12 ops/tests/test_judge_preempt.py
"""
import json, os, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
SANDBOX = tempfile.mkdtemp(prefix="hd-preempt-")
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()
from cells.copilot.chat import copilot
copilot.ROOT = SANDBOX
os.makedirs(os.path.join(SANDBOX, "state"), exist_ok=True)
from spine.agent import drivers, proctable
from spine.auth import auth
from spine.http import server
from spine.comms import notify

OWNER = "tien"
auth.list_users = lambda: [{"name": OWNER, "role": "owner"}]
drivers.argv_form_safe = lambda exe: False
copilot._schedule_compact = copilot._schedule_prune = lambda user: None
server._bg = lambda name, fn: fn()
notify.push_fcm = lambda *a, **k: True
notify.chat_reply = lambda *a, **k: None
copilot.owner_name = lambda: OWNER
proctable._tree_kill = lambda p, grace=2.0: p.kill()

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


class _In:
    def write(self, s): return len(s)
    def flush(self): pass
    def close(self): pass


class _JudgeP:
    """A judgement that runs until killed."""
    pid = 7171
    def __init__(self):
        self.stdin = _In()
        self.dead = threading.Event()
        self.returncode = None
    def communicate(self, input=None, timeout=None):
        self.dead.wait(30)
        return ("", "killed")
    def poll(self): return 1 if self.dead.is_set() else None
    def kill(self): self.dead.set()
    def wait(self, timeout=None): return 1


class _ChatP:
    pid = 7272
    def __init__(self):
        self.stdin = _In()
        self.stdout = iter([json.dumps(e) + "\n" for e in [
            {"type": "system", "subtype": "init", "session_id": "s-chat"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Ship-Karte laeuft wieder."}],
                                              "usage": {"input_tokens": 5, "output_tokens": 5}}},
            {"type": "result", "result": "Ship-Karte laeuft wieder.", "session_id": "s-chat",
             "usage": {"input_tokens": 5, "output_tokens": 5}, "total_cost_usd": 0.0}]])
        self.returncode = 0
    def poll(self): return 0
    def wait(self, timeout=None): return 0
    def kill(self): pass


JP = _JudgeP()


class _Sub:
    PIPE, DEVNULL = -1, -3
    TimeoutExpired = TimeoutError
    @staticmethod
    def Popen(argv, *a, **k):
        return JP if "json" in argv and "stream-json" not in argv else _ChatP()


copilot.subprocess = _Sub
copilot._save_sessions({OWNER: "s-before"})

print("owner preempts a judgement")
db.chat_clear()
box = {}


def _judge():
    try:
        box["out"] = copilot.judge("pruef die Ship-Karte", cwd=SANDBOX)
    except Exception as e:                               # noqa: BLE001
        box["err"] = e


tj = threading.Thread(target=_judge, daemon=True)
tj.start()
t0 = time.time()
while OWNER not in copilot._judge_proc and time.time() - t0 < 5:
    time.sleep(0.02)
check(OWNER in copilot._judge_proc, "a judgement holds the owner's turn lock")
t1 = time.time()
out = copilot.chat(OWNER, "Klaere das jetzt", role="owner")
took = time.time() - t1
tj.join(5)
check("laeuft wieder" in (out.get("reply") or ""), "1. the owner's turn ran (%r)" % out.get("reply"))
check(took < 10, "1. it did not wait out the judgement (%.1fs)" % took)
check(isinstance(box.get("err"), copilot.JudgePreempted), "2. judge() raised JudgePreempted (%r)" % box)
check(copilot._sessions().get(OWNER) != "s-judge", "2. the stopped judgement did not move the session pointer")

# 3) broker accounting
from cells.copilot.broker import henry_broker
from spine.registry import escalations
got = {"attempt": 0, "note": []}
escalations.record_attempt = lambda eid: got.__setitem__("attempt", got["attempt"] + 1)
escalations.record_note = lambda eid, d: got["note"].append(d)
henry_broker._card_log_tail = lambda c: ""
henry_broker._find_track = lambda c: None


def _raise(exc):
    def f(*a, **k):
        raise exc
    return f


henry_broker._ask = _raise(copilot.JudgePreempted("x"))
henry_broker._hands_on_ask = henry_broker._ask
try:
    henry_broker._decide({"id": "e1", "card": "", "kind": "followup", "text": "pruef"})
except Exception as e:                                   # noqa: BLE001
    got["note"].append("CRASH %s" % e)
check(got["attempt"] == 0 and any("unterbrochen" in n for n in got["note"]),
      "3. a preempted round is no attempt (%r)" % got)
got["attempt"] = 0
henry_broker._ask = _raise(RuntimeError("model down"))
henry_broker._hands_on_ask = henry_broker._ask
henry_broker._decide({"id": "e1", "card": "", "kind": "followup", "text": "pruef"})
check(got["attempt"] == 1, "3. a real failure still counts as an attempt")

print("PASS test_judge_preempt" if not _fails else "FAIL test_judge_preempt (%d)" % len(_fails))
sys.exit(1 if _fails else 0)
