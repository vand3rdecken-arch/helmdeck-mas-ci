# -*- coding: utf-8 -*-
"""Switch the tray supervisor between the Python tray and the Rust tray, either
way, without touching the daemon.

    py -3.12 ops/tools/tray_switch.py status
    py -3.12 ops/tools/tray_switch.py rust      # install + autostart + start the Rust tray
    py -3.12 ops/tools/tray_switch.py python    # the way back: Python tray + its autostart

What it changes, and nothing else: the HKCU Run value "HelmDeck", which tray is
running, and (for `rust`) a copy of the exe under %LOCALAPPDATA%\\HelmDeck\\tray.
The daemon is never stopped: killing a tray does not kill the daemon it started
(plain Popen, no job object), and the new tray ADOPTS it by health, exactly as
either tray adopts a daemon someone started by hand. The tool checks that the
daemon pid and its answer survived and says so.

Why the exe is COPIED to a stable path: a Run value pointing into
tray-rs/target/release dies with `cargo clean` - an autostart that launches
nothing, the measured 2026-08-29 outage ("EMPTY Run value"). Re-run `rust` after
a rebuild to refresh the copy.

The Python tray repairs the Run value to ITSELF whenever it starts (tray.py
main). So starting it by hand while on the Rust tray takes autostart back;
`rust` stops it first and `status` shows who owns the value.
"""
import os
import shutil
import socket
import subprocess
import sys
import time
import winreg

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PORT = 8140
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "HelmDeck"
BUILT = os.path.join(ROOT, "surfaces", "desktop", "tray-rs", "target", "release", "helmdeck-tray.exe")
INSTALL_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "HelmDeck", "tray")
INSTALLED = os.path.join(INSTALL_DIR, "helmdeck-tray.exe")
BRIDGE_BUILT = os.path.join(ROOT, "surfaces", "relay", "bridge-rs", "target", "release", "helmdeck-relay-bridge.exe")
BRIDGE_INSTALLED = os.path.join(INSTALL_DIR, "helmdeck-relay-bridge.exe")   # the tray looks next to itself first
TRAY_PY = os.path.join(ROOT, "surfaces", "desktop", "tray.py")
PS = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"   # not on PATH on this box
NO_WINDOW = 0x08000000
DETACHED = 0x00000008


def ps(script):
    r = subprocess.run([PS, "-NoProfile", "-Command", script], capture_output=True, text=True,
                       timeout=60, creationflags=NO_WINDOW)
    return (r.stdout or "").strip()


def trays():
    """{'rust': [pids], 'python': [pids]} from the live process table."""
    out = ps("Get-CimInstance Win32_Process | Where-Object { "
             "$_.Name -eq 'helmdeck-tray.exe' -or ($_.Name -eq 'pythonw.exe' -and $_.CommandLine -like '*desktop*tray.py*') } | "
             "ForEach-Object { '{0}|{1}' -f $_.Name, $_.ProcessId }")
    res = {"rust": [], "python": []}
    for line in out.splitlines():
        name, _, pid = line.partition("|")
        if pid.strip().isdigit():
            res["rust" if name.startswith("helmdeck-tray") else "python"].append(int(pid))
    return res


def stop(pids):
    for p in pids:
        ps("Stop-Process -Id %d -Force -ErrorAction SilentlyContinue" % p)
    deadline = time.time() + 8
    while time.time() < deadline and any(str(p) in ps("(Get-Process -Id %d -ErrorAction SilentlyContinue).Id" % p) for p in pids):
        time.sleep(0.3)


def serving():
    try:
        s = socket.create_connection(("127.0.0.1", PORT), timeout=2)
        s.settimeout(2)
        s.sendall(b"GET /system/health HTTP/1.0\r\nHost: x\r\n\r\n")
        ok = s.recv(5) == b"HTTP/"
        s.close()
        return ok
    except OSError:
        return False


def daemon_pid():
    out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, creationflags=NO_WINDOW).stdout
    for ln in out.splitlines():
        p = ln.split()
        if len(p) >= 5 and p[0] == "TCP" and p[3] == "LISTENING" and p[1].endswith(":%d" % PORT):
            return int(p[4])
    return None


def run_value():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return winreg.QueryValueEx(k, RUN_NAME)[0]
    except OSError:
        return None


def set_run(value):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, value)


def python_cmd():
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return '"%s" "%s"' % (pyw if os.path.exists(pyw) else sys.executable, TRAY_PY)


def rust_cmd():
    return '"%s" --root "%s"' % (INSTALLED, ROOT)


def who_owns_autostart():
    v = run_value() or ""
    if "helmdeck-tray" in v:
        return "rust"
    if "tray.py" in v:
        return "python"
    return "none" if not v else "other"


def status():
    t = trays()
    print("autostart (Run/%s): %s" % (RUN_NAME, who_owns_autostart()))
    print("   value: %s" % (run_value() or "(none)"))
    print("running: rust=%s python=%s" % (t["rust"] or "-", t["python"] or "-"))
    print("daemon: pid %s, %s" % (daemon_pid(), "answering" if serving() else "NOT answering"))
    print("installed exe: %s%s" % (INSTALLED, "" if os.path.exists(INSTALLED) else " (not installed)"))
    if len(t["rust"]) + len(t["python"]) > 1:
        print("WARNING: more than one tray is running")


def switch(to):
    before, was_up = daemon_pid(), serving()
    t = trays()
    if to == "rust":
        if not os.path.exists(BUILT):
            sys.exit("no release build at %s - cd surfaces/desktop/tray-rs && cargo build --release" % BUILT)
        stop(t["python"] + t["rust"])             # the exe copy needs the old one gone
        os.makedirs(INSTALL_DIR, exist_ok=True)
        shutil.copy2(BUILT, INSTALLED)
        if os.path.exists(BRIDGE_BUILT):
            # the bridge too (the new tray respawns it when relay.engine is "pipe"); a RUNNING bridge
            # locks its exe, so it is stopped first - only when it is the installed copy
            ps("Get-Process helmdeck-relay-bridge -ErrorAction SilentlyContinue | Stop-Process -Force")
            time.sleep(1)
            shutil.copy2(BRIDGE_BUILT, BRIDGE_INSTALLED)
        set_run(rust_cmd())
        subprocess.Popen([INSTALLED, "--root", ROOT], creationflags=DETACHED | NO_WINDOW, close_fds=True)
    else:
        stop(t["rust"] + t["python"])
        set_run(python_cmd())
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        subprocess.Popen([pyw, TRAY_PY], cwd=ROOT, creationflags=DETACHED | NO_WINDOW, close_fds=True)
    time.sleep(6)                                   # one supervisor beat is 4 s
    after = trays()
    ok = (len(after[to]) == 1 and not after["python" if to == "rust" else "rust"]
          and daemon_pid() == before and serving() == was_up and who_owns_autostart() == to)
    print("switched to %s: %s" % (to, "OK" if ok else "CHECK"))
    status()
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        status()
    elif cmd in ("rust", "python"):
        switch(cmd)
    else:
        sys.exit(__doc__)
