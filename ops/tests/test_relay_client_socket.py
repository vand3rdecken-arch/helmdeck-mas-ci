# -*- coding: utf-8 -*-
"""The PHONE as a socket - and the end of polling (owner 2026-09-24: "warum
gibt es noch in app sachen, die gepollt sind, das macht doch kein senior
engineer" -> "mache alles").

Paseo keeps both ends as hibernating sockets and pushes typed state; its app
polls nothing the daemon could push. This pins HelmDeck's version of that,
end to end against the REAL worker code (local workerd) and the REAL daemon
bridge (_ws_session + _EventPublisher), with REAL NaCl sealing:

  1. a phone joining the room gets the current {v, c} at once - the daemon is
     told "a client joined" and answers; that first event is also how the app
     learns this daemon pushes at all;
  2. a request over the phone's socket gets its reply over the socket, routed
     by the reply's own `to` (no in-memory map - survives hibernation);
  3. a board write (db.bump) reaches the phone as an event, and a BURST of
     writes arrives as one or two events, not fifty;
  4. an event is sealed to ONE device: another key cannot open it, and an
     unpinned device gets nothing at all;
  5. a reply too big for a socket message still reaches the phone - either
     whole, or as {retry:"http"} - never silence;
  6. no daemon in the room -> the phone hears 503 at once;
  7. the phone's text "ping" is answered "pong" by the runtime.

    cd surfaces/relay/worker && npx wrangler dev --local --port 8799 --ip 127.0.0.1
    py -3.12 ops/tests/test_relay_client_socket.py
Skips (exit 0) when no worker answers; never touches the live relay."""
import json
import os
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
WSBASE = BASE.replace("http://", "ws://").replace("https://", "wss://")
ROOM = "cs" + uuid.uuid4().hex[:12]

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def keypair():
    sk, pk = e2ee.generate_keypair()
    return e2ee.export_sec(sk), e2ee.export_pub(pk)


