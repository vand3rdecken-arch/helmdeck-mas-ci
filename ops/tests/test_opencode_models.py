# -*- coding: utf-8 -*-
"""OpenCode's model catalog is DERIVED from the CLI, not hand-kept
(spine/agent/opencode_models.py). Pinned, all with the CLI faked:
  1. parse(): `provider/model` lines only, ANSI stripped, unique, order kept
  2. a discovery that works feeds /engines `models`; one that fails falls back to
     the seed - the picker is never empty
  3. engine_for / the whitelist know a discovered id (`deepseek/deepseek-flash`)
     that the hand list never had - and it survives a restart (persisted)
  4. fallback(): the DeepSeek retry model ONLY for an account whose key connects
     it; "" otherwise (the old constant pointed at an id the CLI does not know)
  5. classify(): the CLI's answers -> ok / auth / country / missing / timeout / error
  6. test(): ONE request with THAT account's env, result shaped for the UI
  7. POST /me/providers/test: 400 unknown / no key, 403 client - and the result
     is stored on the row without a secret
SANDBOXED. Run: py -3.12 ops/tests/test_opencode_models.py"""
import json, os, subprocess, sys, tempfile, threading
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
_SANDBOX = tempfile.mkdtemp(prefix="hd-ocmodels-")
import daemon.paths
daemon.paths.DAEMON_ROOT = _SANDBOX
daemon.paths.DATA_ROOT = _SANDBOX
from spine.auth import auth                       # noqa: E402
from spine.storage import db, events              # noqa: E402
from spine.storage import usersecrets as us       # noqa: E402
from spine.agent import opencode_models as om, engines, turnopts   # noqa: E402
assert db.DBPATH.startswith(_SANDBOX)
db.init()

FAILS = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        FAILS.append(msg)


LISTING = ("\x1b[0m\nopencode/big-pickle\nopencode/exo-free\nbad line\n"
           "deepseek/deepseek-flash\nopencode/big-pickle\ndeepseek/deepseek-v4-pro\n")
print("1. parse")
got = [m["id"] for m in om.parse(LISTING)]
check(got == ["opencode/big-pickle", "opencode/exo-free", "deepseek/deepseek-flash", "deepseek/deepseek-v4-pro"],
      "only provider/model lines, unique, ordered (%s)" % got)
check(om.parse("Error: Provider not found: deepseek") == [], "an error line is not a model")
check([m for m in om.parse(LISTING) if m["id"] == "opencode/big-pickle"][0]["desc"].startswith("Free"), "free models say so")

print("2. catalog: derived, seed as the net")
engines._probe = lambda name, defn: {"id": name, "label": defn["label"], "type": defn["type"], "verified": True,
                                     "configured": False, "enabled": True, "config": {}, "status": "ready",
                                     "version": "x", "error": ""}
engines.invalidate()
real_discover = om.discover
om.discover = lambda account="": [{"id": "deepseek/deepseek-flash", "label": "deepseek-flash", "desc": "DeepSeek"}]
ids = {m["id"] for m in {e["id"]: e for e in engines.snapshot(account="ada")}["opencode"]["models"]}
check(ids == {"deepseek/deepseek-flash"}, "/engines opencode models = the CLI's list, not the hand list")
om.discover = lambda account="": None
ids = {m["id"] for m in om.catalog("ada")}
check("opencode/big-pickle" in ids and len(ids) == len(turnopts.OPENCODE_MODELS), "CLI silent -> the seed, never empty")
om.discover = real_discover

print("3. a discovered id is known, and stays known")
check(turnopts.engine_for("deepseek/deepseek-flash") == "claude", "unknown before any discovery")
om._remember([{"id": "deepseek/deepseek-flash"}])
check(turnopts.engine_for("deepseek/deepseek-flash") == "opencode", "engine_for knows it after a discovery")
check("deepseek/deepseek-flash" in turnopts._allowed_ids(), "the whitelist accepts it (a stored pick survives a restart)")
check(turnopts.engine_for("claude-sonnet-5-5") == "claude", "Claude ids stay claude")
seed = {m["id"] for m in turnopts.OPENCODE_MODELS}
check("opencode/deepseek-v4-flash" not in seed and "opencode/jev-1.13-free" not in seed
      and "opencode/mimo-v2.5-free" not in seed, "the seed no longer carries ids the CLI does not know")

print("4. fallback only where it can run")
om.discover = lambda account="": ([{"id": "deepseek/deepseek-flash"}] if account == "ada" else [{"id": "opencode/big-pickle"}])
check(om.fallback("ada") == "deepseek/deepseek-flash", "an account with a DeepSeek key gets the DeepSeek retry")
check(om.fallback("bob") == "" and turnopts.fallback_model("bob") == "", "an account without one gets NO retry")
check(not hasattr(turnopts, "FALLBACK_MODEL"), "the dead constant is gone")
om.discover = real_discover

print("5. classify")
C = om.classify
check(C(0, "\x1b[0mOK\x1b[0m")[0] == "ok", "OK")
check(C(1, "Error from provider (Console): This model is not available in your country")[0] == "country", "country")
check(C(1, "AuthError: Missing API key.")[0] == "auth", "missing key -> auth")
check(C(1, "ProviderModelNotFoundError: Model not found: opencode/x")[0] == "missing", "model not found")
check(C(1, "", timed_out=True)[0] == "timeout", "timeout")
check(C(1, "boom")[0] == "error", "anything else is an error with the text")

print("6. test(): one request with the account's own env")
seen = {}


