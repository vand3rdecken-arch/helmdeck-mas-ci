# -*- coding: utf-8 -*-
"""A steer answering a WAITING goal-path card becomes a pm clarification
(measured bug, 2026-09-04): "Owner macht jetzt das Video selbst" resolved a
real Play-Console blocker on the release card, but only that card's own turn
log ever carried it - four days and 30-odd turns later the planner asked to
release again, having forgotten. sessions.steer() is the ONE choke point
every owner reply to a needs_you card passes through (its own comment: "the
owner either answered it through the buttons ... or decided something else
instead"), so that is where the fold-in lives.

Under test:
  1. a steer to a needs_you card that IS a plan milestone's card -> folds.
  2. a steer to a card that is NOT needs_you -> does not fold (nothing to
     resolve).
  3. a steer to a needs_you card that is NOT on the goal path -> does not
     fold (an unrelated card's Q&A is not the goal's ground truth).
  4. a folding failure (pm.add_clarification raises) never blocks the steer.

Self-sandboxing: same in-memory track + stub driver pattern as
test_steer_replace.py; no real CLI, no real board."""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, DAEMON)
from spine.storage import db
# this test used to db.init() the LIVE store (caught by the state-into-db
# live-db guard): sandbox it
import tempfile
db.DBPATH = os.path.join(tempfile.mkdtemp(prefix="hd-steerfold-"), "test.db")
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


# -- isolate: no real audit/push/driver, a controllable in-memory track -------
_store = {}


def _track(tid, **over):
    t = {"id": tid, "run_dir": os.path.join(HERE, "nx"), "repo": None,
         "branch": None, "worktree": None, "session_id": "sess-0",
         "status": "running", "lane": "working", "task": "t"}
    t.update(over)
    _store[tid] = t


sessions._load = lambda: [dict(v) for v in _store.values()]
sessions._find = lambda tracks, tid: (dict(_store[tid]) if tid in _store else None)
sessions.get_track = lambda tid: (dict(_store[tid]) if tid in _store else None)
sessions._save_track = lambda t: _store[t["id"]].update(t)


def _mutate(tid, fn):
    t = dict(_store[tid])
    if fn(t) is not False:
        _store[tid].update(t)
    return dict(_store[tid])


sessions._mutate = _mutate
events.emit = lambda *a, **k: None
notify.clear_dedup = lambda *a, **k: None
notify.card_event = lambda *a, **k: None
sessions._pending_context = lambda t: ""
sessions._ensure_worktree = lambda t: ""
sessions._maybe_compact = lambda t, log: t
sessions._maybe_fast_track_ship = lambda t, log: None
drivers.turn_inflight = lambda tid: False

from spine.ops import actionlog
actionlog.ActionLog = lambda rd: type("L", (), {"log": lambda *a, **k: None})()
from spine.agent import turnopts
turnopts.save_attachments = lambda *a, **k: []
turnopts.resolve_model = lambda *a, **k: ("model", None)
turnopts.augment_prompt = lambda text, *a, **k: text
sessions._turn = lambda t, prompt, model=None, perm=None, by=None: ("s", "ok: " + prompt, {"usage": {}, "models": []})


def _finish_turn(tid, sid, result, meta, log):
    t = _mutate(tid, lambda tt: tt.__setitem__("status", "running"))
    return t, "done"


sessions._finish_turn = _finish_turn

# -- the fold-in target: a scripted pm double, never the real planner/board ---
from cells.copilot.planning import pm

_clarified = []
pm.get_goal = lambda: "Play-Store-Launch"
pm.latest_plan = lambda: {"milestones": [{"name": "Release freigeben", "card": "REL"}]}
pm.add_clarification = lambda text, actor="owner": (_clarified.append(text), None)[1]


print("\n[1] needs_you + on the goal path -> folds")
_track("REL", status="needs_you", task="Produktionsrelease freigeben",
       question={"question": "Google verlangt ein Video - weiter?", "header": "Video-Nachweis"})
sessions.steer("REL", "Owner macht jetzt das Video selbst und macht spaeter weiter.")
check(len(_clarified) == 1, "exactly one clarification recorded (%d)" % len(_clarified))
check("Video selbst" in _clarified[0], "the owner's actual answer text is in the clarification")
check("Video-Nachweis" in _clarified[0] or "Google verlangt ein Video" in _clarified[0],
      "the worker's pending question text is in the clarification, not just the answer")
check("Produktionsrelease freigeben" in _clarified[0], "the card's own title anchors the fact")

print("\n[2] not needs_you -> no fold (nothing to resolve)")
_clarified.clear()
_track("REL", status="running", task="Produktionsrelease freigeben")
sessions.steer("REL", "mach weiter")
check(not _clarified, "a steer to a card that was NOT waiting folds nothing")

print("\n[3] needs_you but off the goal path -> no fold (not the goal's ground truth)")
_clarified.clear()
_track("OTHER", status="needs_you", task="Irgendeine andere Karte",
       question={"question": "Farbe A oder B?"})
sessions.steer("OTHER", "Farbe A")
check(not _clarified, "an unrelated card's answered question is NOT folded into goal clarifications")

print("\n[4] a folding failure never blocks the steer itself")
_clarified.clear()
_track("REL", status="needs_you", task="Produktionsrelease freigeben")


def _boom(text, actor="owner"):
    raise RuntimeError("disk full")


pm.add_clarification = _boom
result = sessions.steer("REL", "weiter so")
check(result is not None and result.get("status") == "running",
      "the steer still completes normally when the fold itself raises")

print("\n%s (%d failure(s))" % ("FAILED" if _fails else "PASS", len(_fails)))
sys.exit(1 if _fails else 0)
