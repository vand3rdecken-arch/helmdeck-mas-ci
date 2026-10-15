# -*- coding: utf-8 -*-
"""End-to-end test of the Rust tray (surfaces/desktop/tray-rs) as a REAL
supervisor - the part its unit tests can only fake with a stub server.

It starts the release exe WITHOUT --watch-only against a SANDBOX daemon:
another port and a throw-away HELMDECK_DATA_ROOT, so the live daemon, its db,
its pid file and its logs are never touched. Checks, in order:

  1. the tray spawns a daemon when the port is quiet, the daemon is OUR child
     and runs on the sandbox data root;
  2. kill that daemon -> the next beat respawns it (how long it takes is printed);
  3. a second tray for the same port exits at once (single-instance guard);
  4. leaving through the quit path stops the daemon WE started and nothing else;
  5. the live daemon: same pid, still answering, pid file unchanged.

SAFETY GATE: before anything starts, a child interpreter must prove that
daemon.paths.DATA_ROOT resolves to the sandbox dir with this environment. A
sandbox daemon that resolved to the live root would read the live daemon.pid
and tree-kill the live daemon (spine/http/startup.py eviction block).

Needs psutil (the 3.11 interpreter has it):  python ops/tests/test_rust_tray_e2e.py
Needs the release build: cd surfaces/desktop/tray-rs && cargo build --release
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

try:
    import psutil
except ImportError:
    print("SKIP: psutil missing (use the interpreter that has it, e.g. `python`)")
    sys.exit(0)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXE = os.path.join(ROOT, "surfaces", "desktop", "tray-rs", "target", "release", "helmdeck-tray.exe")
PORT = 8191
LIVE_PORT = 8140
NO_WINDOW = 0x08000000
_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def serving(port):
    """ANY http reply = a daemon is there (the tray's own definition)."""
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=2)
        s.settimeout(2)
        s.sendall(b"GET /system/health HTTP/1.0\r\nHost: x\r\n\r\n")
        data = s.recv(5)
        s.close()
        return data == b"HTTP/"
    except OSError:
        return False


def pid_on(port):
    for c in psutil.net_connections(kind="tcp"):
        if c.status == "LISTEN" and c.laddr.port == port:
            return c.pid
    return None


def wait_for(fn, secs, step=0.25):
    t0 = time.time()
    while time.time() - t0 < secs:
        v = fn()
        if v:
            return time.time() - t0
        time.sleep(step)
    return None


def main():
    if not os.path.isfile(EXE):
        print("SKIP: no release build at", EXE)
        return 0
    if pid_on(PORT) is not None:
        print("ABORT: sandbox port %d is in use" % PORT)
        return 1
    live_pid = pid_on(LIVE_PORT)
    pidfile = os.path.join(ROOT, "daemon", "daemon.pid")
    live_pid_text = open(pidfile).read() if os.path.exists(pidfile) else None
    sandbox = tempfile.mkdtemp(prefix="hd-tray-e2e-")
    env = dict(os.environ, HELMDECK_DATA_ROOT=sandbox)

    # THE GATE: prove the sandbox env really redirects the daemon's data root
    got = subprocess.run(
        [sys.executable if False else "py", "-3.12", "-c",
         "import daemon.paths as p;print(p.DATA_ROOT)"],
        cwd=ROOT, env=env, capture_output=True, text=True).stdout.strip()
    if os.path.normcase(os.path.normpath(got)) != os.path.normcase(os.path.normpath(sandbox)):
        print("ABORT: DATA_ROOT resolves to %r, not the sandbox %r - refusing to start a daemon" % (got, sandbox))
        shutil.rmtree(sandbox, ignore_errors=True)
        return 1
    print("gate ok: sandbox daemon data root =", got)

    tray = None
    try:
        t0 = time.time()
        tray = subprocess.Popen([EXE, "--root", ROOT, "--port", str(PORT), "--run-for", "75"],
                                env=env, creationflags=NO_WINDOW,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        up = wait_for(lambda: serving(PORT), 60)
        check(up is not None, "tray starts a daemon on the quiet sandbox port (%.1fs to first reply)" % (up or -1))
        dpid = pid_on(PORT)
        d = psutil.Process(dpid) if dpid else None
        check(d is not None and d.ppid() == tray.pid, "the daemon is the tray's own child")
        try:
            denv = d.environ() if d else {}
        except psutil.Error:
            denv = {}
        check(denv.get("HELMDECK_DATA_ROOT") == sandbox, "...and it runs on the sandbox data root")
        check(os.path.getsize(os.path.join(sandbox, "daemon.out.log")) > 0 if os.path.exists(os.path.join(sandbox, "daemon.out.log")) else False,
              "its output went to the sandbox daemon.out.log, not the live one")

        # steady state, then the resilience beat
        time.sleep(3)
        t_kill = time.time()
        for ch in d.children(recursive=True):
            ch.kill()
        d.kill()
        d.wait(10)
        gone = wait_for(lambda: not serving(PORT), 10)
        back = wait_for(lambda: serving(PORT) and pid_on(PORT) not in (None, dpid), 60)
        check(back is not None, "killed daemon is respawned by the next beat (%.1fs after it died)" % ((time.time() - t_kill) if back is not None else -1))
        new = pid_on(PORT)
        check(new is not None and new != dpid and psutil.Process(new).ppid() == tray.pid, "the new daemon is again the tray's child")

        # second tray for the same port
        t2 = time.time()
        second = subprocess.Popen([EXE, "--root", ROOT, "--port", str(PORT)], env=env,
                                  creationflags=NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            rc = second.wait(timeout=10)
        except subprocess.TimeoutExpired:
            second.kill()
            rc = None
        check(rc == 4, "a second tray for the same port exits at once with code 4 (%.1fs)" % (time.time() - t2))
        check(psutil.pid_exists(tray.pid) and serving(PORT), "...and the first tray and its daemon are unaffected")

        # quit path (--run-for) stops OUR daemon
        try:
            rc = tray.wait(timeout=90)
        except subprocess.TimeoutExpired:
            rc = None
        check(rc == 0, "the tray leaves cleanly through the quit path (exit %s)" % rc)
        check(wait_for(lambda: not serving(PORT), 15) is not None, "...and the daemon it started is stopped with it")

        # the live daemon never noticed
        check(live_pid is not None and pid_on(LIVE_PORT) == live_pid and serving(LIVE_PORT),
              "live daemon: same pid, still answering")
        now_text = open(pidfile).read() if os.path.exists(pidfile) else None
        check(now_text == live_pid_text, "live daemon.pid is unchanged")
    finally:
        # never leave a sandbox daemon behind - but ONLY one that proves it is the sandbox
        for p in psutil.process_iter(["pid"]):
            try:
                if p.pid == live_pid:
                    continue
                if (p.environ().get("HELMDECK_DATA_ROOT") == sandbox):
                    p.kill()
            except (psutil.Error, OSError):
                pass
        if tray and tray.poll() is None:
            tray.kill()
        time.sleep(1)
        shutil.rmtree(sandbox, ignore_errors=True)

    print()
    if _fails:
        print("FAILED: %d check(s)" % len(_fails))
        return 1
    print("ALL GREEN - the Rust tray supervises a real daemon end to end")
    return 0


if __name__ == "__main__":
    sys.exit(main())
