# -*- coding: utf-8 -*-
"""The background-task registry must stay FIRST-CLASS (Paseo's
ProviderSubagentStore principle): the driver's pump folds stream events into
per-card open-task state at EVENT TIME - never reconstructed by transcript
forensics. Pins the exact flows of the 'mittendrin gestorben' incident: an async
agent (Task tool, no run_in_background flag) must be seen as background work so
waiting_on=background protects the session from idle eviction."""
import inspect, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "daemon"))
import db
db.init()
import drivers, sessions

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


cls = [o for n, o in inspect.getmembers(drivers)
       if inspect.isclass(o) and hasattr(o, "_scan_bg")][0]


class S:
    tid = "TESTBG"

    def __init__(self):
        self._bg_candidates = {}
        self._bg_open = {}


recorded = {}
sessions.record_bg = lambda tid, open_tasks: recorded.update({tid: dict(open_tasks)})


def ev_use(uid, name="Task", desc="x", bg=False):
    inp = {"description": desc}
    if bg:
        inp["run_in_background"] = True
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": uid, "name": name, "input": inp}]}}


def ev_result(uid, text):
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": uid, "content": text}]}}


def ev_notif(uid):
    return {"type": "user", "message": {"content": [{"type": "text",
        "text": "<task-notification><task-id>t</task-id><tool-use-id>%s</tool-use-id></task-notification>" % uid}]}}


# 1) async agent (Task, NO run_in_background flag - the scam-check case)
s = S()
cls._scan_bg(s, ev_use("tu1", desc="Scam check"))
cls._scan_bg(s, ev_result("tu1", "Async agent launched successfully. agentId: abc"))
check(s._bg_open == {"tu1": "Scam check"}, "async Task agent counted as background")
check(recorded.get("TESTBG") == {"tu1": "Scam check"}, "open set persisted to the track")

# 2) a SYNC Task result must NOT count
cls._scan_bg(s, ev_use("tu2", desc="sync explore"))
cls._scan_bg(s, ev_result("tu2", "Here is my full report: ..."))
check("tu2" not in s._bg_open, "sync Task result not counted as background")

# 3) run_in_background shell task counts too
cls._scan_bg(s, ev_use("tu3", name="Bash", desc="long build", bg=True))
cls._scan_bg(s, ev_result("tu3", "Command running in background with ID: xyz"))
check("tu3" in s._bg_open, "run_in_background command counted")

# 4) task-notification closes exactly its task
cls._scan_bg(s, ev_notif("tu1"))
check("tu1" not in s._bg_open and "tu3" in s._bg_open,
      "notification closed tu1, tu3 still open")
check(recorded.get("TESTBG") == {"tu3": "long build"}, "persisted state follows")

# 5) closing the last task clears the registry (record_bg pops the key)
cls._scan_bg(s, ev_notif("tu3"))
check(recorded.get("TESTBG") == {}, "all closed -> empty set persisted")

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails)); sys.exit(1)
print("bg-registry: all pinned - PASS")
