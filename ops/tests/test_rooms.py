# -*- coding: utf-8 -*-
"""Headless test for TEAM ROOMS (team-rooms-member stage 3a).

Membership is the whole authorization story of a room, so every case is a way
it could leak or be bypassed, run through the REAL route handlers + the real
permission gate + the real db layer (sandboxed):

 1. A guest (client) reads and posts ONLY in rooms she is a member of; a room
    she is not in answers 404, exactly like an unknown id (no existence leak).
 2. The AUTHOR of a message is the authenticated account - a `by` smuggled in
    the body is ignored.
 3. Creating a room / changing members needs `rooms.manage` (owner, operator);
    a client is refused by the permission gate, not by luck.
 4. @mentions resolve only to MEMBERS (and `henry`); a non-member's name is not
    a mention, so nobody outside a room is ever addressed through it.
 5. Removing a member cuts access immediately (derived from the record).
 6. Room messages never appear in the account chat table.

Self-sandboxing: temp DB, no network. Run: py -3.12 ops/tests/test_rooms.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-rooms-")

from spine.storage import db
db.ROOT = SANDBOX   # BOTH, not just DBPATH - see test_hook_idle.py's preamble
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from spine.auth import auth, permissions
from cells.copilot.chat import rooms
from cells.copilot.routes import routes_rooms
from cells.copilot.chat import room_henry
room_henry_calls = []
room_henry.maybe_answer = lambda msg, **k: room_henry_calls.append(msg) and False   # this file tests MEMBERSHIP; Henry's turn has its own test (and a real CLI call costs plan quota)

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


PW = "Correct-Horse-Battery-9"
for n, r in (("tien", "owner"), ("ops", "operator"), ("***", "client"), ("fremd", "client")):
    auth.create_user(n, PW, r, actor="test")
U = {n: {"name": n, "role": r} for n, r in
     (("tien", "owner"), ("ops", "operator"), ("***", "client"), ("fremd", "client"))}


class Req(object):
    def __init__(self, path=""):
        self.path = path
        self.sent = None

    def _send(self, status, body):
        self.sent = (status, json.loads(body) if body else None)


def call(handler, user, body=None, path="/x"):
    q = Req(path)
    handler(q, U[user], body) if body is not None else handler(q, U[user])
    return q.sent


def gated(path, user):
    """What server.py's permission gate says for POST `path` (None = allowed)."""
    cap = permissions.cap_for("POST", path, path.strip("/").split("/"))
    return permissions.require(U[user], cap) if cap else None


# -- 3. who may create / change members ----------------------------------------
check(gated("/rooms/new", "***") is not None and gated("/rooms/members", "***") is not None,
      "a client is refused room creation and member changes by the permission gate")
check(gated("/rooms/new", "tien") is None and gated("/rooms/new", "ops") is None,
      "owner and operator hold rooms.manage")
check(gated("/rooms/post", "***") is None, "posting needs no capability - membership decides")

st, room = call(routes_rooms.rooms_new_post, "ops", {"name": "Team Alpha", "members": ["***"]})
check(st == 200 and set(room["members"]) == {"ops", "***"},
      "the operator creates a room; the creator is a member automatically")
RID = room["id"]
st, _b = call(routes_rooms.rooms_new_post, "ops", {"name": "x", "members": ["nobody"]})
check(st == 400, "an unknown account cannot be added")

# -- 1. membership gates read and post -----------------------------------------
st, lst = call(routes_rooms.rooms_get, "***", path="/rooms")
check(st == 200 and [r["id"] for r in lst] == [RID], "she sees the room she is in")
st, lst = call(routes_rooms.rooms_get, "fremd", path="/rooms")
check(st == 200 and lst == [], "an account outside the room sees no rooms")
st, lst = call(routes_rooms.rooms_get, "tien", path="/rooms")
check(lst == [], "even the OWNER does not see rooms he is not a member of in the plain list")
st, lst = call(routes_rooms.rooms_get, "tien", path="/rooms?all=1")
check(len(lst) == 1 and "messages" not in lst[0] and "preview" not in lst[0],
      "the manager overview (?all=1) lists names and members, never content")
st, lst = call(routes_rooms.rooms_get, "fremd", path="/rooms?all=1")
check(lst == [], "?all=1 is ignored for an account without rooms.manage")

