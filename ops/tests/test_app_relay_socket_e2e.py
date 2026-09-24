# -*- coding: utf-8 -*-
"""The whole chain, both real ends: the APP's relay socket (surfaces/app/src/
data/relay_socket.ts, compiled, run under node as the phone) <-> the relay
room (the real worker code in local workerd) <-> the DAEMON bridge (the real
_ws_session, _EventPublisher and _serve_one -> _local -> an HTTP API).
Real NaCl on both sides: tweetnacl seals on the phone, PyNaCl opens on the
daemon and back.

Owner 2026-09-24: "warum gibt es noch in app sachen, die gepollt sind" ->
"mache alles". What this proves:
  1. joining the room makes events live at once (the daemon was told);
  2. GET, POST and 8 concurrent requests travel the phone's socket, each
     reply finding its own request;
  3. a ~1.5 MB reply arrives - whole, or as retry:http for the HTTP path;
  4. a daemon write (db.bump) reaches the phone as a pushed event;
  5. a DAEMON restart does not drop the phone - the new daemon re-announces;
  6. a PHONE socket drop reconnects by itself and is live again.

    cd surfaces/relay/worker && npx wrangler dev --local --port 8799 --ip 127.0.0.1
    cd surfaces/app && npx tsc -p tsconfig.relaysocket.json
    py -3.12 ops/tests/test_app_relay_socket_e2e.py
Skips (exit 0) when the worker or the compiled phone is missing."""
import http.server
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from spine.comms import e2ee
from spine.comms import relay_client as rc
from spine.storage import db

BASE = os.environ.get("HELMDECK_WS_TEST_URL", "http://127.0.0.1:8799").rstrip("/")
APP = os.path.join(ROOT, "surfaces", "app")
DRIVER = os.path.join(APP, ".relaysocket-out", "data", "__relay_socket_e2e__.js")
NODE = os.environ.get("NODE", r"C:\Program Files\nodejs\node.exe")
ROOM = "app" + uuid.uuid4().hex[:12]
BIG = 1_500_000

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


class Api(http.server.BaseHTTPRequestHandler):
    """Stands in for the daemon's own HTTP API behind _local()."""
    protocol_version = "HTTP/1.1"

    def _send(self, code, body):
        b = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/me":
            return self._send(200, json.dumps({"name": "owner"}))
        if self.path.startswith("/n/"):
            return self._send(200, json.dumps({"n": int(self.path[3:])}))
        if self.path == "/big":
            return self._send(200, json.dumps({"blob": "x" * BIG}))
        return self._send(404, "{}")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self._send(200, self.rfile.read(n).decode() or "{}")

    def log_message(self, *a):
        pass


def main():
    try:
        urllib.request.urlopen(BASE + "/health", timeout=3)
    except Exception:
        print("SKIP - no worker at %s" % BASE)
        return 0
    if not os.path.exists(DRIVER) or not os.path.exists(NODE):
        print("SKIP - phone driver not compiled (%s) or node missing" % DRIVER)
        return 0

    d_sk, d_pk = e2ee.generate_keypair()
    p_sk, p_pk = e2ee.generate_keypair()
    D_SEC, D_PUB = e2ee.export_sec(d_sk), e2ee.export_pub(d_pk)
    P_SEC, P_PUB = e2ee.export_sec(p_sk), e2ee.export_pub(p_pk)

    api = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Api)
    threading.Thread(target=api.serve_forever, daemon=True).start()
    port = api.server_address[1]

    real = (rc._cfg, rc._admit)
    rc._cfg = lambda: (BASE, ROOM, D_SEC, [P_PUB])
    rc._admit = lambda pub: ((True, "") if pub == P_PUB else (False, "not paired"))

    def run_daemon():
        try:
            rc._ws_session(BASE, ROOM, D_SEC, port)      # REAL serve: _serve_one -> _local
        except Exception:                                # noqa: BLE001
            pass

    rc._stop = False
    dt = threading.Thread(target=run_daemon, daemon=True)
    dt.start()
    for _ in range(60):
        if rc.bridge_mode()[0] == "websocket":
            break
        time.sleep(0.1)

    ws_url = BASE.replace("http://", "ws://") + "/tunnel/client?room=%s&pub=%s" % (
        ROOM, urllib.request.quote(P_PUB, safe=""))
    env = dict(os.environ, URL=ws_url, P_SEC=P_SEC, D_PUB=D_PUB)
    proc = subprocess.Popen([NODE, DRIVER], cwd=APP, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    steps = {}
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            d = json.loads(line)
            steps[d["step"]] = d
            if d["step"] == "await-bump":
                db.bump()
            elif d["step"] == "await-restart":
                rc._stop = True                          # the daemon goes away ...
                dt.join(10)
                rc._stop = False
                time.sleep(0.5)
                dt = threading.Thread(target=run_daemon, daemon=True)   # ... and comes back
                dt.start()
            elif d["step"] == "done":
                break
        proc.wait(30)
    finally:
        if proc.poll() is None:
            proc.kill()
        rc._stop = True
        dt.join(10)
        rc._stop = False
        rc._cfg, rc._admit = real
        api.shutdown()

    err = proc.stderr.read() if proc.stderr else ""
    if err.strip():
        print("   node stderr:", err.strip()[:300])

    s = steps.get("live", {})
    check(s.get("live") is True and s.get("open") is True,
          "joining the room makes events LIVE at once (the daemon was told)")
    check((s.get("first") or {}).get("v") == 0 or isinstance((s.get("first") or {}).get("v"), int),
          "...the first event opens (tweetnacl <- PyNaCl) to {v, c}: %s" % s.get("first"))
    s = steps.get("me", {})
    check(s.get("ok") and s.get("status") == 200 and '"owner"' in (s.get("body") or ""),
          "GET /me over the phone socket -> the daemon's real _serve_one -> 200 (%s)" % s)
    s = steps.get("echo", {})
    check(s.get("ok") and "socket" in (s.get("body") or ""), "POST with a body over the socket (%s)" % s)
    s = steps.get("burst", {})
    check(s.get("ok") == 8, "8 concurrent socket requests each got their OWN reply (%s/8)" % s.get("ok"))
    s = steps.get("big", {})
    check((s.get("ok") and s.get("len", 0) > BIG) or s.get("retry") == "http",
          "a ~1.5 MB reply arrives whole, or as retry:http for the HTTP path (%s)"
          % {k: s.get(k) for k in ("ok", "len", "retry", "code")})
    s = steps.get("event2", {})
    check(s.get("got") and isinstance((s.get("ev") or {}).get("v"), int),
          "db.bump() on the daemon -> a PUSHED event on the phone (%s)" % s.get("ev"))
    s = steps.get("daemon-restart", {})
    check(s.get("phoneSocketStayedUp") is True, "a DAEMON restart does not drop the phone's socket")
    check(s.get("reannounced") is True, "...and the new daemon re-announces its state to the phone")
    s = steps.get("after-restart", {})
    check(s.get("ok") and s.get("status") == 200, "requests work again after the daemon restart (%s)" % s)
    s = steps.get("phone-reconnect", {})
    check(s.get("dropped") is True, "a dropped PHONE socket is noticed (events no longer live)")
    check(s.get("back") is True and s.get("open") is True,
          "...it reconnects by itself and is live again")
    s = steps.get("after-reconnect", {})
    check(s.get("ok") and s.get("status") == 200, "requests work after the phone reconnects (%s)" % s)
    check("done" in steps, "the phone driver ran to the end")

    print("\n%d FAIL" % len(_fails) if _fails else "\nall ok")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
