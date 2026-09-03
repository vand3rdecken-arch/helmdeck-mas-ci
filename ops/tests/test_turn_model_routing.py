# -*- coding: utf-8 -*-
"""sessions._turn model routing - NO turn may fall through to the Claude
CLI's global default. Found live 2026-08-14: only steer()'s composer path
resolved "auto"; dispatch, auto-continue and ask-repair called _turn with no
model, so the spawned CLI ran on whatever the OWNER'S interactive /model was
last set to (fable-5 that day - the most expensive tier, silently billed on
cards everyone believed were on Auto/sonnet). Pinned here:
  - no model on the card -> _turn resolves Auto to a CONCRETE id (never none)
  - "auto" stored on the card -> same
  - an explicit model (card field or per-steer override) passes through
  - the card's own facts route: high value/priority -> the strong tier
Self-sandboxing: temp db/events/settings, drivers.run monkeypatched - no CLI."""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

SANDBOX = tempfile.mkdtemp()
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from spine.agent import drivers
from cells.engineer.cards import sessions

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


captured = {}


def _fake_run(cfg, t, prompt, by=None):
    captured["cfg"] = cfg
    return ("sid-x", "ok", {"usage": {}, "models": []})


drivers.run = _fake_run


def _track(tid, **kw):
    run_dir = os.path.join(SANDBOX, tid)
    os.makedirs(run_dir, exist_ok=True)
    t = {"id": tid, "status": "needs_you", "lane": "working", "task": "t",
         "branch": tid, "run_dir": run_dir, "turns": 0,
         "updated": "2026-08-14 00:00:00"}
    t.update(kw)
    db.track_put(t)
    return t


CONCRETE = {"claude-sonnet-5", "claude-opus-5", "claude-haiku-4-5"}

# 1) no model anywhere -> Auto resolves to a concrete id (the old leak: cfg
#    carried no model at all and the CLI global decided)
t = _track("t-none")
sessions._turn(t, "please fix the flaky test in ci")
check(captured["cfg"].get("model") in CONCRETE,
      "no model on card -> concrete Auto pick (%r), never the CLI global" % captured["cfg"].get("model"))

# 2) "auto" stored on the card -> same resolution (never literally --model auto)
t = _track("t-auto", model="auto")
sessions._turn(t, "please fix the flaky test in ci")
check(captured["cfg"].get("model") in CONCRETE,
      "'auto' on card -> concrete pick (%r), not the literal string" % captured["cfg"].get("model"))

# 3) explicit model on the card passes through untouched
t = _track("t-explicit", model="claude-haiku-4-5")
sessions._turn(t, "anything")
check(captured["cfg"].get("model") == "claude-haiku-4-5", "card's explicit model wins")

# 4) per-turn override beats everything
t = _track("t-override", model="claude-haiku-4-5")
sessions._turn(t, "anything", model="claude-opus-5")
check(captured["cfg"].get("model") == "claude-opus-5", "per-turn override wins over the card field")

# 5) the card's facts route: a high-value card lands on the strong tier
t = _track("t-value", value=500.0, priority="high")
sessions._turn(t, "ok")
check(captured["cfg"].get("model") == "claude-opus-5",
      "high-value/priority card -> strong tier (%r)" % captured["cfg"].get("model"))

print()
if _fails:
    print("FAILED: %d check(s)" % len(_fails))
    sys.exit(1)
print("ALL GREEN - no turn can leak to the CLI's global model default")
