# -*- coding: utf-8 -*-
"""The KEY-LESS Rust relay bridge (surfaces/relay/bridge-rs) against the REAL relay worker and the
REAL Python daemon half (spine/comms/relay_client._pipe_session / _serve_one / _deliver).

A throw-away room and pipe name, a stub HTTP "daemon" on loopback, a simulated phone speaking the
wire with PyNaCl. The daemon half runs as a SUBPROCESS so it can be killed like a crashed daemon.
Nothing of the live daemon, its db, its room or its keys is touched.

  1. the bridge dials nothing until a daemon says hello; then a phone request is answered
     (GET, unicode POST, a 1.3 MB reply via /tunnel/push, the daemon's own 404);
  2. admission is the DAEMON's decision: an unpinned key gets 409 sealed to itself, and after the
     daemon opens its pairing window the same key is served - the bridge never knew either way;
  3. a forged frame gets no answer and serving continues;
  4. the daemon is KILLED while a phone request is in flight: the bridge holds the frame, a new
     daemon attaches, the request is answered (the point of the whole exercise);
  5. a phone joining the room reaches the daemon (client announce) and gets its event back;
  6. a daemon that stays away longer than the grace window: the bridge closes the room socket and
     the worker answers phones with its own 503;
  7. the pipes carry an owner-only DACL (read back from the kernel), and a second bridge on the
     same name is refused;
  8. 8 phones x 20 requests at once: all 160 answered correctly.

Needs the release build (cd surfaces/relay/bridge-rs && cargo build --release) and the internet
(the worker). Skips, loudly, when either is missing.
Run: py -3.12 ops/tests/test_relay_bridge_rs_e2e.py
"""
import base64
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from nacl.public import Box, PrivateKey                     # noqa: E402

EXE = os.path.join(ROOT, "surfaces", "relay", "bridge-rs", "target", "release", "helmdeck-relay-bridge.exe")
RELAY = os.environ.get("HELMDECK_TEST_RELAY", "https://relay.helmdeck.de")
BIG = 1_300_000
GRACE = 6
NO_WINDOW = 0x08000000

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


# ------------------------------------------------------------------ the daemon half (subprocess)

def daemon_main(room, port, sk_b64, pins, pipe, window_file):
    """What the real daemon runs in pipe mode, with config injected instead of read from its db."""
    from spine.comms import relay_client as rc
    from spine.comms import e2ee
    from spine.storage import events
    events.log = lambda *a, **k: None                        # never write the live db
    pinned = [p for p in pins.split(",") if p]
    rc._cfg = lambda: (RELAY, room, sk_b64, pinned)
    rc.pipe_base = lambda: pipe

    def admit(pub):
        if pub in pinned:
            return True, ""
        if os.path.exists(window_file):                      # the pairing window is open: pin it
            pinned.append(pub)
            return True, ""
        return False, "this device is not paired with the workspace"
    rc._admit = admit

    class Events:                                            # the real one waits on the live db
        def __init__(self, sk, send_obj):
            self.sk, self.send_obj = sk, send_obj

        def start(self):
            pass

        def stop(self):
            pass

        def announce(self, pub):
            c = e2ee.seal_b64(json.dumps({"v": 7, "c": 9}).encode(), e2ee.import_sec(self.sk), e2ee.import_pub(pub))
            self.send_obj({"kind": "event", "to": pub, "cipher": c})
    rc._EventPublisher = Events
    while True:
        try:
            rc._pipe_session(RELAY, room, sk_b64, port)
        except rc._PipeAbsent:
            time.sleep(0.3)
        time.sleep(0.2)


class Stub(BaseHTTPRequestHandler):
    """What the real daemon would answer on loopback."""
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


def sddl_of_pipe(name):
    """The DACL the kernel holds for \\\\.\\pipe\\<name>, as SDDL."""
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    kern = ctypes.WinDLL("kernel32", use_last_error=True)
    pdacl, psd, pstr = ctypes.c_void_p(), ctypes.c_void_p(), wintypes.LPWSTR()
    adv.GetNamedSecurityInfoW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p,
                                          ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    rc = adv.GetNamedSecurityInfoW("\\\\.\\pipe\\" + name, 6, 4, None, None, ctypes.byref(pdacl), None, ctypes.byref(psd))
    if rc != 0:
        return "ERR%d" % rc
    adv.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.LPWSTR), ctypes.c_void_p]
    adv.ConvertSecurityDescriptorToStringSecurityDescriptorW(psd, 1, 4, ctypes.byref(pstr), None)
    out = pstr.value
    kern.LocalFree(psd)
    return out


def start_bridge(pipe, grace, run_for=240):
    p = subprocess.Popen([EXE, "--pipe", pipe, "--grace", str(grace), "--run-for", str(run_for)],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=NO_WINDOW)
    lines = []
    threading.Thread(target=lambda: [lines.append(ln.strip()) for ln in p.stdout], daemon=True).start()
    return p, lines


