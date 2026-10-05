# -*- coding: utf-8 -*-
"""Headless test for CARD SHARING (team-rooms-member stage 3b) - least privilege.

A card shared with a guest shows title, status and result and NOTHING else.
Run through the real route handlers and the real db:

 1. A guest sees her own cards and the cards shared with her - and no others.
 2. A card shared with her returns only the whitelisted SUMMARY: no repo path,
    worktree, run_dir, session, cost or transcript pointers. A field added to
    the card tomorrow stays private (whitelist, not blacklist).
 3. Sharing grants seeing, not acting: she still cannot read the card's
    transcript/live feed or steer it (owns_card stays the gate).
 4. Only cards.admin holders can share; a guest cannot widen her own access.
 5. Unsharing takes effect on the next request (derived from the record).
 6. Her OWN cards keep the full view; owner/operator keep everything.

Self-sandboxing: temp DB, no network. Run: py -3.12 ops/tests/test_card_sharing.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-share-")

from spine.storage import db
db.ROOT = SANDBOX   # BOTH, not just DBPATH - see test_hook_idle.py's preamble
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from spine.auth import auth
from cells.engineer.cards import sessions
from cells.engineer.routes import routes_tracks

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


def card(cid, client="", **kw):
    t = {"id": cid, "dispatched_by": kw.pop("dispatched_by", "tien"), "task": "Aufgabe " + cid, "lane": "working", "status": "idle",
         "client": client, "repo": "C:/Users/Tien/secret-repo", "worktree": "C:/wt/" + cid,
         "run_dir": "C:/rec/" + cid, "session_id": "sess-" + cid, "ai_cost": 12.5,
         "last_reply": "Ergebnis " + cid, "created": "2026-10-04 10:00:00",
         "updated": "2026-10-04 10:00:00", "branch": "req-" + cid}
    t.update(kw)
    from spine.storage.trackstore import _save_track
    _save_track(t)
    return t


card("mine", client="***")
card("owners")                       # the owner's private card
card("shared")                       # the owner's card, to be shared
card("theirs", client="fremd")


class Req(object):
    def __init__(self, path="/tracks"):
        self.path = path
        self.sent = None

    def _send(self, status, body, *a):
        self.sent = (status, json.loads(body) if isinstance(body, (str, bytes)) and body[:1] in ("{", "[", b"{", b"[") else body)


def lst(user):
    q = Req()
    routes_tracks.tracks_list_get(q, U[user])
    return q.sent[1]


def get(user, tid):
    q = Req()
    routes_tracks.tracks_get(q, U[user], tid)
    return q.sent


def share(user, body):
    q = Req()
    routes_tracks.tracks_share_post(q, U[user], body)
    return q.sent


ids = lambda rows: sorted(r["id"] for r in rows)

check(ids(lst("***")) == ["mine"], "before any share she sees only her own card")

# -- 4. who may share -------------------------------------------------------------
st, _b = share("***", {"id": "shared", "add": ["***"]})
check(st == 403, "a guest cannot share a card with herself")
st, _b = share("tien", {"id": "shared", "add": ["nobody"]})
check(st == 400, "an unknown account cannot be added")
st, _b = share("ops", {"id": "gibtsnicht", "add": ["***"]})
check(st == 404, "an unknown card answers 404")
st, _b = share("ops", {"id": "shared", "add": ["***"]})
check(st == 404, "an OPERATOR cannot share a card that is neither theirs nor assigned to them")
st, out = share("tien", {"id": "shared", "add": ["***"]})
check(st == 200 and out["geteilt_mit"] == ["***"], "the owner shares the card")

# -- 1. visibility ------------------------------------------------------------------
check(ids(lst("***")) == ["mine", "shared"],
      "she now sees her own card and the shared one - not the owner's private one")
check(ids(lst("fremd")) == ["theirs"], "another guest is unaffected by the share")
check(len(lst("tien")) == 4, "the owner still sees every card")

# -- 2. summary only ------------------------------------------------------------------
row = next(r for r in lst("***") if r["id"] == "shared")
check(set(row) <= set(auth.SHARED_FIELDS) | {"summary"} and row.get("summary") is True,
      "the list row of a shared card carries only whitelisted fields, flagged summary by the daemon")
for leak in ("repo", "worktree", "run_dir", "session_id", "ai_cost", "branch"):
    check(leak not in row, "shared list row has no %s" % leak)
st, one = get("***", "shared")
check(st == 200 and one["task"] == "Aufgabe shared" and one["last_reply"] == "Ergebnis shared",
      "the card GET shows title and result")
check("repo" not in one and "run_dir" not in one and "session_id" not in one,
      "the card GET of a shared card leaks no machine path or session")

# -- 6. her own card keeps the full view; owner unchanged -------------------------------
st, own = get("***", "mine")
check(own.get("repo") and own.get("run_dir"), "her OWN card keeps the full record")
st, full = get("tien", "shared")
check(full.get("repo") and full.get("session_id"), "the owner sees the full record")
st, _b = get("fremd", "shared")
check(st == 404, "a guest it was NOT shared with gets 404")

# -- 3. seeing is not acting ---------------------------------------------------------------
check(auth.owns_card(U["***"], {"id": "shared", "client": "", "geteilt_mit": ["***"]}) is False,
      "owns_card is still False for a shared card - transcript, live, steer stay closed")
check(auth.sees_card(U["***"], {"id": "shared", "client": "", "geteilt_mit": ["***"]}) is True,
      "sees_card is True")

# -- 5. unshare ------------------------------------------------------------------------------
st, out = share("tien", {"id": "shared", "remove": ["***"]})
check(st == 200 and out["geteilt_mit"] == [], "the owner withdraws the share")
check(ids(lst("***")) == ["mine"] and get("***", "shared")[0] == 404,
      "it takes effect on the very next request")

# -- 7. ASSIGNMENT (owner decree 2026-10-05: the operator, too, works only on what is
#       theirs or assigned) --------------------------------------------------------
card("ops-own", client="ops", dispatched_by="ops")
ops_ids = lambda: sorted(r["id"] for r in lst("ops"))
check(ops_ids() == ["ops-own"], "an operator sees only the cards they filed - not the owner's, not a guest's")
st, _b = get("ops", "owners")
check(st == 404, "and cannot open another card by id")
st, out = share("tien", {"id": "owners", "add": ["ops"]})
check(st == 200 and "owners" in ops_ids() and "task" in get("ops", "owners")[1]
      and "repo" not in get("ops", "owners")[1],
      "a card SHARED with an operator is a summary only (no repo path)")

def assign(user, body):
    q = Req()
    routes_tracks.tracks_assign_post(q, U[user], body)
    return q.sent

check(assign("ops", {"id": "owners", "add": ["ops"]})[0] == 403, "an operator cannot assign cards (not even to themselves)")
check(assign("tien", {"id": "owners", "add": ["***"]})[0] == 400, "only operator accounts can be assigned (a guest gets the summary via share)")
st, out = assign("tien", {"id": "owners", "add": ["ops"]})
check(st == 200 and out["zugewiesen_an"] == ["ops"], "the owner assigns the card to the operator")
st, full = get("ops", "owners")
check(full.get("repo") and full.get("run_dir"), "an ASSIGNED card is full access for the operator")
check(auth.owns_card(U["ops"], sessions.get_track("owners")) is True, "owns_card is True for the assignee")
check(auth.owns_card(U["ops"], sessions.get_track("theirs")) is False, "and False for a card nobody gave them")

# every id-addressed verb is gated by owns_card for the operator
def hit(fn, user, tid, body=None):
    q = Req()
    fn(q, U[user], body or {}, tid)
    return q.sent[0]
from cells.engineer.routes import routes_track_actions as rta
check(hit(routes_tracks.tracks_delete_post, "ops", "theirs") == 403, "operator: delete a foreign card -> 403")
check(hit(routes_tracks.tracks_archive_post, "ops", "theirs") == 403, "operator: archive a foreign card -> 403")
check(hit(routes_tracks.tracks_update_post, "ops", "theirs", {"priority": "high"}) == 403, "operator: update a foreign card -> 403")
check(hit(rta.tracks_lane_post, "ops", "theirs", {"lane": "done"}) == 403, "operator: move a foreign card -> 403")
check(hit(rta.tracks_steer_post, "ops", "theirs", {"text": "x"}) == 403, "operator: steer a foreign card -> 403")
q = Req(); routes_tracks.tracks_reorder_post(q, U["ops"], {"ids": ["theirs"]})
check(q.sent[0] == 403, "operator: reorder the board -> 403 (a whole-board act)")

print()
if _fails:
    print("FAILED (%d):" % len(_fails))
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("CARD SHARING: all pinned - PASS")
