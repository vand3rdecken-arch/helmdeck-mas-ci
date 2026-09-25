# -*- coding: utf-8 -*-
"""Long-term planning on the existing hierarchy Ziel -> Prozess -> Karte
(owner 2026-09-25, Meta Muse / Claude Projects benchmark) - no new object.

Pinned through the real action runner and GET /chat/threads' builder:
 1. set_goal with a repo writes the PROJECT's goal; pm.get_goal(repo) reads
    it; without repo it is the workspace goal (and the fallback)
 2. /chat/threads serves the goals, the open processes with the right
    done/total (sync owns completion: state/done, never step.status), and
    `needs` from pm_push.derive (a proposal nobody accepted)
 3. a process that completes says so in the owner's chat
Run: py -3.12 ops/tests/test_goals_plans.py
"""
import os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
SANDBOX = tempfile.mkdtemp(prefix="hd-goals-")
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
from cells.copilot.chat import copilot, copilot_actions, threads
from cells.copilot.planning import pm
from spine.ops import projects
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


repo = os.path.join(SANDBOX, "alphaloop")
os.makedirs(repo)
subprocess.run(["git", "init", "-q", repo], check=True)
proj = projects.sight_repo(repo) if hasattr(projects, "sight_repo") else None
check(projects.for_repo(repo) is not None, "setup: the repo has its project record")

print("goals and plans")
r = copilot_actions._run_action({"type": "set_goal", "goal": "50 zahlende Nutzer bis Oktober", "repo": repo},
                                "tien", "owner")
check((projects.for_repo(repo) or {}).get("goal") == "50 zahlende Nutzer bis Oktober",
      "1. set_goal with repo writes the project's goal (%s)" % r)
check(pm.get_goal(repo) == "50 zahlende Nutzer bis Oktober", "1. pm.get_goal(repo) reads it")
copilot_actions._run_action({"type": "set_goal", "goal": "HelmDeck profitabel"}, "tien", "owner")
check(pm.get_goal() == "HelmDeck profitabel", "1. without repo: the workspace goal")
check(pm.get_goal(os.path.join(SANDBOX, "unknown")) == "HelmDeck profitabel", "1. unknown repo falls back")

# 2) plans + needs
p = processes.create("Launch-Plan", actor="tien",
                     steps=[{"title": "Preisseite", "mode": "do", "status": "proposed", "track": None},
                            {"title": "Store-Eintrag", "mode": "do", "status": "proposed", "track": None}])
th = threads.threads("tien")
goals = {g["repo"]: g["goal"] for g in th.get("goals", [])}
check(goals.get("alphaloop") == "50 zahlende Nutzer bis Oktober" and goals.get(None) == "HelmDeck profitabel",
      "2. threads serve project + workspace goals (%r)" % goals)
pl = [x for x in th["processes"] if x["id"] == p["id"]]
check(pl and pl[0]["total"] == 2 and pl[0]["done"] == 0, "2. the open plan is listed with 0/2 (%r)" % pl)
check(any(n["kind"] == "proposal" and n["process"] == p["id"] for n in th.get("needs", [])),
      "2. an unaccepted plan is under needs (%r)" % th.get("needs"))

# done/total counts sync's completion, not step.status
for i in range(2):
    processes.accept_step(p["id"], i, repo, actor="tien")
for c in sessions._load():
    if c.get("process") == p["id"] and c.get("process_step") == 1:
        sessions._mutate(c["id"], lambda tt: tt.update(lane="done"))
processes.sync()
pl = [x for x in threads.threads("tien")["processes"] if x["id"] == p["id"]]
check(pl and pl[0]["done"] == 1, "2. one finished step counts as 1/2 (%r)" % pl)

# 3) completion speaks
said = []
copilot.say = lambda text, *a, **k: said.append(text)
for c in sessions._load():
    if c.get("process") == p["id"]:
        sessions._mutate(c["id"], lambda tt: tt.update(lane="done"))
processes.sync()
check(any("Prozess fertig: Launch-Plan" in s and "2/2" in s for s in said), "3. completion said in chat (%r)" % said)
processes.sync()
check(sum("Prozess fertig" in s for s in said) == 1, "3. ... exactly once")

print("PASS test_goals_plans" if not _fails else "FAIL test_goals_plans (%d)" % len(_fails))
sys.exit(1 if _fails else 0)
