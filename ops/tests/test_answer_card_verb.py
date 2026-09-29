# -*- coding: utf-8 -*-
"""answer_card: Henry relays the OWNER's answer to a card's open question.

Owner 2026-09-29 'Warum kommen die Fragen nicht zu Henry': two answers given in
the board chat left both cards parked, because steer is HELD while a card waits
on an owner question and the only door was the card's own panel.

Real path: copilot_actions._run_action -> sessions.answer_question -> real
sessions.steer (only the claude turn is faked). Pins:
 1. OLD behaviour (the steer verb): card stays parked, no turn runs.
 2. answer_card with an owner message: question cleared, turn runs with the
    words, audit row names the owner message + actor owner-via-henry.
 3. answer_card WITHOUT an owner message (broker / wake): refused, card parked.
 4. stale request_id -> 409, no turn.
Run: py -3.12 ops/tests/test_answer_card_verb.py
"""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
SANDBOX = tempfile.mkdtemp(prefix="hd-ac-")

from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from cells.engineer.cards import sessions
from cells.copilot.chat import copilot_actions as ca
from spine.ops import bgthread
from spine.ops.actionlog import ActionLog

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


BLOCK = ('<helmdeck-ask>{"questions": [{"question": "Wohin mit dem Button?", "header": "Ort",'
         ' "options": [{"label": "Mitte"}, {"label": "Links"}]}]}</helmdeck-ask>')


def _parked(tid):
    run_dir = os.path.join(SANDBOX, tid)
    os.makedirs(run_dir, exist_ok=True)
    t = {"id": tid, "status": "needs_you", "lane": "working", "task": "button " + tid,
         "branch": tid, "run_dir": run_dir, "worktree": "", "turns": 1, "machine": True,
         "session_id": "s-" + tid, "ai_cost": 0.0, "tokens_in": 0, "tokens_out": 0,
         "models": [], "updated": "2026-09-29 00:00:00"}
    db.track_put(t)
    sessions._settle_reply(t, BLOCK, ActionLog(run_dir))
    sessions._save_track(t)
    return t["question"]["id"]


prompts = []
class _Spawn(Exception):
    pass


def _fake_turn(track, prompt, model=None, perm=None, by=None):
    prompts.append(prompt)
    raise _Spawn()          # the turn REACHED the driver; nothing else to run


sessions._turn = _fake_turn


def _inline(name, fn):      # run the backgrounded door inline
    try:
        fn()
    except _Spawn:
        pass


bgthread.spawn = _inline

qid = _parked("c-one")
print("old path: steer verb on a parked card")
r = ca._run_action({"type": "steer", "card": "c-one", "text": "nicht in die Mitte"}, "duy", "owner")
check(r.startswith("HELD") and prompts == [], "steer is HELD, no turn runs")
check((sessions.get_track("c-one").get("question") or {}).get("id") == qid, "card still parked")

print("answer_card with the owner's message:")
r = ca._run_action({"type": "answer_card", "card": "c-one", "text": "nicht in die Mitte, verorten"},
                   "duy", "owner", owner_msg="nicht in die Mitte, verorten")
t = sessions.get_track("c-one")
check("question" not in t, "question cleared")
check(len(prompts) == 1 and "nicht in die Mitte" in prompts[0], "worker resumed with the owner's words")
audit = [e for e in events.query_audit(kind="answer_card")]
check(audit and audit[-1].get("actor") == "owner-via-henry"
      and "verorten" in audit[-1].get("owner_msg", ""), "audit row: actor + underlying owner message")

print("no owner message (broker / wake):")
_parked("c-two")
n = len(prompts)
r = ca._run_action({"type": "answer_card", "card": "c-two", "text": "Mitte"}, "henry", "owner")
check("REFUSED" in r and len(prompts) == n, "refused, no turn")
check(sessions.get_track("c-two").get("question"), "card stays parked")

print("stale request_id:")
r = ca._run_action({"type": "answer_card", "card": "c-two", "text": "Mitte", "request_id": "q-old"},
                   "duy", "owner", owner_msg="Mitte")
check("409" in r and len(prompts) == n, "409, no turn")
r = ca._run_action({"type": "answer_card", "card": "c-one", "text": "Mitte"},
                   "duy", "owner", owner_msg="Mitte")
check("409" in r and len(prompts) == n, "already answered -> 409")

print()
if _fails:
    print("FAILED: " + "; ".join(_fails))
    sys.exit(1)
print("ALL ANSWER_CARD CHECKS PASSED")
