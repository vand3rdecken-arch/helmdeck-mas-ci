# -*- coding: utf-8 -*-
"""Accept-and-rebind: when the first turn after a --resume spawn demonstrably
started FRESH (resume_detached), _finish_turn must FOLLOW the pointer to the new
session (which holds this turn's steer+reply), drop the old head into
session_chain, and leave a visible 'Kontext verloren' note - not keep the
pointer on the old head (which hid the steer as out-of-order chain history and
re-resumed the same unattachable session forever). Paseo parity: agent.ts
handleSystemMessage accepts a changed session id, emits a notice, never fails.
Pins the 'Fix AI-Kosten-Tracking' incident (2026-08-10)."""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(HERE)
sys.path.insert(0, DAEMON)

SANDBOX = tempfile.mkdtemp(prefix="hd-rebind-")
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from spine.ops import runs
runs.REC = os.path.join(SANDBOX, "runs")
os.makedirs(runs.REC, exist_ok=True)
from spine.comms import notify
from cells.engineer import sessions as S
S.REC = runs.REC
notify.card_event = lambda *a, **k: None

from spine.ops.actionlog import ActionLog

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _mk(tid, sid, ctx):
    run_dir = os.path.join(runs.REC, tid)
    os.makedirs(run_dir, exist_ok=True)
    t = {"id": tid, "task": "t", "status": "running", "lane": "working",
         "machine": True, "session_id": sid, "session_chain": [],
         "ctx_tokens": ctx, "turns": 3, "run_dir": run_dir}
    tracks = S._load(); tracks.append(t); S._save(tracks)
    return t, ActionLog(run_dir)


def _detached_meta(resumed):
    # no echo + a first API call carrying only the brief = silent fresh start
    return {"usage": {}, "cost_usd": None, "models": [], "subtype": "success",
            "resumed_from": resumed, "resume_echo": False,
            "ctx_first": {"cache_read_input_tokens": 12000}}


def _healthy_meta():
    # not a resume spawn (no resumed_from) - a normal same-session turn
    return {"usage": {}, "cost_usd": None, "models": [], "subtype": "success"}


# --- 1) detached resume: pointer FOLLOWS the new session -------------------
t, log = _mk("card-detach", "old-aaaa", ctx=200000)
S._finish_turn("card-detach", "new-bbbb", "echo done.", _detached_meta("old-aaaa"), log)
t2 = S._find(S._load(), "card-detach")
check(t2["session_id"] == "new-bbbb", "pointer advanced to the continuation session")
check("old-aaaa" in (t2.get("session_chain") or []), "old head preserved in session_chain")
raw = open(os.path.join(t2["run_dir"], "actions.jsonl"), encoding="utf-8").read()
check("Kontext verloren" in raw, "a visible 'Kontext verloren' note was left")

# --- 2) healthy same-session turn: no spurious rotation --------------------
t, log = _mk("card-same", "sess-x", ctx=50000)
S._finish_turn("card-same", "sess-x", "echo done.", _healthy_meta(), log)
t2 = S._find(S._load(), "card-same")
check(t2["session_id"] == "sess-x", "same session id -> pointer unchanged")
check(not (t2.get("session_chain") or []), "no chain churn on a same-session turn")

# --- 3) normal rotation (compaction-style, id changed but NOT detached) ----
t, log = _mk("card-rot", "old-1", ctx=160000)
S._finish_turn("card-rot", "new-2", "echo done.", _healthy_meta(), log)
t2 = S._find(S._load(), "card-rot")
check(t2["session_id"] == "new-2", "legit rotation advances the pointer")
check("old-1" in (t2.get("session_chain") or []), "rotated-away session kept in chain")
raw = open(os.path.join(t2["run_dir"], "actions.jsonl"), encoding="utf-8").read()
check("Kontext verloren" not in raw, "silent rotation: no scary note (chain divider only)")

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails)); sys.exit(1)
print("resume-rebind: all pinned - PASS")
