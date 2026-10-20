# -*- coding: utf-8 -*-
"""POST /relay/direct - the phone's LAN path to the daemon (2026-10-20).

Measured on the phone: 829 ms per request, 710 ms of it the network legs via
Cloudflare. On the same WiFi the phone sends the SAME sealed frame straight to
the daemon. Drives the REAL server (spine.http.server.H over a real socket) and
the real relay_client.serve_direct, with the security half first:
  - only a PINNED device key is served; pairing never happens on this door;
  - a captured frame cannot be replayed (nonce), nor sent late (timestamp);
  - the answer is sealed to the caller, the inner request authenticates as usual;
  - no session needed at the HTTP level (it is a sealed door, like the relay).

SELF-SANDBOXING like test_boards_http.py. Run: py -3.12 ops/tests/test_relay_direct.py
"""
import json, os, sys, tempfile, threading, time, uuid
import urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
_SANDBOX = tempfile.mkdtemp(prefix="hd-direct-")
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
SID = auth.login("owner1", "hunter2hunter2")

from spine.comms import e2ee, relay_client as rc    # noqa: E402
from http.server import ThreadingHTTPServer        # noqa: E402
from spine.http.server import H                    # noqa: E402

d_sk, d_pk = e2ee.generate_keypair()
p_sk, p_pk = e2ee.generate_keypair()
x_sk, x_pk = e2ee.generate_keypair()               # a key that never paired
PUB = e2ee.export_pub(p_pk)
events.save_settings({"relay": {"sk": e2ee.export_sec(d_sk), "phone_pubs": [PUB],
                                "url": "https://relay.invalid", "room": "r1"}}, actor="test")

PORT = int(os.environ.get("HELMDECK_DEV_PORT") or 3863)
_srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
threading.Thread(target=_srv.serve_forever, daemon=True).start()
rc.serve_inproc(H)
rc.serve_direct_on(PORT)


def inner(path="/me", ts=None, n=None, method="GET", body=""):
    return {"method": method, "path": path, "body": body,
            "headers": {"Cookie": "sd_session=%s" % SID},
            "ts": time.time() if ts is None else ts, "n": n or uuid.uuid4().hex}


def post(frame_body):
    req = urllib.request.Request("http://127.0.0.1:%d/relay/direct" % PORT,
                                 data=json.dumps(frame_body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def sealed(i, sk=p_sk, pub=PUB):
    return {"pub": pub, "cipher": e2ee.seal_b64(json.dumps(i).encode(), sk, d_pk)}


def opened(out):
    return json.loads(e2ee.open_b64(out["cipher"], p_sk, d_pk))


# 1. the happy path, over a real socket, without any session at the HTTP level
fr = sealed(inner())
code, out = post(fr)
check(code == 200 and "cipher" in out, "a pinned phone's sealed frame is answered (HTTP %s)" % code)
r = opened(out) if "cipher" in out else {}
check(r.get("status") == 200 and json.loads(r.get("body") or "{}").get("name") == "owner1",
      "the phone opens it: its own /me")
check(isinstance((r.get("tm") or {}).get("h"), int), "with the daemon time split (tm.h)")

# 2. replay: the SAME frame again
code, out = post(fr)
r = opened(out) if "cipher" in out else {}
check(r.get("status") == 409, "the same frame a second time is refused (replay)")

# 3. late: a frame from 5 minutes ago
code, out = post(sealed(inner(ts=time.time() - 300)))
check((opened(out) if "cipher" in out else {}).get("status") == 409, "a frame outside the clock window is refused")

# 4. no nonce at all
i = inner(); del i["n"]
code, out = post(sealed(i))
check((opened(out) if "cipher" in out else {}).get("status") == 409, "a frame without a nonce is refused")

# 5. a key that never paired
code, out = post(sealed(inner(), sk=x_sk, pub=e2ee.export_pub(x_pk)))
check(code == 403 and "cipher" not in out, "an unpaired key gets 403 and nothing sealed")

# 6. a pinned pub with a cipher it did not seal (forged)
code, out = post({"pub": PUB, "cipher": e2ee.seal_b64(b'{"path":"/me"}', x_sk, d_pk)})
check(code == 400, "a forged frame under a pinned pub is undecryptable (400)")

# 7. the inner request still authenticates on its own
i = inner(); i["headers"] = {}
code, out = post(sealed(i))
check((opened(out) if "cipher" in out else {}).get("status") == 401, "inside the box, no session = 401")

# 8. no frames inside frames
code, out = post(sealed(inner(path="/relay/direct", method="POST", body="{}")))
check((opened(out) if "cipher" in out else {}).get("status") == 400, "a frame cannot nest /relay/direct")

# 9. a write runs exactly once even if the frame is sent twice - and the second
#    send gets the FIRST answer (the app's safe resend after a failed direct try)
i = inner(path="/me/boards", method="PUT",
          body=json.dumps({"board": {"name": "Direct", "columns": [{"label": "", "station": "working"}]}}))
f2 = sealed(i)
a = opened(post(f2)[1])
b = opened(post(f2)[1])
check(a.get("status") == 200 and b.get("status") == 200 and a.get("body") == b.get("body"),
      "a replayed PUT gets the first run's answer")
code, out = post(sealed(inner()))
names = [b.get("name") for b in json.loads(opened(out)["body"]).get("boards") or []]
check(names.count("Direct") == 1, "...and ran once (%s)" % names)

# 9b. the SAME write resent over the RELAY door (same nonce) runs once too
i = inner(path="/me/boards", method="PUT",
          body=json.dumps({"board": {"name": "Both", "columns": [{"label": "", "station": "working"}]}}))
post(sealed(i))                                   # the direct try (ran)
got = []
rc._serve_one("http://relay.invalid", "r1", e2ee.export_sec(d_sk), PORT,
              {"id": "f9", "pub": PUB, "t": time.time(), "cipher": e2ee.seal_b64(json.dumps(i).encode(), p_sk, d_pk)},
              send=lambda fid, c, to: got.append(c))
rr = json.loads(e2ee.open_b64(got[0], p_sk, d_pk)) if got else {}
code, out = post(sealed(inner()))
names = [b.get("name") for b in json.loads(opened(out)["body"]).get("boards") or []]
check(rr.get("status") == 200 and names.count("Both") == 1,
      "a write resent over the relay after the direct try: answered, ran once (%s)" % names)

# 10. advertised address: only with the direct door on
check(rc.lan_endpoints() and rc.lan_endpoints()[0].endswith(":%d" % PORT), "lan_endpoints advertises the port (%s)" % rc.lan_endpoints())
rc.serve_direct_on(None)
check(rc.lan_endpoints() == [], "no direct door (TLS box) - nothing advertised")
code, out = post(sealed(inner()))
check(code == 404, "and the door is shut (404)")

_srv.shutdown()
print("RESULT:", "PASS" if not _fails else "FAIL (%d)" % len(_fails))
sys.exit(1 if _fails else 0)
