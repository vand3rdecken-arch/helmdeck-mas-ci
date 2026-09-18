# -*- coding: utf-8 -*-
"""A chain step with `not_before` must NOT become ready before that day.

Owner incident 2026-09-18: a posting calendar (r/SideProject on Sunday,
Product Hunt on Tuesday, ...) was modelled as a process. The chain's only
notion of order was "next step starts when the previous one finishes", so
the moment step 0 closed, the Sunday post went to "ready" on a Thursday and
was one sync tick away from auto-dispatching. Owner: "in Zukunft keine
bloeden Dependenzen einplanen wenn man sie nicht braucht".

Pins:
  1. step with not_before in the FUTURE: ready=False, state=waiting,
     held_until set, up_next NOT raised, no auto_dispatched stamp
     (on the pre-fix code this pin FAILS: ready was True)
  2. same step once not_before is today/past: ready=True, held_until empty
  3. update_step validates not_before (YYYY-MM-DD or empty), refuses junk
  4. a blank not_before never blocks anything

Self-sandboxing: db.ROOT/db.DBPATH + events.SET redirected to a temp dir;
tracks are injected straight into the sandboxed card store so no agent
session and no git worktree is ever touched.

Run: py -3.12 ops/tests/test_process_not_before.py
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-procnotbefore-")
    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from spine.storage import events
    events.SET = os.path.join(tmp, "settings.json")
    db.init(role="tool")
    assert db.DBPATH.startswith(tmp), "REFUSING TO RUN: db not sandboxed"

    from cells.engineer.chains import processes
    from cells.engineer.cards import sessions
    assert sessions._load() == [], "REFUSING TO RUN: card store not sandboxed"

    today = time.strftime("%Y-%m-%d")
    tomorrow = time.strftime("%Y-%m-%d", time.localtime(time.time() + 86400))
    yesterday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))

    # cowork on purpose: not in the default auto_dispatch_modes (do/prepare),
    # so a READY step never spawns an agent inside this test.
    p = processes.create("Posting-Kalender", actor="owner",
                         steps=[{"title": "Show HN Thread", "mode": "cowork", "days": 1},
                                {"title": "r/SideProject Sonntag", "mode": "cowork", "days": 1}])
    pid = p["id"]

    # Inject the two step cards straight into the sandboxed store: step 0
    # already done, step 1 waiting in backlog - the exact shape of the incident.
    sessions._save([
        {"id": "t-step0", "lane": "done", "repo": "", "up_next": False},
        {"id": "t-step1", "lane": "backlog", "repo": "", "up_next": False},
    ])
    allp = db.processes_all()
    for q in allp:
        if q["id"] == pid:
            q["steps"][0]["track"] = "t-step0"
            q["steps"][1]["track"] = "t-step1"
    db.processes_replace(allp)

    # 1. future not_before -> held.
    processes.update_step(pid, 1, {"not_before": tomorrow})
    processes.sync()
    s1 = processes.get(pid)["steps"][1]
    t1 = next(t for t in sessions._load() if t["id"] == "t-step1")
    check(s1["ready"] is False, "future not_before: step is NOT ready (fails on pre-fix code)")
    check(s1["state"] == "waiting", "future not_before: state stays 'waiting' (%r)" % s1["state"])
    check(s1.get("held_until") == tomorrow, "future not_before: held_until names the day (%r)" % s1.get("held_until"))
    check(not t1.get("up_next"), "future not_before: card is not raised as up_next")
    check(not s1.get("auto_dispatched"), "future not_before: no auto_dispatched stamp")

    # 2. date reached -> ready.
    processes.update_step(pid, 1, {"not_before": today})
    processes.sync()
    s1 = processes.get(pid)["steps"][1]
    t1 = next(t for t in sessions._load() if t["id"] == "t-step1")
    check(s1["ready"] is True, "not_before == today: step IS ready")
    check(s1.get("held_until") == "", "not_before == today: held_until cleared")
    check(t1.get("up_next") is True, "not_before == today: card raised as up_next")

    processes.update_step(pid, 1, {"not_before": yesterday})
    processes.sync()
    check(processes.get(pid)["steps"][1]["ready"] is True, "not_before in the past: ready")

    # 3. validation.
    try:
        processes.update_step(pid, 1, {"not_before": "Sonntag"})
        check(False, "update_step refuses a non-ISO not_before")
    except RuntimeError:
        check(True, "update_step refuses a non-ISO not_before")

    # 4. blank clears and never blocks.
    processes.update_step(pid, 1, {"not_before": ""})
    processes.sync()
    s1 = processes.get(pid)["steps"][1]
    check(s1.get("not_before", "") == "" and s1["ready"] is True, "blank not_before: cleared, step ready")

    print()
    if _fails:
        print("process-not-before: %d FAIL" % len(_fails))
        sys.exit(1)
    print("process-not-before: all pinned - PASS")


if __name__ == "__main__":
    main()
