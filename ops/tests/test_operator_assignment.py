# -*- coding: utf-8 -*-
"""Headless test for the ASSIGNMENT MODEL (owner decree 2026-10-05: "operator auch
nur per Zuweisung"): owner sees everything; operator and client work only on what
is THEIRS or ASSIGNED/SHARED. Each case is a way an operator could still reach
the whole board, run through the real handlers:

 1. A STALE stored permission matrix (an operator with recordings.view, pm.view,
    chat.use ... from before the model) is capped by ROLE_CEILING - the stored list
    would otherwise stay authoritative for every cap it knew.
 2. Filing a card: a restricted role cannot aim it at another repo, pick the
    agent's permission mode, set billing/value, or (guest) start it at once.
 3. Rooms: an operator manages only rooms they are IN; the all-rooms overview is
    the owner's.
 4. The private Henry chat (board-wide context) is the owner's: operator -> 403.
 5. Board-wide reads (dashboard, escalations, Claude sessions) -> 403 for the
    operator, still 200 for the owner.

Self-sandboxing: temp DB and recordings. Run: py -3.12 ops/tests/test_operator_assignment.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-opassign-")

from spine.storage import db
db.ROOT = SANDBOX   # BOTH, not just DBPATH - see test_hook_idle.py's preamble
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from spine.auth import auth, permissions
from cells.engineer.cards import dispatch, sessions
from cells.engineer.routes import routes_tracks
from cells.copilot.chat import rooms, room_henry
from cells.copilot.routes import routes_rooms, routes_copilot
from spine.http.routes import routes_system, routes_info

room_henry.maybe_answer = lambda msg, **k: False
dispatch.REC = os.path.join(SANDBOX, "recordings")

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


PW = "Correct-Horse-Battery-9"
for n, r in (("tien", "owner"), ("ops", "operator"), ("member", "client")):
    auth.create_user(n, PW, r, actor="test")
U = {n: {"name": n, "role": r} for n, r in (("tien", "owner"), ("ops", "operator"), ("member", "client"))}


class Req(object):
    def __init__(self, path="/x"):
        self.path = path
        self.sent = None

    def _send(self, status, body, *a):
        try:
            self.sent = (status, json.loads(body))
        except (TypeError, ValueError):
            self.sent = (status, body)


def run(handler, user, *args, path="/x"):
    q = Req(path)
    handler(q, U[user], *args)
    return q.sent


# -- 1. the ceiling beats a stale stored matrix ---------------------------------------
old_style = ["recordings.view", "devices.manage", "devices.use", "chat.use", "cards.admin",
             "projects.view", "pm.view", "templates.view", "rooms.manage"]
permissions.set_role_caps("operator", old_style, actor="test")
check(permissions.matrix()["operator"] == {"cards.admin", "rooms.manage"},
      "a stored operator matrix with the OLD caps is capped to cards.admin + rooms.manage")
check(permissions.can(U["ops"], "recordings.view") is False and permissions.can(U["ops"], "chat.use") is False
      and permissions.can(U["tien"], "recordings.view") is True,
      "the operator has no board-wide read cap and no private chat; the owner keeps them")

# -- 2. filing a card -----------------------------------------------------------------------
REPO = os.path.join(SANDBOX, "repo")
OTHER = os.path.join(SANDBOX, "other-repo")
for d in (REPO, OTHER):
    os.makedirs(d)
    subprocess.run(["git", "init", "-q", d], check=True)
events.save_settings({"default_repo": REPO})
body = {"task": "Angriff auf anderes Repo", "repo": OTHER, "perm": "bypassPermissions", "lane": "working",
        "value": 999, "billing": "tm", "rate": 500, "project_id": "p-x", "client": "someone-else", "driver": "claude"}
st, card = run(routes_tracks.tracks_new_post, "member", dict(body))
check(st == 200 and os.path.abspath(card["repo"]) == os.path.abspath(REPO),
      "a guest cannot aim a card at another repo - the server uses default_repo")
check(card["perm"] == sessions.DEFAULT_PERM, "nor choose the agent's permission mode (bypassPermissions ignored)")
check(card["lane"] == "backlog", "a guest's card waits in the backlog even when she asks for 'working'")
check(card["value"] != 999 and card["billing"] == "fixed" and card["rate"] is None and not card.get("project_id"),
      "nor set value, billing, rate or project")
check(card["client"] == "member" and card["dispatched_by"] == "member", "and the card is hers (client + dispatched_by)")
st, card2 = run(routes_tracks.tracks_new_post, "ops", dict(body, lane="backlog"))
check(st == 200 and os.path.abspath(card2["repo"]) == os.path.abspath(REPO) and card2["perm"] == sessions.DEFAULT_PERM
      and card2["client"] == "ops",
      "an operator is held to the same defaults, and the card is theirs (client = their name)")
st, card3 = run(routes_tracks.tracks_new_post, "tien", dict(body, lane="backlog", client="acme"))
check(st == 200 and os.path.abspath(card3["repo"]) == os.path.abspath(OTHER)
      and card3["perm"] == "bypassPermissions" and card3["client"] == "acme" and card3["billing"] == "tm",
      "the OWNER keeps every knob (own repo, mode, billing label)")

# -- 3. rooms ------------------------------------------------------------------------------------
r_mine = rooms.create("Ops Raum", "ops", [])
r_other = rooms.create("Owner Raum", "tien", ["member"])
st, out = run(routes_rooms.rooms_members_post, "ops", {"room": r_other["id"], "add": ["ops"]})
check(st == 404, "an operator cannot add THEMSELVES to a room they are not in")
st, out = run(routes_rooms.rooms_members_post, "ops", {"room": r_mine["id"], "add": ["member"]})
check(st == 200 and "member" in out["members"], "but manages a room they are in")
st, lst = run(routes_rooms.rooms_get, "ops", path="/rooms?all=1")
check([r["id"] for r in lst] == [r_mine["id"]], "?all=1 gives an operator only THEIR rooms")
st, lst = run(routes_rooms.rooms_get, "tien", path="/rooms?all=1")
check({r["id"] for r in lst} == {r_mine["id"], r_other["id"]}, "the owner overview lists every room (names + members only)")
st, out = run(routes_rooms.rooms_members_post, "tien", {"room": r_mine["id"], "add": ["tien"]})
check(st == 200 and "tien" in out["members"], "the owner can put himself into any room (visible in the member list)")

# -- 4./5. board-wide surfaces ---------------------------------------------------------------------
check(run(routes_copilot.chat_history_get, "ops")[0] == 403, "the private Henry chat: operator -> 403")
check(run(routes_copilot.chat_threads_get, "ops")[0] == 403, "the chat thread list: operator -> 403")
check(run(routes_system.dashboard_data_get, "ops")[0] == 403, "dashboard data (every card's economics): operator -> 403")
check(run(routes_info.escalations_get, "ops")[0] == 403, "escalations (repos, failures): operator -> 403")
check(run(routes_system.sessions_claude_get, "ops")[0] == 403, "the machine's Claude sessions: operator -> 403")
check(run(routes_system.dashboard_data_get, "tien")[0] == 200, "the owner still reads the dashboard")

# -- 6. the outer fence: what a restricted role may POST at all --------------------------------
ok_ = auth.restricted_post_allowed
check(not ok_(U["ops"], "/control/teach/start") and not ok_(U["ops"], "/control/demo"),
      "an operator cannot start a desktop recording (/control/teach/start) - it had no role check at all")
check(not ok_(U["ops"], "/processes/abc/step") and not ok_(U["ops"], "/tracks/assign") and not ok_(U["ops"], "/chat"),
      "nor operate processes, assign cards or use the private chat")
check(ok_(U["ops"], "/tracks/x/lane") and ok_(U["ops"], "/tracks/x/steer") and ok_(U["ops"], "/rooms/post"),
      "but does their card work and posts in rooms")
check(ok_(U["member"], "/push/register") and ok_(U["member"], "/rooms/post") and not ok_(U["member"], "/tracks/x/lane"),
      "a guest can register her push device (it was blocked: no pushes ever reached a guest) but not move cards")
check(not ok_(U["member"], "/control/teach/start") and not ok_(U["member"], "/tracks/assign"),
      "and nothing else outside the list")

print()
if _fails:
    print("FAILED (%d):" % len(_fails))
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("OPERATOR ASSIGNMENT: all pinned - PASS")
