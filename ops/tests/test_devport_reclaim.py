# -*- coding: utf-8 -*-
"""A finished card's dev-port listener dies with the card.

Found live 2026-09-19: `expo start --web --port 3891` of a card accepted the
day before ran on for three days (63 CPU-hours). Spawns a REAL listener on a
free port, hands a track with that dev_port to the real reclaim, and checks
the process is gone. Run: py -3.12 ops/tests/test_devport_reclaim.py
"""
import os, socket, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from cells.engineer.cards import devport

s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
srv = subprocess.Popen([sys.executable, "-c",
    "import socket,time; s=socket.socket(); s.bind(('127.0.0.1',%d)); s.listen(); time.sleep(120)" % port])
deadline = time.time() + 10
while time.time() < deadline and srv.pid not in devport._listeners_on(port):
    time.sleep(0.2)

fails = 0
def check(cond, msg):
    global fails
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails += 1

check(srv.pid in devport._listeners_on(port), "listener found on the card's port (pid %d)" % srv.pid)
check(devport.reclaim_dev_port({"id": "t", "dev_port": None}) == [], "a card without a port kills nothing")
killed = devport.reclaim_dev_port({"id": "t", "dev_port": port})
try:
    srv.wait(timeout=5); alive = False
except subprocess.TimeoutExpired:
    alive = True; srv.kill()
check(srv.pid in killed and not alive, "reclaim killed the listener (killed=%s)" % killed)
check(devport._listeners_on(port) == set(), "port is free again")
print("RESULT:", "PASS" if not fails else "FAIL (%d)" % fails)
sys.exit(1 if fails else 0)
