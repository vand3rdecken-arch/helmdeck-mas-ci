# -*- coding: utf-8 -*-
"""GET/PUT/DELETE /me/providers over the real HTTP server (spine/storage/
usersecrets.py is tested in test_user_secrets.py; this pins the DOOR):

  1. an owner stores a key; the answer says set + hint and NEVER the key
  2. GET /me/providers never carries the key either, and a second account sees
     nothing of the first one's keys (self-scoped: the account is the session's)
  3. a client is refused (403) and nothing is written
  4. bad input is a 400 (unknown provider, short key, pasted newline)
  5. DELETE removes it; the audit trail records set/delete WITHOUT the value
  6. no session -> 401
SELF-SANDBOXING like test_boards_http: temp data root, 127.0.0.1:$HELMDECK_DEV_PORT.
Run: py -3.12 ops/tests/test_providers_http.py"""
import json, os, sys, tempfile, threading
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
_SANDBOX = tempfile.mkdtemp(prefix="hd-providers-")
import daemon.paths
daemon.paths.DAEMON_ROOT = _SANDBOX
daemon.paths.DATA_ROOT = _SANDBOX

from spine.auth import auth                     # noqa: E402
from spine.storage import db, events            # noqa: E402
from spine.storage import usersecrets as us     # noqa: E402

for label, path in (("db", db.DBPATH), ("settings", events.SET), ("users", auth.USERS)):
    assert path.startswith(_SANDBOX), "REFUSING TO RUN: %s points at %s" % (label, path)

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


db.init()
auth.create_user("owner1", "hunter2hunter2", "owner")
auth.create_user("op1", "hunter2hunter2", "operator")
auth.create_user("ada", "hunter2hunter2", "client")
SID = {n: auth.login(n, "hunter2hunter2") for n in ("owner1", "op1", "ada")}
assert all(SID.values()), SID

from http.server import ThreadingHTTPServer     # noqa: E402
from spine.http.server import H                 # noqa: E402
PORT = int(os.environ.get("HELMDECK_DEV_PORT") or 3861)
_srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
threading.Thread(target=_srv.serve_forever, daemon=True).start()


def call(method, path, body=None, who=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path), data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if who:
        req.add_header("Cookie", "sd_session=" + SID[who])
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw, code = r.read().decode(), r.status
    except urllib.error.HTTPError as e:
        raw, code = e.read().decode(), e.code
    return code, raw


KEY = "sk-live-0123456789abcdefWXYZ"
if us.available():
    print("1. owner stores a key")
    code, raw = call("PUT", "/me/providers", {"provider": "deepseek", "key": KEY}, who="owner1")
    r = json.loads(raw)
    dk = {p["id"]: p for p in r["providers"]}["deepseek"]
    check(code == 200 and dk["set"] and dk["hint"] == "...WXYZ", "PUT answers set + hint (got %s)" % code)
    check(KEY not in raw, "...and the key is nowhere in the response")
    check(r["can_store"] is True and r["encrypted"] is True, "can_store + encrypted reported")

    print("2. GET is self-scoped and keyless")
    code, raw = call("GET", "/me/providers", who="owner1")
    check(code == 200 and KEY not in raw and json.loads(raw)["providers"][0]["id"] in us.PROVIDERS, "GET carries no key")
    code, raw = call("GET", "/me/providers", who="op1")
    check(not any(p["set"] for p in json.loads(raw)["providers"]), "another account sees none of owner1's keys")
    check(us.env_for("op1") == {} and us.env_for("owner1") == {"DEEPSEEK_API_KEY": KEY}, "env_for stays per account")

    print("3. a client is refused")
    code, raw = call("PUT", "/me/providers", {"provider": "deepseek", "key": KEY}, who="ada")
    check(code == 403 and us.count("ada") == 0, "client PUT -> 403 and nothing written")
    code, raw = call("GET", "/me/providers", who="ada")
    check(code == 200 and json.loads(raw)["can_store"] is False, "a client still reads its own (empty) status")

    print("4. bad input")
    for body, why in (({"provider": "nope", "key": KEY}, "unknown provider"),
                      ({"provider": "deepseek", "key": "short"}, "short key"),
                      ({"provider": "deepseek", "key": KEY + "\n"}, "pasted newline"),
                      ({"provider": "deepseek"}, "missing key")):
        code, raw = call("PUT", "/me/providers", body, who="op1")
        check(code == 400, "%s -> 400 (got %s)" % (why, code))
    check(us.count("op1") == 0, "nothing was stored by the bad calls")

    print("5. delete + audit without the value")
    code, raw = call("DELETE", "/me/providers?provider=deepseek", who="owner1")
    check(code == 200 and not any(p["set"] for p in json.loads(raw)["providers"]), "DELETE clears it")
    code, raw = call("DELETE", "/me/providers?provider=nope", who="owner1")
    check(code == 400, "DELETE of an unknown provider -> 400")
    ev = json.dumps([e for e in db.conn().execute("SELECT data FROM events WHERE kind='auth'").fetchall()])
    check("provider_key.set" in ev and "provider_key.delete" in ev, "set and delete are audited")
    check(KEY not in ev, "...and the audit trail never holds the key")

print("6. no session")
code, raw = call("GET", "/me/providers")
check(code == 401, "GET without a session -> 401 (got %s)" % code)
code, raw = call("PUT", "/me/providers", {"provider": "deepseek", "key": KEY})
check(code == 401, "PUT without a session -> 401 (got %s)" % code)

_srv.shutdown()
print()
if _fails:
    print("FAILED: %d" % len(_fails)); sys.exit(1)
print("ALL GREEN - /me/providers is self-scoped, role-gated, keyless in every response")
