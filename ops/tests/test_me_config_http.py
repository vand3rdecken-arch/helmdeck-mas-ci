# -*- coding: utf-8 -*-
"""accounts-boards-prd phase 1 over the REAL wire: GET /me + PUT /me/config.

test_user_config.py proves the storage/policy layer. This one proves the thing
that layer is useless without, and that no unit test can reach: that the daemon
actually ANSWERS a PUT at all. `PUT` was the third HTTP verb this server ever
learned (spine/http/server.py had only do_GET/do_POST), so "the route exists"
and "the route is reachable" were genuinely separate questions here - a missing
do_PUT answers 501 from BaseHTTPRequestHandler with the handler never called,
and every unit test in the world would still be green.

What it drives, on a real socket, with real sessions:
  - a client-role account (the weakest role) writing its OWN profile: allowed,
  - that same account trying to write ANOTHER account's: structurally
    impossible - the body's `user` is ignored, self-scope is the authorization,
  - two accounts holding two languages simultaneously via /me,
  - the migration flag over the wire, twice,
  - an unauthenticated PUT: 401. An unknown PUT path: 404.

SELF-SANDBOXING: daemon.paths.DAEMON_ROOT is repointed at a temp dir before the
first storage import (see test_user_config.py's header), so users.json,
sessions.json, helmdeck.db and settings.json are all throwaway copies. Binds
127.0.0.1 on $HELMDECK_DEV_PORT (this card's reserved port) so parallel cards
never collide.

Run by hand: py -3.12 ops/tests/test_me_config_http.py
"""
import json, os, sys, tempfile, threading
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

_SANDBOX = tempfile.mkdtemp(prefix="hd-meconfig-")
import daemon.paths
daemon.paths.DAEMON_ROOT = _SANDBOX

from spine.auth import auth                       # noqa: E402
from spine.storage import db, events, userconfig  # noqa: E402

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
db.workspace_config_replace({"policy": {"lang": "de"}, "appearance": {"backdrop": "mesh"}})

auth.create_user("owner1", "hunter2hunter2", "owner")
auth.create_user("ada", "hunter2hunter2", "client")
auth.create_user("bob", "hunter2hunter2", "client")
SID = {n: auth.login(n, "hunter2hunter2") for n in ("owner1", "ada", "bob")}
assert all(SID.values()), "sandbox logins failed: %s" % SID

from http.server import ThreadingHTTPServer       # noqa: E402
from spine.http.server import H                   # noqa: E402

PORT = int(os.environ.get("HELMDECK_DEV_PORT") or 3858)
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


def test_the_daemon_answers_put_at_all():
    code, _ = call("PUT", "/me/config", {"config": {"lang": "en"}}, who="ada")
    check(code == 200,
          "the daemon answers PUT /me/config (do_PUT is wired - a 501 here "
          "means the verb never reached a handler)")
    code, out = call("PUT", "/me/nonexistent", {"config": {}}, who="ada")
    check(code == 404, "an undeclared PUT path 404s - the table does not fall through")
    code, out = call("PUT", "/me/config", {"config": {"lang": "en"}})
    check(code == 401, "an unauthenticated PUT is refused")


def test_a_client_may_write_its_own_profile():
    # The point of the whole route: `client` is the role that may otherwise
    # "file and comment only" (server.py's blanket POST denial). Its own view
    # is not the workspace's, so this must work.
    code, out = call("PUT", "/me/config", {"config": {"lang": "en"}}, who="ada")
    check(code == 200 and out.get("written") == ["lang"],
          "a CLIENT-role account writes its own language")
    check(out.get("profile", {}).get("lang") == "en"
          and out.get("profile_keys") == ["lang"],
          "the reply carries the new resolved profile + what was chosen, so "
          "the client needs no second round trip")

    # the owner-only global settings route is untouched by all this
    code, _ = call("POST", "/settings", {"policy": {"lang": "en"}}, who="ada")
    check(code == 403,
          "the same client still cannot write WORKSPACE settings - a personal "
          "profile route is not a privilege-escalation seam")


def test_self_scope_is_the_authorization():
    call("PUT", "/me/config", {"config": {"lang": "de"}}, who="bob")
    # ada tries every shape of "write bob's row" the body allows
    for body in ({"config": {"lang": "en"}, "user": "bob"},
                 {"config": {"lang": "en"}, "name": "bob"},
                 {"user": "bob", "config": {"lang": "en"}}):
        code, out = call("PUT", "/me/config", body, who="ada")
        check(code == 200, "ada's write is accepted...")
    check(userconfig.stored("bob") == {"lang": "de"},
          "...and lands on ADA every time - the body cannot name an account, "
          "so there is no cross-account write to authorize (or to get wrong)")


def test_two_accounts_two_languages_over_the_wire():
    call("PUT", "/me/config", {"config": {"lang": "en"}}, who="ada")
    call("PUT", "/me/config", {"config": {"lang": "de"}}, who="bob")
    _, ada = call("GET", "/me", who="ada")
    _, bob = call("GET", "/me", who="bob")
    check(ada["profile"]["lang"] == "en" and bob["profile"]["lang"] == "de",
          "two accounts on two devices hold different languages (PRD 7.1)")
    check(ada["ui"]["lang"] == "en" and bob["ui"]["lang"] == "de",
          "the legacy `ui.lang` an older bundle reads resolves per-ACCOUNT too "
          "- one question, one answer")
    _, owner = call("GET", "/me", who="owner1")
    check(owner["profile"]["lang"] == "de" and owner["profile_keys"] == [],
          "an account that never chose still gets the workspace language, and "
          "says so via an empty profile_keys (the first-login step's trigger)")


def test_migration_over_the_wire_runs_once():
    auth.create_user("erin", "hunter2hunter2", "operator")
    SID["erin"] = auth.login("erin", "hunter2hunter2")
    _, me = call("GET", "/me", who="erin")
    check(me["profile_keys"] == [],
          "a legacy device sees an empty profile_keys and knows to push up")

    code, out = call("PUT", "/me/config",
                     {"config": {"lang": "en"}, "migrate": True}, who="erin")
    check(code == 200 and out["written"] == ["lang"],
          "the device's local preference is pushed up")
    code, out = call("PUT", "/me/config",
                     {"config": {"lang": "de"}, "migrate": True}, who="erin")
    check(out["written"] == [] and out["skipped"] == ["lang"],
          "a second push writes nothing and says which key it skipped")
    _, me = call("GET", "/me", who="erin")
    check(me["profile"]["lang"] == "en", "the account's value survived")


def test_bad_input_over_the_wire():
    for body, why in (({}, "no config at all"),
                      ({"config": {"auto_accept_green": True}}, "a policy knob"),
                      ({"config": {"lang": "fr"}}, "an unknown language")):
        code, out = call("PUT", "/me/config", body, who="ada")
        check(code == 400 and "error" in out, "400 + a reason for %s" % why)


try:
    for fn in (test_the_daemon_answers_put_at_all,
               test_a_client_may_write_its_own_profile,
               test_self_scope_is_the_authorization,
               test_two_accounts_two_languages_over_the_wire,
               test_migration_over_the_wire_runs_once,
               test_bad_input_over_the_wire):
        print(fn.__name__)
        fn()
finally:
    _srv.shutdown()

print(("FAILED: %d" % len(_fails)) if _fails else "all /me/config HTTP checks passed")
sys.exit(1 if _fails else 0)
