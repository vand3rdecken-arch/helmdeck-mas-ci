"""Henry's board-chat snapshot stays slim (owner, 2026-09-15): done processes
collapse to a count, done steps to a counter, debt to slugs (a title only when
live work names it), ship.process only on ship-ish turns - while live cards and
the PM PLAN still ride. Also: mojibake step titles render as real umlauts.

Self-sandboxing: in-memory board, fake events/processes/debt/plan - no daemon,
no live db."""
import os, sys, types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from cells.copilot.chat import copilot
from spine.storage import trackstore

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


store = {}


class FakeDB:
    def tracks_all(self):
        return list(store.values())
    def track_put(self, t):
        store[t["id"]] = t
    def track_get(self, tid):
        return store.get(tid)
    def track_delete(self, tid):
        store.pop(tid, None)


trackstore._db = FakeDB()

sys.modules["spine.storage.events"] = types.SimpleNamespace(
    metrics=lambda tracks: {"capacity": {"wip": 1, "wip_limit": 3, "headroom": 2}},
    settings=lambda: {"policy": {}})
sys.modules["cells.engineer.chains.processes"] = types.SimpleNamespace(list_processes=lambda: [
    {"id": "p-done", "status": "done", "request": "OLD FINISHED PROCESS", "steps": [
        {"state": "done", "mode": "do", "title": "old step"}]},
    {"id": "p-run", "status": "running", "request": "Live process", "steps": [
        {"state": "done", "mode": "do", "title": "ALREADY DONE STEP"},
        {"state": "ready", "mode": "do", "title": "PrÃ¼fung offen"}]},
])
from spine.registry import debt as _debt
_debt.list_debt = lambda: [
    {"id": "debt-quiet", "title": "QUIET DEBT TITLE", "trigger": "never", "status": "open"},
    {"id": "debt-hot", "title": "HOT DEBT TITLE", "trigger": "now", "status": "open"},
]
from cells.copilot.planning import pm
pm.live_plan = lambda: {"goal": "Launch", "risks": ["touches debt-hot"],
                        "milestones": [{"name": "M1", "est_turns": 1, "priority": "high"}]}


def card(tid, **kw):
    t = {"id": tid, "task": "Karte " + tid, "branch": "b", "status": "running",
         "lane": "working", "repo": "/r/swarmdeck", "priority": "high", "last_reply": ""}
    t.update(kw)
    store[tid] = t


card("live-1", status="needs_you", last_reply="LIVE REPLY TEXT")
card("fin-1", lane="done", task="FINISHED CARD")

snap = copilot._snapshot()
check("live-1" in snap and "LIVE REPLY TEXT" in snap, "live card with last_reply rides")
check("FINISHED CARD" not in snap, "finished card stays out")
check("OLD FINISHED PROCESS" not in snap and "1 finished process" in snap,
      "done process is one count line")
check("ALREADY DONE STEP" not in snap and "1/2 done" in snap, "done steps are a counter")
check("Prüfung offen" in snap, "mojibake step title rendered as umlaut")
check("QUIET DEBT TITLE" not in snap and "debt-quiet" in snap, "untouched debt = slug only")
check("HOT DEBT TITLE" in snap, "debt named by the PM plan keeps its title")
check("PM PLAN" in copilot._pm_plan_digest(), "PM PLAN digest still produced")

full = copilot._snapshot(full=True)
check("OLD FINISHED PROCESS" in full and "QUIET DEBT TITLE" in full, "--full keeps everything")

check(copilot._ship_relevant("bitte als OTA shippen"), "ship-ish message pulls ship.process")
check(not copilot._ship_relevant("wie ist der Stand?"), "plain message skips ship.process")
card("ship-1", ship_kind="decide")
check(copilot._ship_relevant("wie ist der Stand?"), "live ship card pulls ship.process")

print("FAILED: %d" % len(_fails) if _fails else "ALL OK")
sys.exit(1 if _fails else 0)
