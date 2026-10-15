# -*- coding: utf-8 -*-
"""A/B: the Python relay bridge (spine/comms/relay_client.py) against the Rust one
(surfaces/relay/bridge-rs), same throw-away rooms on the REAL relay worker, same stub
daemon on loopback, same simulated phones. Prints latency percentiles, memory, threads
and CPU per bridge. Touches nothing of the live daemon (sandbox db for the Python side).

  py -3.12 ops/tools/bench_relay_bridge.py [requests-per-phone=40] [phones=8]
"""
import base64
import ctypes
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from nacl.public import Box, PrivateKey             # noqa: E402

EXE = os.path.join(ROOT, "surfaces", "relay", "bridge-rs", "target", "release", "helmdeck-relay-bridge.exe")
RELAY = "https://relay.helmdeck.de"


def b64(raw):
    return base64.b64encode(raw).decode()


class Daemon(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        data = json.dumps({"ok": True, "path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t)]


def proc_stats(pid=None):
    """(private MB, cpu seconds, threads) of a pid, or of this process."""
    k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    k32.OpenProcess.restype = wintypes.HANDLE
    h = k32.GetCurrentProcess() if pid is None else k32.OpenProcess(0x1000 | 0x0400, False, pid)
    pmc = PMC()
    pmc.cb = ctypes.sizeof(PMC)
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
    psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb)
    ft = [wintypes.FILETIME() for _ in range(4)]
    k32.GetProcessTimes(h, *[ctypes.byref(f) for f in ft])
    cpu = sum(((f.dwHighDateTime << 32) | f.dwLowDateTime) / 1e7 for f in ft[2:])
    return pmc.PrivateUsage / 1e6, cpu


def phone_call(room, p_sk, p_pub, d_pk, path):
    inner = json.dumps({"method": "GET", "path": path, "headers": {}, "body": ""}).encode()
    payload = json.dumps({"pub": p_pub, "cipher": b64(bytes(Box(p_sk, d_pk).encrypt(inner)))}).encode()
    req = urllib.request.Request("%s/relay?room=%s" % (RELAY, room), data=payload,
                                 headers={"Content-Type": "application/json", "User-Agent": "helmdeck-bench"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    return json.loads(Box(p_sk, d_pk).decrypt(base64.b64decode(data["cipher"])))


def battery(room, p_sk, p_pub, d_pk, phones, per):
    lat, bad = [], []

    def phone(i):
        for k in range(per):
            t = time.time()
            try:
                r = phone_call(room, p_sk, p_pub, d_pk, "/ping?c=%d-%d" % (i, k))
                if r["status"] != 200:
                    bad.append(r)
            except Exception as e:                          # noqa: BLE001
                bad.append(repr(e))
            lat.append(time.time() - t)
    ts = [threading.Thread(target=phone, args=(i,)) for i in range(phones)]
    t0 = time.time()
    [t.start() for t in ts]
    [t.join() for t in ts]
    return sorted(lat), time.time() - t0, bad


PS = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"


def thread_count(pid):
    r = subprocess.run([PS, "-NoProfile", "-Command", "(Get-Process -Id %d).Threads.Count" % pid],
                       capture_output=True, text=True, creationflags=0x08000000)
    return int((r.stdout or "0").strip() or 0)


PY_RUNNER = """
import sys, os, tempfile
sys.path.insert(0, sys.argv[1])
from spine.storage import db, events
from spine.comms import relay_client
relay, room, sk, pub, port = sys.argv[2:7]
db.DBPATH = os.path.join(tempfile.mkdtemp(prefix='hd-bench-'), 'helmdeck.db')
db.init()
events.SET = os.path.join(os.path.dirname(db.DBPATH), 'settings.json')
events.save_settings({'relay': {'url': relay, 'room': room, 'sk': sk, 'phone_pub': pub, 'phone_pubs': [pub]}})
relay_client._ws_session(relay, room, sk, int(port))
"""


def run(kind, port, phones, per):
    d_sk, p_sk = PrivateKey.generate(), PrivateKey.generate()
    p_pub = b64(bytes(p_sk.public_key))
    room = "hdbench-" + uuid.uuid4().hex[:14]
    if kind == "rust":
        cmd = [EXE, "--relay", RELAY, "--room", room, "--sk", b64(bytes(d_sk)), "--pubs", p_pub,
               "--port", str(port), "--run-for", "300"]
    else:
        cmd = [sys.executable, "-c", PY_RUNNER, ROOT, RELAY, room, b64(bytes(d_sk)), p_pub, str(port)]
    handle = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x08000000)
    try:
        time.sleep(4.0)                                       # connect + the room registers the daemon socket
        battery(room, p_sk, p_pub, d_sk.public_key, 2, 3)     # warm up
        mem0, cpu0 = proc_stats(handle.pid)
        lat, total, bad = battery(room, p_sk, p_pub, d_sk.public_key, phones, per)
        mem1, cpu1 = proc_stats(handle.pid)
        threads = thread_count(handle.pid)
    finally:
        handle.kill()
    n = len(lat)
    return {"kind": kind, "n": n, "bad": bad, "p50": lat[n // 2] * 1000, "p95": lat[int(n * .95)] * 1000,
            "max": lat[-1] * 1000, "rps": n / total, "mem": mem1, "cpu_per_1k": (cpu1 - cpu0) / n * 1000,
            "threads": threads}


if __name__ == "__main__":
    per = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    phones = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Daemon)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    rows = [run("python", port, phones, per), run("rust", port, phones, per), run("python", port, phones, per), run("rust", port, phones, per)]
    srv.shutdown()
    print("%d phones x %d requests each, through the real relay worker (internet round trip included); each bridge in its OWN process\n" % (phones, per))
    print("%-8s %6s %4s %8s %8s %9s %7s %11s %13s %8s" % ("bridge", "reqs", "bad", "p50 ms", "p95 ms", "max ms", "req/s", "private MB", "CPU s/1k req", "threads"))
    for r in rows:
        print("%-8s %6d %4d %8.0f %8.0f %9.0f %7.1f %11.1f %13.2f %8d" % (
            r["kind"], r["n"], len(r["bad"]), r["p50"], r["p95"], r["max"], r["rps"], r["mem"], r["cpu_per_1k"], r["threads"]))
        for b in r["bad"][:2]:
            print("          bad request:", str(b)[:160])
