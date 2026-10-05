# -*- coding: utf-8 -*-
"""Headless test for CHAT CONSENT (team-rooms-member stage 7).

An admin may read someone's private Henry chat only while that person has
granted it. Every case is a way the rule could leak, through the real route
handlers and db:

 1. Closed by default - for the OWNER too. No grant -> 403, and the same answer
    whether the account exists or not (no enumeration).
 2. A grant opens exactly the NAMED admin, for exactly that account; another
    admin is still refused.
 3. "Active" is DERIVED at every read: an expired grant is refused with no
    sweeper involved; a revoked one at once.
 4. Only the account that gave a grant may revoke it.
 5. Every read under a grant is recorded - the account sees who read what and
    when (table) and the append-only audit has the event.
 6. A grant can only name an existing admin other than yourself; hours bounded.

Self-sandboxing: temp DB, no network. Run: py -3.12 ops/tests/test_chat_grants.py
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-grants-")

from spine.storage import db
db.ROOT = SANDBOX   # BOTH, not just DBPATH - see test_hook_idle.py's preamble
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from spine.auth import auth
from cells.copilot.chat import chat_grants
from cells.copilot.routes import routes_grants

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


PW = "Correct-Horse-Battery-9"
for n, r in (("tien", "owner"), ("ops", "operator"), ("ops2", "operator"), ("***", "client")):
    auth.create_user(n, PW, r, actor="test")
U = {n: {"name": n, "role": r} for n, r in
     (("tien", "owner"), ("ops", "operator"), ("ops2", "operator"), ("***", "client"))}

db.chat_append("ops", [{"role": "user", "kind": "text", "text": "privat: Gehaltsfrage", "ts": "09:00", "date": "2026-10-05"},
                       {"role": "assistant", "kind": "text", "text": "Antwort", "ts": "09:01", "date": "2026-10-05"}])


class Req(object):
    def __init__(self, path="/x"):
        self.path = path
        self.sent = None

    def _send(self, status, body):
        self.sent = (status, json.loads(body))


def get(handler, user, path="/x"):
    q = Req(path)
    handler(q, U[user])
    return q.sent


def post(handler, user, body):
    q = Req()
    handler(q, U[user], body)
    return q.sent


# -- 1. closed by default ---------------------------------------------------------
st, _b = get(routes_grants.chat_admin_get, "tien", "/chat/admin?account=ops")
check(st == 403, "the OWNER cannot read an operator's private chat without a grant")
st2, b2 = get(routes_grants.chat_admin_get, "tien", "/chat/admin?account=nobody")
check(st2 == 403 and b2 == _b, "same answer for an account that does not exist (no enumeration)")

# -- 6. who may be named ------------------------------------------------------------------
check(post(routes_grants.grants_post, "ops", {"grantee": "***", "hours": 2})[0] == 400,
      "a grant to a non-admin (a guest) is refused")
check(post(routes_grants.grants_post, "ops", {"grantee": "ops", "hours": 2})[0] == 400,
      "you cannot grant yourself")
check(post(routes_grants.grants_post, "ops", {"grantee": "ghost", "hours": 2})[0] == 400,
      "an unknown account cannot be named")
check(post(routes_grants.grants_post, "ops", {"grantee": "tien", "hours": 0})[0] == 400
      and post(routes_grants.grants_post, "ops", {"grantee": "tien", "hours": 99999})[0] == 400,
      "the duration is bounded")

# -- 2. a grant opens exactly the named admin ---------------------------------------------
st, g = post(routes_grants.grants_post, "ops", {"grantee": "tien", "hours": 2})
check(st == 200 and g["grantee"] == "tien" and g["account"] == "ops", "ops grants the owner 2 hours")
st, out = get(routes_grants.chat_admin_get, "tien", "/chat/admin?account=ops")
check(st == 200 and [e["text"] for e in out["entries"]] == ["privat: Gehaltsfrage", "Antwort"],
      "the named admin now reads that chat")
check(get(routes_grants.chat_admin_get, "ops2", "/chat/admin?account=ops")[0] == 403,
      "ANOTHER admin is still refused")
check(get(routes_grants.chat_admin_get, "tien", "/chat/admin?account=***")[0] == 403,
      "and the grant covers only that account")

# -- 5. the account sees who read what -----------------------------------------------------
st, mine = get(routes_grants.grants_get, "ops")
gv = mine["given"][0]
check(gv["active"] is True and len(gv["reads"]) == 1 and gv["reads"][0]["reader"] == "tien"
      and gv["reads"][0]["n"] == 2,
      "ops sees the read: WHO (tien), WHEN, and how many entries")
check(any(e.get("kind") == "chat_grant" and e.get("op") == "read" and e.get("actor") == "tien"
          for e in events.read_events()),
      "the append-only audit holds the read event too")
st, theirs = get(routes_grants.grants_get, "tien")
check([r["account"] for r in theirs["received"]] == ["ops"],
      "the admin sees which chats are currently open to him")

# -- 3. expiry is derived -----------------------------------------------------------------
gx = dict(g, expires=time.time() - 1)
db.chat_grant_put(gx)
check(get(routes_grants.chat_admin_get, "tien", "/chat/admin?account=ops")[0] == 403,
      "an EXPIRED grant is refused with no sweeper - active is derived from the clock")
check(get(routes_grants.grants_get, "ops")[1]["given"][0]["active"] is False
      and get(routes_grants.grants_get, "tien")[1]["received"] == [],
      "and it is listed as inactive / no longer received")

# -- 4. revoke ----------------------------------------------------------------------------------
st, g2 = post(routes_grants.grants_post, "ops", {"grantee": "tien", "hours": 5})
check(get(routes_grants.chat_admin_get, "tien", "/chat/admin?account=ops")[0] == 200, "a fresh grant opens again")
check(post(routes_grants.grants_revoke_post, "tien", {"id": g2["id"]})[0] == 404,
      "the admin cannot revoke (or extend) a grant he RECEIVED - only the giver can")
st, _b = post(routes_grants.grants_revoke_post, "ops", {"id": g2["id"]})
check(st == 200 and get(routes_grants.chat_admin_get, "tien", "/chat/admin?account=ops")[0] == 403,
      "the giver revokes and the very next read is refused")
check(any(e.get("op") == "revoke" for e in events.read_events()), "revocation is audited")

print()
if _fails:
    print("FAILED (%d):" % len(_fails))
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("CHAT GRANTS: all pinned - PASS")