st, _b = call(routes_rooms.rooms_post_post, "fremd", {"room": RID, "text": "hallo"})
check(st == 404, "a non-member cannot post (404, same as an unknown room)")
st, _b = call(routes_rooms.rooms_messages_get, "fremd", path="/rooms/messages?room=" + RID)
check(st == 404, "a non-member cannot read the history")
st, _b = call(routes_rooms.rooms_messages_get, "fremd", path="/rooms/messages?room=nope")
check(st == 404, "an unknown id answers the same 404 - no existence leak")

# -- 2. author = authenticated account -------------------------------------------
st, msg = call(routes_rooms.rooms_post_post, "***",
               {"room": RID, "text": "Status?", "by": "ops", "byKind": "henry"})
check(st == 200 and msg["by"] == "***" and msg["byKind"] == "human",
      "the author is the logged-in account; a forged `by`/`byKind` is ignored")

# -- 4. mentions -------------------------------------------------------------------
st, msg = call(routes_rooms.rooms_post_post, "ops",
               {"room": RID, "text": "@*** schau mal, @henry fasse zusammen. cc @fremd"})
check(msg["mentions"] == ["***"] and msg["henry"] is True,
      "@*** (case-insensitive) and @henry resolve; @fremd (not a member) is NOT a mention")
st, msg = call(routes_rooms.rooms_post_post, "***", {"room": RID, "text": "mail an a@***.de"})
check(msg["mentions"] == [], "an e-mail address is not a mention")

st, hist = call(routes_rooms.rooms_messages_get, "***", path="/rooms/messages?room=" + RID)
check(st == 200 and [m["by"] for m in hist["messages"]] == ["***", "ops", "***"],
      "members read the whole history with authors, oldest first")
st, hist2 = call(routes_rooms.rooms_messages_get, "***",
                 path="/rooms/messages?room=%s&after=%d" % (RID, hist["messages"][0]["seq"]))
check(len(hist2["messages"]) == 2, "?after= returns only newer messages")

# -- 5. removal cuts access at once --------------------------------------------------
st, room = call(routes_rooms.rooms_members_post, "ops", {"room": RID, "remove": ["***"]})
check(st == 200 and room["members"] == ["ops"], "the operator removes her")
st, _b = call(routes_rooms.rooms_messages_get, "***", path="/rooms/messages?room=" + RID)
check(st == 404, "she can no longer read - access is derived from the record, not cached")
st, _b = call(routes_rooms.rooms_post_post, "***", {"room": RID, "text": "noch da?"})
check(st == 404, "nor post")
st, _b = call(routes_rooms.rooms_members_post, "ops", {"room": RID, "remove": ["ops"]})
check(st == 400, "the last member cannot be removed (a room is never orphaned)")

# -- 7. mentions push THAT account only; unread is derived ----------------------------
from spine.comms import notify
pushed = []
notify.push_fcm = lambda *a, **k: pushed.append(k) or True
st, room2 = call(routes_rooms.rooms_new_post, "ops", {"name": "Team B", "members": ["***", "tien"]})
R2 = room2["id"]
call(routes_rooms.rooms_post_post, "ops", {"room": R2, "text": "hallo zusammen"})
check(pushed == [], "a plain message buzzes nobody")
call(routes_rooms.rooms_post_post, "ops", {"room": R2, "text": "@*** kannst du das pruefen"})
check(len(pushed) == 1 and pushed[0]["account"] == "***" and pushed[0]["extra"] == {"room": R2}
      and pushed[0]["kind"] == "room",
      "an @mention pushes ONLY the mentioned account, carrying the room id in the sealed payload")
n = len(pushed)
call(routes_rooms.rooms_post_post, "***", {"room": R2, "text": "@*** ich selbst"})
check(len(pushed) == n, "mentioning yourself buzzes nobody")
rooms.post(R2, "Henry", "Antwort fuer dich", by_kind="henry", extra={"to": "***"})
check(len(pushed) == n + 1 and pushed[-1]["account"] == "***",
      "Henry's reply buzzes the person he answered")

st, lst = call(routes_rooms.rooms_get, "***", path="/rooms")
mine = next(r for r in lst if r["id"] == R2)
check(mine["unread"] == 3 and mine["unread_mentions"] == 1,
      "unread = messages by OTHERS past her cursor (3), of which 1 mentions her")
