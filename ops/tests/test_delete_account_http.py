# -*- coding: utf-8 -*-
"""POST /auth/delete-account over the REAL wire (App Store guideline 5.1.1(v):
an app that creates accounts must let the person delete theirs in the app).

What it drives, on a real socket, with the app's own Bearer-token auth:
  - a signed-in client deleting ITS OWN account with the right password: 200,
    the account is gone, and the very token that asked no longer authenticates,
  - a wrong password: 401 and the account survives (no one-tap erase),
  - no credentials: 401,
  - the name comes from the token, never the body: ada cannot delete bob,
  - the last owner cannot delete themselves (auth.delete_user's guard) - 400
    with the reason, not a locked-out workspace.

SELF-SANDBOXING: daemon.paths.DAEMON_ROOT is repointed at a temp dir before the
first storage import, same as test_boards_http.py.

Run by hand: py -3.12 ops/tests/test_delete_account_http.py
"""
import json, os, sys, tempfile, threading
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

_SANDBOX = tempfile.mkdtemp(prefix="hd-delacct-")
import daemon.paths
daemon.paths.DAEMON_ROOT = _SANDBOX

from spine.auth import auth                     # noqa: E402
from spine.storage import db, events            # noqa: E402

for label, path in (("db", db.DBPATH), ("settings", events.SET),
                    ("users", auth.USERS)):
    assert path.startswith(_SANDBOX), \
        "REFUSING TO RUN: %s points at %s, not the sandbox" % (label, path)

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


db.init()
PW = "hunter2hunter2"
auth.create_user("owner1", PW, "owner")
auth.create_user("ada", PW, "client")
auth.create_user("bob", PW, "client")
TOK = {n: auth.issue_token(n, "phone") for n in ("owner1", "ada", "bob")}

from http.server import ThreadingHTTPServer     # noqa: E402
from spine.http.server import H                 # noqa: E402

PORT = int(os.environ.get("HELMDECK_DEV_PORT") or 3861)
_srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
threading.Thread(target=_srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % PORT


def call(method, path, body=None, who=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if who:
        req.add_header("Authorization", "Bearer " + TOK[who])
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw, code = r.read().decode(), r.status
    except urllib.error.HTTPError as e:
        raw, code = e.read().decode(), e.code
    try:
        return code, json.loads(raw)
    except ValueError:
        return code, raw


code, _ = call("POST", "/auth/delete-account", {"password": PW})
check(code == 401, "no credentials -> 401 (got %s)" % code)

code, r = call("POST", "/auth/delete-account", {"password": "wrong-password"}, who="ada")
check(code == 401 and auth.get_user("ada"),
      "wrong password -> 401 and ada still exists (got %s %r)" % (code, r))

code, r = call("POST", "/auth/delete-account", {"password": PW, "name": "bob"}, who="ada")
check(code == 200 and not auth.get_user("ada") and auth.get_user("bob"),
      "ada deletes HERSELF; a name in the body is ignored, bob survives (got %s %r)" % (code, r))

code, _ = call("GET", "/me", who="ada")
check(code == 401, "the deleted account's own token no longer authenticates (got %s)" % code)

code, r = call("POST", "/auth/delete-account", {"password": PW}, who="owner1")
check(code == 400 and "last owner" in str(r) and auth.get_user("owner1"),
      "the last owner is refused with the reason (got %s %r)" % (code, r))

_srv.shutdown()
print("FAIL (%d)" % len(_fails) if _fails else "PASS")
sys.exit(1 if _fails else 0)
