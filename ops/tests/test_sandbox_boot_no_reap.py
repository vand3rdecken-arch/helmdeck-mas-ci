# -*- coding: utf-8 -*-
"""A SANDBOX boot of serve() must not reap the live daemon's processes.

serve() runs three reapers at boot (drivers.reap_orphans, wincap.reap_orphans,
copilot.reap_chat_ports). Each reads a pid/port table under daemon/state/ and
kills whatever is listed. Those tables belong to the LIVE daemon, so a harness
that boots a real server against a sandbox (e2e_lane_http.py) killed a card's
own claude and Henry's chat port (measured 2026-09-25). serve() now reaps only
when it owns DAEMON_ROOT (db.DBPATH lives there).

Stand-in for "the live table": temp files bound to proctable._PIDFILE and
copilot._PORTS_FILE. The victim is a dummy sleeper THIS test spawns - never a
real card process. Step 1 proves the setup is armed (the reaper DOES kill the
dummy when called directly); step 2 boots serve() against a sandbox db and
requires the dummy to survive. On the old code step 2 is red.

Run:  py -3.12 ops/tests/test_sandbox_boot_no_reap.py
"""
import json, os, socket, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

SANDBOX = tempfile.mkdtemp(prefix="helmdeck-noreap-")
from spine.storage import db, events
from spine.auth import auth
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
db._LEGACY_DB = os.path.join(SANDBOX, "legacy.db")
events.SET = os.path.join(SANDBOX, "settings.json")
auth.USERS = os.path.join(SANDBOX, "users.json")
db.init(role="tool")

from spine.agent import proctable, drivers
from cells.copilot.chat import copilot
from spine.http import server, startup

startup._DAEMON_ROOT = SANDBOX                    # singleton pidfile, not the live one
proctable._PIDFILE = os.path.join(SANDBOX, "driver_pids.json")
copilot._PORTS_FILE = os.path.join(SANDBOX, "chat_ports.json")
copilot.prewarm = lambda *a, **k: None            # no real claude in a test
copilot._start_keepalive_loop = lambda *a, **k: None

fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        fails.append(msg)


def dummy():
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    time.sleep(0.5)
    return p, time.time()


def alive(p):
    return p.poll() is None


procs = []
try:
    # 1. armed: the reaper really kills a listed, ours-by-start-time process
    p1, t1 = dummy(); procs.append(p1)
    proctable._record_pid(p1.pid, t1)
    drivers.reap_orphans()
    time.sleep(1)
    check(not alive(p1), "control: drivers.reap_orphans() kills a listed dummy (the test is armed)")

    # 2. a sandbox serve() boot leaves both tables' processes alone
    p2, t2 = dummy(); procs.append(p2)
    p3, t3 = dummy(); procs.append(p3)
    proctable._record_pid(p2.pid, t2)
    with open(copilot._PORTS_FILE, "w") as f:
        json.dump({str(p3.pid): t3}, f)
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    threading.Thread(target=lambda: server.serve(port), daemon=True).start()
    time.sleep(8)                                   # reapers run at boot, chat one after 3s
    check(alive(p2), "sandbox serve() left the driver-table process alive")
    check(alive(p3), "sandbox serve() left the chat-port process alive")
    check(json.load(open(proctable._PIDFILE)).get(str(p2.pid)) is not None,
          "and did not wipe the driver table")
finally:
    for p in procs:
        if alive(p):
            p.kill()

if fails:
    print("FAILED (%d)" % len(fails))
    sys.exit(1)
print("all checks passed")
os._exit(0)                                         # the serve() thread never returns
