# -*- coding: utf-8 -*-
"""Headless test for the idle resource sweeper (spine/ops/idle_sweep.py).

Real code paths, no mocks: a tiny local HTTP server stands in for the
HelmDeck Chrome's CDP port (so sweep_browser_tabs() makes its REAL
urllib.request close call against a REAL socket), and a REAL bound TCP
listener stands in for a card's dev server (same shape as
test_devport_reclaim.py). Self-sandboxing: temp sqlite DB, temp settings.json,
temp tab-registry file - no daemon, no real Chrome, no network.

Run: py -3.12 ops/tests/test_idle_sweep.py
"""
import http.server
import os
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, DAEMON)

SANDBOX = tempfile.mkdtemp()
# sandboxed for the WHOLE process (not just test_locks_backstop): run_sweep()
# in test_policy_and_summary also calls sweep_locks(), which must never touch
# the real ~/.helmdeck/locks on the machine this test happens to run on.
os.environ["HELMDECK_LOCK_DIR"] = os.path.join(SANDBOX, "locks")

from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from spine.media import browsercap
browsercap._TAB_REGFILE = os.path.join(SANDBOX, "browser_tabs.json")

from spine.ops import idle_sweep

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# ---- a fake CDP endpoint: the ONLY call sweep_browser_tabs ever makes is
# GET /json/close/<id> on the tab's own registered port. Recording every
# request received is what proves an UNregistered target (standing in for
# the owner's own windows-mcp-driven Chrome, which never has a registry
# entry at all) is never even asked about, let alone closed.
class _CDPHandler(http.server.BaseHTTPRequestHandler):
    closed = []

    def do_GET(self):
        if self.path.startswith("/json/close/"):
            _CDPHandler.closed.append(self.path[len("/json/close/"):])
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Target.detachedFromTarget")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a):
        pass


def _dead_pid():
    """A pid that is provably not alive right now."""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait(timeout=10)
    return p.pid


def test_tabs_registry_reclaim():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _CDPHandler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        dead = _dead_pid()
        alive = os.getpid()
        browsercap._write_tab_reg({
            "tab-done": {"pid": dead, "port": port, "run_id": "done-card"},
            "tab-running": {"pid": alive, "port": port, "run_id": "live-card"},
        })
        # a target the fake Chrome holds that HelmDeck never registered at
        # all - stands in for the owner's own browser window.
        _CDPHandler.closed.clear()

        closed = idle_sweep.sweep_browser_tabs()

        closed_ids = {c["target_id"] for c in closed}
        check(closed_ids == {"tab-done"}, "only the dead-owner tab reclaimed (got %r)" % closed_ids)
        check(_CDPHandler.closed == ["tab-done"],
              "exactly one close request reached the CDP port, for the reclaimed tab only")
        reg = browsercap.registered_tabs()
        check("tab-done" not in reg, "closed tab's registration removed")
        check("tab-running" in reg, "a tab whose owning process is still alive is never touched")
        check("owner-window" not in _CDPHandler.closed,
              "an id HelmDeck never registered (the owner's own window) is never asked about")
    finally:
        srv.shutdown()
        browsercap._write_tab_reg({})


def _track(tid, lane, archived, dev_port):
    return {"id": tid, "status": "needs_you" if lane != "working" else "running",
            "lane": lane, "archived": archived, "dev_port": dev_port,
            "task": "t", "branch": tid, "run_dir": os.path.join(SANDBOX, tid),
            "turns": 1, "updated": "2026-09-20 00:00:00"}


def test_dev_port_backstop():
    # a REAL listener for the finished card - reclaim must kill it
    done_srv = subprocess.Popen([sys.executable, "-c",
        "import socket,time; s=socket.socket(); s.bind(('127.0.0.1',0)); "
        "print(s.getsockname()[1], flush=True); s.listen(); time.sleep(120)"],
        stdout=subprocess.PIPE, text=True)
    done_port = int(done_srv.stdout.readline().strip())
    # a REAL listener for the still-open card - must survive
    live_srv = subprocess.Popen([sys.executable, "-c",
        "import socket,time; s=socket.socket(); s.bind(('127.0.0.1',0)); "
        "print(s.getsockname()[1], flush=True); s.listen(); time.sleep(120)"],
        stdout=subprocess.PIPE, text=True)
    live_port = int(live_srv.stdout.readline().strip())
    try:
        from cells.engineer.cards import devport
        deadline = time.time() + 10
        while time.time() < deadline and (
                done_srv.pid not in devport._listeners_on(done_port)
                or live_srv.pid not in devport._listeners_on(live_port)):
            time.sleep(0.2)

        db.track_put(_track("t-done", "done", False, done_port))
        db.track_put(_track("t-working", "working", False, live_port))

        out = idle_sweep.sweep_dev_ports()

        reclaimed_cards = {o["card"] for o in out}
        check("t-done" in reclaimed_cards, "finished card's dev port reclaimed (got %r)" % out)
        check("t-working" not in reclaimed_cards, "a working card's dev port is never touched")
        try:
            done_srv.wait(timeout=5); done_dead = True
        except subprocess.TimeoutExpired:
            done_dead = False
        check(done_dead, "the finished card's listener process actually died")
        check(live_srv.poll() is None, "the working card's listener process is still alive")
    finally:
        for p in (done_srv, live_srv):
            if p.poll() is None:
                p.kill()


def test_locks_backstop():
    lockdir = os.path.join(SANDBOX, "locks", "android-build")
    os.makedirs(lockdir, exist_ok=True)
    with open(os.path.join(lockdir, "pid"), "w", encoding="utf-8") as f:
        f.write("%d\n%d\n" % (_dead_pid(), _dead_pid()))

    out = idle_sweep.sweep_locks()
    check(any(o["lock"] == "android-build" for o in out), "stale android-build lock cleared (got %r)" % out)
    check(not os.path.isdir(lockdir), "the lock directory itself is gone")

    # a lock held by a genuinely live pid (this test process) must survive
    os.makedirs(lockdir, exist_ok=True)
    with open(os.path.join(lockdir, "pid"), "w", encoding="utf-8") as f:
        f.write("%d\n%d\n" % (os.getpid(), os.getpid()))
    out2 = idle_sweep.sweep_locks()
    check(not any(o["lock"] == "android-build" for o in out2), "a live-pid lock is never touched")
    check(os.path.isdir(lockdir), "the live lock directory still exists")
    import shutil
    shutil.rmtree(lockdir, ignore_errors=True)


def test_policy_and_summary():
    pol = idle_sweep.sweep_policy()
    check(pol == {"enabled": True, "idle_minutes": 30}, "default policy is on, 30 min (got %r)" % pol)
    check(idle_sweep.last_sweep_summary() is None, "no summary before any sweep has run")

    n = idle_sweep.run_sweep(force=True)
    check(n is not None, "a forced sweep runs regardless of idle time/liveness")
    summ = idle_sweep.last_sweep_summary()
    check(summ is not None and summ["items"] == n,
          "last_sweep_summary reads the just-emitted kind=sweep event back (got %r)" % summ)


if __name__ == "__main__":
    test_tabs_registry_reclaim()
    test_dev_port_backstop()
    test_locks_backstop()
    test_policy_and_summary()
    print()
    if _fails:
        print("FAILED: %d check(s)" % len(_fails))
        sys.exit(1)
    print("ALL GREEN - idle resource sweeper holds its contract")
