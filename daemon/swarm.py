# -*- coding: utf-8 -*-
"""HelmDeck daemon CLI. Run as a package from the REPO ROOT (daemon/ is a
real Python package now, not a sys.path trick):

  python -m daemon.swarm wincap-test    5s desktop capture -> recordings/<id>/screen.mp4
  python -m daemon.swarm browser-demo   scripted, audited browser run (video + timeline)
  python -m daemon.swarm teach "task name"   record YOUR demo; Ctrl+Esc stops
  python -m daemon.swarm distill <run-id>    demo -> editable playbook (claude -p)
  python -m daemon.swarm list           runs + step counts
  python -m daemon.swarm serve [port]   local review/index server (APK + browser pull this)
"""
import os, subprocess, sys, time

# ---- no console windows for children (Windows, pythonw) ---------------------
# The daemon runs under pythonw (tray / Electron shell) = no console of its own.
# Every console child it starts (git, taskkill, claude -p, ffmpeg, gpg, ...)
# then gets a NEW console = a visible window that steals focus (measured
# 2026-09-22: with Windows Terminal as the default terminal that was a full
# terminal window per git call). ONE shim here beats a creationflags= on each
# of ~100 call sites: subprocess.run / check_output / call all construct Popen.
# Gated on "no console attached" so an interactive `python -m daemon.swarm
# serve` from a terminal is untouched, and an explicit CREATE_NEW_CONSOLE from
# a caller still wins.
if os.name == "nt":
    try:
        import ctypes
        _has_console = bool(ctypes.windll.kernel32.GetConsoleWindow())
    except Exception:
        _has_console = True
    if not _has_console:
        _Popen_init = subprocess.Popen.__init__

        def _popen_init_no_window(self, *args, **kw):
            flags = kw.get("creationflags", 0)
            if not flags & subprocess.CREATE_NEW_CONSOLE:
                kw["creationflags"] = flags | subprocess.CREATE_NO_WINDOW
            _Popen_init(self, *args, **kw)
        subprocess.Popen.__init__ = _popen_init_no_window

# Line-buffer stdout/stderr regardless of launcher (Electron/tray redirect to a
# file, which Python block-buffers by default - a crash before the buffer fills
# left daemon.out.log looking untouched even though the process ran for a
# while). Belt-and-suspenders alongside PYTHONUNBUFFERED set by the launchers.
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(line_buffering=True)
    except Exception: pass

def wincap_test():
    from spine.media import wincap
    from spine.ops.runs import new_run, finish_run
    from spine.ops.actionlog import ActionLog
    rid, d = new_run("test", "wincap 5s smoke")
    log = ActionLog(d)
    log.log("note", "wincap smoke start")
    p = wincap.start(d)
    time.sleep(5)
    wincap.stop(p)
    log.log("note", "wincap smoke end")
    finish_run(d)
    print("run:", rid)

def browser_demo():
    from spine.media.browsercap import AgentBrowser
    from spine.ops.runs import new_run, finish_run
    rid, d = new_run("agent", "browser demo: example.com walk")
    b = AgentBrowser(d)
    try:
        b.goto("https://example.com")
        b.note("landed on example.com")
        b.click("a", label="the 'More information' link")
        b.note("on iana.org explanation page")
        b.flag("demo flag: a reviewer-attention step looks like this")
    finally:
        b.close()
    finish_run(d)
    print("run:", rid)

def main():
    if len(sys.argv) < 2:
        print(__doc__); return
    cmd = sys.argv[1]
    if cmd == "wincap-test": wincap_test()
    elif cmd == "browser-demo": browser_demo()
    elif cmd == "teach":
        from spine.ops.teach import record_demo
        record_demo(sys.argv[2] if len(sys.argv) > 2 else "unnamed task")
    elif cmd == "distill":
        from spine.ops.distill import distill
        distill(sys.argv[2])
    elif cmd == "list":
        from spine.ops.runs import list_runs
        from spine.ops.actionlog import read_timeline
        import os
        from spine.ops.runs import REC
        for m in list_runs():
            n = len(read_timeline(os.path.join(REC, m["id"])))
            print("%s  %-6s %-8s %3d steps  %s" %
                  (m["id"], m["kind"], m["status"], n, m["title"]))
    elif cmd == "serve":
        from spine.http import server
        server.serve(int(sys.argv[2]) if len(sys.argv) > 2 else 8140)
    else:
        print(__doc__)

if __name__ == "__main__":
    main()
