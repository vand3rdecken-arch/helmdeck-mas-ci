# -*- coding: utf-8 -*-
"""Interrupt-and-replace steer (Paseo replaceAgentRun parity).

A steer arriving mid-turn must take effect NOW - soft-interrupt the live turn
and run the new instruction, instead of queuing behind the whole running turn on
the per-card lock. A burst of steers collapses to LAST-WINS via the steer epoch.
Self-sandboxing: a stub driver whose _turn is interruptible; no real CLI."""
import os, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, DAEMON)
from spine.storage import db
# this test used to db.init() the LIVE store (caught by the state-into-db
# live-db guard): sandbox it
import tempfile
db.DBPATH = os.path.join(tempfile.mkdtemp(prefix="hd-steer-"), "test.db")
db.init()
from cells.engineer.cards import sessions
from spine.agent import drivers
from spine.storage import events
from spine.comms import notify

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# -- isolate: no real audit/push, a controllable in-memory track ---------------
_store = {"TID": {"id": "TID", "run_dir": os.path.join(HERE, "nx"), "repo": None,
                  "branch": None, "worktree": None, "session_id": "sess-0",
                  "status": "running", "lane": "working", "task": "t"}}
sessions._load = lambda: [dict(_store["TID"])]
sessions._find = lambda tracks, tid: (dict(_store["TID"]) if tid == "TID" else None)
sessions.get_track = lambda tid: (dict(_store["TID"]) if tid == "TID" else None)
sessions._save_track = lambda t: _store["TID"].update(t)


def _mutate(tid, fn):
    t = dict(_store["TID"])
    if fn(t) is not False:
        _store["TID"].update(t)
    return dict(_store["TID"])
sessions._mutate = _mutate
sessions._finish_turn = lambda tid, sid, result, meta, log: (
    _mutate(tid, lambda tt: tt.__setitem__("status", "needs_you")), "done")[1] and (dict(_store["TID"]), "done")
events.emit = lambda *a, **k: None
notify.clear_dedup = lambda *a, **k: None
notify.card_event = lambda *a, **k: None
sessions._pending_context = lambda t: ""
sessions._ensure_worktree = lambda t: ""
sessions._maybe_compact = lambda t, log: t
sessions._maybe_fast_track_ship = lambda t, log: None

from spine.ops import actionlog
actionlog.ActionLog = lambda rd: type("L", (), {"log": lambda *a, **k: None})()
from spine.agent import turnopts
turnopts.save_attachments = lambda *a, **k: []
turnopts.resolve_model = lambda *a, **k: ("model", None)
turnopts.augment_prompt = lambda text, *a, **k: text

# -- stub driver: every turn is interruptible (blocks until cancel or timeout) --
_live = {"active": False, "ev": None, "any_interrupt": False}
_order = []
_guard = threading.Lock()

drivers.turn_active = lambda tid: _live["active"]


def _cancel(tid):
    with _guard:
        _live["any_interrupt"] = True
        ev = _live["ev"]
    if ev:
        ev.set()
    return True
drivers.cancel = _cancel


_delivered = []                          # every prompt that REACHED the session
                                         # (an interrupted turn's message stays in
                                         # the conversation history - not lost)


def _fake_turn(t, prompt, model=None, perm=None, by=None):
    _delivered.append(prompt)
    ev = threading.Event()
    with _guard:
        _live["active"] = True
        _live["ev"] = ev
    interrupted = ev.wait(0.4)          # a turn takes ~0.4s unless interrupted
    with _guard:
        _live["active"] = False
    if interrupted:
        return "s", "(turn cancelled by you)", {"usage": {}, "models": []}
    _order.append(prompt)
    return "s", "done: " + prompt, {"usage": {}, "models": []}
sessions._turn = _fake_turn

# 1) a turn is already running
t_run = threading.Thread(target=lambda: sessions.steer("TID", "RUNNING"), daemon=True)
t_run.start()
for _ in range(50):
    if _live["active"]:
        break
    time.sleep(0.01)
check(_live["active"], "a turn is live before the replacing steers arrive")

# 2) two steers arrive DURING the running turn - last must win
def _do(tag): sessions.steer("TID", tag)
a = threading.Thread(target=_do, args=("S1",), daemon=True); a.start()
time.sleep(0.05)
b = threading.Thread(target=_do, args=("S2",), daemon=True); b.start()
a.join(6); b.join(6); t_run.join(6)
time.sleep(0.6)                          # let the winning turn's 0.4s complete

check(_live["any_interrupt"], "the live turn was soft-interrupted (not queued)")
check("RUNNING" not in _order, "the original running turn did NOT complete its old goal")
check(len(_order) == 1, "exactly ONE turn completed after the burst (order=%s)" % _order)
# NO COMMAND LOST: each steer either reached the session (delivered - an
# interrupted turn's message stays in the conversation history) or was bundled
# into the winning turn's prompt.
_alltext = "\n".join(_delivered)
check("S1" in _alltext, "S1 reached the session or was bundled (delivered=%d)" % len(_delivered))
check("S2" in _alltext and len(_order) == 1 and "S2" in _order[0],
      "S2 (the newest) completed its turn")

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails)); sys.exit(1)
print("steer-replace: all pinned - PASS")
