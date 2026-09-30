# -*- coding: utf-8 -*-
"""Henry drives every process (owner 2026-09-30, cells/copilot/planning/process_drive).

Pinned, on a sandbox db (the live db is never touched - db.DBPATH first):
 1. wake: a proposal nobody started wakes HENRY (process-move, the process
    as a record on the escalation), not the owner; one open escalation per
    process; the same decision never re-fires; a finished process leaves
    the latch
 2. delivered / stalled / deadline for an ordinary process; the goal's
    process gets none of those here (goal_drive owns them) - only next/decide
 3. set_next through the real chat action runner records the next move;
    the drive wakes Henry once when it is due, never again for the same move
 4. the broker's process verbs on a process-move: accept_steps turns the
    proposal into cards, set_next records, cancel_process stops the chain,
    direct_task files a card that is a step of THAT process; an escalation
    without a process refuses them; direct_task with "goal": true from ANY
    escalation (the 2026-09-30 idle-check card) lands in the goal's process
 5. processes.create(propose=False) is born empty + running (no proposer)
Run: py -3.12 ops/tests/test_process_drive.py
"""
import os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
SANDBOX = tempfile.mkdtemp(prefix="hd-procdrive-")
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
from cells.copilot.chat import copilot_actions
from cells.copilot.planning import process_drive
from cells.copilot.broker import henry_broker
from spine.registry import escalations
from spine.auth import auth
auth.list_users = lambda: [{"name": "tien", "role": "owner"}]
from spine.comms import notify
notify.card_event = lambda *a, **k: None
notify.push_fcm = lambda *a, **k: True
notify.chat_reply = lambda *a, **k: None
proposer_calls = []
processes._propose_steps = lambda text: (proposer_calls.append(text), ([], 0))[1]

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


NOW = time.mktime(time.strptime("2026-09-30 12:00:00", "%Y-%m-%d %H:%M:%S"))


def ts(h_ago):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(NOW - h_ago * 3600))


emitted = []


def emit(kind, card, detail, process=None):
    emitted.append({"kind": kind, "card": card, "detail": detail, "process": process})
    return "process-move-%d" % len(emitted)


def run(st, now=NOW, procs=None, tracks=None, ev=None, open_ids=(), goal_pid="", decide=None):
    return process_drive.wake(st, now, processes=procs, tracks=tracks or [], ev=ev or [],
                              emit=emit, save=lambda s: None, open_ids=set(open_ids),
                              goal_pid=goal_pid, decide_items=decide)


print("1. a proposal wakes Henry")
from cells.copilot.planning import pm_push
PROP = {"id": "p-prop", "status": "ready", "created": ts(30), "request": "***-Test\nlang",
        "steps": [{"title": "a", "mode": "do", "state": "proposed", "track": None}] * 3}
decide = [x for x in pm_push.derive(NOW, [PROP], [], "") if x["who"] == "henry"]
check([x["kind"] for x in decide] == ["proposal"], "derive calls the proposal Henry's (%r)" % decide)
st = {}
r = run(st, procs=[PROP], decide=decide)
check(len(r) == 1 and emitted[-1]["kind"] == "process-move" and emitted[-1]["process"] == "p-prop"
      and emitted[-1]["card"] is None, "one process-move naming the process as a record")
check("decide: 3 Schritte vorgeschlagen" in emitted[-1]["detail"] and "accept_steps" in emitted[-1]["detail"]
      and "PROZESS p-prop: ***-Test" in emitted[-1]["detail"], "detail = evidence + reason + verbs")
n = len(emitted)
run(st, now=NOW + 60, procs=[PROP], decide=decide, open_ids=[r[0]])
check(len(emitted) == n, "an open escalation blocks the next wake for that process")
run(st, now=NOW + 120, procs=[PROP], decide=decide)
check(len(emitted) == n, "the same decision never re-fires once Henry closed it")
run(st, now=NOW + 180, procs=[dict(PROP, status="cancelled")], decide=[])
check("p-prop" not in st["proc_wake"], "a cancelled process leaves the latch")

print("2. delivered / stalled / deadline, and the goal process")
RUN = {"id": "p-run", "status": "running", "created": ts(100), "request": "Studie", "due": "2026-10-02",
       "steps": [{"title": "s1", "mode": "do", "track": "c1"}, {"title": "s2", "mode": "do", "track": "c2"}]}
T = [{"id": "c1", "lane": "working", "created": ts(90)}, {"id": "c2", "lane": "backlog", "created": ts(90)}]
EV = [{"kind": "lane", "track": "c1", "ts": ts(30)}]
st = {}
run(st, procs=[RUN], tracks=T, ev=EV, decide=[])
d = emitted[-1]["detail"]
check("stalled: seit 30 h" in d and "deadline: noch 2 Tage" in d, "stalled 30 h + T-2 in one wake (%r)" % d[-400:])
n = len(emitted)
T2 = [dict(T[0], lane="done"), T[1]]
run(st, now=NOW + 600, procs=[RUN], tracks=T2, ev=EV + [{"kind": "lane", "track": "c1", "ts": ts(0)}], decide=[])
check(len(emitted) == n + 1 and "delivered: Schritt-Karte fertig (c1)" in emitted[-1]["detail"]
      and "stalled" not in emitted[-1]["detail"], "a delivery the same day fires, stalled/deadline do not repeat")
