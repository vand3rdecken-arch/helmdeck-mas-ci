# -*- coding: utf-8 -*-
"""Engine and model are ONE choice (owner 2026-10-08: "Engine und Modell muessen
zusammengehoeren"). Pinned:
  1. every engine entry carries its own `models`: claude/claude-desktop the Claude
     catalog, opencode the gateway models, engines without a catalog []
  2. the model->engine decision is MEMBERSHIP in that catalog, not an id prefix
  3. check_pair refuses a pair the engine cannot run (both directions), accepts
     ""/auto/aliases, and passes an engine with no catalog
  4. the flat /models list is the runnable half of the same catalog
Self-sandboxing: temp db, probes faked - no network, no CLI.
Run: py -3.12 ops/tests/test_engine_models.py"""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
SANDBOX = tempfile.mkdtemp()
os.environ["CLAUDE_CONFIG_DIR"] = os.path.join(SANDBOX, "claude-config")
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
db.init()

from spine.agent import engines, turnopts

FAILS = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


turnopts._fetch_models = lambda: None
engines._probe = lambda name, defn: {"id": name, "label": defn["label"], "type": defn["type"],
                                     "verified": True, "configured": False, "enabled": True,
                                     "config": {}, "status": "ready", "version": "x", "error": ""}
engines.invalidate()
OC = turnopts.OPENCODE_MODELS[0]["id"]
CL = "claude-sonnet-5-5"

snap = {e["id"]: e for e in engines.snapshot()}
ids = lambda e: {m["id"] for m in e["models"]}
check(CL in ids(snap["claude"]) and CL in ids(snap["claude-desktop"]), "claude engines carry the Claude catalog")
check(OC not in ids(snap["claude"]), "...and no opencode model")
check(OC in ids(snap["opencode"]) and CL not in ids(snap["opencode"]), "opencode carries only its gateway models")
check(snap["omp"]["models"] == [] and snap["codex"]["models"] == [], "engines without a catalog say []")

check(turnopts.engine_for(OC) == "opencode", "model->engine: a catalog id runs on opencode")
check(turnopts.engine_for("opencode/not-in-the-catalog") == "claude",
      "model->engine is membership, not the 'opencode/' prefix")
check(turnopts.engine_for(CL) == "claude" and turnopts.engine_for("") == "claude", "claude and default stay claude")

check(engines.check_pair("claude", CL) is None, "pair ok: claude + a Claude model")
check(engines.check_pair("claude-desktop", "sonnet") is None, "pair ok: alias resolves")
check(engines.check_pair("claude", "") is None and engines.check_pair("opencode", "auto") is None, "'' and auto always fit")
check(engines.check_pair("claude", OC), "pair refused: claude + an opencode model")
check(engines.check_pair("opencode", CL), "pair refused: opencode + a Claude model")
check(engines.check_pair("omp", CL) is None, "an engine with no catalog cannot be checked -> passes")

flat = {m["id"] for m in turnopts.list_models()}
check(OC in flat, "/models includes opencode while the engine is ready")
engines._probe = lambda name, defn: {**{"id": name, "label": "x", "type": defn["type"], "verified": True,
                                        "configured": False, "enabled": True, "config": {},
                                        "version": "", "error": "not installed"}, "status": "unavailable"}
engines.invalidate()
check(OC not in {m["id"] for m in turnopts.list_models()}, "/models drops it when the engine is not installed")
check(OC in ids({e["id"]: e for e in engines.snapshot()}["opencode"]),
      "...but the engine entry still lists its models (shown greyed out in the picker)")

print()
if FAILS:
    print("FAILED: %d" % len(FAILS)); sys.exit(1)
print("ALL GREEN - engine and model are one catalog")
