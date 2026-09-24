# -*- coding: utf-8 -*-
"""The relay's WebSocket bridge, end to end against the REAL worker code.

2026-09-23: the long-poll bridge burned ~3,500 relay requests a day per PC
while idle and three per phone request; one user tripped Cloudflare's free
limit and the phone was cut off for the rest of the UTC day. The daemon now
holds ONE hibernatable WebSocket to its room (surfaces/relay/worker/src/
room.js + spine/comms/relay_client.py). This pins the behaviour that makes it
safe to ship:

  1. a phone frame reaches the daemon over the socket and the reply returns
     over it - with ZERO /tunnel/pull calls;
  2. the room counts a socket as "daemon present" (the diagnosis panel's 400
     vs 503 probe keeps working);
  3. the keepalive "ping" is answered "pong" by the runtime;
  4. a reply too big for a socket message falls back to /tunnel/push and
     still reaches the phone (same waiting id);
  5. a reply whose socket is gone falls back to /tunnel/push as well;
  6. a newer daemon socket REPLACES the older one (no twin bridges);
  7. a relay without /ws is recognised as such - the bridge long-polls.

Needs the worker running locally (workerd via wrangler, no Cloudflare):
    cd surfaces/relay/worker && npx wrangler dev --local --port 8799 --ip 127.0.0.1
    py -3.12 ops/tests/test_relay_websocket.py
HELMDECK_WS_TEST_URL overrides the address. Skips (exit 0, says so) when no
worker answers - it never touches the live relay."""
import http.server
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from spine.comms import relay_client as rc

BASE = os.environ.get("HELMDECK_WS_TEST_URL", "http://127.0.0.1:8799").rstrip("/")
ROOM = "wstest%d" % int(time.time())

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def call(method, path, body=None, timeout=20):
    data = body.encode() if isinstance(body, str) else body
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def phone(cipher, timeout=30):
    return call("POST", "/relay?room=" + ROOM, json.dumps({"pub": "phonepub", "cipher": cipher}),
                timeout=timeout)


