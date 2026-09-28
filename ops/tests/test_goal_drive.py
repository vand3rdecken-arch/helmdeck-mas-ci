# -*- coding: utf-8 -*-
"""Henry drives the goal (owner 2026-09-28, cells/copilot/planning/goal_drive).

Pinned, on a sandbox db (the live db is never touched - db.DBPATH first):
 1. goal_state derives share, last movement and owner steps from the record:
    goal=true cards and the goal process' steps count, nothing else; no
    marked card -> share None (said, not guessed)
 2. goal_line renders the evidence Henry reads first in both snapshots, and
    copilot._snapshot really carries it
 3. wake: history never fires, stalled/deadline once a day, a delivery fires
    even the same day, an open goal-move blocks without swallowing the
    delivery, the rule toggle turns it off
 4. the broker's direct_task verb starts a card and records goal=true for a
    goal-move; a client-card judgement cannot use it
 5. file_card with "goal": true through the real action runner records the flag;
    mark_goal flips it on an existing card
Run: py -3.12 ops/tests/test_goal_drive.py
"""
import os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
SANDBOX = tempfile.mkdtemp(prefix="hd-goaldrive-")
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
from cells.copilot.chat import copilot, copilot_actions
from cells.copilot.planning import pm, goal_drive
from cells.copilot.broker import henry_broker
from spine.registry import escalations
from spine.auth import auth
copilot.ROOT = SANDBOX
auth.list_users = lambda: [{"name": "tien", "role": "owner"}]
from spine.comms import notify
notify.card_event = lambda *a, **k: None
notify.push_fcm = lambda *a, **k: True
notify.chat_reply = lambda *a, **k: None
processes._propose_steps = lambda text: []

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


NOW = time.mktime(time.strptime("2026-09-28 12:00:00", "%Y-%m-%d %H:%M:%S"))
GOAL = "Ersten fremden User finden bis 2026-09-30."


def ts(h_ago):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(NOW - h_ago * 3600))


def card(cid, lane="working", **kw):
    t = {"id": cid, "lane": lane, "status": "", "task": cid, "created": ts(100)}
    t.update(kw)
    return t


def turn(track, n, h_ago=5):
    return {"kind": "turn", "track": track, "ts": ts(h_ago), "usage": {"input_tokens": n}}


print("1. goal_state")
tracks = [card("g1", goal=True), card("p1", process="PGOAL"), card("side")]
ev = [turn("g1", 100), turn("p1", 100), turn("side", 800), turn("side", 5000, h_ago=24 * 9),
      {"kind": "lane", "track": "g1", "ts": ts(30), "to": "working"}]
gs = goal_drive.goal_state(NOW, tracks=tracks, processes=[], ev=ev, goal=GOAL, goal_pid="PGOAL")
check(gs["goal_cards"] == 2, "goal flag + goal-process step count, the side card does not (%s)" % gs["goal_cards"])
check(abs(gs["share"] - 0.2) < 1e-9, "share over 7 days only: 200 of 1000 (%s)" % gs["share"])
check(gs["days_left"] == 2, "deadline from the goal text via pm_push (%s)" % gs["days_left"])
check(gs["last_move"] and abs(gs["last_move"] - (NOW - 30 * 3600)) < 2,
      "last movement = the newest lane event of a goal card")
gs0 = goal_drive.goal_state(NOW, tracks=[card("side")], processes=[], ev=ev, goal=GOAL, goal_pid="")
check(gs0["share"] is None and gs0["last_move"] is None, "no marked card: share None, never guessed")
check(goal_drive.goal_state(NOW, tracks=tracks, processes=[], ev=ev, goal="", goal_pid="") is None,
      "no goal -> None")

print("2. goal_line + snapshot")
line = goal_drive.goal_line(gs, NOW)
check(line.startswith("GOAL: Ersten fremden User") and "noch 2 Tage" in line and "20%" in line
      and "vor 30 h" in line, "the evidence line (%r)" % line)
check("noch keine Ziel-Karten markiert" in goal_drive.goal_line(gs0, NOW),
      "unmarked board says so")
pm.set_goal(GOAL)
snap = copilot._snapshot()
check(snap.startswith("GOAL: Ersten fremden User"), "copilot._snapshot leads with the goal (%r)" % snap[:80])
check(henry_broker._snapshot().startswith("GOAL: Ersten fremden User"), "the broker snapshot too")

print("3. wake")
emitted = []
def emit(kind, c, detail):
    emitted.append((kind, detail))
    return "goal-move-%d" % len(emitted)
saves = []
st = {}
fresh = dict(gs, last_move=NOW - 3600, done=["old1"], days_left=10)
r = goal_drive.wake(st, NOW, gs=fresh, emit=emit, save=saves.append, enabled=True, open_exists=False)
check(r is None and not emitted, "first look: an already-done card is history, nothing fires")
check(st["goal_wake"]["seen_done"] == ["old1"], "... but it is recorded as seen")
stalled = dict(fresh, last_move=NOW - 30 * 3600)
r = goal_drive.wake(st, NOW, gs=stalled, emit=emit, save=saves.append, enabled=True, open_exists=False)
check(r and emitted[-1][0] == "goal-move" and "stalled" in emitted[-1][1] and "Frage:" in emitted[-1][1],
      "stalled 30 h -> one goal-move with the goal line and the question")
