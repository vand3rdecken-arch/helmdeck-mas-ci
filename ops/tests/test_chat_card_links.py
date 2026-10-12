# -*- coding: utf-8 -*-
"""Cards Henry files from chat land in the right PROJECT, PROCESS and THREAD
(owner 2026-09-25: "Ueberpruefe ob das zu Threads und Projekte richtig
zugeordnet wird").

Findings this pins shut (all through the REAL action runner,
copilot_actions._run_action, and the real chat() turn for the context part):
 1. file_card honours `repo` - it was dropped, every card went to default_repo
 2. file_card / direct_task with `process` join that process as a step
    (card.process + process step track) - only accept_steps could before
 3. attach_process puts an existing card into a process; new_process takes
    `cards`
 4. a card filed from a CARD chat remembers it (origin_card); a hands run
    from a card chat carries that card (it reported into the board chat)
 5. GET /chat/threads rows carry the project (repo) and origin_card
Run: py -3.12 ops/tests/test_chat_card_links.py
"""
import json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
SANDBOX = tempfile.mkdtemp(prefix="hd-links-")
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()
from spine.ops import runs as _runs
_runs.REC = os.path.join(SANDBOX, "runs"); os.makedirs(_runs.REC, exist_ok=True)
from cells.engineer.cards import sessions, dispatch
sessions.REC = dispatch.REC = _runs.REC
from cells.engineer.chains import processes
from cells.copilot.chat import copilot, copilot_actions, threads, hands
copilot.ROOT = SANDBOX
os.makedirs(os.path.join(SANDBOX, "state"), exist_ok=True)
from spine.comms import notify
notify.card_event = lambda *a, **k: None
notify.push_fcm = lambda *a, **k: True
processes._propose_steps = lambda text: []          # no LLM for the proposer

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


def mkrepo(name):
    r = os.path.join(SANDBOX, name)
    os.makedirs(r)
    subprocess.run(["git", "init", "-q", r], check=True)
    subprocess.run(["git", "-C", r, "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "base"], check=True)
    return r


DEFAULT, OTHER = mkrepo("helmdeck"), mkrepo("alphaloop")
s = events.settings()
s["default_repo"] = DEFAULT
events.save_settings(s) if hasattr(events, "save_settings") else None
_real_settings = events.settings
events.settings = lambda: dict(_real_settings(), default_repo=DEFAULT)
card = lambda tid: sessions._find(sessions._load(), tid)

print("chat card links")
# 1) repo honoured
a = {"type": "file_card", "task": "Screener fuer Small Caps", "repo": OTHER}
r = copilot_actions._run_action(a, "tien", "owner")
t1 = card(a.get("_card"))
check(t1 and os.path.normcase(t1["repo"]) == os.path.normcase(OTHER),
      "1. file_card lands in the named project, not default_repo (%s)" % r)

# 2) process pointer at filing
p = processes.create("Investing-Radar v2", actor="tien", steps=[])
a = {"type": "file_card", "task": "Radar Datenquelle", "process": p["id"]}
copilot_actions._run_action(a, "tien", "owner")
t2 = card(a["_card"])
p2 = processes.get(p["id"])
check(t2.get("process") == p["id"] and t2.get("process_title"), "2. file_card with process -> card.process set")
check(any(st.get("track") == t2["id"] for st in p2["steps"]), "2. ... and the process has it as a step")
check(t2.get("process_step") == len(p2["steps"]), "2. ... step number recorded on the card")

# 3) attach_process + new_process cards
a = {"type": "attach_process", "card": t1["id"], "process": "Radar v2"}
r = copilot_actions._run_action(a, "tien", "owner")
check(card(t1["id"]).get("process") == p["id"], "3. attach_process joins an existing card (%s)" % r)
check(a.get("_card") == t1["id"], "3. ... and tags the action so the chat draws its tile")
a3 = {"type": "file_card", "task": "Einzelkarte"}
copilot_actions._run_action(a3, "tien", "owner")
a = {"type": "new_process", "request": "Onboarding-Flow", "cards": [a3["_card"]]}
r = copilot_actions._run_action(a, "tien", "owner")
check(card(a3["_card"]).get("process") and "Karten drin" in r, "3. new_process takes existing cards (%s)" % r)

# 4) card-chat context: origin_card + hands card, through the real chat() turn
SPAWNED = []
hands.spawn = lambda actor, task, skey, card=None, why="": SPAWNED.append(card) or "h-1"
SCRIPT = ("Mach ich.\n```actions\n" + json.dumps([
    {"type": "file_card", "task": "Folgekarte aus dem Karten-Chat"},
    {"type": "hands", "task": "Screenshot vom Dashboard"}]) + "\n```")


class _P:
    def __init__(self):
        lines = [{"type": "system", "subtype": "init", "session_id": "s"},
                 {"type": "stream_event", "event": {"type": "content_block_delta",
                                                    "delta": {"type": "text_delta", "text": SCRIPT}}},
                 {"type": "assistant", "message": {"content": [{"type": "text", "text": SCRIPT}],
                                                   "usage": {"input_tokens": 1, "output_tokens": 1}}},
                 {"type": "result", "result": SCRIPT, "session_id": "s",
                  "usage": {"input_tokens": 1, "output_tokens": 1}, "total_cost_usd": 0.0}]
        self.stdout = iter([json.dumps(e) + "\n" for e in lines])

        class _In:
            def write(self, s): return len(s)
            def flush(self): pass
            def close(self): pass
        self.stdin = _In()
        self.returncode = 0
    def poll(self): return 0
    def wait(self, timeout=None): return 0
    def kill(self): pass


class _Sub:
    PIPE, DEVNULL = -1, -3
    Popen = staticmethod(lambda *a, **k: _P())


from spine.agent import drivers
drivers.argv_form_safe = lambda exe: False
copilot.subprocess = _Sub
copilot._schedule_compact = copilot._schedule_prune = lambda user, agent=False, immediate=False: None
import threading, time
_threads_before = set(threading.enumerate())
copilot.chat("tien", "mach eine Folgekarte und schau aufs Dashboard", role="owner", card=t2["id"])
for th in threading.enumerate():
    if th.name == "copilot-actions":
        th.join(20)
kids = [c for c in sessions._load() if c.get("task") == "Folgekarte aus dem Karten-Chat"]
check(kids and kids[0].get("origin_card") == t2["id"], "4. card filed from a card chat remembers origin_card")
check(SPAWNED == [t2["id"]], "4. hands from a card chat carries that card (got %r)" % SPAWNED)

# 5) threads carry project + origin
rows = {r["id"]: r for r in threads.threads("tien")["threads"]}
check(rows[t1["id"]].get("repo") == "alphaloop", "5. thread row names its project")
check(rows[kids[0]["id"]].get("origin_card") == t2["id"], "5. thread row names the origin card")

print("PASS test_chat_card_links" if not _fails else "FAIL test_chat_card_links (%d)" % len(_fails))
sys.exit(1 if _fails else 0)
