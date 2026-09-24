# -*- coding: utf-8 -*-
"""The relay ROOM owns daemon liveness - real worker code in local workerd,
the real daemon session (relay_client._ws_session) on one side, a phone
socket on the other.

Owner 2026-09-24 21:3x: "Sollte das Handy das System nicht anpingen, warum
hat das nicht geklappt, wer ist der Handler" -> "wenn weg, dann muss Handy
bzw. Relay den PC wecken koennen". The phone's "ping" is answered by the
relay runtime, so it proved phone<->relay and nothing about the PC; at 21:17
the daemon's socket died WITHOUT a close frame and the room kept writing into
it. Paseo's relay (cloudflare-adapter.ts nudgeOrResetControlForConnection)
probes and force-closes such a socket; so does the room now. Proven here:

  1. presence: a phone learns "PC up" on join and "PC down"/"up" on change;
  2. hold: a request sent while the daemon redials is answered, not 503'd;
  3. half-open: a daemon socket that accepts writes but never reads is
     probed, closed by the ROOM, and the stuck request reaches the redialed
     daemon (the case of 2026-09-24 21:17);
  4. no comeback: held requests get an honest 503 once the grace is over;
  5. a SLOW but live daemon answers the probe and is NOT reset.

    cd surfaces/relay/worker && npx wrangler dev --local --port 8799 --ip 127.0.0.1
    py -3.12 ops/tests/test_relay_liveness.py
Skips (exit 0) when no worker is running.
"""
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
from websockets.sync.client import connect

from spine.comms import e2ee
from spine.comms import relay_client as rc
from spine.storage import events

BASE = os.environ.get("HELMDECK_WS_TEST_URL", "http://127.0.0.1:8799").rstrip("/")
WSBASE = BASE.replace("http://", "ws://")
_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


class Phone:
    """A phone socket: collects everything the room sends it."""

    def __init__(self, room, pub):
        self.ws = connect("%s/tunnel/client?room=%s&pub=%s" % (WSBASE, room, urllib.request.quote(pub, safe="")),
                          open_timeout=10)
        self.msgs = []
        self.lock = threading.RLock()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            while True:
                m = self.ws.recv()
                if m == "pong":
                    continue
                with self.lock:
                    self.msgs.append((time.time(), json.loads(m)))
        except Exception:
            pass

    def req(self, rid):
        self.ws.send(json.dumps({"kind": "req", "id": rid, "cipher": "c-" + rid}))
        return time.time()

    def wait(self, pred, timeout):
        end = time.time() + timeout
        while time.time() < end:
            with self.lock:
                for t, m in self.msgs:
                    if pred(m):
                        return t, m
            time.sleep(0.05)
        return None, None

    def daemon_states(self):
        with self.lock:
            return [m["up"] for _, m in self.msgs if m.get("kind") == "daemon"]

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


class Daemon:
    """The REAL relay_client._ws_session; `serve` answers every frame after
    `delay` seconds with a reply addressed to the phone."""

    def __init__(self, room, sk, delay=0.0):
        self.frames = []
        self.delay = delay
        self.room, self.sk = room, sk
        self.t = None

    def _serve(self, relay, room, sk, port, data, send=None):
        self.frames.append(data)
        time.sleep(self.delay)
        send(data["id"], "reply-" + data["id"], to=data.get("pub"))

    def start(self):
        rc._stop = False
        self.t = threading.Thread(target=self._run, daemon=True)
        self.t.start()
        time.sleep(1.0)
        return self

    def _run(self):
        try:
            rc._ws_session(BASE, self.room, self.sk, 1, serve=self._serve)
        except Exception:
            pass

    def stop(self):
        rc._stop = True               # _ws_session returns within its 5 s recv tick
        self.t.join(10)
        rc._stop = False


