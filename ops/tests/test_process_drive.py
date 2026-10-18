# -*- coding: utf-8 -*-
"""THE drive (owner 2026-09-30, cells/copilot/planning/process_drive): one wake
for every process, the goal first; one planner (Henry); steps start.

Pinned, on a sandbox db (the live db is never touched - db.DBPATH first):
 1. slots (owner: "morgens Brief, nachmittags, abends - nicht random 1
    Uhr"): nothing slot-bound fires at 01:00; decide wakes HENRY at the
    14:00 slot (process-move, the process as a record); one open escalation
    per process; a slot handled once; first sight is history; a slot missed
    beyond the grace is not caught up
 2. stalled + deadline at the morning slot, stalled again at 14:00, a
    delivery at once even at night; history never fires; the rule toggle
    turns the drive off
 3. the GOAL is a process of the same drive: the MORNING BRIEF, stalled
    even with no card yet, its deadline from the goal text, the goal
    evidence in the detail; a moving goal is silent at 14:00
 4. empty: a process without steps wakes Henry once (no proposer exists)
 5. set_next through the real chat verb wakes once when due; the Plan button
    (pm.make_plan / pm.brief) is the SAME move on the goal's process - no
    second planner
 6. steps START: create with steps / a template makes cards at once;
    add_step starts; a desktop step becomes a MACHINE card; legacy modes map
    to do/human
 7. broker verbs on a process-move: accept_steps, set_next, direct_task and
    machine_task (steps of THAT process), cancel_process; goal=true from any
    escalation lands in the goal's process; no process -> refused
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
from cells.copilot.planning import process_drive, pm_push, pm
from cells.copilot.broker import henry_broker
from spine.registry import escalations
from spine.auth import auth
auth.list_users = lambda: [{"name": "tien", "role": "owner"}]
from spine.comms import notify
notify.card_event = lambda *a, **k: None
notify.push_fcm = lambda *a, **k: True
notify.chat_reply = lambda *a, **k: None

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


def run(st, now=NOW, procs=None, tracks=None, ev=None, open_ids=(), goal_pid="", decide=None,
        goal="", enabled=True):
    return process_drive.wake(st, now, processes=procs, tracks=tracks or [], ev=ev or [],
                              emit=emit, save=lambda s: None, open_ids=set(open_ids),
                              goal_pid=goal_pid, decide_items=decide or [], goal=goal,
                              enabled=enabled, day_slots=SLOTS)


SLOTS = ("08:00", "14:00", "19:00")
MORNING = time.mktime(time.strptime("2026-09-30 08:05:00", "%Y-%m-%d %H:%M:%S"))
NOON = time.mktime(time.strptime("2026-09-30 14:05:00", "%Y-%m-%d %H:%M:%S"))
NIGHT = time.mktime(time.strptime("2026-10-01 01:00:00", "%Y-%m-%d %H:%M:%S"))


def seen(*pids):
    """A loopstate where these processes were already looked at (first sight
    is history: it only records the running slot)."""
    return {"proc_wake": {pid: {"slot": "", "seen_done": []} for pid in pids}}


print("1. decide wakes Henry - at a slot")
PROP = {"id": "p-prop", "status": "ready", "created": ts(30), "request": "Beispielprojekt-Test\nlang",
        "steps": [{"title": "a", "mode": "do", "state": "proposed", "track": None}] * 3}
decide = [x for x in pm_push.derive(NOW, [PROP], [], "") if x["who"] == "henry"]
check([x["kind"] for x in decide] == ["proposal"], "derive calls unstarted steps Henry's (%r)" % decide)
st = seen("p-prop")
n = len(emitted)
run(st, now=NIGHT, procs=[PROP], decide=decide)
check(len(emitted) == n, "01:00 - no slot, no wake (owner: not a random hour)")
r = run(st, now=NOON, procs=[PROP], decide=decide)
check(len(r) == 1 and emitted[-1]["kind"] == "process-move" and emitted[-1]["process"] == "p-prop"
      and emitted[-1]["card"] is None, "the 14:00 slot: one process-move naming the process as a record")
d = emitted[-1]["detail"]
check("decide: 3 Schritte vorgeschlagen" in d and "PROZESS p-prop: Beispielprojekt-Test" in d
      and "Login" in d and "machine_task" in d, "detail = evidence + reason + the one owner line")
n = len(emitted)
run(st, now=NOON + 60, procs=[PROP], decide=decide, open_ids=[r[0]])
check(len(emitted) == n, "an open escalation blocks the next wake for that process")
run(st, now=NOON + 120, procs=[PROP], decide=decide)
check(len(emitted) == n, "the same slot is handled once per process")
run(st, now=NOON + 180, procs=[dict(PROP, status="cancelled")])
check("p-prop" not in st["proc_wake"], "a cancelled process leaves the latch")
st = {}
run(st, now=NOON, procs=[PROP], decide=decide)
check(len(emitted) == n and st["proc_wake"]["p-prop"]["slot"] == "20260930 14:00",
      "first sight: the running slot is recorded as history, nothing fires")
st = {"proc_wake": {"p-prop": {"seen_done": [], "decide_seen": []}}}   # a pre-slot latch
saved = []
process_drive.wake(st, NIGHT, processes=[PROP], tracks=[], ev=[], emit=emit, save=saved.append,
                   open_ids=set(), goal_pid="", decide_items=decide, goal="", enabled=True,
                   day_slots=SLOTS)
check(saved and st["proc_wake"]["p-prop"].get("slot") == "",
      "first sight outside a slot is PERSISTED - else every slot stays 'first sight' forever")
r = run(st, now=MORNING, procs=[PROP], decide=decide)
check(len(r) == 1, "... so the next slot really fires")
late = time.mktime(time.strptime("2026-09-30 17:00:00", "%Y-%m-%d %H:%M:%S"))
check(process_drive.current_slot(late, SLOTS) is None,
      "a slot missed by more than the grace is not caught up at 17:00")

print("2. delivered / stalled / deadline")
RUN = {"id": "p-run", "status": "running", "created": ts(100), "request": "Studie", "due": "2026-10-02",
       "steps": [{"title": "s1", "mode": "do", "track": "c1"}, {"title": "s2", "mode": "do", "track": "c2"}]}
T = [{"id": "c1", "lane": "working", "created": ts(90)}, {"id": "c2", "lane": "backlog", "created": ts(90)}]
EV = [{"kind": "lane", "track": "c1", "ts": ts(30)}]
st = seen("p-run")
run(st, now=MORNING, procs=[RUN], tracks=T, ev=EV)
d = emitted[-1]["detail"]
check("stalled: keine Bewegung seit dem letzten Slot" in d and "deadline: noch 2 Tage" in d,
      "morning slot: stalled + T-2 in one wake (%r)" % d[-300:])
n = len(emitted)
run(st, now=NOON, procs=[RUN], tracks=T, ev=EV)
check(len(emitted) == n + 1 and "deadline" not in emitted[-1]["detail"],
      "14:00: still stalled -> a check, the deadline only in the morning")
n = len(emitted)
T2 = [dict(T[0], lane="done"), T[1]]
run(st, now=NIGHT, procs=[RUN], tracks=T2, ev=EV + [{"kind": "lane", "track": "c1", "ts": ts(0)}])
check(len(emitted) == n + 1 and "delivered: Schritt-Karte fertig (c1)" in emitted[-1]["detail"]
      and "stalled" not in emitted[-1]["detail"], "a delivery fires at once, even at 01:00, without slot reasons")
st2 = {}
n = len(emitted)
run(st2, now=NOON, procs=[dict(RUN, due="")], tracks=T2, ev=[{"kind": "lane", "track": "c1", "ts": ts(1)}])
check(len(emitted) == n and st2["proc_wake"]["p-run"]["seen_done"] == ["c1"],
      "first look: an already-done card is history, recorded as seen")
n = len(emitted)
check(run(seen("p-run"), now=NOON, procs=[RUN], tracks=T, ev=EV, enabled=False) == [] and len(emitted) == n,
      "initiative.goal_drive off -> no drive")

print("3. the goal: morning brief, same drive")
GOAL = "Nebeneinkommen finden bis 2026-10-02."
GP = {"id": "p-goal", "status": "running", "created": ts(50), "request": GOAL, "steps": [],
      "open_ended": True}
st = seen("p-goal", "p-run")
st["goal_wake"] = {"day": "x"}
n = len(emitted)
run(st, now=MORNING, procs=[GP, RUN], tracks=T, ev=EV, goal_pid="p-goal", goal=GOAL)
check(len(emitted) == n + 2 and emitted[n]["process"] == "p-goal", "the goal wakes first")
d = emitted[n]["detail"]
check("brief: Morgen-Brief" in d and "stalled: noch keine Karte fuer das Ziel" in d
      and "deadline: noch 2 Tage" in d, "morning: brief + stalled + deadline from the goal text (%r)" % d[-600:])
check(d.startswith("WARUM JETZT") and 0 < d.find("GOAL: Nebeneinkommen finden") and d.find("deadline") < d.find("GOAL: "),
      "the REASONS lead the detail (a cut must hit the process summary, never the reason); goal evidence follows")
check("goal_wake" not in st, "the old goal-only latch is dropped")
n = len(emitted)
GC = dict(GP, steps=[{"title": "x", "mode": "do", "track": "g1"}])
GT = [{"id": "g1", "lane": "working", "created": ts(1)}]
run(seen("p-goal"), now=NOON, procs=[GC], tracks=GT, ev=[{"kind": "lane", "track": "g1", "ts": ts(0)}],
    goal_pid="p-goal", goal=GOAL)
check(len(emitted) == n, "14:00 with the goal moving: no brief, no wake - checks only speak with a reason")

print("4. an empty process")
EMP = {"id": "p-emp", "status": "running", "created": ts(1), "request": "Thema X", "steps": []}
st = seen("p-emp")
run(st, now=NOON, procs=[EMP])
check("empty: noch keine Schritte" in emitted[-1]["detail"], "an empty process asks Henry for its first cards")
n = len(emitted)
run(st, now=NOON + 5 * 3600, procs=[EMP])
check(len(emitted) == n, "... once")

print("5. set_next + the Plan button")
repo = os.path.join(SANDBOX, "helmdeck")
os.makedirs(repo)
subprocess.run(["git", "init", "-q", repo], check=True)
real_settings = events.settings
events.settings = lambda: dict(real_settings(), default_repo=repo)
p = processes.create("Beispielprojekt Preistest", actor="tien")
check(p["status"] == "running" and p["steps"] == [], "create without steps: empty + running, no proposer")
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
st = {"proc_wake": {p["id"]: {"empty_seen": True}}}
due = time.mktime(time.strptime("2026-10-03 09:00", "%Y-%m-%d %H:%M"))
n = len(emitted)
run(st, now=due - 60, procs=[processes.get(p["id"])])
check(len(emitted) == n, "before `at`: silent")
run(st, now=due + 60, procs=[processes.get(p["id"])])
check(len(emitted) == n + 1 and "next: faellig seit 2026-10-03 09:00" in emitted[-1]["detail"],
      "at `at`: Henry is woken with the move")
run(st, now=due + 7200, procs=[processes.get(p["id"])])
check(len(emitted) == n + 1, "the same move wakes once")
pm.set_goal(GOAL)
out = pm.make_plan(actor="tien")
gpid = pm_push.goal_process_id()
gnx = (processes.get(gpid) or {}).get("next") or {}
check(out.get("planning") == gpid and gnx.get("what", "").startswith("Plan fuer das Ziel"),
      "the Plan button = a planning move on the goal's process (%r)" % out)
check(processes.get(gpid).get("open_ended") and processes.get(gpid)["status"] == "running",
      "the goal's process is open-ended and running")
check(pm.brief().get("planning") == gpid, "/pm/report is the same move, no PM model turn")

print("6. steps start")
q = processes.create("Launch", actor="tien", steps=[
    {"title": "Landing bauen", "mode": "do", "status": "proposed", "track": None},
    {"title": "Store-Formular ausfuellen", "mode": "prepare", "desktop": True, "status": "proposed", "track": None},
    {"title": "Notar", "mode": "teach", "status": "proposed", "track": None}])
cards = {c["id"]: c for c in sessions._load()}
tr = [s.get("track") for s in q["steps"]]
check(all(tr), "create with steps: every step is a card at once (%r)" % tr)
check(not cards[tr[0]].get("machine") and cards[tr[1]].get("machine"),
      "a desktop step is a MACHINE card (windows-mcp), a plain step a repo card")
check(cards[tr[2]]["task"].startswith("HUMAN STEP") and cards[tr[1]].get("mode") == "do",
      "legacy modes map: teach -> human, prepare -> do")
q2 = processes.add_step(q["id"], "Nachtrag", "do")
check(q2["steps"][-1].get("track"), "add_step starts the step as a card")

print("7. broker verbs")
real_direct = sessions.new_direct_task
real_machine = sessions.new_machine_task
def fake_direct(repo_, task, actor="owner", priority="medium", **kw):
    return sessions.new_track(repo_, "direct-" + task[:20], task, lane="backlog", actor=actor)
def fake_machine(cwd, task, actor="owner", priority="medium", **kw):
    t = sessions.new_track(repo, "machine-" + task[:20], task, lane="backlog", actor=actor)
    sessions._mutate(t["id"], lambda x: x.update(machine=True))
    return t
sessions.new_direct_task = fake_direct
sessions.new_machine_task = fake_machine
try:
    prop = {"id": "p-x"}
    with processes._lock:
        ps = processes._load()
        ps.insert(0, {"id": "p-x", "request": "Studie planen", "status": "ready", "steps": [
            {"title": "Quellen", "mode": "do", "status": "proposed", "track": None}],
            "created": ts(1), "client": "", "due": ""})
        processes._save(ps)
    esc = {"id": escalations.emit("process-move", None, "x", process="p-x"),
           "kind": "process-move", "card": None}
    check([e for e in escalations.list_open() if e["id"] == esc["id"]][0].get("process") == "p-x",
          "the escalation row carries its process")
    esc["process"] = "p-x"
    check(henry_broker._execute("accept_steps", "", "", "", esc)
          and all(s.get("track") for s in processes.get("p-x")["steps"]), "accept_steps starts them")
    check(henry_broker._execute("set_next", "", "", "Ergebnis pruefen", esc, at="2026-10-05")
          and processes.get("p-x")["next"]["at"] == "2026-10-05", "set_next records")
    check(henry_broker._execute("direct_task", "", "", "Nachtrag schreiben", esc), "direct_task executes")
    check(henry_broker._execute("machine_task", "", "", "Formular im Portal", esc), "machine_task executes")
    ids = [s.get("track") for s in processes.get("p-x")["steps"]]
    got = [t for t in sessions._load() if t.get("task") in ("Nachtrag schreiben", "Formular im Portal")]
    check(len(got) == 2 and all(t["id"] in ids and t.get("process") == "p-x" for t in got),
          "... both new cards are steps of THAT process")
    check(henry_broker._execute("cancel_process", "", "", "", esc)
          and processes.get("p-x")["status"] == "cancelled", "cancel_process stops the chain")
    lone = {"id": escalations.emit("idle-check", None, "x"), "kind": "idle-check", "card": None}
    check(not henry_broker._execute("accept_steps", "", "", "", lone),
          "an escalation without a process refuses process verbs")
    check(henry_broker._execute("direct_task", "", "", "Nachfrage messen", lone, goal=True),
          "direct_task with goal=true from an idle-check executes")
    gt = [t for t in sessions._load() if t.get("task") == "Nachfrage messen"]
    check(gt and gt[0].get("process") == gpid, "... and the card is a step of the goal's process")
    henry_broker._execute("direct_task", "", "", "Nebenbei", lone)
    nb = [t for t in sessions._load() if t.get("task") == "Nebenbei"]
    check(nb and not nb[0].get("process"), "without goal=true it is not goal work")
finally:
    sessions.new_direct_task = real_direct
    sessions.new_machine_task = real_machine
    events.settings = real_settings

print("PASS test_process_drive" if not _fails else "FAIL test_process_drive (%d)" % len(_fails))
sys.exit(1 if _fails else 0)
