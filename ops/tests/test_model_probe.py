# -*- coding: utf-8 -*-
"""Which OpenCode models REALLY run for this account (spine/agent/opencode_models.py,
table model_probe, ledger 21). The CLI is faked throughout. Pinned:
  1. the real-request classification (ok / country / missing) is persisted per account x model
  2. probe_all is SEQUENTIAL, in the background, with "done/total" progress; the POST answers at once
  3. results expire (ok 6h, failure 30min) -> untested again
  4. a different account does not see the result; delete_user drops the rows
  5. NOT exported (db_export), like user_secret
  6. /models + /engines carry `avail`; Claude models carry none
  7. a failed model is out of the whitelist FOR THAT ACCOUNT: a stale pick resolves to the default
  8. a REAL turn that fails with a classifiable error updates the same row (event time);
     a transient error writes nothing
SANDBOXED. Run: py -3.12 ops/tests/test_model_probe.py"""
import json, os, subprocess, sys, tempfile, threading, time
import urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
_SANDBOX = tempfile.mkdtemp(prefix="hd-modelprobe-")
import daemon.paths
daemon.paths.DAEMON_ROOT = _SANDBOX
daemon.paths.DATA_ROOT = _SANDBOX
from spine.auth import auth                       # noqa: E402
from spine.storage import db                      # noqa: E402
from spine.agent import opencode_models as om, engines, turnopts, opencode_driver   # noqa: E402
assert db.DBPATH.startswith(_SANDBOX)
db.init()

FAILS = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        FAILS.append(msg)


MODELS = [{"id": "opencode/big-pickle", "label": "big-pickle", "desc": "Free"},
          {"id": "opencode/geo-free", "label": "geo-free", "desc": "Free"},
          {"id": "opencode/old-free", "label": "old-free", "desc": "Free"},
          {"id": "deepseek/deepseek-flash", "label": "deepseek-flash", "desc": "DeepSeek"}]
om.discover = lambda account="": [dict(m) for m in MODELS]
om._exe = lambda: "C:/fake/opencode.exe"
engines._probe = lambda name, defn: {"id": name, "label": defn["label"], "type": defn["type"], "verified": True,
                                     "configured": False, "enabled": True, "config": {}, "status": "ready",
                                     "version": "x", "error": ""}
engines.invalidate()

print("1. a real request per model, classified and persisted")
OUT = {"opencode/big-pickle": (0, "OK\n"),
       "opencode/geo-free": (1, "Error from provider: This model is not available in your country"),
       "opencode/old-free": (1, "ProviderModelNotFoundError: Model not found: opencode/old-free"),
       "deepseek/deepseek-flash": (0, "OK")}
calls, active, peak = [], [0], [0]


def fake_run(argv, **kw):
    active[0] += 1
    peak[0] = max(peak[0], active[0])
    time.sleep(0.05)
    calls.append(argv[3])
    active[0] -= 1
    rc, out = OUT[argv[3]]
    return subprocess.CompletedProcess(argv, rc, out, "")


real_run = subprocess.run
subprocess.run = fake_run
try:
    a = om.probe_model("ada", "opencode/geo-free")
    check(a["state"] == "failed" and a["status"] == "country" and "country" in a["reason"], "country -> failed/country (%s)" % a)
    a = om.probe_model("ada", "opencode/old-free")
    check(a["state"] == "failed" and a["status"] == "missing", "unknown to the CLI -> failed/missing")
    a = om.probe_model("ada", "opencode/big-pickle")
    check(a["state"] == "ok" and "reason" not in a and a["ms"] >= 0, "answered OK -> ok")
    check(len(calls) == 3 and all(len(c.split("/")) == 2 for c in calls), "ONE request per probe")

    print("2. probe_all: sequential, background, progress")
    calls.clear()
    t0 = time.time()
    started = om.probe_all("bob")
    check(started is True and time.time() - t0 < 1.0, "returns at once")
    check(om.probe_all("bob") is False, "a second start while it runs starts nothing")
    seen_progress = set()
    while om.progress("bob")["running"] and time.time() - t0 < 20:
        p = om.progress("bob")
        seen_progress.add((p["done"], p["total"]))
        time.sleep(0.01)
    check(calls == [m["id"] for m in MODELS], "tested in listing order (%s)" % calls)
    check(peak[0] == 1, "never two requests at once (peak %d)" % peak[0])
    check(all(t == 4 for _, t in seen_progress) and len(seen_progress) >= 2, "progress counts for the UI %s" % sorted(seen_progress))
    av = om.avail_map("bob")
    check(av["opencode/geo-free"]["state"] == "failed" and av["deepseek/deepseek-flash"]["state"] == "ok", "all four rows landed")
    calls.clear()
    check(om.probe_all("bob", only_untested=True) is False and calls == [], "only_untested: nothing left -> no request")
