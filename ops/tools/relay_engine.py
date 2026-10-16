# -*- coding: utf-8 -*-
"""Switch who holds the phone's room socket, either way, without touching the daemon process.

    py -3.12 ops/tools/relay_engine.py status
    py -3.12 ops/tools/relay_engine.py pipe     # the key-less Rust bridge holds the socket (tray-supervised)
    py -3.12 ops/tools/relay_engine.py inproc   # the way back: the daemon dials the room itself (default)

The setting is `relay.engine` in workspace_config (home: workspace policy, owner-only; written
through events.save_settings like every other settings write). Both sides READ it each cycle:
the tray (every 4 s) starts/stops helmdeck-relay-bridge.exe, the daemon's relay loop (within
5 s) hands the room over or takes it back. Nothing is remembered in a process.

`pipe` needs the RUST tray (it supervises the bridge) - run tray_switch.py rust first (the tool
checks and says so). A daemon restart while on `pipe` costs the phone nothing: the bridge keeps
the room socket and holds requests until the daemon is back (see bridge-rs/README.md).
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "ops", "tools"))
import tray_switch as ts                                        # noqa: E402

BRIDGE_PROC = "helmdeck-relay-bridge"


def data_dir():
    root = (os.environ.get("HELMDECK_DATA_ROOT") or "").strip()
    return root or os.path.join(ROOT, "daemon")


def engine():
    from spine.storage import events
    return (events.settings().get("relay") or {}).get("engine") or "inproc"


def bridge_pids():
    out = ts.ps("Get-Process %s -ErrorAction SilentlyContinue | ForEach-Object { $_.Id }" % BRIDGE_PROC)
    return [int(x) for x in out.split() if x.strip().isdigit()]


def log_tail(n=6):
    p = os.path.join(data_dir(), "relay-bridge.log")
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return [ln.rstrip() for ln in f.readlines()[-n:]]
    except OSError:
        return []


def status():
    from spine.comms import relay_client as rc
    cfg = rc._cfg()
    t = ts.trays()
    print("relay configured: %s" % ("yes" if cfg[0] and cfg[1] else "NO (no url/room yet)"))
    print("engine setting:   %s" % engine())
    print("tray:             rust=%s python=%s" % (t["rust"] or "-", t["python"] or "-"))
    print("bridge process:   %s" % (bridge_pids() or "-"))
    print("daemon:           pid %s, %s" % (ts.daemon_pid(), "answering" if ts.serving() else "NOT answering"))
    for ln in log_tail():
        print("  bridge log: " + ln)


def set_engine(value):
    from spine.storage import events
    events.save_settings({"relay": {"engine": value}}, actor="relay_engine.py")


def wait(pred, secs):
    end = time.time() + secs
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.5)
    return False


def to_pipe():
    from spine.comms import relay_client as rc
    cfg = rc._cfg()
    if not (cfg[0] and cfg[1]):
        sys.exit("no relay configured yet - pair a phone first")
    if not ts.trays()["rust"]:
        sys.exit("the Rust tray supervises the bridge and it is not running - py -3.12 ops/tools/tray_switch.py rust")
    if not os.path.exists(ts.BRIDGE_INSTALLED) and not os.path.exists(ts.BRIDGE_BUILT):
        sys.exit("no bridge build - cd surfaces/relay/bridge-rs && cargo build --release")
    if not os.path.exists(ts.BRIDGE_INSTALLED):
        os.makedirs(ts.INSTALL_DIR, exist_ok=True)
        import shutil
        shutil.copy2(ts.BRIDGE_BUILT, ts.BRIDGE_INSTALLED)
    daemon_before = ts.daemon_pid()
    set_engine("pipe")
    ok = wait(lambda: bool(bridge_pids()), 20)
    print("bridge started by the tray: %s" % ("yes" if ok else "NO - is the running tray an old build? tray_switch.py rust"))
    ok2 = wait(lambda: any("daemon attached" in ln for ln in log_tail(20)), 20)
    print("daemon attached to the bridge: %s" % ("yes" if ok2 else "NO - check the daemon log"))
    same = ts.daemon_pid() == daemon_before and ts.serving()
    print("daemon process untouched and answering: %s" % ("yes" if same else "NO"))
    if not (ok and ok2 and same):
        print("rolling back to inproc")
        set_engine("inproc")
        sys.exit(1)
    status()


def to_inproc():
    daemon_before = ts.daemon_pid()
    set_engine("inproc")
    gone = wait(lambda: not bridge_pids(), 20)
    if not gone:
        # the Python tray (or none) is supervising: nobody will stop the bridge, so stop it here
        ts.ps("Get-Process %s -ErrorAction SilentlyContinue | Stop-Process -Force" % BRIDGE_PROC)
        gone = wait(lambda: not bridge_pids(), 5)
    print("bridge stopped: %s" % ("yes" if gone else "NO"))
    print("daemon process untouched and answering: %s" % ("yes" if ts.daemon_pid() == daemon_before and ts.serving() else "NO"))
    status()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        status()
    elif cmd == "pipe":
        to_pipe()
    elif cmd == "inproc":
        to_inproc()
    else:
        sys.exit(__doc__)