class Phone:
    """A phone's socket: collects everything the room sends it."""
    def __init__(self, pub, room=ROOM):
        from websockets.sync.client import connect
        self.ws = connect("%s/tunnel/client?room=%s&pub=%s" % (WSBASE, room, urllib.request.quote(pub, safe="")),
                          ping_interval=None, open_timeout=10, max_size=16 * 1024 * 1024)
        self.msgs = []
        self._t = threading.Thread(target=self._rx, daemon=True)
        self._t.start()

    def _rx(self):
        try:
            for m in self.ws:
                self.msgs.append(m if not isinstance(m, str) or m == "pong" else json.loads(m))
        except Exception:                                    # noqa: BLE001
            pass

    def wait(self, pred, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            hit = [m for m in self.msgs if isinstance(m, dict) and pred(m)]
            if hit:
                return hit
            time.sleep(0.05)
        return []

    def send(self, obj):
        self.ws.send(obj if isinstance(obj, str) else json.dumps(obj))

    def close(self):
        try:
            self.ws.close()
        except Exception:                                    # noqa: BLE001
            pass


def main():
    try:
        urllib.request.urlopen(BASE + "/health", timeout=3)
    except Exception:
        print("SKIP - no worker at %s (start wrangler dev, see docstring)" % BASE)
        return 0

    d_sk, d_pub = keypair()                  # the daemon's keys
    p_sk, p_pub = keypair()                  # the paired phone
    o_sk, o_pub = keypair()                  # an UNPINNED device that knows the room id

    def open_event(msg, sk=p_sk):
        return json.loads(e2ee.open_b64(msg["cipher"], e2ee.import_sec(sk), e2ee.import_pub(d_pub)))

    # 6. no daemon yet -> 503 at once
    early = Phone(p_pub)
    early.send({"kind": "req", "id": "r0", "cipher": "x"})
    r = early.wait(lambda m: m.get("kind") == "res" and m.get("id") == "r0", 5)
    check(bool(r) and r[0].get("status") == 503, "no daemon in the room -> the phone hears 503 at once")
    early.close()

    # the daemon: REAL session + publisher, only the config and the handler are stubbed
    real_cfg = rc._cfg
    rc._cfg = lambda: (BASE, ROOM, d_sk, [p_pub])            # p_pub pinned, o_pub NOT
    served = []

    def serve(relay, room, sk, port, frame, send=None):
        served.append(frame)
        c = frame["cipher"]
        reply = ("x" * (rc.WS_MAX_REPLY + 4096)) if c == "BIG" else ("echo:" + c)
        rc._deliver(relay, room, frame["id"], reply, send, to=frame.get("pub"))

    rc._stop = False
    t = threading.Thread(target=lambda: rc._ws_session(BASE, ROOM, d_sk, 0, serve=serve), daemon=True)
    t.start()
    for _ in range(60):
        if rc.bridge_mode()[0] == "websocket":
            break
        time.sleep(0.1)
    time.sleep(0.3)

    try:
        # 1. join -> the current state at once
        phone = Phone(p_pub)
        ev = phone.wait(lambda m: m.get("kind") == "event", 8)
        check(bool(ev), "a phone joining gets an event at once (the daemon was told it joined)")
        if ev:
            got = open_event(ev[0])
            check(got == {"v": db.current_version(), "c": db.current_chat_version()},
                  "...and it opens (NaCl) to the daemon's CURRENT {v, c}: %s" % got)

        # 4a. another key cannot open it
        if ev:
            try:
                open_event(ev[0], sk=o_sk)
                check(False, "an event sealed to the phone cannot be opened with another key")
            except Exception:                                # noqa: BLE001
                check(True, "an event sealed to the phone cannot be opened with another key")

        # 4b. an unpinned device gets nothing, not even on join
        other = Phone(o_pub)
        time.sleep(1.5)
        check(not [m for m in other.msgs if isinstance(m, dict) and m.get("kind") == "event"],
              "an UNPINNED device that knows the room id gets no event")

        # 2. request over the socket, reply routed by `to`
        phone.send({"kind": "req", "id": "q1", "cipher": "hi"})
        r = phone.wait(lambda m: m.get("kind") == "res" and m.get("id") == "q1", 10)
        check(bool(r) and r[0].get("cipher") == "echo:hi",
              "request over the phone socket -> reply over the socket (%s)" % (r[0] if r else "none"))
        check(served and served[-1].get("via") == "ws" and served[-1].get("pub") == p_pub,
              "the daemon saw it as a socket frame from THIS device's key")
        check(not [m for m in other.msgs if isinstance(m, dict) and m.get("id") == "q1"],
              "the reply went to the requesting device only")

        # concurrency over one phone socket
        for i in range(10):
            phone.send({"kind": "req", "id": "c%d" % i, "cipher": "m%d" % i})
        got = phone.wait(lambda m: m.get("kind") == "res" and str(m.get("id", "")).startswith("c"), 10)
        time.sleep(1.0)
        got = [m for m in phone.msgs if isinstance(m, dict) and m.get("kind") == "res"
               and str(m.get("id", "")).startswith("c")]
        good = sum(1 for m in got if m.get("cipher") == "echo:m" + m["id"][1:])
        check(good == 10, "10 concurrent socket requests each got their own reply (%d/10)" % good)

        # 3. a board write reaches the phone as an event
        before = len([m for m in phone.msgs if isinstance(m, dict) and m.get("kind") == "event"])
        db.bump()
        want_v = db.current_version()
        hit = phone.wait(lambda m: m.get("kind") == "event" and open_event(m).get("v") == want_v, 5)
        check(bool(hit), "db.bump() -> the phone gets an event with the new v=%d" % want_v)

        # 3b. a burst coalesces
        base_n = len([m for m in phone.msgs if isinstance(m, dict) and m.get("kind") == "event"])
        for _ in range(50):
            db.bump()
        time.sleep(2.0)
        after = [m for m in phone.msgs if isinstance(m, dict) and m.get("kind") == "event"]
        burst = len(after) - base_n
        check(1 <= burst <= 3, "50 writes in a burst -> %d event(s), not 50" % burst)
        check(after and open_event(after[-1]).get("v") == db.current_version(),
              "...and the last one carries the FINAL v (nothing lost by coalescing)")

        # 5. a reply too big for one socket message
        phone.send({"kind": "req", "id": "big", "cipher": "BIG"})
        r = phone.wait(lambda m: m.get("kind") == "res" and m.get("id") == "big", 30)
        ok_big = bool(r) and (len(r[0].get("cipher") or "") > rc.WS_MAX_REPLY or r[0].get("retry") == "http")
        check(ok_big, "a >900 KB reply reaches the phone whole or as retry:http - never silence (%s)"
              % ("whole" if r and r[0].get("cipher") else (r[0] if r else "none")))

        # 7. the phone's keepalive
        phone.send("ping")
        time.sleep(1.0)
        check("pong" in phone.msgs, "the phone's text 'ping' is answered 'pong' by the runtime")

        other.close()
        phone.close()
    finally:
        rc._stop = True
        t.join(10)
        rc._stop = False
        rc._cfg = real_cfg

    idle_keepalive_does_not_wake()
    print("\n%d FAIL" % len(_fails) if _fails else "\nall ok")
    return 1 if _fails else 0


def _spans(name):
    """How many times the runtime has invoked the Durable Object for this kind
    of event - read from workerd's own trace store, not inferred."""
    body = json.dumps({"sql": "SELECT count(*) FROM spans WHERE name = '%s'" % name}).encode()
    r = urllib.request.Request(BASE + "/cdn-cgi/local/explorer/api/local/observability/query",
                               data=body, headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(r, timeout=10).read())["result"]["rows"][0][0]


def idle_keepalive_does_not_wake():
    """8. THE PASEO PROOF (packages/relay/src/cloudflare-adapter.ts:197-200: they
    moved off app-level pings after those woke the DO, and assert it in an idle
    e2e test). An idle room with BOTH keepalives running - the daemon's
    protocol ping and the phone's text "ping" - must cause ZERO object
    invocations. `hibernatableWebSocket` is the span the runtime records for
    every socket event it delivers to the object."""
    try:
        _spans("hibernatableWebSocket")
    except Exception:                                        # noqa: BLE001
        print("  (skip) idle proof - no trace store at %s" % BASE)
        return
    from websockets.sync.client import connect
    room = "idle" + uuid.uuid4().hex[:10]
    _, pub = keypair()
    daemon = connect("%s/tunnel/ws?room=%s" % (WSBASE, room), open_timeout=10,
                     ping_interval=1.0, ping_timeout=5)      # protocol ping every second
    phone = Phone(pub, room=room)
    time.sleep(2.0)                                          # let the join announcement settle
    before = _spans("hibernatableWebSocket")
    for _ in range(8):                                       # ~8 protocol + 8 text pings
        phone.send("ping")
        time.sleep(1.0)
    after_idle = _spans("hibernatableWebSocket")
    pongs = phone.msgs.count("pong")
    check(pongs >= 6, "the phone got its pongs while idle (%d/8)" % pongs)
    check(after_idle == before,
          "IDLE: 8 s of keepalives on both ends -> %d object invocation(s), must be 0"
          % (after_idle - before))
    # positive control: the measurement CAN see an invocation
    phone.send({"kind": "req", "id": "ctl", "cipher": "x"})
    time.sleep(1.5)
    check(_spans("hibernatableWebSocket") > after_idle,
          "control: one real message DOES show up as an invocation (the counter works)")
    phone.close()
    daemon.close()


if __name__ == "__main__":
    sys.exit(main())
