# -*- coding: utf-8 -*-
"""A finished goal must be able to LEAVE "running", and stored titles must not
carry mangled umlauts (owner screenshot 2026-10-05: a 11/11 plan still in
"Plans", step titles 'VollstÃ¤ndigkeit').

Pinned on a sandbox db (db.DBPATH first - the live db is never touched):
 1. an open-ended process stays "running" by its steps (sync never finishes it)
 2. finish_process closes it as done + closed; sync() does not re-open it;
    a cancelled one is refused
 4. the goal's morning wake lists leftovers as evidence (process_drive.stale_items)
 3. _save repairs mojibake in request/step title/desc, idempotent, and leaves
    clean umlauts and unrelated text alone
Run: py -3.12 ops/tests/test_finish_process.py
"""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
SANDBOX = tempfile.mkdtemp(prefix="hd-finishproc-")
from spine.storage import db, events
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()
from cells.engineer.chains import processes
from spine.storage.textfix import demojibake

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


p = processes.create("Ein Ziel", actor="pm", open_ended=True)
pid = p["id"]
processes.sync()
check(processes.get(pid)["status"] == "running", "open-ended process stays running")

processes.finish_process(pid, actor="henry")
processes.sync()
q = processes.get(pid)
check(q["status"] == "done" and q.get("closed"), "finish_process closes it as done")
check(processes.get(pid)["status"] == "done", "sync() does not re-open a closed process")

c = processes.create("Anderes", actor="pm")
processes.cancel_process(c["id"])
try:
    processes.finish_process(c["id"])
    check(False, "finishing a cancelled process is refused")
except RuntimeError:
    check(True, "finishing a cancelled process is refused")

m = processes.create("Pr\u00c3\u00bcfen & Fertig", actor="pm",
                     steps=[{"title": "Vollst\u00c3\u00a4ndigkeit", "desc": "f\u00c3\u00bcr alle",
                             "mode": "human"}])
st = processes.get(m["id"])
check(st["request"] == "Pr\u00fcfen & Fertig", "request repaired at the persistence edge")
check(st["steps"][0]["title"] == "Vollst\u00e4ndigkeit" and st["steps"][0]["desc"] == "f\u00fcr alle",
      "step title and desc repaired")
check(demojibake("Vollst\u00e4ndigkeit") == "Vollst\u00e4ndigkeit" and demojibake("plain") == "plain"
      and demojibake(None) is None, "clean text, plain text and None come back unchanged")
check(demojibake(demojibake("f\u00c3\u00bcr")) == "f\u00fcr", "idempotent")

# 4) the morning wake carries the leftovers as EVIDENCE (tidy), goal only, slot 0 only
from cells.copilot.planning import process_drive as pd
now = 1_800_000_000.0
done_proc = {"id": "P1", "status": "running", "request": "Ziel",
             "steps": [{"title": "a", "state": "done"}, {"title": "b", "done": True}]}
parked = {"id": "C1", "status": "needs_you", "lane": "working", "task": "alt",
          "turn_ended": "2027-01-14 00:00:00", "waiting_on": "you"}
fresh = dict(parked, id="C2", turn_ended=pd.time.strftime("%Y-%m-%d %H:%M:%S", pd.time.localtime(now - 600)))
asking = dict(parked, id="C3", question={"q": 1})
bg = dict(parked, id="C4", waiting_on="background")
items = pd.stale_items([done_proc], [parked, fresh, asking, bg], now)
check(any("P1" in x and "finish_process" in x for x in items), "all-steps-done running process listed")
check(any("C1" in x for x in items) and not any(k in " ".join(items) for k in ("C2", "C3", "C4")),
      "only the card idle for hours with no question and no bg task is listed")
ps = pd.process_state(done_proc, {}, {}, now)
r, _ = pd.reasons_for(done_proc, ps, {"slot": "x"}, now, [], is_goal=True,
                      slot=("20270115 08:00", 0, now - 86400), stale=items)
check(any(x.startswith("tidy:") for x in r), "goal's morning slot carries the tidy list")
r2, _ = pd.reasons_for(done_proc, ps, {"slot": "x"}, now, [], is_goal=True,
                       slot=("20270115 14:00", 1, now - 3600), stale=items)
check(not any(x.startswith("tidy:") for x in r2), "not repeated at the afternoon slot")

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails))
    sys.exit(1)
print("finish-process: all pinned - PASS")
