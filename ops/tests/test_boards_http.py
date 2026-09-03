# -*- coding: utf-8 -*-
"""accounts-boards-prd phase 2 over the REAL wire: /me boards + PUT/DELETE
/me/boards.

test_boards.py proves the storage/policy layer. This one proves what that layer
is useless without, and what no unit test can reach: that the daemon actually
ANSWERS a DELETE at all. `DELETE` is the FOURTH HTTP verb this server ever
learned (do_GET/do_POST/do_PUT), so "the route exists" and "the route is
reachable" are genuinely separate questions - a missing do_DELETE answers 501
from BaseHTTPRequestHandler with the handler never called, and every unit test
in the world would still be green. That is exactly the trap phase 1 hit with
PUT, one verb earlier.

What it drives, on a real socket, with real sessions:
  - a CLIENT-role account (the weakest role, the one do_POST denies almost
    everything) creating, renaming and deleting its own board,
  - that same account failing to reach another account's board, or the
    workspace's default board, by id - self-scope is the authorization,
  - two accounts seeing two different board lists from the same /me,
  - the default board reaching a client READ-only, so nobody ever lands on an
    empty screen,
  - an unauthenticated PUT/DELETE: 401. An unknown DELETE path: 404.

SELF-SANDBOXING: daemon.paths.DAEMON_ROOT is repointed at a temp dir before the
first storage import, so users.json, sessions.json, helmdeck.db and
settings.json are throwaway copies. Binds 127.0.0.1 on $HELMDECK_DEV_PORT (this
card's reserved port) so parallel cards never collide.

Run by hand: py -3.12 ops/tests/test_boards_http.py
"""
import json, os, sys, tempfile, threading
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

_SANDBOX = tempfile.mkdtemp(prefix="hd-boardshttp-")
import daemon.paths
daemon.paths.DAEMON_ROOT = _SANDBOX

from spine.auth import auth                     # noqa: E402
from spine.storage import boards, db, events    # noqa: E402

for label, path in (("db", db.DBPATH), ("settings", events.SET),
                    ("users", auth.USERS), ("sessions", auth.SESS)):
    assert path.startswith(_SANDBOX), \
        "REFUSING TO RUN: %s points at %s, not the sandbox" % (label, path)

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


db.init()
db.workspace_config_replace({"policy": {"lang": "de", "lane_labels": {"review": "Abnahme"}}})

auth.create_user("owner1", "hunter2hunter2", "owner")
auth.create_user("ada", "hunter2hunter2", "client")
auth.create_user("bob", "hunter2hunter2", "client")
SID = {n: auth.login(n, "hunter2hunter2") for n in ("owner1", "ada", "bob")}
assert all(SID.values()), "sandbox logins failed: %s" % SID

from http.server import ThreadingHTTPServer     # noqa: E402
from spine.http.server import H                 # noqa: E402

