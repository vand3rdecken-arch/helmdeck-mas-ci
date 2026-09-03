# -*- coding: utf-8 -*-
"""GET/POST /harness/config over the REAL wire, plus the two wirings that make
a rule edit actually reach Henry (harness-config-ui phase 3).

test_project_config.py proves the chain. This proves the things it is useless
without, and that no unit test can reach:

  1. the route ANSWERS, and answers with what the screen needs - blocks in
     order, every rule with its per-surface value, layer and inheritance
  2. the capability gate: settings.read to look, settings.write to change; a
     client role gets neither
  3. a write over the wire moves the value, and null CLEARS it back to inherited
  4. a refused write answers 400 with the rule's OWN why-sentence, because a
     refusal the owner cannot read is indistinguishable from a bug
  5. THE WARM PROCESS. copilot._persist_switch must REFUSE to reuse a live
     process whose brief fingerprint moved - the control plane can set a model
     or a permission mode on a running process, but it cannot replace the
     system prompt. Without this the owner flips a switch, the page says
     "gesetzt", and Henry keeps answering out of the brief he was spawned with.
  6. THE PROJECT OVERLAY. Project-scoped rules do not render into the base
     brief (that would cost a respawn per repo); they ride extra_system, and
     ONLY where they differ - so an ordinary turn pays nothing.

SELF-SANDBOXING: daemon.paths.DAEMON_ROOT is repointed before the first storage
import, and the run refuses to start if any store still points outside it -
this suite has already once written a live settings.json through a probe that
only LOOKED sandboxed. Binds 127.0.0.1 on $HELMDECK_DEV_PORT (this card's
reserved port) so parallel cards never collide.

Run: py -3.12 ops/tests/test_harness_config_route.py
"""
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

_SANDBOX = tempfile.mkdtemp(prefix="hd-harnesscfg-")
import daemon.paths                                # noqa: E402
daemon.paths.DAEMON_ROOT = _SANDBOX

from spine.auth import auth                        # noqa: E402
from spine.storage import db, events               # noqa: E402

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
db.workspace_config_replace({"policy": {"lang": "de"}, "default_repo": "c:/proj/alpha"})

auth.create_user("owner1", "hunter2hunter2", "owner")
auth.create_user("ada", "hunter2hunter2", "client")
SID = {n: auth.login(n, "hunter2hunter2") for n in ("owner1", "ada")}
assert all(SID.values()), "sandbox logins failed: %s" % SID

from http.server import ThreadingHTTPServer        # noqa: E402
from spine.http.server import H                    # noqa: E402

