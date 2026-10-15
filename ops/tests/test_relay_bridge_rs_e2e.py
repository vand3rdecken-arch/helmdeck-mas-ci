# -*- coding: utf-8 -*-
"""The Rust relay bridge (surfaces/relay/bridge-rs) against the REAL relay worker.

A throw-away room (random id), a stub "daemon" on loopback, and a simulated phone
that speaks the PYTHON side of the wire (PyNaCl, ops/spine e2ee) - so this proves
the Rust box is byte-compatible with what the phone and the Python bridge use.
Nothing of the live daemon, its db, its relay room or its keys is touched.

  1. the bridge connects its WebSocket to the room;
  2. a pinned phone's request is decrypted, served by the local daemon, and the
     answer comes back sealed - GET, POST with a unicode body, and a 1.3 MB reply
     (too big for a socket message -> /tunnel/push);
  3. an UNPINNED key is answered "not paired", sealed to itself;
  4. a forged frame gets no answer and the bridge keeps serving;
  5. 8 phones x 20 requests at once: every answer correct, none lost.

Needs the release build (cd surfaces/relay/bridge-rs && cargo build --release) and the
internet (the worker). Skips, loudly, when either is missing.
Run: py -3.12 ops/tests/test_relay_bridge_rs_e2e.py
"""
import base64
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from nacl.public import Box, PrivateKey, PublicKey          # noqa: E402

EXE = os.path.join(ROOT, "surfaces", "relay", "bridge-rs", "target", "release", "helmdeck-relay-bridge.exe")
RELAY = os.environ.get("HELMDECK_TEST_RELAY", "https://relay.helmdeck.de")
BIG = 1_300_000

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def b64(raw):
    return base64.b64encode(raw).decode()


def seal(plain, my_sk, peer_pk):
    return b64(bytes(Box(my_sk, peer_pk).encrypt(plain)))


def open_(frame_b64, my_sk, peer_pk):
    return Box(my_sk, peer_pk).decrypt(base64.b64decode(frame_b64))


class Daemon(BaseHTTPRequestHandler):
    """The stub: what the real daemon would answer on loopback."""
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/big"):
            return self._send(200, "x" * BIG, "text/plain")
        if self.path.startswith("/ping"):
            return self._send(200, json.dumps({"ok": True, "path": self.path}))
        return self._send(404, json.dumps({"error": "nope"}))

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n).decode("utf-8")
        self._send(200, json.dumps({"echo": body, "xh": self.headers.get("X-Phone", "")}))


