# -*- coding: utf-8 -*-
"""update_step must carry a rename/re-description to the step's card while the
card is NOT started (backlog, no turn); a started card is left alone and the
result says so. Fails on the old code (card kept the old task text).

Self-sandboxing: db + settings redirected to a temp dir.
Run: py -3.12 ops/tests/test_update_step_card_sync.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-stepcardsync-")
    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from spine.storage import events
    events.SET = os.path.join(tmp, "settings.json")
    db.init(role="tool")
    assert db.DBPATH.startswith(tmp), "REFUSING TO RUN: db not sandboxed"

    from cells.engineer.chains import processes
    from cells.engineer.cards import sessions
    from spine.storage.trackstore import _mutate

    p = processes.create("Sync test", actor="owner", repo=tmp,
                         steps=[{"title": "Alt A", "mode": "do", "days": 1},
                                {"title": "Alt B", "mode": "do", "days": 1}])
    pid = p["id"]
    processes.accept_step(pid, 0, tmp)
    processes.accept_step(pid, 1, tmp)
    steps = processes.get(pid)["steps"]
    ta, tb = steps[0]["track"], steps[1]["track"]

    def task(tid):
        return sessions._find(sessions._load(), tid)["task"]

    r = processes.update_step(pid, 0, {"title": "Neu A", "desc": "mehr Text"})
    check(task(ta) == "Neu A\n\nmehr Text", "unstarted card follows title+desc (%r)" % task(ta))
    check("updated" in (r.get("card_sync") or ""), "result reports the card update")
    check("card_sync" not in processes.get(pid)["steps"][0], "report is not persisted on the step")

    _mutate(tb, lambda t: t.update(turns=2, lane="working"))
    r = processes.update_step(pid, 1, {"title": "Neu B"})
    check(task(tb) == "Alt B", "started card keeps its task (%r)" % task(tb))
    check("NOT touched" in (r.get("card_sync") or ""), "result reports the untouched card")
    check(processes.get(pid)["steps"][1]["title"] == "Neu B", "step title itself still changes")

    r = processes.update_step(pid, 0, {"days": 4})
    check("card_sync" not in r and task(ta) == "Neu A\n\nmehr Text", "days-only edit does not touch the card")

    print()
    if _fails:
        print("=== %d FAILED ===" % len(_fails))
        sys.exit(1)
    print("update-step-card-sync: all pinned - PASS")


if __name__ == "__main__":
    main()