PORT = int(os.environ.get("HELMDECK_DEV_PORT") or 3859)
_srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
threading.Thread(target=_srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % PORT

REPO = "c:/proj/alpha"


def call(method, path, body=None, who=None):
    """(status, parsed-json-or-raw-text)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if who:
        # sd_session, the name spine/http/server.py::_sid actually reads. "sid"
        # is silently no cookie at all, and every call then answers 401 - which
        # reads as a broken route rather than a broken test.
        req.add_header("Cookie", "sd_session=" + SID[who])
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode("utf-8", "replace")
            code = r.status
    except urllib.error.HTTPError as e:
        raw, code = e.read().decode("utf-8", "replace"), e.code
    try:
        return code, json.loads(raw)
    except ValueError:
        return code, raw


# -- 1. the route answers, with what the screen needs ---------------------
print("\n[GET /harness/config]")
code, doc = call("GET", "/harness/config?repo=" + REPO, who="owner1")
check(code == 200, "answers 200 (got %s)" % code)
check(isinstance(doc, dict) and doc.get("project"), "resolves a project key (%r)" % (doc or {}).get("project"))
rules = (doc or {}).get("rules") or []
check(len(rules) >= 20, "carries the whole rule table (%d rules)" % len(rules))
blocks = [b["key"] for b in (doc or {}).get("blocks") or []]
check(blocks == ["tone", "initiative", "hands", "report", "memory"],
      "blocks arrive in the server's order (%r)" % blocks)
check((doc or {}).get("layers") == ["default", "seed", "workspace", "project"],
      "the layer vocabulary is server-owned (%r)" % (doc or {}).get("layers"))

one = next((r for r in rules if r["key"] == "tone.length"), None)
check(one is not None and len(one["surfaces"]) == 4,
      "the length law arrives with all FOUR surface values, not one")
surf_rows = (one or {}).get("surfaces") or []
check(bool(surf_rows) and all({"surface", "path", "value", "default", "layer", "inherited"} <= set(s)
                              for s in surf_rows),
      "every surface row carries value + provenance the badge needs")
locked = [r for r in rules if r["kind"] == "fixed"]
check(bool(locked) and all(r.get("why") and r.get("source") for r in locked),
      "every locked rule brings its why-sentence AND its source (%d locked)" % len(locked))
check(bool(rules) and all(r.get("labelKey") and r.get("descKey") for r in rules),
      "every rule has a label and a one-line description key")

# -- 2. the capability gate ----------------------------------------------
print("\n[who may look, who may change]")
check(call("GET", "/harness/config", who="ada")[0] == 403, "a client may not read the rules")
check(call("GET", "/harness/config")[0] == 401, "an unauthenticated read is 401")
check(call("POST", "/harness/config", {"values": {"rule.tone.humor.pm": False}},
           who="ada")[0] == 403, "a client may not write them")

# -- 3. a write over the wire moves the value ----------------------------
print("\n[POST /harness/config]")
code, res = call("POST", "/harness/config",
                 {"repo": REPO, "values": {"rule.initiative.finish.pm": False}}, who="owner1")
check(code == 200, "the write is accepted (got %s %r)" % (code, res))
code, doc = call("GET", "/harness/config?repo=" + REPO, who="owner1")
row = next(r for r in doc["rules"] if r["key"] == "initiative.finish")["surfaces"][0]
check(row["value"] is False, "the value came back CHANGED (%r)" % row["value"])
check(row["layer"] == "project" and row["inherited"] is False,
      "and badged as set for this project (%r)" % row)

code, doc = call("GET", "/harness/config", who="owner1")
row = next(r for r in doc["rules"] if r["key"] == "initiative.finish")["surfaces"][0]
check(row["value"] is True and row["inherited"] is True,
      "with no repo the workspace answer is unchanged (%r)" % row)

print("\n[null clears back to inherited]")
code, _ = call("POST", "/harness/config",
               {"repo": REPO, "values": {"rule.initiative.finish.pm": None}}, who="owner1")
check(code == 200, "the clear is accepted (got %s)" % code)
code, doc = call("GET", "/harness/config?repo=" + REPO, who="owner1")
row = next(r for r in doc["rules"] if r["key"] == "initiative.finish")["surfaces"][0]
check(row["value"] is True and row["inherited"] is True,
      "the row inherits again rather than holding a null (%r)" % row)

# a workspace-scoped rule needs no repo and lands on the workspace
code, _ = call("POST", "/harness/config", {"values": {"rule.tone.address.pm": "Sie"}}, who="owner1")
code, doc = call("GET", "/harness/config", who="owner1")
row = next(r for r in doc["rules"] if r["key"] == "tone.address")["surfaces"][0]
check(row["value"] == "Sie" and row["layer"] == "workspace",
      "a workspace rule writes the workspace layer without a repo (%r)" % row)

# -- 4. a refusal is readable --------------------------------------------
print("\n[a refusal names itself]")
code, res = call("POST", "/harness/config",
                 {"values": {"rule.tone.examples.pm": "x"}}, who="owner1")
check(code == 400 and "shown, never set" in str(res.get("error")),
      "a readonly rule is refused with its reason (%s %r)" % (code, res))
code, res = call("POST", "/harness/config",
                 {"values": {"rule.tone.length.pm": "riesig"}}, who="owner1")
check(code == 400 and "takes one of" in str(res.get("error")),
      "a value outside the vocabulary names the vocabulary (%r)" % res)
code, res = call("POST", "/harness/config",
                 {"values": {"rule.initiative.finish.pm": False}}, who="owner1")
check(code == 400 and "no project" in str(res.get("error")),
      "a per-project rule with no repo says so instead of writing the workspace (%r)" % res)
check(call("POST", "/harness/config", {"values": {}}, who="owner1")[0] == 400,
      "an empty patch is refused rather than reported as a no-op success")

# -- 5. the warm process observes the brief ------------------------------
print("\n[the warm process cannot keep a stale brief]")
from cells.copilot import copilot                  # noqa: E402


class _FakeProc:
    def poll(self):
        return None


ent = {"p": _FakeProc(), "key": ("m", "acceptEdits", "FP-OLD")}
check(copilot._persist_switch(ent, ("m", "acceptEdits", "FP-NEW")) is False,
      "a moved fingerprint REFUSES the cheap path (caller respawns)")
check(ent["key"][2] == "FP-OLD", "and the refusal does not quietly adopt the new key")
check(copilot._persist_switch(ent, ("m", "acceptEdits", "FP-OLD")) is True,
      "an unchanged fingerprint still reuses the process")

fp = copilot._brief_fp()
call("POST", "/harness/config", {"values": {"rule.tone.humor.pm": False}}, who="owner1")
check(fp != copilot._brief_fp(), "a rule edit over the wire moves the brief fingerprint")
check(copilot._brief_fp() == copilot._brief_fp(), "and the fingerprint is stable between reads")

# -- 6. the project overlay ----------------------------------------------
print("\n[the project overlay rides the turn, not the spawn]")
from spine.registry import behavior                # noqa: E402
from spine.storage import projectconfig            # noqa: E402

P = projectconfig.project_key(REPO)
check(behavior.overlay(P) == "", "no deviation, no overlay - the usual turn pays nothing")
call("POST", "/harness/config",
     {"repo": REPO, "values": {"rule.hands.own_hands.pm": False}}, who="owner1")
ovl = behavior.overlay(P)
check("NO hands of your own" in ovl, "a deviating rule appears in the overlay (%r)" % ovl[:120])
check("Mild dry humor" not in ovl and "always" not in ovl,
      "and NOTHING else does - the overlay is deltas, not a second brief")
check(behavior.overlay("") == "", "the workspace itself never gets an overlay")

base = __import__("spine.registry.harness", fromlist=["x"]).brief("board-copilot")
check("{{rule:" not in base, "the base brief still renders every slot")
check("FUER DIESES PROJEKT" not in base,
      "and does NOT carry the project overlay - that is what keeps Henry warm across repos")

print("\n%d failure(s)" % len(_fails))
_srv.shutdown()
sys.exit(1 if _fails else 0)