finally:
    subprocess.run = real_run

print("3. expiry")
with db.conn() as c:
    c.execute("UPDATE model_probe SET tested_at=? WHERE user='bob' AND model_id='opencode/big-pickle'", (time.time() - om.OK_TTL - 5,))
    c.execute("UPDATE model_probe SET tested_at=? WHERE user='bob' AND model_id='opencode/geo-free'", (time.time() - om.FAIL_TTL - 5,))
    c.execute("UPDATE model_probe SET tested_at=? WHERE user='bob' AND model_id='deepseek/deepseek-flash'", (time.time() - om.FAIL_TTL - 5,))
av = om.avail_map("bob")
check(av["opencode/big-pickle"]["state"] == "untested", "ok older than 6h reads untested")
check(av["opencode/geo-free"]["state"] == "untested", "a failure older than 30min reads untested")
check(av["deepseek/deepseek-flash"]["state"] == "ok", "...but an ok is still trusted after 30min")
check(av["opencode/old-free"]["state"] == "failed", "a fresh failure stays failed")

print("4. per account; dropped with the account")
check(om.avail_map("ada")["opencode/geo-free"]["state"] == "failed" and om.avail_map("carl", ["opencode/geo-free"])["opencode/geo-free"]["state"] == "untested",
      "another account does not inherit ada's result")
auth.create_user("boss", "hunter2hunter2", "owner")
auth.create_user("ada", "hunter2hunter2", "client")
auth.delete_user("ada")
n = db.conn().execute("SELECT COUNT(*) FROM model_probe WHERE user='ada'").fetchone()[0]
check(n == 0, "auth.delete_user drops the account's probes")
check(db.conn().execute("SELECT COUNT(*) FROM model_probe WHERE user='bob'").fetchone()[0] == 4, "...and only that account's")

print("5. not exported")
sys.path.insert(0, os.path.join(ROOT, "ops", "tools"))
import db_export                                   # noqa: E402
for kw in ({"secrets": True}, {"account": "bob", "secrets": True}, {}):
    doc = json.dumps(db_export.export(**kw))
    check("model_probe" not in doc and "geo-free" not in doc, "db_export %s carries no probe row" % kw)

print("6. /models and /engines carry avail")
for m in ("opencode/big-pickle", "opencode/geo-free", "opencode/old-free", "deepseek/deepseek-flash"):
    om.record("dora", m, {"status": "ok", "ms": 5})
om.record("dora", "opencode/geo-free", {"status": "country", "reason": "", "ms": 0})
lm = {m["id"]: m for m in turnopts.list_models("dora")}
check(lm["opencode/geo-free"]["avail"]["state"] == "failed" and lm["opencode/geo-free"]["avail"]["reason"], "list_models: failed + German-mappable status + reason")
check(lm["opencode/big-pickle"]["avail"]["state"] == "ok", "list_models: ok")
check(om.catalog("erin")[0]["avail"]["state"] == "untested", "an account that never tested sees untested")
check(all("avail" not in m for m in turnopts.claude_models()), "Claude models are not probed")
eng = {e["id"]: e for e in engines.snapshot(account="dora")}["opencode"]
check(any(m["id"] == "opencode/geo-free" and m["avail"]["state"] == "failed" for m in eng["models"]), "/engines models carry avail")

print("7. a failed model is out of the whitelist for that account")
ids = turnopts._allowed_ids("dora")
check("opencode/geo-free" not in ids and "opencode/big-pickle" in ids, "failed dropped, ok kept")
om._remember([{"id": "opencode/geo-free"}])      # a discovery once returned it: known_ids still has it
check("opencode/geo-free" not in turnopts._allowed_ids("dora"), "...even though a discovery remembered the id")
check("opencode/geo-free" in turnopts._allowed_ids("erin"), "an account without a verdict still gets the benefit of the doubt")
cm, _ = turnopts.resolve_model("opencode/geo-free", "hi", account="dora")
check(cm is None, "a stale pick resolves to the default, not to the dead model")
cm, _ = turnopts.resolve_model("opencode/big-pickle", "hi", account="dora")
check(cm == "opencode/big-pickle", "a working pick still wins")

