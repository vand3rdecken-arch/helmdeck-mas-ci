# -*- coding: utf-8 -*-
"""Pins 2026-10-20: Henry's chat verbs run under the OWNER's account name, so a
process Henry deleted looked like an owner decision - another Henry run read it
as "der Owner hat sie bewusst geloescht" and dropped its own task. The account
stays (billing/dispatch attribution); the event carries `via: henry` beside it.
RED on the old code (no via on the process events).

Self-sandboxing: temp db + events. Run: py -3.12 ops/tests/test_chat_process_verbs_via_henry.py
"""
import json, os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SANDBOX = tempfile.mkdtemp(prefix="hd-via-")
from spine.storage import db
db.ROOT = SANDBOX
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
events.EV = os.path.join(SANDBOX, "events.jsonl")
db.init(role="tool")
assert db.DBPATH.startswith(SANDBOX)
from cells.engineer.chains import processes
from cells.copilot.chat import copilot_actions as ca

fails = []


def check(c, m):
    print(("  ok   " if c else "  FAIL ") + m)
    if not c:
        fails.append(m)


def last_event(pid, action):
    for e in reversed(events.read_all() if hasattr(events, "read_all") else []):
        if e.get("kind") == "process" and e.get("track") == pid and e.get("action") == action:
            return e
    return None


seen = []
real_emit = events.emit
events.emit = lambda kind, track, **f: (seen.append(dict(f, kind=kind, track=track)), real_emit(kind, track, **f))[1]
try:
    for verb, action in (("cancel_process", "cancelled"), ("finish_process", "finished"), ("delete_process", "deleted")):
        p = processes.create("Test %s" % verb, actor="owner")
        r = ca._run_action({"type": verb, "process": p["id"]}, "owner", "owner")
        ev = [e for e in seen if e.get("kind") == "process" and e.get("track") == p["id"] and e.get("action") == action]
        check(ev and ev[-1].get("via") == "henry" and ev[-1].get("actor") == "owner",
              "%s: event carries via=henry, account actor stays owner (%s)" % (verb, r[:60]))
    check("BY HENRY" in r, "the delete result names Henry as the hand")
    p = processes.create("UI-Pfad", actor="owner")
    processes.delete_process(p["id"], actor="owner")
    ev = [e for e in seen if e.get("track") == p["id"] and e.get("action") == "deleted"]
    check(ev and "via" not in ev[-1], "an owner tap (no via) stays a plain owner event")
finally:
    events.emit = real_emit
print("PASS test_chat_process_verbs_via_henry" if not fails else "FAIL (%d)" % len(fails))
sys.exit(1 if fails else 0)
