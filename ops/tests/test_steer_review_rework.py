# -*- coding: utf-8 -*-
"""A steer to a card on REVIEW (owner 2026-10-18: "karten auf review wenn neue steer kommt geht nicht auf
in arbeit und zeigt falsch als das ist ok so"): the OWNER's instruction sends it back to In Arbeit and
clears the verdict that described the work before it; a DELEGATED steer (Henry resolving a conflict) keeps
it on Review. Same in-memory track + stub driver harness as test_steer_folds_clarification.py."""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, DAEMON)
from spine.storage import db
# this test used to db.init() the LIVE store (caught by the state-into-db
# live-db guard): sandbox it
import tempfile
db.DBPATH = os.path.join(tempfile.mkdtemp(prefix="hd-steer-review-"), "test.db")
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
    # like trackstore._mutate: the WHOLE edited track is saved, so a popped key is gone
    t = dict(_store[tid])
    if fn(t) is not False:
        _store[tid] = t
    return dict(_store[tid])


sessions._mutate = _mutate
_lanes = []
events.emit = lambda kind, tid, **k: _lanes.append((kind, tid, k)) if kind == "lane" else None
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


print("[1] the OWNER steers a card on Review -> back to In Arbeit, the old verdict is gone")
_track("RV", status="needs_you", lane="review", merge_kind="mergeable", merge_report="clean - mergeable",
       review_report="review passed", gate_report="gate green")
sessions.steer("RV", "Bitte noch den Button nach unten.")
t = _store["RV"]
check(t["lane"] == "working", "lane review -> working (%s)" % t["lane"])
check(t["status"] == "running", "status running")
check(not any(k in t for k in ("merge_report", "merge_kind", "review_report", "gate_report")),
      "the stale green verdict is cleared, so the board cannot show it as 'ok' (%s)" %
      [k for k in ("merge_report", "merge_kind", "review_report", "gate_report") if k in t])
check(any(k[2].get("frm") == "review" and k[2].get("to") == "working" and k[2].get("verb") == "bounce" for k in _lanes),
      "a lane event review -> working (verb bounce) is recorded (%s)" % _lanes)

print("[2] a DELEGATED steer (Henry fixing a merge conflict) keeps the card on Review")
_lanes.clear()
_track("CF", status="needs_you", lane="review", merge_kind="conflict", merge_report="conflict in a.py")
sessions.steer("CF", "Konflikt in a.py loesen", actor="henry", source="henry")
t = _store["CF"]
check(t["lane"] == "review" and t.get("merge_kind") == "conflict", "stays on Review with its finding (%s)" % t["lane"])
check(not _lanes, "no lane event")

print("[3] a steer on Done still reopens it (unchanged)")
_track("DN", status="done", lane="done")
sessions.steer("DN", "noch eine Kleinigkeit")
check(_store["DN"]["lane"] == "working", "done -> working")

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails)); sys.exit(1)
print("steer on review: PASS")
