# -*- coding: utf-8 -*-
"""GET /processes carries what the Prozesse screen reads per step (owner 2026-10-21:
"ich sehe nicht, an welchem Schritt ich stehe, was schon erledigt ist"): `step.card` =
the card's lane, a one-line delivered summary, the pending owner question and whether
the step waits on the owner - DERIVED from the card at read time, never stored on the
step. A step without a card has card=None.

Self-sandboxing: temp db. Run: py -3.12 ops/tests/test_processes_view.py
"""
import os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SANDBOX = tempfile.mkdtemp(prefix="hd-procview-")
from spine.storage import db
db.ROOT = SANDBOX
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
events.EV = os.path.join(SANDBOX, "events.jsonl")
db.init(role="tool")
assert db.DBPATH.startswith(SANDBOX)
from cells.engineer.chains import processes

fails = []


def check(c, m):
    print(("  ok   " if c else "  FAIL ") + m)
    if not c:
        fails.append(m)


def card(cid, lane, status, reply="", question=None):
    t = {"id": cid, "task": cid, "lane": lane, "status": status, "priority": "medium", "branch": cid,
         "repo": SANDBOX, "created": "2026-10-21 05:00:00", "rank": 0, "driver": "claude", "actor": "owner",
         "client": "", "ai_cost": 0.0, "last_reply": reply, "run_dir": ""}
    if question:
        t["question"] = question
    db.track_put(t)


card("c1", "done", "accepted", "**DELIVERED** Baum   laeuft\nauf der Testseite")
card("c2", "review", "submitted", "bitte pruefen")
card("c3", "working", "needs_you", "", {"id": "q", "kind": "question", "questions": [
    {"question": "Anhaenge kopieren?", "header": "Anhaenge?", "options": []}]})
card("c4", "backlog", "queued")
ps = processes._load()
ps.insert(0, {"id": "p-1", "request": "Plan", "status": "running", "client": "", "due": "", "cost": 0.0,
              "steps": [{"title": "a", "mode": "do", "status": "accepted", "track": "c1"},
                        {"title": "b", "mode": "human", "status": "accepted", "track": "c2"},
                        {"title": "c", "mode": "do", "status": "accepted", "track": "c3"},
                        {"title": "d", "mode": "do", "status": "accepted", "track": "c4"},
                        {"title": "e", "mode": "do", "status": "proposed", "track": None}]})
processes._save(ps)

v = next(p for p in processes.view() if p["id"] == "p-1")
c = [s.get("card") for s in v["steps"]]
check(c[0]["summary"] == "DELIVERED Baum laeuft auf der Testseite", "summary: markdown stars and line breaks folded to one line")
check(c[0]["owner"] is False and c[0]["lane"] == "done", "a done card does not wait on the owner")
check(c[1]["owner"] is True, "a card in review waits on the owner")
check(c[2]["owner"] is True and c[2]["ask"] == "Anhaenge?", "a pending question waits on the owner and names it")
check(c[3]["owner"] is False and c[3]["ask"] == "", "a queued card waits on nobody")
check(c[4] is None, "a step without a card has card=None")
check("card" not in processes.get("p-1")["steps"][0], "the card view is derived at read time, never stored on the step")
print("PASS test_processes_view" if not fails else "FAIL (%d)" % len(fails))
sys.exit(1 if fails else 0)
