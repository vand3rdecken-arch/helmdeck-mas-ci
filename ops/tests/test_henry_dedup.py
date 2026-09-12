# -*- coding: utf-8 -*-
"""One event, one line, one push (owner report 2026-09-12: "viele Meldungen
doppelt - Karte sendet Push und Henry auch").

Measured on the owner's chat of 2026-09-11 (card tbh-d, 13:30-13:35): a single
landing produced SIX messages - the lane pipeline's "auf Review geprueft" and
"abgenommen und gemergt" lines, and for each a second "Henry (kind): move ->
lane - why" bubble, plus a ship line - and Henry's bubbles pushed the phone
UNGATED (raw push_fcm, no presence policy) while the card's own push was
correctly suppressed because the owner was looking at the chat.

Three rules pinned here, each proven to FAIL on the pre-fix code shape:
  1. Henry's push goes through notify.escalate (presence-gated), never raw
     push_fcm.
  2. A successful `move` writes NO separate Henry bubble - his `why` rides
     inside the lane pipeline's own outcome line via move_lane(note=...).
  3. _move_lane folds that note into the success lines (review / landed).

Sandboxed: no daemon, no network, no model; every sink is stubbed.
"""
import inspect
import os
import sys

import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

# Sandbox BEFORE any daemon import: _execute reads the track store for real
# (trackstore._load), and the live-db guard refuses that from a test.
SANDBOX = tempfile.mkdtemp(prefix="hd-dedup-")
from spine.storage import db  # noqa: E402
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events  # noqa: E402
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()
from spine.ops import runs  # noqa: E402
runs.REC = os.path.join(SANDBOX, "runs"); os.makedirs(runs.REC, exist_ok=True)

from cells.copilot.broker import henry_broker as hb  # noqa: E402
from cells.copilot.planning import pm_comm  # noqa: F401 (bind i18n before stubs)
from cells.copilot.chat import copilot as _  # noqa: F401

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# ---------------------------------------------------------------------------
# 1) _notify_owner: presence-gated escalate, not raw push
pushed_raw, escalated, said = [], [], []


class _Notify:
    push_fcm = staticmethod(lambda *a, **k: pushed_raw.append(a))
    escalate = staticmethod(lambda title, body, track_id="": escalated.append((body, track_id)))


class _I18n:
    t = staticmethod(lambda k, **kw: "Henry")


class _Copilot:
    say = staticmethod(lambda text, cls="pm", card=None: said.append((text, card)))


import spine.comms.notify, spine.registry.i18n, cells.copilot.chat.copilot  # noqa: E402,F401
import spine.comms, spine.registry, cells.copilot.chat  # noqa: E402
_prev = (spine.comms.notify, spine.registry.i18n, cells.copilot.chat.copilot)
spine.comms.notify, spine.registry.i18n, cells.copilot.chat.copilot = _Notify, _I18n, _Copilot
saved_audit = hb._audit
hb._audit = lambda c, n: None
try:
    hb._notify_owner("Henry (ship-decision): ship none - nur daemon-seitig", {"id": "c9"})
finally:
    spine.comms.notify, spine.registry.i18n, cells.copilot.chat.copilot = _prev
    hb._audit = saved_audit

check(not pushed_raw, "1. Henry never pushes raw (push_fcm untouched)")
check(escalated == [("Henry (ship-decision): ship none - nur daemon-seitig", "c9")],
      "1. the push goes through notify.escalate with the card id (presence policy applies)")
check(len(said) == 1, "1. exactly one chat line")


# ---------------------------------------------------------------------------
# 2) _decide on a successful `move`: no Henry bubble, note handed to move_lane
class _Esc:
    def __init__(self):
        self.notes, self.decisions = [], []

    def record_attempt(self, i):
        pass

    def record_note(self, i, n):
        self.notes.append(n)

    def record_decision(self, i, a, card=None, why=""):
        self.decisions.append(a)


moves, notified = [], []


class _Sessions:
    @staticmethod
    def move_lane(tid, lane, actor="owner", _autopark=True, note=""):
        moves.append((tid, lane, actor, note))
        return {"lane": lane}


class _Events:
    settings = staticmethod(lambda: {})


import cells.engineer.cards  # noqa: E402
from cells.engineer.cards import sessions as _real_sessions  # noqa: E402
_run_dir = os.path.join(runs.REC, "c1"); os.makedirs(_run_dir, exist_ok=True)
_real_sessions._save([{"id": "c1", "task": "Karte D", "status": "needs_you", "lane": "working",
                       "run_dir": _run_dir, "worktree": SANDBOX, "branch": "c1"}])
_prev_sessions = getattr(cells.engineer.cards, "sessions", None)
_prev_events = sys.modules.get("spine.storage.events")
saved = {k: getattr(hb, k) for k in
         ("escalations", "_hands_on_ask", "_ask", "_audit", "_notify_owner", "_find_track",
          "_dispatcher_privileged", "_card_log_tail", "_audit_context", "_snapshot",
          "_judgement_policy")}
verb = {"action": "move", "card": "c1", "lane": "review",
        "text": "Commit e926034 verifiziert, beide Defekte gefixt", "why": "gruen"}
hb.escalations = _Esc()
hb._hands_on_ask = lambda *a, **k: dict(verb)
hb._ask = lambda *a, **k: dict(verb)
hb._audit = lambda c, n: None
hb._notify_owner = lambda text, t: notified.append(text)
hb._find_track = lambda c: {"id": "c1", "lane": "working"} if c else None
hb._dispatcher_privileged = lambda t: True
hb._card_log_tail = lambda *a, **k: ""
hb._audit_context = lambda t: ""
hb._snapshot = lambda: ""
hb._judgement_policy = lambda t: "policy"
cells.engineer.cards.sessions = _Sessions
sys.modules["spine.storage.events"] = _Events
try:
    closed = hb._decide({"id": "e1", "kind": "delivered-parked", "card": "c1",
                         "attempts": 0, "detail": "x"})
finally:
    for k, v in saved.items():
        setattr(hb, k, v)
    if _prev_sessions is not None:
        cells.engineer.cards.sessions = _prev_sessions
    if _prev_events is not None:
        sys.modules["spine.storage.events"] = _prev_events
    else:
        sys.modules.pop("spine.storage.events", None)

check(closed is True, "2. a verified move closes the escalation")
check(moves == [("c1", "review", "henry", "Commit e926034 verifiziert, beide Defekte gefixt")],
      "2. Henry's text rides into move_lane(note=...)")
check(notified == [], "2. NO separate Henry bubble for a move - the lane line is the report")

# ---------------------------------------------------------------------------
# 3) _move_lane folds the note into the pipeline's own success lines
from cells.engineer.cards import lanemachine as lm  # noqa: E402
src = inspect.getsource(lm._move_lane)
check('note=""' in src.splitlines()[0] and "_by" in src,
      "3. _move_lane accepts note= and builds the by-line")
check("say.reviewChecked" in src and "verdict=_verdict) + _by" in src,
      "3. review outcome line carries the mover's note")
check("say.shipHenry" in src and 'else "") + _by' in src,
      "3. landed outcome line carries the mover's note")
check("note=note" in inspect.getsource(lm.move_lane),
      "3. move_lane wrapper threads note through")

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails))
    sys.exit(1)
print("henry-dedup: all pinned - PASS")
