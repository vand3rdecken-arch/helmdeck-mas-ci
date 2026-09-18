# -*- coding: utf-8 -*-
"""Root-cause fix, owner complaint 2026-09-18 ("warum muss ich immer wieder
nachfragen"): a card finishing had no path back into the owner's board chat
unless a HANDS sub-agent produced it (cells/copilot/chat/hands.py's `_land`) -
the Henry-broker closing a card via `action: move` (review or done), or a
gate-less machine/direct/research card landing on done, printed at most a
generic template line ("abgenommen und gemergt") with no trace of what the
worker actually said. Henry would promise "im naechsten Chat-Turn" and nothing
ever woke the chat up again.

Fixed by threading the worker's own `last_reply` (spine.turn.outcomes.excerpt)
plus Henry's own `why`/`note` into the SAME reuse-not-rebuild mechanisms
already used elsewhere in this file's neighbourhood:
  - henry_broker._notify_owner (already the chat+push door for every other
    closing action - did/ship/restart/rerun_deploy/steer) now also fires for
    `move`, carrying the reply excerpt.
  - dispatch._accept_machine's DONE branch (the one gate-less cards actually
    land through) now writes a `_say_card` line with that same excerpt when
    Henry's own move report is deliberately skipped there (see the
    _machine_done guard in henry_broker.py) - one line, not zero, not two.

This test drives the REAL cells/engineer/cards/sessions.move_lane path (not a
stub) through henry_broker._decide, exactly the shape the owner's card
description named ("Henry-Broker ... move done"), for a machine card whose
last_reply carries real, distinctive content - proven to FAIL on the pre-fix
code shape (which wrote nothing about the reply anywhere in the chat for this
transition).

Sandboxed: temp db/settings, no daemon, no network, no model.
Run: py -3.12 ops/tests/test_broker_move_result_to_chat.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-move-chat-")

from spine.storage import db  # noqa: E402
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events  # noqa: E402
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()
from spine.ops import runs  # noqa: E402
runs.REC = os.path.join(SANDBOX, "runs")
os.makedirs(runs.REC, exist_ok=True)

from cells.copilot.chat import copilot  # noqa: E402
from cells.engineer.cards import sessions  # noqa: E402
from spine.auth import auth  # noqa: E402
from spine.comms import notify  # noqa: E402
from cells.copilot.broker import henry_broker as hb  # noqa: E402

OWNER = "tien"
auth.list_users = lambda: [{"name": OWNER, "role": "owner"}]
notify.push_fcm = lambda *a, **k: False   # never touch the real FCM path

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


def cards_text():
    msgs = (copilot.history(OWNER) or {}).get("messages") or []
    return [m.get("text") or "" for m in msgs]


# The worker's own words - distinctive enough that finding them proves the
# REAL reply travelled, not a generic template line.
REPLY = "DELIVERED: Autostart-Task fuer den Emulator angelegt und verifiziert (xk291f)."

CARD_ID = "c-move-done"
run_dir = os.path.join(runs.REC, CARD_ID)
os.makedirs(run_dir, exist_ok=True)
db.track_put({"id": CARD_ID, "task": "Autostart-Task", "status": "needs_you",
              "lane": "working", "machine": True, "run_dir": run_dir,
              "worktree": SANDBOX, "branch": sessions.MACHINE_BRANCH,
              "repo": SANDBOX, "last_reply": REPLY})

decision = {"action": "move", "card": CARD_ID, "lane": "done",
            "text": "", "why": "auf dem Rechner erledigt"}


class _Esc:
    def record_attempt(self, i):
        pass

    def record_note(self, i, n):
        pass

    def record_decision(self, i, a, card=None, why="", kind=""):
        pass


saved = {k: getattr(hb, k) for k in
         ("escalations", "_ask", "_hands_on_ask", "_dispatcher_privileged",
          "_card_log_tail", "_audit_context", "_snapshot", "_judgement_policy",
          "_audit")}
hb.escalations = _Esc()
hb._ask = lambda *a, **k: dict(decision)
hb._hands_on_ask = lambda *a, **k: dict(decision)
hb._dispatcher_privileged = lambda t: True
hb._card_log_tail = lambda *a, **k: ""
hb._audit_context = lambda t: ""
hb._snapshot = lambda: ""
hb._judgement_policy = lambda t: "policy"
hb._audit = lambda c, n: None
try:
    closed = hb._decide({"id": "e1", "kind": "delivered-parked", "card": CARD_ID,
                         "attempts": 0, "detail": "x"})
finally:
    for k, v in saved.items():
        setattr(hb, k, v)

check(closed is True, "the escalation closes on a verified move")

t = db.track_get(CARD_ID)
check((t or {}).get("lane") == "done", "the card actually landed on done")

texts = cards_text()
check(any(REPLY in tx for tx in texts),
      "the worker's own last reply reached the owner's board chat - "
      "this is RED on the pre-fix code (move/accept wrote no reply anywhere)")

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails))
    sys.exit(1)
print("broker-move-result-to-chat: all pinned - PASS")