def main():
    try:
        st, _ = call("GET", "/health", timeout=3)
    except Exception:
        st = 0
    if st != 200:
        print("SKIP - no worker at %s (start wrangler dev, see docstring)" % BASE)
        return 0

    # count the long-poll calls the bridge makes - the point is that there are none
    pulls = []
    real_pull = rc._pull

    def counting_pull(relay, room):
        pulls.append(1)
        return real_pull(relay, room)
    rc._pull = counting_pull

    # A fake daemon handler: echo through the REAL delivery path (_deliver),
    # so the socket/HTTP choice is the production one.
    served = []

    def serve(relay, room, sk, port, frame, send=None):
        served.append(frame)
        c = frame["cipher"]
        if c == "BIG":
            reply = "x" * (rc.WS_MAX_REPLY + 1024)            # too big for a socket message
        elif c == "SOCKET-DIES":
            reply = "after-death"
            send = (lambda fid, cipher: (_ for _ in ()).throw(ConnectionError("gone")))
        else:
            reply = "echo:" + c
        rc._deliver(relay, room, frame["id"], reply, send)

    rc._stop = False
    sess_err = []

    def run_session():
        try:
            rc._ws_session(BASE, ROOM, "sk", 0, serve=serve)
        except Exception as e:                               # noqa: BLE001
            sess_err.append(e)
    t = threading.Thread(target=run_session, daemon=True)
    t.start()
    for _ in range(50):
        if rc.bridge_mode()[0] == "websocket":
            break
        time.sleep(0.1)
    check(rc.bridge_mode()[0] == "websocket", "bridge reports transport=websocket once connected")

    # 2. presence: the empty-body probe gets past the "no daemon" gate
    code, _ = call("POST", "/relay?room=" + ROOM, "")
    check(code == 400, "room probe answers 400 (daemon present via socket), got %d" % code)

    # 1. round trip over the socket, no pull at all
    code, body = phone("hello")
    check(code == 200 and json.loads(body).get("cipher") == "echo:hello",
          "phone frame -> daemon over the socket -> reply back (%d %s)" % (code, body[:60]))
    check(served and served[-1].get("kind") == "frame" and served[-1].get("id"),
          "the daemon got the frame with its id")
    check(not pulls, "ZERO /tunnel/pull calls while on the socket (%d)" % len(pulls))

    # a burst, concurrently - the socket must multiplex by id
    results = {}

    def one(i):
        results[i] = phone("m%d" % i)
    ths = [threading.Thread(target=one, args=(i,)) for i in range(12)]
    [x.start() for x in ths]
    [x.join(30) for x in ths]
    good = sum(1 for i, (c, b) in results.items()
               if c == 200 and json.loads(b).get("cipher") == "echo:m%d" % i)
    check(good == 12, "12 concurrent phone requests each got THEIR OWN reply (%d/12)" % good)

    # 4. too big for a socket message -> /tunnel/push, same waiting id
    code, body = phone("BIG", timeout=60)
    check(code == 200 and len(json.loads(body).get("cipher", "")) > rc.WS_MAX_REPLY,
          "a >%d KB reply travels over /tunnel/push and still arrives" % (rc.WS_MAX_REPLY // 1024))

    # 5. socket gone while answering -> /tunnel/push
    code, body = phone("SOCKET-DIES")
    check(code == 200 and json.loads(body).get("cipher") == "after-death",
          "a reply whose socket send fails falls back to /tunnel/push")

    # 3. keepalive answered by the runtime
    from websockets.sync.client import connect
    probe = connect(rc._ws_url(BASE, ROOM + "-ping"), ping_interval=None, open_timeout=10)
    probe.send("ping")
    check(probe.recv(timeout=5) == "pong", "text 'ping' is answered 'pong' (runtime auto-response)")
    probe.close()

    # 6. a newer daemon socket replaces the older one
    newer = connect(rc._ws_url(BASE, ROOM), ping_interval=None, open_timeout=10)
    t.join(10)
    closed = not t.is_alive()
    check(closed, "the older bridge session ENDS when a newer socket joins the room")
    reason = str(sess_err[0]) if sess_err else ""
    check("1012" in reason or "replaced" in reason,
          "...closed with 1012 'replaced' (%s)" % reason[:80])
    newer.close()

    # 7. a relay without /ws -> _WSUnsupported (the loop then long-polls)
    class NoWS(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(404)
            self.end_headers()

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), NoWS)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        rc._ws_session("http://127.0.0.1:%d" % srv.server_address[1], ROOM, "sk", 0, serve=serve)
        check(False, "a relay without /ws raises _WSUnsupported")
    except rc._WSUnsupported as e:
        check(True, "a relay without /ws raises _WSUnsupported (%s)" % e)
    except Exception as e:                                   # noqa: BLE001
        check(False, "a relay without /ws raises _WSUnsupported, got %r" % e)
    finally:
        srv.shutdown()

    # 8. THE LOOP picks the transport - websocket against the worker, long-poll
    #    against a relay without /ws - and serves the phone either way.
    rc._pull = real_pull
    real_cfg, real_base, real_serve = rc._cfg, rc._resolve_base, rc._serve_one
    rc._resolve_base = lambda r: r
    rc._serve_one = serve
    try:
        rc._stop = False
        rc._ws_state.update(unsupported_until=0.0, fails=0, mode="starting", reason="")
        room8 = ROOM + "-loop"
        rc._cfg = lambda: (BASE, room8, "sk", [])
        lt = threading.Thread(target=rc._loop, args=(0,), daemon=True)
        lt.start()
        for _ in range(80):
            if rc.bridge_mode()[0] == "websocket":
                break
            time.sleep(0.1)
        check(rc.bridge_mode()[0] == "websocket", "_loop connects over WEBSOCKET to a worker relay")
        code, body = call("POST", "/relay?room=" + room8, json.dumps({"pub": "p", "cipher": "via-loop"}), timeout=30)
        check(code == 200 and json.loads(body).get("cipher") == "echo:via-loop",
              "...and serves a phone request through it (%d)" % code)
        rc._stop = True
        lt.join(15)
        check(not lt.is_alive(), "_loop stops cleanly when told to")
    finally:
        rc._stop = False
        rc._cfg, rc._resolve_base, rc._serve_one = real_cfg, real_base, real_serve

    relaypy = os.environ.get("HELMDECK_WS_TEST_RELAYPY", "")   # e.g. http://127.0.0.1:6799
    if relaypy:
        rc._resolve_base = lambda r: r
        rc._serve_one = serve
        try:
            rc._ws_state.update(unsupported_until=0.0, fails=0, mode="starting", reason="")
            room9 = ROOM + "-relaypy"
            rc._cfg = lambda: (relaypy, room9, "sk", [])
            lt = threading.Thread(target=rc._loop, args=(0,), daemon=True)
            lt.start()
            for _ in range(80):
                if rc.bridge_mode()[0] == "long-poll":
                    break
                time.sleep(0.1)
            check(rc.bridge_mode()[0] == "long-poll",
                  "_loop falls back to LONG-POLL against relay.py (%s)" % rc.bridge_mode()[2][:50])
            time.sleep(1.5)            # let the first pull park
            req = urllib.request.Request(relaypy + "/relay?room=" + room9,
                                         data=json.dumps({"pub": "p", "cipher": "via-pull"}).encode(),
                                         method="POST", headers={"content-type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=40) as r:
                    code, body = r.status, r.read().decode()
            except urllib.error.HTTPError as e:
                code, body = e.code, e.read().decode()
            check(code == 200 and json.loads(body).get("cipher") == "echo:via-pull",
                  "...and still serves the phone over the pull path (%d %s)" % (code, body[:50]))
            rc._stop = True
        finally:
            rc._cfg, rc._resolve_base, rc._serve_one = real_cfg, real_base, real_serve
    else:
        print("  (skip) relay.py fallback leg - set HELMDECK_WS_TEST_RELAYPY to run it")

    # the URL mapping
    check(rc._ws_url("https://relay.helmdeck.de", "a b") == "wss://relay.helmdeck.de/tunnel/ws?room=a%20b",
          "https -> wss, room quoted")
    check(rc._ws_url("http://127.0.0.1:6790/", "r") == "ws://127.0.0.1:6790/tunnel/ws?room=r",
          "http -> ws, trailing slash dropped")
    check(rc._ws_url("ftp://x", "r") == "", "unknown scheme -> no websocket")

    rc._pull = real_pull
    print("\n%d FAIL" % len(_fails) if _fails else "\nall ok")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
