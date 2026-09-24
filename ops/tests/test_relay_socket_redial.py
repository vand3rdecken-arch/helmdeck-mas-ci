# -*- coding: utf-8 -*-
"""An ESTABLISHED bridge socket that drops must redial at once - every time.

Owner 2026-09-24 15:19: "Desktop offline error. again". The relay (Cloudflare)
closes long-lived sockets now and then; that is normal. The bridge loop
counted each such drop as one more FAILED attempt and never reset the count
while a socket was up, so the backoff grew with every drop of the day
(3 -> 6 -> 12 -> 24 -> 48 -> 60 s) - and for that long the room had no daemon
and the phone said "Desktop offline". Only every 10th drop was logged.

This runs the REAL relay_client._loop against a local websocket server that
accepts the daemon's /tunnel/ws and closes each connection after 0.3 s, and
measures the gap between one close and the next connect. Old code: the gaps
double. Fixed: every gap stays under 2 s, and every drop is logged.

    py -3.12 ops/tests/test_relay_socket_redial.py
"""
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

DROPS = 5
_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def run(life_s, stable_s, want):
    """Real _loop against a server closing every socket after `life_s`;
    returns (gaps between a close and the next connect, logged messages)."""
    opened, closed = [], []

    def handler(ws):
        opened.append(time.time())
        time.sleep(life_s)
        ws.close(1012, "edge restart")          # what Cloudflare does now and then
        closed.append(time.time())

    srv = serve(handler, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.socket.getsockname()[1]

    logged = []
    sk, _ = e2ee.generate_keypair()
    real = (rc._cfg, rc._resolve_base, events.log)
    rc._cfg = lambda: ("http://127.0.0.1:%d" % port, "redialtest", e2ee.export_sec(sk), [])
    rc._resolve_base = lambda relay: relay
    events.log = lambda kind, msg, *a, **k: logged.append(msg)   # never the live db
    real_stable = rc.WS_STABLE_S
    rc.WS_STABLE_S = stable_s
    rc._stop = False
    rc._ws_state["unsupported_until"] = 0
    rc._ws_state["fails"] = 0
    t = threading.Thread(target=rc._loop, args=(1,), daemon=True)
    t.start()
    try:
        deadline = time.time() + 60
        while len(opened) < want and time.time() < deadline:
            time.sleep(0.1)
    finally:
        rc._stop = True
        t.join(10)
        rc._stop = False
        rc._cfg, rc._resolve_base, events.log = real
        rc.WS_STABLE_S = real_stable
        srv.shutdown()
    return [round(opened[i + 1] - closed[i], 2) for i in range(min(len(opened) - 1, len(closed)))], logged


def main():
    # 1. a socket that WAS established (lived past WS_STABLE_S) and drops
    gaps, logged = run(0.4, 0.2, DROPS + 1)
    print("   established socket - reconnect gaps after each drop (s):", gaps)
    check(len(gaps) >= DROPS, "%d drops each followed by a reconnect (got %d)"
          % (DROPS, len(gaps)))
    check(gaps and max(gaps) < 2.0,
          "every redial after a drop is quick - no growing backoff (max %.2fs)" % (max(gaps) if gaps else -1))
    drops = [m for m in logged if "socket dropped" in m]
    check(len(drops) >= DROPS, "every drop is logged with its reason (%d logged): %s"
          % (len(drops), drops[:1]))
    check(not any("bridge unreachable" in m for m in logged),
          "a drop of an established socket is not reported as 'unreachable'")

    # 2. a relay that closes EVERY socket at once must not be hammered at 2/s
    #    (each dial is a billed Worker request - the 2026-09-23 429 lesson)
    gaps, logged = run(0.1, 10.0, 3)
    print("   instantly-closing relay - gaps (s):", gaps)
    check(len(gaps) >= 2 and gaps[1] > gaps[0] >= 2.5,
          "a socket that never became stable stays on the growing backoff (%s)" % gaps)
    print("\n%d FAIL" % len(_fails) if _fails else "\nall ok")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
