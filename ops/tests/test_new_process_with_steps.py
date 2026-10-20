# -*- coding: utf-8 -*-
"""Pins 2026-10-20: Henry announced a ten-step chain, `new_process` could not
carry steps, so three processes were born EMPTY (0/0) with the chain as prose.
`new_process` now takes `steps` / `template` + `repo`: the steps become cards at
birth. Also: save_process_template (owner only), the step cap is refused loudly
(no silent cut to 8), no repo -> steps stay proposed (never default_repo).

Self-sandboxing: temp db. Run: py -3.12 ops/tests/test_new_process_with_steps.py
"""
import os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SANDBOX = tempfile.mkdtemp(prefix="hd-newproc-")
from spine.storage import db as _db
_db.ROOT = SANDBOX
_db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
_db.init(role="tool")
assert _db.DBPATH.startswith(SANDBOX)
from cells.engineer.chains import processes
from cells.copilot.chat import copilot_actions as ca

REPO = os.path.join(SANDBOX, "repo")
os.makedirs(REPO)
_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


steps = [{"title": "Schritt %d" % i, "mode": "human" if i == 4 else "do"} for i in range(1, 11)]

r = ca._run_action({"type": "save_process_template", "name": "App-Kette", "steps": steps}, "henry", "owner")
check("gespeichert (10 Schritte)" in r, "template with 10 steps saved whole (cap was 8): %s" % r[:80])
tid = next(iter(processes.list_templates()))
check(len(processes.get_template(tid)["steps"]) == 10, "all 10 steps in the stored template")
r = ca._run_action({"type": "save_process_template", "name": "x", "steps": steps}, "henry", "client")
check("gesperrt" in r, "save_process_template is owner-only")
r = ca._run_action({"type": "save_process_template", "name": "x", "steps": steps * 2}, "henry", "owner")
check("at most" in r, "more than the cap is refused, not cut: %s" % r[:60])

r = ca._run_action({"type": "new_process", "request": "App X", "repo": REPO, "steps": steps[:3]}, "henry", "owner")
p = processes.list_processes()[0]
check(len(p["steps"]) == 3 and all(s.get("track") for s in p["steps"]),
      "steps given -> 3 step cards at birth: %s" % r[:80])
check("Schritt-Karten laufen an" in r, "the result tells Henry the chain runs")

r = ca._run_action({"type": "new_process", "request": "App Y", "repo": REPO, "template": tid}, "henry", "owner")
p = processes.list_processes()[0]
check(len(p["steps"]) == 10 and all(s.get("track") for s in p["steps"]), "template -> 10 step cards at birth")

r = ca._run_action({"type": "new_process", "request": "App Z", "steps": steps[:2]}, "henry", "owner")
p = processes.list_processes()[0]
check(len(p["steps"]) == 2 and not any(s.get("track") for s in p["steps"]) and "NO project" in r,
      "no repo -> steps stay proposed, Henry is told to ask")

r = ca._run_action({"type": "new_process", "request": "App W", "template": "gibts-nicht"}, "henry", "owner")
check("kenne ich nicht" in r, "unknown template is named, no empty process filed")

r = ca._run_action({"type": "new_process", "request": "Leer"}, "henry", "owner")
check("still EMPTY" in r, "plain new_process still born empty")
print("PASS test_new_process_with_steps" if not _fails else "FAIL (%d)" % len(_fails))
sys.exit(1 if _fails else 0)