def phone_call(room, phone_sk, phone_pub_b64, daemon_pk, method, path, body="", timeout=30, headers=None):
    inner = {"method": method, "path": path, "headers": headers or {}, "body": body}
    payload = json.dumps({"pub": phone_pub_b64, "cipher": seal(json.dumps(inner).encode("utf-8"), phone_sk, daemon_pk)}).encode()
    req = urllib.request.Request("%s/relay?room=%s" % (RELAY, room), data=payload,
                                 headers={"Content-Type": "application/json", "User-Agent": "helmdeck-test"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    return json.loads(open_(data["cipher"], phone_sk, daemon_pk))


def main():
    if not os.path.isfile(EXE):
        print("SKIP: no release build at", EXE)
        return 0
    try:
        urllib.request.urlopen(urllib.request.Request(RELAY + "/health", headers={"User-Agent": "helmdeck-test"}), timeout=8)
    except Exception as e:                                   # noqa: BLE001
        print("SKIP: relay unreachable (%s)" % e)
        return 0

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Daemon)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    d_sk = PrivateKey.generate()
    p_sk = PrivateKey.generate()
    s_sk = PrivateKey.generate()                              # a stranger, never pinned
    p_pub = b64(bytes(p_sk.public_key))
    room = "hdtest-" + uuid.uuid4().hex[:16]

    bridge = subprocess.Popen(
        [EXE, "--relay", RELAY, "--room", room, "--sk", b64(bytes(d_sk)), "--pubs", p_pub,
         "--port", str(port), "--run-for", "150"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=0x08000000)
    lines = []
    up = threading.Event()

    def reader():
        for ln in bridge.stdout:
            lines.append(ln.strip())
            if "transport: websocket" in ln:
                up.set()
    threading.Thread(target=reader, daemon=True).start()
    try:
        check(up.wait(30), "the bridge connects its WebSocket to the room")
        if not up.is_set():
            print("\n".join(lines[-5:]))
            return 1
        time.sleep(1.0)                                       # let the room register the daemon socket
        dpk = d_sk.public_key

        r = phone_call(room, p_sk, p_pub, dpk, "GET", "/ping?x=1")
        check(r["status"] == 200 and json.loads(r["body"]) == {"ok": True, "path": "/ping?x=1"},
              "GET: decrypted, served by the local daemon, sealed back")
        check(r["headers"]["Content-Type"] == "application/json", "...with the daemon's content type")

        text = "Grüße, 日本語, \"quotes\" und\nZeilenumbruch"
        r = phone_call(room, p_sk, p_pub, dpk, "POST", "/echo", body=text, headers={"X-Phone": "ja"})
        e = json.loads(r["body"])
        check(r["status"] == 200 and e["echo"] == text and e["xh"] == "ja", "POST: a unicode body and a header travel intact")

        r = phone_call(room, p_sk, p_pub, dpk, "GET", "/big", timeout=60)
        check(r["status"] == 200 and len(r["body"]) == BIG, "a %.1f MB reply (over the socket limit) arrives via /tunnel/push" % (BIG / 1e6))

        r = phone_call(room, p_sk, p_pub, dpk, "GET", "/missing")
        check(r["status"] == 404, "the daemon's own error status passes through (404)")

        s_pub = b64(bytes(s_sk.public_key))
        r = phone_call(room, s_sk, s_pub, dpk, "GET", "/ping")
        check(r["status"] == 409 and "not paired" in r["body"], "an UNPINNED key is answered 'not paired', sealed to itself")

        # forged: sealed by a key that is not the one it claims -> silence (the room times the phone out)
        forged = json.dumps({"pub": p_pub, "cipher": seal(b'{"method":"GET","path":"/ping"}', s_sk, dpk)}).encode()
        got = "reply"
        try:
            urllib.request.urlopen(urllib.request.Request(
                "%s/relay?room=%s" % (RELAY, room), data=forged,
                headers={"Content-Type": "application/json", "User-Agent": "helmdeck-test"}), timeout=6)
        except Exception:                                    # noqa: BLE001
            got = "silence"
        check(got == "silence", "a forged frame gets NO answer")
        r = phone_call(room, p_sk, p_pub, dpk, "GET", "/ping?after=forged")
        check(r["status"] == 200, "...and the bridge keeps serving afterwards")

        errs, lat = [], []

        def phone(i):
            for k in range(20):
                t = time.time()
                try:
                    rr = phone_call(room, p_sk, p_pub, dpk, "GET", "/ping?c=%d-%d" % (i, k))
                    if rr["status"] != 200 or json.loads(rr["body"])["path"] != "/ping?c=%d-%d" % (i, k):
                        errs.append((i, k, rr))
                except Exception as ex:                      # noqa: BLE001
                    errs.append((i, k, repr(ex)))
                lat.append(time.time() - t)
        ts = [threading.Thread(target=phone, args=(i,)) for i in range(8)]
        t0 = time.time()
        [t.start() for t in ts]
        [t.join() for t in ts]
        lat.sort()
        check(not errs and len(lat) == 160, "8 phones x 20 requests at once: all 160 answered correctly%s" % ("" if not errs else " %s" % errs[:2]))
        print("      latency p50 %.0f ms, p95 %.0f ms, %.1f s total (internet round trip included)"
              % (lat[len(lat) // 2] * 1000, lat[int(len(lat) * .95)] * 1000, time.time() - t0))
    finally:
        bridge.kill()
        srv.shutdown()
    print()
    if _fails:
        print("=== %d FAILED ===" % len(_fails))
        return 1
    print("relay-bridge-rs e2e: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
