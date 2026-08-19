# -*- coding: utf-8 -*-
"""Server bootstrap - extracted from server.py. TLS config (env > settings >
auto-detect), Windows PATH + registry-env hydration (the daemon launched
from a tray/service does not inherit the user PATH/env), and the single-
instance port lock. Called by serve(); _tls_config is also read directly by
test_transport_tls. server.py re-imports the names.
"""
import os
import socket
import subprocess

from daemon.paths import DAEMON_ROOT as _DAEMON_ROOT


def _tls_config():
    """Resolve the daemon's TLS material: env (HELMDECK_TLS_CERT/KEY) beats
    settings.tls {cert,key,port} beats auto-detected daemon/certs/tls.crt+key
    (what tools/make_tls_cert.py writes). Returns (cert, key, port) or
    (None, None, port) when TLS is not configured."""
    from daemon.spine import events
    t = events.settings().get("tls") or {}
    cert = os.environ.get("HELMDECK_TLS_CERT") or t.get("cert") or ""
    key = os.environ.get("HELMDECK_TLS_KEY") or t.get("key") or ""
    if not (cert and key):
        base = os.path.join(_DAEMON_ROOT, "certs")
        c, k = os.path.join(base, "tls.crt"), os.path.join(base, "tls.key")
        if os.path.isfile(c) and os.path.isfile(k):
            cert, key = c, k
    tls_port = int(os.environ.get("HELMDECK_TLS_PORT") or t.get("port") or 8443)
    return (cert, key, tls_port) if (cert and key) else (None, None, tls_port)


def _hydrate_windows_path():
    """A daemon launched from Git-bash inherits a MinGW-only PATH that LACKS the
    standard Windows dirs, so `py`, `cmd`, `powershell` and friends are not found.
    The merge gate (`py ... run_gate.py`, run via cmd.exe) then fails with "'py' is
    not recognized" even though the gate itself passes - the card looks like it has
    a code bug when the daemon simply can't invoke the gate. Ensure the core Windows
    dirs + this interpreter's dir are on PATH so anything the daemon (or a driver it
    spawns, which inherits os.environ) shells out to resolves, regardless of how the
    daemon was launched. Append (don't prepend) so a driver's own toolchain still
    wins. Paseo adoption Phase 4.4. No-op off Windows / when already present."""
    if os.name != "nt":
        return
    import sys
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    want = [os.path.join(root, "System32"), root,
            os.path.join(root, "System32", "WindowsPowerShell", "v1.0"),
            os.path.dirname(sys.executable)]
    parts = os.environ.get("PATH", "").split(os.pathsep)
    have = {p.lower() for p in parts if p}
    add = [d for d in want if d and d.lower() not in have and os.path.isdir(d)]
    if add:
        os.environ["PATH"] = os.pathsep.join(parts + add)
        print("PATH: hydrated with Windows dirs (%s) - gate/tools now resolve" %
              ", ".join(os.path.basename(d) or d for d in add), flush=True)