def main():
    try:
        urllib.request.urlopen(BASE + "/health", timeout=3)
    except Exception:
        print("SKIP - no worker at %s (start wrangler dev, see docstring)" % BASE)
        return 0
    sk, _ = e2ee.generate_keypair()
    SK = e2ee.export_sec(sk)
    _, ppk = e2ee.generate_keypair()
    PUB = e2ee.export_pub(ppk)
    real = (rc._cfg, events.log)
    events.log = lambda *a, **k: None                    # never the live db
    try:
        # ---- 1. presence ---------------------------------------------------
        room = "live" + uuid.uuid4().hex[:10]
        rc._cfg = lambda: (BASE, room, SK, [PUB])
        ph = Phone(room, PUB)
        ph.wait(lambda m: m.get("kind") == "daemon", 3)
        d = Daemon(room, SK).start()
        ph.wait(lambda m: m.get("kind") == "daemon" and m.get("up"), 5)
        d.stop()
        ph.wait(lambda m: m.get("kind") == "daemon" and m.get("up") is False and len(ph.daemon_states()) >= 3, 5)
        states = ph.daemon_states()
        check(states[:3] == [False, True, False],
              "phone learns the PC's presence from the ROOM: join=down, daemon up, daemon gone (%s)" % states)
        ph.close()

        # ---- 2. hold across a redial ---------------------------------------
        room = "hold" + uuid.uuid4().hex[:10]
        rc._cfg = lambda: (BASE, room, SK, [PUB])
        ph = Phone(room, PUB)
        d = Daemon(room, SK).start()
        d.stop()                                         # the daemon drops ...
        t0 = ph.req("r2")                                # ... a request arrives in the gap ...
        time.sleep(2.0)
        d2 = Daemon(room, SK).start()                    # ... the daemon redials
        t, m = ph.wait(lambda m: m.get("kind") == "res" and m.get("id") == "r2", 10)
        check(m is not None and m.get("cipher") == "reply-r2",
              "a request sent while the PC redials is HELD and answered, not 503'd (%s after %.1fs)"
              % (m, (t - t0) if t else -1))
        d2.stop()
        ph.close()

        # ---- 3. half-open daemon socket -> room resets it -------------------
        room = "zomb" + uuid.uuid4().hex[:10]
        rc._cfg = lambda: (BASE, room, SK, [PUB])
        zombie = connect("%s/tunnel/ws?room=%s" % (WSBASE, room), open_timeout=10)   # accepts writes, never reads
        ph = Phone(room, PUB)
        ph.wait(lambda m: m.get("kind") == "daemon" and m.get("up"), 5)
        t0 = ph.req("r3")
        tdown, _ = ph.wait(lambda m: m.get("kind") == "daemon" and m.get("up") is False, 25)
        check(tdown is not None and 11 <= tdown - t0 <= 18,
              "the ROOM detects the half-open daemon socket and closes it (%.1fs after the request)"
              % ((tdown - t0) if tdown else -1))
        closed_by_room = None
        try:
            while True:                     # it still gets the frame and the probe first
                zombie.recv(timeout=20)   # workerd delivers the close ~10 s late
        except Exception as e:                                                     # noqa: BLE001
            closed_by_room = getattr(getattr(e, "rcvd", None), "code", None)
        check(closed_by_room == 1011, "...with close 1011, so the daemon side errors out and redials (%s)" % closed_by_room)
        d3 = Daemon(room, SK).start()
        t, m = ph.wait(lambda m: m.get("kind") == "res" and m.get("id") == "r3", 10)
        check(m is not None and m.get("cipher") == "reply-r3",
              "the request stuck in the dead socket reaches the redialed daemon (%s)" % m)
        d3.stop()
        ph.close()

        # ---- 4. the daemon does not come back -------------------------------
        room = "gone" + uuid.uuid4().hex[:10]
        rc._cfg = lambda: (BASE, room, SK, [PUB])
        ph = Phone(room, PUB)
        d = Daemon(room, SK).start()
        d.stop()
        t0 = ph.req("r4")
        t, m = ph.wait(lambda m: m.get("kind") == "res" and m.get("id") == "r4", 25)
        check(m is not None and m.get("status") == 503 and 12 <= t - t0 <= 18,
              "no comeback: the held request gets an honest 503 when the grace ends (%s after %.1fs)"
              % (m, (t - t0) if t else -1))
        ph.close()

        # ---- 5. slow but alive: probed, NOT reset ---------------------------
        room = "slow" + uuid.uuid4().hex[:10]
        rc._cfg = lambda: (BASE, room, SK, [PUB])
        ph = Phone(room, PUB)
        d = Daemon(room, SK, delay=20.0).start()
        t0 = ph.req("r5")
        t, m = ph.wait(lambda m: m.get("kind") == "res" and m.get("id") == "r5", 30)
        st = ph.daemon_states()
        after_up = st[st.index(True):] if True in st else []
        check(m is not None and m.get("cipher") == "reply-r5" and after_up and False not in after_up,
              "a daemon busy for 20 s answers the probe and is NOT reset (reply after %.1fs, states %s)"
              % ((t - t0) if t else -1, ph.daemon_states()))
        d.stop()
        ph.close()
    finally:
        rc._cfg, events.log = real
        rc._stop = False

    print("\n%d FAIL" % len(_fails) if _fails else "\nall ok")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
