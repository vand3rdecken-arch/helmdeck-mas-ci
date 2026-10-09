# -*- coding: utf-8 -*-
"""Headless test: the OWNER's @henry in a room runs as its OWN run, beside the chat.

 1. owner asks -> hands.spawn(kind="agent", room=...) is called, copilot.chat is NOT
    (no shared per-user chat state, so the main chat is neither waited on nor interrupted)
 2. a non-owner asks -> the isolated one-shot runner, never the owner's tools
 3. the run's end lands as Henry's message in THAT room, addressed to the asker
    (completed, failed and canceled), via the one room writer
 4. the task carries the projects shared with the room's other members, and only those

Self-sandboxing, no model call. Run: py -3.12 ops/tests/test_room_owner_henry.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-roomowner-")
from spine.storage import db
db.ROOT = SANDBOX
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from spine.auth import auth
from spine.ops import projects
from cells.copilot.chat import rooms, room_henry, hands, copilot

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


PW = "Correct-Horse-Battery-9"
auth.create_user("tien", PW, "owner", actor="test")
auth.create_user("***", PW, "operator", actor="test")
room = rooms.create("Family", "tien", ["***"])
rid = room["id"]
repo = os.path.join(SANDBOX, "immobilien")
os.makedirs(repo)
p = projects.sight_repo(repo, name="Immobilien")
other = projects.sight_repo(os.path.join(SANDBOX, "privat"), name="Privat")
projects.share(p["id"], add=["***"])

calls = {"spawn": [], "chat": 0}
room_henry.run_claude = lambda *a, **k: (_ for _ in ()).throw(AssertionError("real model call"))
print("users:", [(u["name"], u["role"]) for u in auth.list_users()])
hands.spawn = lambda *a, **k: calls["spawn"].append((a, k)) or "hid-1"
copilot.chat = lambda *a, **k: calls.__setitem__("chat", calls["chat"] + 1) or {"reply": "x"}

msg = rooms.post(rid, "tien", "@henry was gibt es Neues", by_kind="human")
room_henry.answer(rid, "tien", msg["text"])
check(len(calls["spawn"]) == 1 and calls["chat"] == 0, "1. owner: own run spawned, copilot.chat untouched")
a, k = calls["spawn"][0]
check(k.get("kind") == "agent" and k.get("room") == {"id": rid, "to": "tien"},
      "1. kind=agent, answer routed to this room and the asker")
check("Immobilien" in a[1] and repo in a[1], "4. the task names the project shared with the room")
check("Privat" not in a[1], "4. a project shared with nobody in the room is not offered")

seen = []
room_henry.answer(rid, "***", "@henry hi", runner=lambda system, prompt: (seen.append(prompt) or "ok", {}))
check(len(calls["spawn"]) == 1 and seen, "2. non-owner: isolated runner, no spawn")

t = {"room": {"id": rid, "to": "tien"}, "user": "tien"}
hands._land_room(t, "h1", "completed", "Zwei neue Angebote.", 3)
hands._land_room(t, "h2", "failed", "FAILED - spawn: boom", 0)
hands._land_room(t, "h3", "canceled", "CANCELLED", 1)
last = [m for m in rooms.history(rid, "tien") if m["byKind"] == "henry"][-3:]
check([m["text"] for m in last][0] == "Zwei neue Angebote." and all(m["to"] == "tien" for m in last),
      "3. completed: the answer is Henry's message to the asker")
check(last[1].get("error") and "boom" in last[1]["text"], "3. failed: honest error line")
check(last[2].get("error") and "gestoppt" in last[2]["text"], "3. canceled: says so")

print()
print("FAILED: %d" % len(_fails) if _fails else "ALL PASS")
sys.exit(1 if _fails else 0)
