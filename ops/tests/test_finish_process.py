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
check(any("P1" in x for x in items) and not any("finish_process" in x or "abnehmen" in x for x in items),
      "all-steps-done running process listed as a FACT, without an imperative")
check(any("C1" in x for x in items) and not any(k in " ".join(items) for k in ("C2", "C3", "C4")),
      "only the card idle for hours with no question and no bg task is listed")
blk = pd.stale_block([done_proc], [parked, fresh, asking, bg], now)
check("AUTOMATISCH GEFUNDEN" in blk and "kann mehr geben" in blk and "geprueft: 1 Prozesse, 4 Karten" in blk
      and "Kriterium" in blk, "the stale block names criteria, what was checked and that more can exist")
check("nicht, dass es nichts gibt" in pd.stale_block([], [], now), "an empty result says 'nothing by these criteria', not 'nothing'")
ps = pd.process_state(done_proc, {}, {}, now)
for _slot in (("20270115 08:00", 0, now - 86400), ("20270115 14:00", 1, now - 3600)):
    r, _ = pd.reasons_for(done_proc, ps, {"slot": "x"}, now, [], is_goal=True, slot=_slot, stale=blk)
    check(any(x.startswith("gefunden:") for x in r), "the found-block rides the goal wake at slot %s" % _slot[0][-5:])

# 5) alignment evidence: where the card work of the week went
import time as _t
_now = 1_800_000_000.0
_mk = lambda repo, days: {"repo": repo, "created": _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(_now - days * 86400))}
_wp = pd.work_by_project([_mk("C:" + chr(92) + "x" + chr(92) + "alphaloop", 1)] * 3 + [_mk("C:/x/helmdeck", 2), _mk("C:/x/old", 30)], _now)
check(_wp == "4 Karten in 7 Tagen: alphaloop 3, helmdeck 1", "work_by_project counts the last 7 days per repo - got %r" % _wp)
_many = [_mk("C:/x/p%02d" % i, 1) for i in range(11)]
_wm = pd.work_by_project(_many, _now)
check("+ 3 weitere Projekte (3 Karten)" in _wm and _wm.startswith("11 Karten"), "a cut project list says how many were cut - got %r" % _wm)
from spine.turn import listing as _ls
_l = _ls.found(["a%d" % i for i in range(30)], "Dinge", cap=5)
check("und 25 weitere nicht gezeigt" in _l and "kann mehr geben" in _l, "listing.found discloses the cut")
check("vollstaendig" in _ls.found(["a"], "x", complete=True) and "kann mehr geben" not in _ls.found(["a"], "x", complete=True),
      "a plain complete listing says so instead of the open-world caveat")
_po = pd.plans_overview([done_proc, {"id": "P2", "status": "running", "request": "zwei", "steps": [{"state": "done"}, {}]}])
check(len(_po) == 2 and "P2 [running] 1/2" in _po[1], "plans_overview lists every process with done/total")

# 6) the broker refuses a set_next without text instead of clearing the schedule
from cells.copilot.broker import henry_broker as hb
from spine.registry import escalations as _esc
_pp = processes.create("Plan mit Next", actor="pm", open_ended=True)
processes.set_next(_pp["id"], "alter Zug", "2027-02-01")
_eid = _esc.emit("process-move", None, "x", process=_pp["id"])
_ok = hb._execute("set_next", "", "", "", {"id": _eid, "kind": "process-move", "process": _pp["id"]},
                  kind="", why="warum", at="2027-02-02")
check(_ok is False and (processes.get(_pp["id"]).get("next") or {}).get("what") == "alter Zug",
      "set_next without text is refused and the recorded next move survives")

# 7) an escalation detail that is cut SAYS so
from spine.registry import escalations as _e2
_big = _e2.emit("test-cut", None, "x" * (_e2.DETAIL_MAX + 500))
_rec = [r for r in _e2.list_open() if r["id"] == _big][0]
check(len(_rec["detail"]) <= _e2.DETAIL_MAX and "gekuerzt" in _rec["detail"], "a cut escalation detail names the loss")
_fit = _e2.emit("test-fit", None, "kurz")
check("gekuerzt" not in [r for r in _e2.list_open() if r["id"] == _fit][0]["detail"], "a short detail is untouched")

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails))
    sys.exit(1)
print("finish-process: all pinned - PASS")
