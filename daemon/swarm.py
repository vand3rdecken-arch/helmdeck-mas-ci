# -*- coding: utf-8 -*-
"""HelmDeck daemon CLI.

  python swarm.py wincap-test           5s desktop capture -> recordings/<id>/screen.mp4
  python swarm.py browser-demo          scripted, audited browser run (video + timeline)
  python swarm.py teach "task name"     record YOUR demo; Ctrl+Esc stops
  python swarm.py distill <run-id>      demo -> editable playbook (claude -p)
  python swarm.py list                  runs + step counts
  python swarm.py serve [port]          local review/index server (APK + browser pull this)
"""
import sys, time

def wincap_test():
    import wincap
    from runs import new_run, finish_run
    from actionlog import ActionLog
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
    from browsercap import AgentBrowser
    from runs import new_run, finish_run
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
        from teach import record_demo
        record_demo(sys.argv[2] if len(sys.argv) > 2 else "unnamed task")
    elif cmd == "distill":
        from distill import distill
        distill(sys.argv[2])
    elif cmd == "list":
        from runs import list_runs
        from actionlog import read_timeline
        import os
        from runs import REC
        for m in list_runs():
            n = len(read_timeline(os.path.join(REC, m["id"])))
            print("%s  %-6s %-8s %3d steps  %s" %
                  (m["id"], m["kind"], m["status"], n, m["title"]))
    elif cmd == "serve":
        import server
        server.serve(int(sys.argv[2]) if len(sys.argv) > 2 else 8140)
    else:
        print(__doc__)

if __name__ == "__main__":
    main()