PORT = int(os.environ.get("HELMDECK_DEV_PORT") or 3859)
_srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
threading.Thread(target=_srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % PORT


def call(method, path, body=None, who=None):
    """(status, parsed-json-or-raw-text)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if who:
        req.add_header("Cookie", "sd_session=" + SID[who])
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw, code = r.read().decode(), r.status
    except urllib.error.HTTPError as e:
        raw, code = e.read().decode(), e.code
    try:
        return code, json.loads(raw)
    except ValueError:
        return code, raw


def cols(*stations):
    return [{"label": "", "station": s} for s in stations]


# -- 1. the daemon speaks the two new verbs on this path ---------------------
def test_the_daemon_answers_put_and_delete_at_all():
    code, r = call("PUT", "/me/boards",
                   {"board": {"name": "Smoke", "columns": cols("working")}}, who="ada")
    check(code == 200 and r.get("ok"),
          "PUT /me/boards answers 200 (got %s %r)" % (code, r))
    bid = (r.get("board") or {}).get("id")
    code, r = call("DELETE", "/me/boards?id=" + str(bid), who="ada")
    check(code == 200 and r.get("ok"),
          "DELETE /me/boards?id= answers 200 - do_DELETE exists and dispatched, "
          "which is the whole reason this file is not a unit test "
          "(got %s %r)" % (code, r))

    code, _ = call("DELETE", "/me/nonesuch?id=x", who="ada")
    check(code == 404, "an unknown DELETE path 404s - the table is CLOSED, "
                       "there is no fall-through (got %s)" % code)
    code, _ = call("DELETE", "/me/boards?id=whatever")
    check(code == 401, "an unauthenticated DELETE is 401, not 404 - the new "
                       "verb runs the same auth gate as the other three "
                       "(got %s)" % code)
    code, _ = call("PUT", "/me/boards", {"board": {"name": "x", "columns": cols("done")}})
    check(code == 401, "and so does the new PUT route (got %s)" % code)
    code, r = call("DELETE", "/me/boards", who="ada")
    check(code == 400 and "id" in str(r), "DELETE with no id is a 400 with a "
                                          "reason, not a silent no-op (got %s %r)" % (code, r))


# -- 2. a CLIENT owns its own boards -----------------------------------------
def test_a_client_may_own_boards():
    code, me = call("GET", "/me", who="ada")
    ids = [b["id"] for b in (me.get("boards") or [])]
    check(code == 200 and ids == [boards.DEFAULT_ID],
          "before creating anything, a client's /me already carries the "
          "shared default board - a fresh login never lands on an empty "
          "screen (got %r)" % ids)
    default = me["boards"][0]
    by_station = {c["station"]: c["label"] for c in default["columns"]}
    check(by_station.get("review") == "Abnahme",
          "and it carries the owner's policy.lane_labels rename, migrated "
          "into the column label (got %r)" % by_station)

    code, r = call("PUT", "/me/boards", {"board": {
        "name": "Nur meins", "columns": [{"label": "Los", "station": "backlog"},
                                         {"label": "", "station": "done"}]}}, who="ada")
    check(code == 200, "a CLIENT - the role do_POST denies almost everything - "
                       "may create its own board (got %s %r)" % (code, r))
    ada_board = r["board"]
    check(ada_board["owner"] == "ada",
          "owned by the SESSION account, never by anything in the body")
    check([b["id"] for b in r["boards"]] == [boards.DEFAULT_ID, ada_board["id"]],
          "and the reply carries the whole new list, so the client never has "
          "to guess the minted id or refetch")

    # Self-scope, demonstrated the way it actually gets attacked.
    code, r = call("PUT", "/me/boards", {"board": {
        "id": ada_board["id"], "name": "Geklaut", "columns": cols("done")}}, who="bob")
    check(code == 403, "bob cannot write ada's board by id (got %s %r)" % (code, r))
    code, r = call("DELETE", "/me/boards?id=" + ada_board["id"], who="bob")
    check(code == 403, "nor delete it (got %s %r)" % (code, r))
    code, me_bob = call("GET", "/me", who="bob")
    check([b["id"] for b in me_bob["boards"]] == [boards.DEFAULT_ID],
          "and it is not in his /me at all - two accounts, two board lists, "
          "one card pool")
    code, me_ada = call("GET", "/me", who="ada")
    check(me_ada["boards"][1]["name"] == "Nur meins",
          "ada's is untouched after both of bob's attempts")


# -- 3. renaming a column is what device B re-renders on ---------------------
def test_renaming_a_column_moves_the_version_cursor():
    _, me = call("GET", "/me", who="ada")
    board = me["boards"][1]
    before = db.current_version()

    renamed = [dict(c) for c in board["columns"]]
    renamed[0]["label"] = "Ideen"
    code, r = call("PUT", "/me/boards",
                   {"board": {"id": board["id"], "name": board["name"],
                              "columns": renamed}}, who="ada")
    check(code == 200 and r["board"]["columns"][0]["label"] == "Ideen",
          "renaming a column on a personal board lands (got %s %r)" % (code, r))
    check(db.current_version() > before,
          "and bumps the version cursor /stream/wait blocks on - which IS the "
          "PRD's acceptance: device B re-renders within one SSE tick, with no "
          "board-specific client plumbing at all")

    code, again = call("GET", "/me", who="ada")
    check(again["boards"][1]["columns"][0]["label"] == "Ideen",
          "and the next /me (what that tick triggers) serves the new label")


# -- 4. the default board is the workspace's, over the wire ------------------
def test_default_board_is_owner_only_over_the_wire():
    _, me = call("GET", "/me", who="ada")
    default = me["boards"][0]
    patch = {"id": boards.DEFAULT_ID, "name": "Board",
             "columns": [dict(c, label="Meins") for c in default["columns"]]}

    code, r = call("PUT", "/me/boards", {"board": patch}, who="ada")
    check(code == 403, "a client may READ the default board but not write it - "
                       "it is what every account lands on (got %s %r)" % (code, r))
    code, r = call("DELETE", "/me/boards?id=" + boards.DEFAULT_ID, who="owner1")
    check(code == 400 and "cannot be deleted" in str(r.get("error")),
          "not even the owner may delete it (got %s %r)" % (code, r))

    code, r = call("PUT", "/me/boards", {"board": patch}, who="owner1")
    check(code == 200, "the owner role may rewrite it (got %s %r)" % (code, r))
    _, me = call("GET", "/me", who="bob")
    check(me["boards"][0]["columns"][0]["label"] == "Meins",
          "and every other account sees that change on its next /me - one "
          "shared board, one edit surface")


# -- 5. a bad board over the wire is a 400 with a reason ---------------------
def test_bad_input_over_the_wire():
    for body, why in (
        ({}, "no board at all"),
        ({"board": {"name": "X", "columns": [{"label": "", "station": "gate"}]}},
         "a station the lane machine would refuse"),
        ({"board": {"name": "X", "columns": []}}, "no columns"),
        ({"board": {"id": "b-nope", "name": "X", "columns": cols("done")}},
         "an id nobody owns"),
    ):
        code, r = call("PUT", "/me/boards", body, who="ada")
        check(code == 400 and isinstance(r, dict) and r.get("error"),
              "400 + a reason: %s (got %s %r)" % (why, code, r))


try:
    for fn in (test_the_daemon_answers_put_and_delete_at_all,
               test_a_client_may_own_boards,
               test_renaming_a_column_moves_the_version_cursor,
               test_default_board_is_owner_only_over_the_wire,
               test_bad_input_over_the_wire):
        print(fn.__name__)
        fn()
finally:
    _srv.shutdown()

print(("FAILED: %d" % len(_fails)) if _fails else "all board HTTP checks passed")
sys.exit(1 if _fails else 0)
