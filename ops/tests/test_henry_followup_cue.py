# -*- coding: utf-8 -*-
"""A Henry follow-up is BACKGROUND WORK and must show as such in the chat
(owner report 2026-09-12: "Henry sagt er macht was, aber ich sehe nichts").

The follow_up chat verb files a henry-followup escalation and answers
"notiert"; the broker then judges it on its own thread - 3 minutes that day,
up to 15 - and nothing in the Henry chat said so. Same class as the card's
bg_tasks (Paseo descriptors, status running|completed|failed), same UI line
(BackgroundTasks) - so this pins the DERIVATION the chat history serves:

  open escalation           -> running   (title = the ask, since = opened)
  decided (any real action) -> completed (result = why)
  given up ("escalated")    -> failed    (result = the last note / detail)
  closed longer than an hour ago -> gone (the chat line already reported it)

Derived from the append-only escalation records at read time - no flag.
Sandboxed db.
"""
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

SANDBOX = tempfile.mkdtemp(prefix="hd-fucue-")
from spine.storage import db  # noqa: E402
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events  # noqa: E402
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from spine.registry import escalations  # noqa: E402
from cells.copilot.broker import henry_broker as hb  # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# 1) open -> running
eid = escalations.emit("henry-followup", card=None, detail="Daemon-Neustart ausfuehren, damit Fable 5.1 sichtbar wird")
escalations.record_attempt(eid)
tasks = hb.followup_tasks()
check(eid in tasks and tasks[eid]["status"] == "running", "open follow-up -> running")
check(tasks[eid]["title"].startswith("Daemon-Neustart"), "title is the ask")
check(abs(tasks[eid]["since"] - time.time()) < 120, "since = when it was filed (epoch s)")
check(tasks[eid].get("detail") and "Fable" in tasks[eid]["detail"], "detail carries the full ask")

# 2) a note while running is visible (ask failed / lock busy)
escalations.record_note(eid, "ask failed: repo tree busy")
tasks = hb.followup_tasks()
check("repo tree busy" in (tasks[eid].get("result") or ""), "the last note shows while running")

# 3) decided -> completed with the why
escalations.record_decision(eid, "notify_owner", card="", why="Restart braucht den Owner")
tasks = hb.followup_tasks()
check(tasks[eid]["status"] == "completed" and "Owner" in tasks[eid]["result"],
      "decided -> completed, result = why")

# 4) given up -> failed
e2 = escalations.emit("henry-followup", card=None, detail="zweiter Auftrag")
escalations.record_note(e2, "ask failed: no JSON in reply")
escalations.record_decision(e2, "escalated", card="", why="")
tasks = hb.followup_tasks()
check(tasks[e2]["status"] == "failed" and "no JSON" in tasks[e2]["result"],
      "given up -> failed, result = the last note")

# 5) other kinds never appear; old closed ones age out
e3 = escalations.emit("ship-decision", card="c1", detail="x")
check(e3 not in hb.followup_tasks(), "only henry-followup escalations are follow-ups")
old = hb.followup_tasks(closed_within_s=0)
check(eid not in old and e2 not in old, "closed follow-ups age out of the line")

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails))
    sys.exit(1)
print("henry-followup-cue: all pinned - PASS")