def start_daemon(room, port, sk_b64, pins, pipe, window_file):
    return subprocess.Popen([sys.executable, os.path.abspath(__file__), "--daemon", room, str(port), sk_b64, pins, pipe, window_file],
                            cwd=ROOT, creationflags=NO_WINDOW, stdout=subprocess.DEVNULL, stderr=(None if os.environ.get("HD_DEBUG") else subprocess.DEVNULL))


def wait_for(pred, timeout):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.1)
    return False


def main():
    if not os.path.isfile(EXE):
        print("SKIP: no release build at", EXE)
        return 0
    try:
        urllib.request.urlopen(urllib.request.Request(RELAY + "/health", headers={"User-Agent": "helmdeck-test"}), timeout=8)
    except Exception as e:                                   # noqa: BLE001
        print("SKIP: relay unreachable (%s)" % e)
        return 0

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    d_sk, p_sk, s_sk = PrivateKey.generate(), PrivateKey.generate(), PrivateKey.generate()
    d_b64, p_pub, s_pub = b64(bytes(d_sk)), b64(bytes(p_sk.public_key)), b64(bytes(s_sk.public_key))
    dpk = d_sk.public_key
    room = "hdtest-" + uuid.uuid4().hex[:16]
    pipe = "hd-bridge-test-" + uuid.uuid4().hex[:8]
    window = os.path.join(tempfile.mkdtemp(prefix="hd-pair-"), "window")
    procs = []

    bridge, blog = start_bridge(pipe, GRACE)
    procs.append(bridge)
    try:
        check(wait_for(lambda: any("bridge up" in l for l in blog), 10), "the bridge is up and listening on its pipes")
        time.sleep(2.0)
        check(not any("websocket" in l for l in blog), "...and dials NOTHING until a daemon says hello")

        # --- the DACL, read back from the kernel (on a SEPARATE bridge so the probe cannot attach)
        probe_pipe = pipe + "-acl"
        pb, plog = start_bridge(probe_pipe, 5, run_for=30)
        procs.append(pb)
        wait_for(lambda: any("bridge up" in l for l in plog), 10)
        for suffix in (".rx", ".tx"):
            sd = sddl_of_pipe(probe_pipe + suffix)
            check(sd.startswith("D:P(A;;GA;;;S-1-5-") and sd.count("(A;") == 1 and "WD" not in sd and "AN" not in sd and "BU" not in sd,
                  "pipe %s carries a protected, one-ACE, current-user-only DACL: %s" % (suffix, sd))
        dup = subprocess.run([EXE, "--pipe", probe_pipe, "--run-for", "2"], capture_output=True, text=True, creationflags=NO_WINDOW, timeout=20)
        check(dup.returncode == 3, "a second bridge on the same pipe name is refused (exit %d)" % dup.returncode)
        pb.kill()

        # --- a daemon attaches
        daemon = start_daemon(room, port, d_b64, p_pub, pipe, window)
        procs.append(daemon)
        check(wait_for(lambda: any("transport: websocket" in l for l in blog), 40), "after the daemon's hello the bridge connects its WebSocket to the room")
        check(any("daemon attached" in l for l in blog), "...and logs the attach")
        time.sleep(1.0)

        r = phone_call(room, p_sk, p_pub, dpk, "GET", "/ping?x=1")
        check(r["status"] == 200 and json.loads(r["body"]) == {"ok": True, "path": "/ping?x=1"}, "GET: served by the daemon half through the pipe, sealed back")
        text = "Grüße, 日本語, \"quotes\" und\nZeilenumbruch"
        r = phone_call(room, p_sk, p_pub, dpk, "POST", "/echo", body=text, headers={"X-Phone": "ja"})
        e = json.loads(r["body"])
        check(r["status"] == 200 and e["echo"] == text and e["xh"] == "ja", "POST: a unicode body and a header travel intact")
        r = phone_call(room, p_sk, p_pub, dpk, "GET", "/big", timeout=60)
        check(r["status"] == 200 and len(r["body"]) == BIG, "a %.1f MB reply (over the socket limit) arrives via /tunnel/push" % (BIG / 1e6))
        r = phone_call(room, p_sk, p_pub, dpk, "GET", "/missing")
        check(r["status"] == 404, "the daemon's own error status passes through (404)")

        # --- admission is the daemon's call
        r = phone_call(room, s_sk, s_pub, dpk, "GET", "/ping")
        check(r["status"] == 409 and "not paired" in r["body"], "an UNPINNED key is answered 'not paired' BY THE DAEMON, sealed to itself")
        open(window, "w").close()
        r = phone_call(room, s_sk, s_pub, dpk, "GET", "/ping?paired=1")
        check(r["status"] == 200, "...and once the daemon opens its pairing window the same key is served (the bridge never knew)")
        os.remove(window)

        forged = json.dumps({"pub": p_pub, "cipher": seal(b'{"method":"GET","path":"/ping"}', PrivateKey.generate(), dpk)}).encode()
        got = "reply"
        try:
            urllib.request.urlopen(urllib.request.Request("%s/relay?room=%s" % (RELAY, room), data=forged,
                                                          headers={"Content-Type": "application/json", "User-Agent": "helmdeck-test"}), timeout=6)
        except Exception:                                    # noqa: BLE001
            got = "silence"
        check(got == "silence", "a forged frame gets NO answer")
        check(phone_call(room, p_sk, p_pub, dpk, "GET", "/ping?after=forged")["status"] == 200, "...and serving continues")

        # --- a phone joins: client announce -> daemon -> event back
        from websockets.sync.client import connect
        got_ev = []
        ws = connect("%s/tunnel/client?room=%s&pub=%s" % (RELAY.replace("https://", "wss://").replace("http://", "ws://"), room,
                                                         urllib.request.quote(p_pub, safe="")), ping_interval=None, open_timeout=10)

        def rx():
            try:
                for m in ws:
                    if isinstance(m, str) and m != "pong":
                        got_ev.append(json.loads(m))
            except Exception:                                # noqa: BLE001
                pass
        threading.Thread(target=rx, daemon=True).start()

        def event_ok():
            for m in got_ev:
                if m.get("cipher"):
                    try:
                        return json.loads(open_(m["cipher"], p_sk, dpk)) == {"v": 7, "c": 9}
                    except Exception:                        # noqa: BLE001
                        pass
            return False
        check(wait_for(event_ok, 15), "a joining phone is announced to the daemon and gets its event back through the pipe")
        ws.close()

        # --- THE POINT: the daemon dies while a request is in flight
        daemon.kill()
        daemon.wait()
        check(wait_for(lambda: any("daemon detached" in l for l in blog), 10), "the bridge notices the daemon is gone")
        res = {}

        def held():
            t = time.time()
            try:
                res["r"] = phone_call(room, p_sk, p_pub, dpk, "GET", "/ping?held=1", timeout=60)
            except Exception as ex:                          # noqa: BLE001
                res["r"] = repr(ex)
            res["dt"] = time.time() - t
        th = threading.Thread(target=held)
        th.start()
        time.sleep(3.0)
        check(th.is_alive(), "a request that arrives while the daemon is away is HELD (not failed)")
        daemon = start_daemon(room, port, d_b64, p_pub, pipe, window)
        procs.append(daemon)
        th.join(40)
        ok = isinstance(res.get("r"), dict) and res["r"].get("status") == 200 and json.loads(res["r"]["body"])["path"] == "/ping?held=1"
        check(ok, "...and answered after the new daemon attached (%.1f s)%s" % (res.get("dt", -1), "" if ok else " got %r" % (res.get("r"),)))

        # --- gone for good: socket closes after the grace window, the worker speaks for itself
        daemon.kill()
        daemon.wait()
        time.sleep(GRACE + 4)
        check(any("bridge socket closed" in l for l in blog), "past the grace window the bridge closes the room socket")
        try:
            phone_call(room, p_sk, p_pub, dpk, "GET", "/ping", timeout=20)
            msg = "answered?!"
        except urllib.error.HTTPError as ex:
            msg = "HTTP %d" % ex.code
        except Exception as ex:                              # noqa: BLE001
            msg = repr(ex)
        check(msg.startswith("HTTP 503") or msg.startswith("HTTP 502"), "...so the worker answers phones itself: %s" % msg)

        # --- it comes back: a daemon returns after the long absence, the bridge redials from its hello
        daemon = start_daemon(room, port, d_b64, p_pub, pipe, window)
        procs.append(daemon)
        time.sleep(0.5)
        t0 = time.time()
        ok2 = False
        while time.time() - t0 < 40:
            try:
                ok2 = phone_call(room, p_sk, p_pub, dpk, "GET", "/ping?back=1", timeout=10)["status"] == 200
                if ok2:
                    break
            except Exception:                                # noqa: BLE001
                time.sleep(1)
        check(ok2, "a daemon that returns after the grace window is served again (%.1f s)" % (time.time() - t0))

        # --- load
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
        for p in procs:
            try:
                p.kill()
            except Exception:                                # noqa: BLE001
                pass
        srv.shutdown()
        if _fails:
            print("\n".join(blog[-25:]))
    print()
    if _fails:
        print("=== %d FAILED ===" % len(_fails))
        return 1
    print("relay-bridge-rs e2e: PASS")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--daemon":
        daemon_main(*sys.argv[2:7], sys.argv[7])
    else:
        sys.exit(main())
