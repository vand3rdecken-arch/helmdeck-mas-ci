# -*- coding: utf-8 -*-
"""E2E for the P3.4 verify line: cancel a LIVE turn -> the card is needs_you in
<65s and the next steer resumes the SAME session.

Runs the real sessions.steer -> drivers stack (persistent stream-json session,
soft interrupt, _finish_turn's atomic commit) against the fake_claude stand-in,
so it proves the wiring without spending model turns. Self-sandboxing: own db/
events/runs in a temp dir, fake CLI via the drivers.CLAUDE seam.

Run: py -3.12 ops/tests/e2e_cancel_resume.py
"""
import os, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
# REPO ROOT. This pointed at "<repo>/daemon" and did `import db, events, runs,
# drivers, notify, sessions` - dead since the tree became spine/cells/surfaces/
# ops, and silently, because a dead script compiles exactly like a live one.
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

SANDBOX = tempfile.mkdtemp(prefix="hd-e2e-cancel-")

from spine.storage import db, events
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
db._LEGACY_DB = os.path.join(SANDBOX, "legacy.db")
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")
db.init(role="tool")                         # role=tool: no boot devaluation

from spine.ops import runs
runs.REC = os.path.join(SANDBOX, "runs")
os.makedirs(runs.REC, exist_ok=True)

from spine.agent import drivers, proctable
from spine.comms import notify
from cells.engineer import sessions
# dispatch/cardadmin bind their OWN copy of REC at import time (`from runs import
# REC`), which is why test_server_routes.py patches each of them by hand. Same
# hazard here: patch every holder, or a real card lands in the owner's
# daemon/recordings while this file believes it is sandboxed.
sessions.REC = runs.REC
from cells.engineer import dispatch as _dispatch, cardadmin as _cardadmin
_dispatch.REC = runs.REC
_cardadmin.REC = runs.REC
notify.card_event = lambda *a, **k: None     # no push targets in the sandbox
notify.clear_dedup = lambda *a, **k: None

# fake CLI through the same seam test_driver_session.py uses
_WRAP = os.path.join(tempfile.mkdtemp(), "fake_claude.cmd")
with open(_WRAP, "w", encoding="utf-8") as f:
    f.write('@echo off\r\n"%s" "%s" %%*\r\n'
            % (sys.executable, os.path.join(HERE, "fake_claude.py")))
drivers.CLAUDE = _WRAP
# The pid table moved into its own module (spine/agent/proctable.py) in the same
# split - drivers re-exports the helpers but NOT the _PIDFILE constant, so
# setting it on drivers would silently write the real daemon/driver_pids.json.
proctable._PIDFILE = os.path.join(tempfile.mkdtemp(), "driver_pids.json")

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


TID = "e2e-cancel"
RUN = os.path.join(runs.REC, TID)
os.makedirs(RUN, exist_ok=True)
# session_id pre-set: a None would route steer through _start's worktree
# dispatch (needs a real git repo); the fake CLI resumes any id and reports
# its own ("fake-session-123"), which is exactly what the track then carries.
t = {"id": TID, "repo": None, "branch": "(none)", "worktree": SANDBOX,
     "task": "e2e cancel/resume", "description": "", "client": "",
     "session_id": "fake-session-123", "perm": "acceptEdits", "lane": "working",
     "status": "needs_you", "turns": 0, "run_dir": RUN, "last_reply": "",
     "value": 0.0, "driver": "claude", "priority": "medium", "due": "",
     "rank": None, "model": "", "attachments": [], "billing": "none",
     "rate": None, "ai_cost": 0.0, "tokens_in": 0, "tokens_out": 0,
     "models": [], "created": time.strftime("%Y-%m-%d %H:%M:%S"),
     "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
sessions._save_track(t)

# turn 1: a normal turn so a session id exists on the track
sessions.steer(TID, "hello")
t1 = sessions.get_track(TID)
SID = t1.get("session_id")
check(bool(SID), "turn 1 captured a session id (%r)" % SID)
check(t1.get("status") == "needs_you", "turn 1 settled to needs_you")

# turn 2: a HUNG turn (the live one), cancelled from a second thread
box = {}


def _steer_hang():
    try:
        box["t"] = sessions.steer(TID, "__HANG__")
    except Exception as e:
        box["err"] = str(e)


th = threading.Thread(target=_steer_hang, daemon=True)
t_cancel = time.time()
th.start()
deadline = time.time() + 20
while time.time() < deadline:                # wait until the turn is truly live
    cur = sessions.get_track(TID)
    if cur.get("status") == "running" and drivers.turn_active(TID):
        break
    time.sleep(0.2)
check(drivers.turn_active(TID), "turn 2 is live (turn_active) before cancel")

t_cancel = time.time()
sessions.cancel_turn(TID, actor="e2e")
th.join(timeout=60)
settle = None
deadline = time.time() + 65
while time.time() < deadline:
    cur = sessions.get_track(TID)
    if cur.get("status") == "needs_you" and not drivers.turn_active(TID):
        settle = time.time() - t_cancel
        break
    time.sleep(0.5)
check(settle is not None and settle < 65,
      "cancel -> needs_you in %.1fs (<65s)" % (settle if settle else -1))
cur = sessions.get_track(TID)
check(cur.get("session_id") == SID, "session id INTACT after cancel (%r)" % cur.get("session_id"))
check(not th.is_alive(), "the steer thread was unblocked by the cancel")

# turn 3: steering again RESUMES the same session
t3 = sessions.steer(TID, "again")
check(t3.get("session_id") == SID, "steer after cancel resumed the SAME session")
check(t3.get("status") == "needs_you", "turn 3 settled to needs_you")
check((t3.get("last_reply") or "").startswith("echo:again"),
      "turn 3 got a real reply (%r)" % (t3.get("last_reply") or "")[:30])

drivers.cancel(TID)
print()
if _fails:
    print("=== %d FAILED ===" % len(_fails))
    sys.exit(1)
print("e2e cancel/resume: PASS")