n = len(emitted)
goal_drive.wake(st, NOW + 600, gs=stalled, emit=emit, save=saves.append, enabled=True, open_exists=False)
check(len(emitted) == n, "stalled fires once a day, not every tick")
deliv = dict(stalled, done=["old1", "new2"])
r = goal_drive.wake(st, NOW + 900, gs=deliv, emit=emit, save=saves.append, enabled=True, open_exists=True)
check(r is None and st["goal_wake"]["seen_done"] == ["old1"],
      "an open goal-move blocks - and the delivery is NOT swallowed")
r = goal_drive.wake(st, NOW + 1200, gs=deliv, emit=emit, save=saves.append, enabled=True, open_exists=False)
check(r and "delivered" in emitted[-1][1] and "new2" in emitted[-1][1],
      "once free: the delivery fires the same day")
st2 = {}
near = dict(fresh, days_left=2)
goal_drive.wake(st2, NOW, gs=near, emit=emit, save=saves.append, enabled=True, open_exists=False)
check("deadline: noch 2 Tage" in emitted[-1][1], "T-2 fires the deadline reason")
n = len(emitted)
check(goal_drive.wake({}, NOW, gs=stalled, emit=emit, save=saves.append, enabled=False,
                      open_exists=False) is None and len(emitted) == n,
      "initiative.goal_drive off -> no wake")
idle_saves = len(saves)
goal_drive.wake(st, NOW + 1500, gs=deliv, emit=emit, save=saves.append, enabled=True, open_exists=False)
check(len(saves) == idle_saves, "an idle tick writes nothing")

print("4. broker direct_task")
repo = os.path.join(SANDBOX, "helmdeck")
os.makedirs(repo)
subprocess.run(["git", "init", "-q", repo], check=True)
started = []
def fake_direct(repo_, task, actor="owner", priority="medium", **kw):
    t = sessions.new_track(repo_, "direct-" + task[:20], task, lane="backlog", actor=actor)
    started.append((task, actor, priority))
    return t
real_direct, real_settings = sessions.new_direct_task, events.settings
sessions.new_direct_task = fake_direct
events.settings = lambda: dict(real_settings(), default_repo=repo)
try:
    esc = {"id": escalations.emit("goal-move", None, "x"), "kind": "goal-move", "card": None}
    ok = henry_broker._execute("direct_task", "", "", "PH-Eintrag vorbereiten", esc)
    check(ok and started and started[0][1] == "henry", "direct_task starts a card as henry (%r)" % started)
    mine = [t for t in sessions._load() if t.get("task") == "PH-Eintrag vorbereiten"]
    check(mine and mine[0].get("goal") is True, "a goal-move card is goal work by record")
    check(not henry_broker._execute("direct_task", "", "", "", esc), "no task text -> refused, stays open")
    # a client-card judgement: no hands, so no direct_task either
    henry_broker._find_track = lambda c: {"id": "c1", "dispatched_by": "kunde"}
    henry_broker._dispatcher_privileged = lambda t: False
    henry_broker._ask = lambda prompt, model="", perm=None: {"action": "direct_task", "text": "x"}
    henry_broker._card_log_tail = lambda c, n=35: ""
    henry_broker._audit_context = lambda t: ""
    n = len(started)
    esc2 = {"id": escalations.emit("turn-shape", "c1", "x"), "kind": "turn-shape", "card": "c1",
            "attempts": 0, "detail": "x"}
    check(henry_broker._decide(esc2) is False and len(started) == n,
          "client card: direct_task refused before it runs")
finally:
    sessions.new_direct_task, events.settings = real_direct, real_settings

print("5. file_card goal flag")
r = copilot_actions._run_action({"type": "file_card", "task": "Landing-Umfrage bauen", "repo": repo,
                                 "goal": True}, "tien", "owner")
t = [x for x in sessions._load() if x.get("task") == "Landing-Umfrage bauen"]
check(t and t[0].get("goal") is True, "file_card with goal:true records the flag (%s)" % r)
copilot_actions._run_action({"type": "file_card", "task": "Nebensache", "repo": repo}, "tien", "owner")
t = [x for x in sessions._load() if x.get("task") == "Nebensache"]
check(t and not t[0].get("goal"), "without it the card is not goal work")
r = copilot_actions._run_action({"type": "mark_goal", "card": t[0]["id"]}, "tien", "owner")
check(sessions._find(sessions._load(), t[0]["id"]).get("goal") is True,
      "mark_goal makes an existing card goal work (%s)" % r)
copilot_actions._run_action({"type": "mark_goal", "card": t[0]["id"], "goal": False}, "tien", "owner")
check(sessions._find(sessions._load(), t[0]["id"]).get("goal") is False, "... and goal:false undoes it")

print("PASS test_goal_drive" if not _fails else "FAIL test_goal_drive (%d)" % len(_fails))
sys.exit(1 if _fails else 0)
