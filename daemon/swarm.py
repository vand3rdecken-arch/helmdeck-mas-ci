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
import sys, time

# Line-buffer stdout/stderr regardless of launcher (Electron/tray redirect to a
# file, which Python block-buffers by default - a crash before the buffer fills
# left daemon.out.log looking untouched even though the process ran for a
# while). Belt-and-suspenders alongside PYTHONUNBUFFERED set by the launchers.
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(line_buffering=True)
    except Exception: pass

def wincap_test():
    from daemon.spine import wincap
    from daemon.spine.runs import new_run, finish_run
    from daemon.spine.actionlog import ActionLog
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
    from daemon.spine.browsercap import AgentBrowser
    from daemon.spine.runs import new_run, finish_run
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
        from daemon.spine.teach import record_demo
        record_demo(sys.argv[2] if len(sys.argv) > 2 else "unnamed task")
    elif cmd == "distill":
        from daemon.spine.distill import distill
        distill(sys.argv[2])
    elif cmd == "list":
        from daemon.spine.runs import list_runs
        from daemon.spine.actionlog import read_timeline
        import os
        from daemon.spine.runs import REC
        for m in list_runs():
            n = len(read_timeline(os.path.join(REC, m["id"])))
            print("%s  %-6s %-8s %3d steps  %s" %
                  (m["id"], m["kind"], m["status"], n, m["title"]))
    elif cmd == "serve":
        from daemon.spine import server
        server.serve(int(sys.argv[2]) if len(sys.argv) > 2 else 8140)
    else:
        print(__doc__)

if __name__ == "__main__":
    main()