n = len(emitted)
run({}, procs=[RUN], tracks=T, ev=EV, decide=[], goal_pid="p-run")
check(len(emitted) == n, "the goal's process gets no stalled/deadline here (goal_drive owns them)")

print("3. set_next through the chat verb")
repo = os.path.join(SANDBOX, "helmdeck")
os.makedirs(repo)
subprocess.run(["git", "init", "-q", repo], check=True)
real_settings = events.settings
events.settings = lambda: dict(real_settings(), default_repo=repo)
p = processes.create("*** Preistest", actor="tien", propose=False)
check(p["status"] == "running" and p["steps"] == [] and not proposer_calls,
      "5. propose=False: born empty + running, no proposer")
r = copilot_actions._run_action({"type": "set_next", "process": "Preistest",
                                 "what": "Zahlen der ersten 3 Tage auswerten", "at": "2026-10-03 09:00"},
                                "tien", "owner")
nx = processes.get(p["id"]).get("next") or {}
check(nx.get("what") == "Zahlen der ersten 3 Tage auswerten" and nx.get("at") == "2026-10-03 09:00",
      "set_next records the move (%s)" % r)
bad = copilot_actions._run_action({"type": "set_next", "process": "Preistest", "what": "x", "at": "morgen"},
                                  "tien", "owner")
check(bad.startswith("set_next:") and processes.get(p["id"])["next"]["what"] != "x",
      "an unparseable time is refused, the old move stays (%s)" % bad)
st = {}
due = time.mktime(time.strptime("2026-10-03 09:00", "%Y-%m-%d %H:%M"))
n = len(emitted)
run(st, now=due - 60, procs=[processes.get(p["id"])], decide=[])
check(len(emitted) == n, "before `at`: silent")
run(st, now=due + 60, procs=[processes.get(p["id"])], decide=[])
check(len(emitted) == n + 1 and "next: faellig seit 2026-10-03 09:00" in emitted[-1]["detail"],
      "at `at`: Henry is woken with the move")
run(st, now=due + 7200, procs=[processes.get(p["id"])], decide=[])
check(len(emitted) == n + 1, "the same move wakes once")

print("4. broker process verbs")
real_direct = sessions.new_direct_task
def fake_direct(repo_, task, actor="owner", priority="medium", **kw):
    return sessions.new_track(repo_, "direct-" + task[:20], task, lane="backlog", actor=actor)
sessions.new_direct_task = fake_direct
try:
    prop = processes.create("Studie planen", actor="pm",
                            steps=[{"title": "Quellen", "mode": "do", "status": "proposed", "track": None},
                                   {"title": "Auswerten", "mode": "do", "status": "proposed", "track": None}])
    esc = {"id": escalations.emit("process-move", None, "x", process=prop["id"]),
           "kind": "process-move", "card": None}
    check([e for e in escalations.list_open() if e["id"] == esc["id"]][0].get("process") == prop["id"],
          "the escalation row carries its process")
    esc["process"] = prop["id"]
    check(henry_broker._execute("accept_steps", "", "", "", esc), "accept_steps executes")
    q = processes.get(prop["id"])
    check(all(s.get("track") for s in q["steps"]) and q["status"] == "running",
          "... every proposed step is a card now (%r)" % [s.get("track") for s in q["steps"]])
    check(henry_broker._execute("set_next", "", "", "Ergebnis pruefen", esc, at="2026-10-05"),
          "set_next executes")
    check(processes.get(prop["id"])["next"]["at"] == "2026-10-05", "... and records")
    check(henry_broker._execute("direct_task", "", "", "Nachtrag schreiben", esc), "direct_task executes")
    nt = [t for t in sessions._load() if t.get("task") == "Nachtrag schreiben"]
    check(nt and nt[0].get("process") == prop["id"]
          and nt[0]["id"] in [s.get("track") for s in processes.get(prop["id"])["steps"]],
          "... the new card is a step of THAT process")
    check(henry_broker._execute("cancel_process", "", "", "", esc)
          and processes.get(prop["id"])["status"] == "cancelled", "cancel_process stops the chain")
    lone = {"id": escalations.emit("idle-check", None, "x"), "kind": "idle-check", "card": None}
    check(not henry_broker._execute("accept_steps", "", "", "", lone),
          "an escalation without a process refuses process verbs")
    from cells.copilot.planning import pm
    pm.set_goal("Nebeneinkommen finden bis 2026-12-31.")
    check(henry_broker._execute("direct_task", "", "", "Nachfrage messen", lone, goal=True),
          "direct_task with goal=true from an idle-check executes")
    gpid = pm_push.goal_process_id()
    gt = [t for t in sessions._load() if t.get("task") == "Nachfrage messen"]
    check(gpid and gt and gt[0].get("process") == gpid, "... and the card is a step of the goal's process")
    henry_broker._execute("direct_task", "", "", "Nebenbei", lone)
    nb = [t for t in sessions._load() if t.get("task") == "Nebenbei"]
    check(nb and not nb[0].get("process"), "without goal=true it is not goal work")
finally:
    sessions.new_direct_task = real_direct
    events.settings = real_settings

print("PASS test_process_drive" if not _fails else "FAIL test_process_drive (%d)" % len(_fails))
sys.exit(1 if _fails else 0)