print("8. a real turn that fails teaches the same row")


class FakeSess:
    def __init__(self, exc=None, meta=None):
        self.exc, self.meta = exc, meta

    def run_turn(self, prompt, run_dir):
        if self.exc:
            raise self.exc
        return "sid", "", self.meta


real_get = opencode_driver._get_session
t = {"id": "henry-x", "dispatched_by": "fred"}
try:
    opencode_driver._get_session = lambda cfg, t: FakeSess(meta={"is_error": True, "error": "Error: This model is not available in your country"})
    opencode_driver.run({"type": "opencode", "model": "opencode/geo-free"}, t, "hi")
    a = om.avail_map("fred", ["opencode/geo-free"])["opencode/geo-free"]
    check(a["state"] == "failed" and a["status"] == "country", "an error reply classified as country lands on fred's row")
    v0 = db._version
    opencode_driver._get_session = lambda cfg, t: FakeSess(exc=RuntimeError("opencode turn stalled (no output for 900s)"))
    try:
        opencode_driver.run({"type": "opencode", "model": "opencode/big-pickle"}, t, "hi")
    except RuntimeError:
        pass
    check(om.avail_map("fred", ["opencode/big-pickle"])["opencode/big-pickle"]["state"] == "untested", "a stall/transient error proves nothing: no row")
    opencode_driver._get_session = lambda cfg, t: FakeSess(exc=RuntimeError("ProviderModelNotFoundError: Model not found"))
    try:
        opencode_driver.run({"type": "opencode", "model": "opencode/old-free"}, t, "hi")
    except RuntimeError:
        pass
    check(om.avail_map("fred", ["opencode/old-free"])["opencode/old-free"]["state"] == "failed", "an exception that classifies as missing is recorded")
    check(db._version > v0, "...and bumps the version (the app reloads from the event stream, no polling)")
finally:
    opencode_driver._get_session = real_get

print("9. POST /me/models/probe")
auth.create_user("owner1", "hunter2hunter2", "owner")
auth.create_user("cli1", "hunter2hunter2", "client")
SID = {n: auth.login(n, "hunter2hunter2") for n in ("owner1", "cli1")}
from http.server import ThreadingHTTPServer       # noqa: E402
from spine.http.server import H                   # noqa: E402
PORT = int(os.environ.get("HELMDECK_DEV_PORT") or 3866)
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


GATE = threading.Event()
done_models = []


def slow_test(account, provider, model=""):
    GATE.wait(10)
    done_models.append((account, model))
    return {"ok": True, "status": "ok", "reason": "", "model": model, "ms": 7}


om.test = slow_test
t0 = time.time()
code, raw = call("POST", "/me/models/probe", {}, who="owner1")
r = json.loads(raw)
check(code == 200 and r["started"] and r["running"] and r["total"] == 4 and time.time() - t0 < 3, "answers AT ONCE with the count (%s)" % raw)
check(json.loads(call("POST", "/me/models/probe", {}, who="owner1")[1])["started"] is False, "idempotent while running")
check(json.loads(call("GET", "/me/models/probe", who="owner1")[1])["running"] is True, "GET shows the progress")
rr = call("POST", "/me/models/probe", {"model": "nope/none"}, who="owner1"); check(rr[0] == 400, "unknown model -> 400 (%s)" % (rr,))
check(call("POST", "/me/models/probe", {}, who="cli1")[0] == 403, "a client role is refused by the global role gate")
GATE.set()
t0 = time.time()
while om.progress("owner1")["running"] and time.time() - t0 < 10:
    time.sleep(0.05)
check([m for a, m in done_models] == [m["id"] for m in MODELS], "the thread probed every model in order")
srv.shutdown()

print()
if FAILS:
    print("FAILED: %d" % len(FAILS)); sys.exit(1)
print("ALL GREEN - model availability is proven per account by a real request, stored, expiring, and never shown as pickable when dead")