def fake_run(argv, **kw):
    seen["argv"], seen["env"] = argv, kw.get("env") or {}
    return subprocess.CompletedProcess(argv, 0, "OK\n", "")


real_run, real_exe = subprocess.run, om._exe
om._exe = lambda: "C:/fake/opencode.exe"
subprocess.run = fake_run
om.discover = lambda account="": [{"id": "deepseek/deepseek-v4-pro"}, {"id": "deepseek/deepseek-flash"}]
if us.available():
    us.put("ada", "deepseek", "sk-test-0123456789abcdefAAAA")
try:
    res = om.test("ada", "deepseek")
    check(res["ok"] and res["model"] == "deepseek/deepseek-flash", "the cheap model of the provider is chosen (%s)" % res["model"])
    check(seen["argv"][1:3] == ["run", "--model"] and seen["argv"][3] == "deepseek/deepseek-flash", "ONE `run --model` request")
    if us.available():
        check(seen["env"].get("DEEPSEEK_API_KEY") == "sk-test-0123456789abcdefAAAA", "with ada's own key in the env")
    check(set(res) >= {"ok", "status", "reason", "model", "ms"} and "sk-test" not in json.dumps(res), "result is UI-shaped and keyless")
    check(om.test("ada", "openai")["status"] == "missing", "a provider with no listed model says so")
finally:
    subprocess.run, om._exe, om.discover = real_run, real_exe, real_discover

print("7. POST /me/providers/test")
auth.create_user("owner1", "hunter2hunter2", "owner")
auth.create_user("ada2", "hunter2hunter2", "client")
SID = {n: auth.login(n, "hunter2hunter2") for n in ("owner1", "ada2")}
from http.server import ThreadingHTTPServer       # noqa: E402
from spine.http.server import H                   # noqa: E402
PORT = int(os.environ.get("HELMDECK_DEV_PORT") or 3863)
srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()


def call(method, path, body=None, who=None):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path),
                                 data=json.dumps(body).encode() if body is not None else None, method=method)
    req.add_header("Content-Type", "application/json")
    if who:
        req.add_header("Cookie", "sd_session=" + SID[who])
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


import time
GATE = threading.Event()


def slow_test(account, provider, model=""):
    GATE.wait(10)
    return {"ok": True, "status": "ok", "reason": "", "model": "deepseek/deepseek-flash", "ms": 42}


def wait_result(who, provider, want, secs=8):
    t0 = time.time()
    while time.time() - t0 < secs:
        d = {p["id"]: p for p in us.status(who)}[provider]
        if (d["test"] or {}).get("status") == want:
            return d
        time.sleep(0.1)
    return {"test": None}


om.test = slow_test
check(call("POST", "/me/providers/test", {"provider": "nope"}, who="owner1")[0] == 400, "unknown provider -> 400")
check(call("POST", "/me/providers/test", {"provider": "deepseek"}, who="owner1")[0] == 400, "no key stored -> 400, no request spent")
check(call("POST", "/me/providers/test", {"provider": "deepseek"}, who="ada2")[0] in (400, 403), "a client cannot test")
if us.available():
    call("PUT", "/me/providers", {"provider": "deepseek", "key": "sk-test-0123456789abcdefAAAA"}, who="owner1")
    t0 = time.time()
    code, raw = call("POST", "/me/providers/test", {"provider": "deepseek"}, who="owner1")
    r = json.loads(raw)
    d = {p["id"]: p for p in r["providers"]}["deepseek"]
    check(code == 200 and r["started"] and time.time() - t0 < 3, "the POST answers AT ONCE (a real test takes 10-80s, longer than any app transport bound)")
    check(d["test"]["status"] == "running" and d["set"], "...and the row says running")
    code, raw2 = call("POST", "/me/providers/test", {"provider": "deepseek"}, who="owner1")
    check(json.loads(raw2)["started"] is False, "a second tap while it runs starts nothing (idempotent)")
    v0 = db._version
    GATE.set()
    d = wait_result("owner1", "deepseek", "ok")
    check(d["test"] and d["test"]["ms"] == 42, "the result lands on the row when the thread finishes")
    check(db._version > v0, "...and bumps the version, so the app reloads it from the event stream (no polling)")
    check("sk-test" not in json.dumps(us.status("owner1")), "...with no key anywhere")
    check(json.loads(call("GET", "/me/providers", who="owner1")[1])["providers"][0]["test"] is not None, "GET shows the stored result")

    print("8. keyless provider (the Zen free tier) + an interrupted test")
    GATE.clear(); GATE.set()
    check(call("POST", "/me/providers/test", {"provider": "opencode"}, who="owner1")[0] == 200, "a provider that needs no key may be tested without one")
    z = wait_result("owner1", "opencode", "ok")
    check(z["test"] and z["set"] is False and z["hint"] == "", "its result is stored, and it still reads as NO key")
    check(us.get("owner1", "opencode") is None and us.env_for("owner1").get("OPENCODE_API_KEY") is None, "a keyless row never becomes an env var")
    check(us.count("owner1") == 1, "count() counts keys, not test rows")
    us._write_test("owner1", "openai", {"status": "running", "started": time.time() - 999})
    o = {p["id"]: p for p in us.status("owner1")}["openai"]
    check(o["test"]["status"] == "error" and "interrupted" in o["test"]["reason"], "a test 'running' for 999s reads as interrupted (derived, not a stored flag)")
srv.shutdown()

print()
if FAILS:
    print("FAILED: %d" % len(FAILS)); sys.exit(1)
print("ALL GREEN - the catalog is the CLI's, the retry only where it can run, the test is one real request")