st, lst = call(routes_rooms.rooms_get, "tien", path="/rooms")
check(next(r for r in lst if r["id"] == R2)["unread"] == 4,
      "another member's unread is counted from HIS own cursor (4 - nothing of his own)")
call(routes_rooms.rooms_messages_get, "***", path="/rooms/messages?room=" + R2)
st, lst = call(routes_rooms.rooms_get, "***", path="/rooms")
check(next(r for r in lst if r["id"] == R2)["unread"] == 0,
      "opening the room (fetching its messages) advances HER cursor only")
check(next(r for r in call(routes_rooms.rooms_get, "tien", path="/rooms")[1] if r["id"] == R2)["unread"] == 4,
      "and leaves his untouched")
db.room_read_set(R2, "***", 1)
check(next(r for r in call(routes_rooms.rooms_get, "***", path="/rooms")[1] if r["id"] == R2)["unread"] == 0,
      "a cursor never moves backwards")
try:
    rooms.mark_read(R2, "fremd", 99)
    check(False, "a non-member cannot set a read cursor")
except PermissionError:
    check(True, "a non-member cannot set a read cursor")

# -- 8. a card FROM a room (stage 6) -----------------------------------------------------
import subprocess
from cells.engineer.cards import dispatch, sessions
dispatch.REC = os.path.join(SANDBOX, "recordings")          # never the live recordings dir
REPO = os.path.join(SANDBOX, "repo")
os.makedirs(REPO)
subprocess.run(["git", "init", "-q", REPO], check=True)
st, out = call(routes_rooms.rooms_card_post, "***", {"room": R2, "task": "Angebot Kunde X"})
check(st == 400, "without a default repo the card is refused with a clear error")
events.save_settings({"default_repo": REPO})
st, out = call(routes_rooms.rooms_card_post, "fremd", {"room": R2, "task": "x"})
check(st == 404, "a non-member cannot file a card into a room")
st, out = call(routes_rooms.rooms_card_post, "***", {"room": R2, "task": "  "})
check(st == 400, "an empty task is refused")
_wakes_before = len(room_henry_calls)
st, out = call(routes_rooms.rooms_card_post, "***", {"room": R2, "task": "Angebot Kunde X"})
check(st == 200 and out["zugewiesen_an"] == ["ops"] and out["geteilt_mit"] == [],
      "a guest files a card: the operator in the room is ASSIGNED (works on it), the owner needs no share")
card = sessions.get_track(out["id"])
check(card["lane"] == "backlog" and card["client"] == "***" and card["dispatched_by"] == "***",
      "it lands in the backlog, billed/owned by her, nothing started")
check(card["branch"] != "(direct)" and not card.get("direct") and not card.get("machine"),
      "and as a worktree card - never a live-tree/machine card, whatever the repo template says")
check(card["zugewiesen_an"] == ["ops"], "zugewiesen_an is recorded on the card")
hist = rooms.history(R2, "***")
check(hist[-1]["byKind"] == "system" and hist[-1]["card"] == out["id"]
      and "Angebot Kunde X" in hist[-1]["text"],
      "the room gets a system line carrying the card id (the app links it)")
check(len(room_henry_calls) == _wakes_before, "a card line never wakes Henry")

# -- 9. the member picker ----------------------------------------------------------------
cap = permissions.cap_for("GET", "/rooms/accounts", ["rooms", "accounts"])
check(cap == "rooms.manage" and permissions.require(U["***"], cap) is not None
      and permissions.require(U["ops"], cap) is None,
      "the account list is for rooms.manage holders only")
st, accts = call(routes_rooms.rooms_accounts_get, "ops", path="/rooms/accounts")
check(st == 200 and {a["name"] for a in accts} == {"tien", "ops", "***", "fremd"}
      and all(set(a) == {"name", "role"} for a in accts),
      "it lists names and roles only - no tokens, no hashes")

# -- 6. not in the account chat -------------------------------------------------------
check(all(not a.startswith("room") and a not in (RID,) for a in db.chat_accounts()),
      "room messages never land in the per-account chat table")

print()
if _fails:
    print("FAILED (%d):" % len(_fails))
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("TEAM ROOMS: all pinned - PASS")
