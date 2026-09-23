# -*- coding: utf-8 -*-
"""One daemon per machine, enforced by the kernel - not by a scan.

2026-09-23, measured: two daemons started 19:23:20 and 19:23:21, each ran the
`netstat` check before the other had bound, each evicted only the OLD daemon,
and BOTH bound :8140 - Python's HTTPServer sets allow_reuse_address = 1, and
on Windows that lets a second process bind the same addr:port instead of
failing EADDRINUSE. Two relay bridges then pulled the same room and two
daemons wrote the same db for half an hour, until the owner's phone went
strange and it was found by hand.

Two independent guards now, and this pins both:
  1. a named mutex, taken BEFORE the eviction - a check can lose a race, a
     kernel object cannot;
  2. allow_reuse_address = False - the second bind fails, the OS states the
     invariant.
Plus the split that makes it central: only an explicit --takeover may depose
a running daemon; a supervisor spawn exits 3."""
import io
import os
import socket
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# -- 1: the server class refuses to share its port -------------------------
from spine.http import server

check(server._Daemon.allow_reuse_address is False,
      "_Daemon.allow_reuse_address is False (Python's default 1 is what let two bind)")
from http.server import ThreadingHTTPServer
check(ThreadingHTTPServer.allow_reuse_address == 1,
      "...and the stdlib default really is 1, so this had to be overridden")

# a real double bind must now fail
s1 = socket.socket()
s1.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
s1.bind(("127.0.0.1", 0))
port = s1.getsockname()[1]
s1.listen(1)
s2 = socket.socket()
s2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
try:
    s2.bind(("127.0.0.1", port))
    check(False, "a second bind without SO_REUSEADDR is refused by the OS")
except OSError:
    check(True, "a second bind without SO_REUSEADDR is refused by the OS")
finally:
    s1.close()
    s2.close()

# -- 2: the mutex is exclusive, and released when its owner dies -----------
from spine.http import startup

if os.name == "nt":
    check(startup._acquire_daemon_mutex(59999, 200) is True, "first caller takes the daemon mutex")
    check(startup._MUTEX_HANDLE is not None, "...and keeps the handle alive past the call")
    # a SECOND process must not get it: the same name, from a child interpreter
    import subprocess
    probe = (
        "import sys; sys.path.insert(0, %r)\n"
        "from spine.http import startup\n"
        "print('GOT' if startup._acquire_daemon_mutex(59999, 300) else 'REFUSED')\n" % ROOT)
    r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, cwd=ROOT)
    check("REFUSED" in r.stdout, "a second PROCESS is refused while we hold it (got %r)"
          % (r.stdout.strip()[:40]))
    # and a dead owner's mutex is free again (abandoned -> WAIT_ABANDONED)
    probe2 = (
        "import sys; sys.path.insert(0, %r)\n"
        "from spine.http import startup\n"
        "print('GOT' if startup._acquire_daemon_mutex(59998, 300) else 'REFUSED')\n" % ROOT)
    r2 = subprocess.run([sys.executable, "-c", probe2], capture_output=True, text=True, cwd=ROOT)
    check("GOT" in r2.stdout, "a different port has its own mutex")
    r3 = subprocess.run([sys.executable, "-c", probe2], capture_output=True, text=True, cwd=ROOT)
    check("GOT" in r3.stdout, "the dead process' mutex is free again (no wedge after a crash)")
else:
    check(startup._acquire_daemon_mutex(59999, 200) is True, "no-op True off Windows")

# -- 3: the SPLIT - only an explicit takeover may depose a daemon ----------
src = io.open(os.path.join(ROOT, "spine", "http", "startup.py"), encoding="utf-8").read()
at = src.find("def _take_singleton_lock")
body = src[at:at + 3000]
check("takeover=False" in src[at:at + 200], "_take_singleton_lock(port, takeover=False) by default")
check("if not takeover:" in body and "_refuse_start" in body,
      "without takeover a losing start is REFUSED, not promoted to a second daemon")

swarm = io.open(os.path.join(ROOT, "daemon", "swarm.py"), encoding="utf-8").read()
check('"--takeover"' in swarm, "daemon.swarm parses --takeover")

for tool, name in ((os.path.join(ROOT, "ops", "tools", "restart_daemon.py"), "restart_daemon.py"),
                   (os.path.join(ROOT, "ops", "tools", "restart_helmdeck.ps1"), "restart_helmdeck.ps1")):
    t = io.open(tool, encoding="utf-8").read()
    check("--takeover" in t, "%s (an explicit restart verb) passes --takeover" % name)

# the supervisors must NOT - they only ever "make sure one runs"
for sup, name in ((os.path.join(ROOT, "surfaces", "desktop", "tray.py"), "tray.py"),
                  (os.path.join(ROOT, "surfaces", "desktop", "main.js"), "main.js")):
    t = io.open(sup, encoding="utf-8").read()
    check("--takeover" not in t, "%s is a supervisor and does NOT take over" % name)

print("\n%d FAIL" % len(_fails) if _fails else "\nall ok")
sys.exit(1 if _fails else 0)