def _hydrate_registry_env():
    """Windows counterpart of Paseo's inheritLoginShellEnv (Paseo captures the
    LOGIN-SHELL env on mac/linux and explicitly SKIPS win32 - login-shell-env.ts
    throws reason:'win32'). On Windows the durable place users and installers
    declare JAVA_HOME, ANDROID_HOME and PATH additions is the REGISTRY
    environment (machine + user). A daemon launched from git-bash or a GUI can
    miss those (var set after login; launcher stripped the env) - and then
    every gradle/adb build inside a card dies on 'JAVA_HOME is not set' even
    though the same build works in the owner's own terminal. Merge at start:
    variables only when absent (a genuinely inherited value wins), PATH
    entries APPENDED (the inherited toolchain order wins). Read via winreg
    (stdlib) - NEVER by shelling to powershell, which is not guaranteed to be
    on PATH (this very dev box lacks it). Paseo adoption Phase 4.4."""
    if os.name != "nt":
        return
    try:
        import winreg
    except ImportError:
        return

    def read_key(root, subkey):
        vals = {}
        try:
            with winreg.OpenKey(root, subkey) as k:
                i = 0
                while True:
                    try:
                        name, val, typ = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    i += 1
                    if typ in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) and isinstance(val, str):
                        vals[name] = val
        except OSError:
            pass
        return vals

    machine = read_key(winreg.HKEY_LOCAL_MACHINE,
                       r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")
    user = read_key(winreg.HKEY_CURRENT_USER, "Environment")
    merged = dict(machine)
    merged.update(user)                      # user overrides machine, like Windows does
    added = []
    # 1) plain variables first, so PATH entries like %JAVA_HOME%\bin expand next
    for name, val in merged.items():
        if name.upper() == "PATH":
            continue
        if name not in os.environ:          # os.environ is case-insensitive on nt
            os.environ[name] = os.path.expandvars(val)
            added.append(name)
    # 2) PATH: append registry entries the launcher dropped
    have = {p.lower().rstrip("\\") for p in os.environ.get("PATH", "").split(os.pathsep) if p}
    extra = []
    for src in (machine, user):
        for key, val in src.items():
            if key.upper() != "PATH":
                continue
            for p in val.split(os.pathsep):
                p = os.path.expandvars(p.strip())
                if p and p.lower().rstrip("\\") not in have and os.path.isdir(p):
                    extra.append(p)
                    have.add(p.lower().rstrip("\\"))
    if extra:
        os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + os.pathsep.join(extra)
        added.append("PATH+%d" % len(extra))
    if added:
        print("ENV: hydrated from registry (%s) - build env present regardless of launcher"
              % ", ".join(sorted(added)), flush=True)


def _take_singleton_lock(port):
    """One daemon per machine. A restart used to race the old instance: the new
    process couldn't bind the port until the old one died, and in that gap the
    RELAY reverse-tunnel poll dropped - the phone showed "paired but takes very
    long" until a poll re-established. So on start we cleanly evict a prior
    daemon (pidfile + tree-kill) and wait for the port to actually free before
    binding, making restart deterministic instead of a bind race."""
    import socket, subprocess, time, signal
    pidfile = os.path.join(_DAEMON_ROOT, "daemon.pid")

    def _kill(pid, why):
        if not pid or pid == os.getpid():
            return
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
            print("SINGLETON: evicted %s pid %d - taking over relay/port %d." % (why, pid, port), flush=True)
        except Exception:
            pass   # already gone

    def _pids_on_port():
        """Every PID LISTENING on the port. The pidfile alone is NOT enough: Python's
        HTTPServer sets SO_REUSEADDR, so on Windows several daemons can silently
        double-bind the same port and stale ones (old code, no reconciler) keep
        serving. Kill ALL of them so exactly one daemon owns the port - the leak
        Paseo avoids by never using SO_REUSEADDR (a 2nd server fails EADDRINUSE)."""
        found = set()
        try:
            out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=10).stdout
            for line in out.splitlines():
                p = line.split()
                if len(p) >= 5 and p[0].upper() == "TCP" and p[3].upper() == "LISTENING" \
                        and p[1].endswith(":%d" % port):
                    try:
                        found.add(int(p[4]))
                    except ValueError:
                        pass
        except Exception:
            pass
        found.discard(os.getpid())
        return found

    def _running_turns():
        """Card ids with a LIVE turn, read straight from the store. The old
        daemon's workers are its process CHILDREN, so evicting it tree-kills
        them mid-run - the owner lost the same 15-minute machine turn to a
        deploy twice in one evening ('killed during run' / 'Broke up in the
        middle'). The store is the shared truth both daemons can see; the
        driver pidfile is NOT (it read {} during a live turn)."""
        try:
            from daemon.spine import db
            return [d.get("id") for d in db.tracks_all() if d.get("status") == "running"]
        except Exception:
            return []

    # GRACE before eviction: a restart is a deploy, a live turn is the owner's
    # running work - the deploy waits, bounded. HELMDECK_RESTART_GRACE=0 forces
    # the old brutal behaviour (emergency: the old daemon IS the problem).
    grace = float(os.environ.get("HELMDECK_RESTART_GRACE", "600"))
    waited = 0.0
    while grace > 0:
        if not _pids_on_port():
            break                        # no live daemon = a STALE running flag,
                                         # not a live turn (boot devaluation fixes it)
        live = _running_turns()
        if not live:
            break
        if waited >= grace:
            print("SINGLETON: grace expired (%ds) - evicting despite live turn(s): %s"
                  % (int(grace), ", ".join(live)), flush=True)
            break
        if waited % 30 < 5:
            print("SINGLETON: waiting for live turn(s) to finish before eviction: %s "
                  "(%ds/%ds)" % (", ".join(live), int(waited), int(grace)), flush=True)
        time.sleep(5)
        waited += 5

    try:
        old = int(open(pidfile).read().strip())
    except Exception:
        old = None
    _kill(old, "prior daemon (pidfile)")
    for pid in _pids_on_port():          # + any stale daemon double-bound to the port
        _kill(pid, "stale daemon on port")
    # wait for the port to free (old listener socket releasing), up to ~5s
    for _ in range(50):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
            s.close()
            break
        except OSError:
            s.close()
            time.sleep(0.1)
    try:
        open(pidfile, "w").write(str(os.getpid()))
        import atexit
        atexit.register(lambda: os.path.exists(pidfile) and os.remove(pidfile))
    except Exception:
        pass


