# -*- coding: utf-8 -*-
"""A flood of phone frames must not become a flood of daemon threads.

2026-09-25 13:00, owner: "Wieder tot". The daemon had 1,504 threads, 4.8 GB
and the machine sat at 100 % CPU: pushed events made the app refetch
everything several times a second, abandoning each running request - which
the daemon still served to its 115 s timeout, one new thread per frame. The
slower it got, the more piled up.

This runs the REAL relay_client._ws_session against a local websocket
server that fires 300 frames at once; each serve takes 3 s. Old code: ~300
extra threads. Fixed: never more than SERVE_WORKERS extra, and every frame
is still answered.

    py -3.12 ops/tests/test_relay_serve_pool.py
"""
import json
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from websockets.sync.server import serve

from spine.comms import e2ee
from spine.comms import relay_client as rc
from spine.storage import events

N = 300
_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def main():
    replies = []

    def handler(ws):
        for i in range(N):
            ws.send(json.dumps({"kind": "frame", "id": "f%d" % i, "pub": "p", "cipher": "c", "t": time.time()}))
        try:
            while len(replies) < N:
                m = json.loads(ws.recv(timeout=60))
                if m.get("kind") == "reply":
                    replies.append(m["id"])
        except Exception:
            pass

    srv = serve(handler, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.socket.getsockname()[1]

    def slow_serve(relay, room, sk, p, data, send=None):
        time.sleep(3)
        send(data["id"], "ok", to="p")

    sk, _ = e2ee.generate_keypair()
    real = (rc._cfg, events.log)
    rc._cfg = lambda: ("http://127.0.0.1:%d" % port, "pool", e2ee.export_sec(sk), [])
    events.log = lambda *a, **k: None                     # never the live db
    base = threading.active_count()
    peak = [base]
    rc._stop = False
    t = threading.Thread(target=lambda: rc._ws_session("http://127.0.0.1:%d" % port, "pool",
                                                       e2ee.export_sec(sk), 1, serve=slow_serve), daemon=True)
    t.start()
    end = time.time() + 120
    while len(replies) < N and time.time() < end:
        peak[0] = max(peak[0], threading.active_count())
        time.sleep(0.05)
    rc._stop = True
    t.join(10)
    rc._stop = False
    rc._cfg, events.log = real
    srv.shutdown()

    extra = peak[0] - base
    limit = getattr(rc, "SERVE_WORKERS", 0) + 12      # + the session's own few threads
    print("   %d frames, peak extra threads %d (pool %s)" % (N, extra, getattr(rc, "SERVE_WORKERS", "none")))
    check(extra <= limit, "a flood of %d frames stays within the serve pool (+%d threads, limit %d)" % (N, extra, limit))
    check(len(set(replies)) == N, "every frame is still answered (%d/%d)" % (len(set(replies)), N))
    print("\n%d FAIL" % len(_fails) if _fails else "\nall ok")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
