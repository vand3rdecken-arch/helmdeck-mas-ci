# -*- coding: utf-8 -*-
"""Relay frames served IN-PROCESS answer exactly what the loopback hop did.

Owner 2026-10-19: "warum soviele Instanz vs paseo". A phone request used to be
an HTTP request from the relay's serve pool to the daemon's own loopback port:
two threads and a TCP hop per call. relay_client._inproc runs the SAME handler
class on an in-memory request. This drives the REAL spine.http.server.H both
ways - over a real loopback socket (_local, the old path) and in-process - and
requires identical status and body for open, authenticated, refused, POST and
unknown routes; plus the two things only the in-process path has to get right
itself: an SSE route must not hold a serve thread forever, and a request that
outlives LOCAL_TIMEOUT still answers `held` exactly once.

SELF-SANDBOXING like test_boards_http.py. Run: py -3.12 ops/tests/test_relay_inproc.py
"""
import json, os, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

_SANDBOX = tempfile.mkdtemp(prefix="hd-inproc-")
import daemon.paths
daemon.paths.DAEMON_ROOT = _SANDBOX
daemon.paths.DATA_ROOT = _SANDBOX

from spine.auth import auth                     # noqa: E402
from spine.storage import db, events            # noqa: E402

for label, path in (("db", db.DBPATH), ("settings", events.SET), ("users", auth.USERS)):
    assert path.startswith(_SANDBOX), "REFUSING TO RUN: %s points at %s" % (label, path)

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


db.init()
auth.create_user("owner1", "hunter2hunter2", "owner")
auth.create_user("ada", "hunter2hunter2", "client")
SID = {n: auth.login(n, "hunter2hunter2") for n in ("owner1", "ada")}

from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler  # noqa: E402
from spine.http.server import H                 # noqa: E402
from spine.comms import relay_client as rc      # noqa: E402

PORT = int(os.environ.get("HELMDECK_DEV_PORT") or 3861)
_srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
threading.Thread(target=_srv.serve_forever, daemon=True).start()


def frame(method, path, body=None, who=None):
    h = {"Content-Type": "application/json"}
    if who:
        h["Cookie"] = "sd_session=%s" % SID[who]
    return {"method": method, "path": path, "headers": h,
            "body": json.dumps(body) if body is not None else ""}


CASES = [
    ("open route", frame("GET", "/auth/state")),
    ("owner /me", frame("GET", "/me", who="owner1")),
    ("no auth -> 401", frame("GET", "/me")),
    ("client refused owner-only", frame("GET", "/settings", who="ada")),
    ("owner settings", frame("GET", "/settings", who="owner1")),
    ("PUT with a body", frame("PUT", "/me/boards",
                              {"board": {"name": "Inproc", "columns": [{"label": "", "station": "working"}]}},
                              who="ada")),
    ("unknown route", frame("GET", "/no/such/route", who="owner1")),
    ("query string", frame("GET", "/tracks?since=0", who="owner1")),
]

rc.serve_inproc(H)
for name, f in CASES:
    a = rc._local(PORT, f)
    b = rc._inproc(f)
    if name == "PUT with a body":           # a second create gets its own id - compare shape
        ja, jb = json.loads(a["body"] or "{}"), json.loads(b["body"] or "{}")
        same = a["status"] == b["status"] == 200 and jb.get("ok") and sorted(ja) == sorted(jb)             and jb["board"]["name"] == "Inproc"
    else:
        same = (a["status"], a["body"]) == (b["status"], b["body"])
    check(same, "%s: loopback %s == in-process %s" % (name, a["status"], b["status"]))
    check(a["headers"].get("Content-Type") == b["headers"].get("Content-Type"),
          "%s: same content type (%s)" % (name, b["headers"].get("Content-Type")))

bid = json.loads(rc._inproc(frame("GET", "/me", who="ada"))["body"])
names = [b.get("name") for b in (bid.get("boards") or [])]
check(names.count("Inproc") == 2, "both writes landed - the body really arrived (%s)" % names)

t0 = time.time()
r = rc._inproc(frame("GET", "/stream", who="owner1"))
check(r["status"] == 400 and time.time() - t0 < 1, "SSE /stream refused at once, never holds a thread")
r = rc._inproc(frame("GET", "/tracks/x/stream", who="owner1"))
check(r["status"] == 400, "per-card SSE refused too")

r = rc._inproc({"method": "GET", "path": "/me", "body": "",
                "headers": {"Cookie": "sd_session=%s" % SID["owner1"], "X-Evil": "a\r\nCookie: x"}})
check(r["status"] == 200, "a header with CR/LF is dropped, not spliced into the request")


# held: a route still running after LOCAL_TIMEOUT answers `held` once, keeps
# running, and its late answer is dropped - the same protocol _serve_one runs.
class Slow(H):
    def do_GET(self):
        if self.path == "/slow":
            time.sleep(1.5)
            return self._send(200, json.dumps({"late": True}))
        return H.do_GET(self)


rc.HELD_TICK_S = 0.1
rc.serve_inproc(Slow)
delivered = []
token = object()
rc._held_arm(token, lambda: delivered.append("held"), 0.4)
resp = rc._inproc(frame("GET", "/slow", who="owner1"))
finished_first = rc._held_disarm(token)
if finished_first:
    delivered.append(resp)
check(delivered == ["held"], "slow route: exactly one answer, and it is `held` (%s)" % delivered)

token = object()
rc._held_arm(token, lambda: delivered.append("held-2"), 5)
resp = rc._inproc(frame("GET", "/auth/state"))
check(rc._held_disarm(token) and "held-2" not in delivered, "fast route: no held answer, the real one")
time.sleep(0.3)
check("held-2" not in delivered, "a disarmed request never fires later")

_srv.shutdown()
print("RESULT:", "PASS" if not _fails else "FAIL (%d)" % len(_fails))
sys.exit(1 if _fails else 0)
