# -*- coding: utf-8 -*-
"""Headless test for HENRY IN A ROOM (team-rooms-member stage 4).

The model call is stubbed (`runner`), everything around it is the real code:
what goes INTO the turn, who may trigger it, where the answer and memory land.

 1. He answers ONLY on @henry; ordinary messages and his own never trigger him.
 2. The turn is built from the RECORD: members, every history line with its
    author's name, and the room's notes - and NOT the owner's private notes,
    nor another room's.
 3. The reply is stored as Henry's, addressed to the author of THAT message.
 4. A <memory-save> lands in the ROOM scope (readable by the room, invisible to
    the owner-side store) and is stripped from the visible reply.
 5. The CLI is spawned with NO tools, plan mode, no MCP, no ambient settings and
    an empty cwd - the isolation is in the argv, not in a sentence.
 6. Two asks are answered one after the other (the second turn already sees the
    first answer); a flood is bounded.
 7. A failing model never leaves the room silent: an honest note, to the asker.

Self-sandboxing: temp DB, no network, no real CLI. Run: py -3.12 ops/tests/test_room_henry.py
"""
import os
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-roomhenry-")

from spine.storage import db
db.ROOT = SANDBOX   # BOTH, not just DBPATH - see test_hook_idle.py's preamble
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from spine.auth import auth
from cells.copilot.chat import rooms, room_henry, copilot_memory

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


PW = "Correct-Horse-Battery-9"
for n, r in (("tien", "owner"), ("member", "client")):
    auth.create_user(n, PW, r, actor="test")

# the owner's PRIVATE store - must never reach a room turn
db.memory_put("depot", "GEHEIM Depot 50k AAA BBB", actor="henry")

room = rooms.create("Team Alpha", "tien", ["member"])
RID = room["id"]
other = rooms.create("Team Beta", "tien", [])
db.memory_put("beta-regel", "BETA nur fuer Beta", actor="henry", scope="room", scope_id=other["id"])
db.memory_put("standup", "ALPHA Standup um 9 Uhr", actor="henry", scope="room", scope_id=RID)

calls = []


def stub(system, prompt):
    calls.append({"system": system, "prompt": prompt})
    return "Hallo, Standup ist um 9 Uhr.\n<memory-save name=\"standup-ort\">Standup im Raum Mars</memory-save>", {}


# -- 1. who triggers him ------------------------------------------------------------
m_plain = rooms.post(RID, "member", "wann ist standup?")
check(room_henry.maybe_answer(m_plain, background=False, runner=stub) is False and not calls,
      "an ordinary message does not wake Henry")
m_ask = rooms.post(RID, "member", "@henry wann ist standup?")
check(room_henry.maybe_answer(m_ask, background=False, runner=stub) is True and len(calls) == 1,
      "@henry wakes him exactly once")
last = rooms.history(RID, "member")[-1]
check(last["byKind"] == "henry" and last["by"] == "Henry" and last["to"] == "member",
      "his reply is stored as Henry's, addressed to the person who asked")
check(room_henry.maybe_answer(last, background=False, runner=stub) is False,
      "his own message can never trigger him (no loop)")
off = dict(room, henry_on_mention=False)
db.room_put(off)
check(room_henry.maybe_answer(rooms.post(RID, "member", "@henry hallo"), background=False,
                              runner=stub) is False,
      "a room with Henry switched off ignores @henry")
db.room_put(room)

# -- 2. what goes in ---------------------------------------------------------------------
p = calls[0]["prompt"]
check("member: wann ist standup?" in p and "member: @henry wann ist standup?" in p,
      "the turn carries the history with each line's AUTHOR")
check("tien, member" in p or "member, tien" in p or ("tien" in p and "MITGLIEDER" in p),
      "and the member list")
check("ALPHA Standup um 9 Uhr" in p, "the room's own note is recalled")
check("GEHEIM" not in p and "AAA" not in p and "depot" not in p.lower(),
      "the owner's private notes never ride into a room turn")
check("BETA" not in p, "another room's notes do not either")
check("Du bist Henry in einem Team-Raum" in calls[0]["system"],
      "the system brief is the ROOM brief, not the board copilot's")

# -- 4. memory lands in the room scope --------------------------------------------------
check("memory-save" not in last["text"] and last["text"].startswith("Hallo"),
      "the sentinel block is stripped from the visible reply")
vis = copilot_memory.all_notes(copilot_memory.room_viewer(RID))
check("room:%s/standup-ort" % RID in vis, "the save landed in the ROOM scope")
check("standup-ort" not in db.memory_all(), "and not in the owner's store")
check("room:%s/standup-ort" % other["id"] not in copilot_memory.all_notes(
    copilot_memory.room_viewer(other["id"])), "nor in another room")

# -- 5. isolation lives in the argv ---------------------------------------------------------
argv = room_henry._argv()
i = argv.index("--tools")
check(argv[i + 1] == "", "the CLI gets an EMPTY tool list")
check(argv[argv.index("--permission-mode") + 1] == "plan", "permission mode plan")
check("--strict-mcp-config" in argv and "--resume" not in argv,
      "no MCP servers and no session to resume (stateless)")
check(argv[argv.index("--setting-sources") + 1] == "", "no ambient settings layer")
check(os.path.isdir(room_henry._empty_cwd()) and not os.listdir(room_henry._empty_cwd()),
      "the working directory is an EMPTY dir outside the repo")

# -- 6. order and bounds -----------------------------------------------------------------------
order = []


def slow(system, prompt):
    order.append(("start", prompt.count("Henry:")))
    time.sleep(0.15)
    order.append(("end",))
    return "Antwort %d" % len(order), {}


a = rooms.post(RID, "member", "@henry erste Frage")
b = rooms.post(RID, "tien", "@henry zweite Frage")
ts = [threading.Thread(target=room_henry.answer, args=(RID, m["by"], m["text"], slow)) for m in (a, b)]
for t in ts:
    t.start()
    time.sleep(0.03)
for t in ts:
    t.join()
check([o[0] for o in order] == ["start", "end", "start", "end"],
      "two asks run one AFTER the other, never overlapping")
check(order[2][1] > order[0][1],
      "the second turn already sees the first answer in its history")

room_henry.MAX_QUEUED = 1
gate = threading.Event()


def blocked(system, prompt):
    gate.wait(2)
    return "ok", {}


results = []
msgs = [rooms.post(RID, "member", "@henry flut %d" % i) for i in range(4)]
ths = [threading.Thread(target=lambda m=m: results.append(
    room_henry.answer(RID, m["by"], m["text"], blocked))) for m in msgs]
for t in ths:
    t.start()
    time.sleep(0.03)
gate.set()
for t in ths:
    t.join()
check(results.count(None) >= 2, "a flood beyond the queue bound is refused, not queued forever (%d dropped)"
      % results.count(None))
room_henry.MAX_QUEUED = 3

# -- 7. a failing model is said out loud ----------------------------------------------------------
def boom(system, prompt):
    raise RuntimeError("rate limit")


r = room_henry.answer(RID, "tien", "@henry hilf", boom)
check(r["byKind"] == "henry" and r["to"] == "tien" and r.get("error") and "rate limit" in r["text"],
      "a failing model leaves an honest note addressed to the asker, never silence")

print()
if _fails:
    print("FAILED (%d):" % len(_fails))
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("ROOM HENRY: all pinned - PASS")
