# -*- coding: utf-8 -*-
"""The restart verb (spine/ops/daemonctl) decides from live signals and never
touches the Task Scheduler in a test.

  * status() is derived: pid/boot time are process facts, `stale` compares
    the booted commit with the repo HEAD read NOW.
  * restart() refuses while a card turn is live (drivers.turn_active, not the
    stored flag), unless forced.
  * restart() fires exactly `schtasks /Run /TN HelmDeckRestart` through the
    injectable runner, creating the task first only if it is missing.
Sandboxed db.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

SANDBOX = tempfile.mkdtemp(prefix="hd-daemonctl-")
from spine.storage import db  # noqa: E402
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events  # noqa: E402
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from spine.ops import daemonctl  # noqa: E402
from spine.agent import drivers  # noqa: E402
from cells.engineer.cards import sessions  # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# 1) status shape + derivation
daemonctl._task_present = lambda: True
s = daemonctl.status()
check(s["pid"] == os.getpid() and s["uptime_s"] >= 0, "status: pid/uptime are process facts")
check(isinstance(s["stale"], bool) and "commit" in s and "repo_head" in s, "status: stale is derived from commit vs HEAD")
check(s["running_turns"] == [], "status: no live turns in an empty store")

# 2) refuse while a turn is live (turn_active is the judge, not the flag)
sessions._save([{"id": "c1", "task": "x", "status": "running", "lane": "working",
                 "run_dir": SANDBOX, "worktree": SANDBOX}])
calls = []
runner = lambda argv: calls.append(argv) or (0, "SUCCESS")  # noqa: E731
drivers.turn_active = lambda tid: True
r = daemonctl.restart(runner=runner)
check(r["ok"] is False and r["reason"] == "turn_active" and r["turns"] == ["c1"],
      "restart: refused while c1's turn is live")
check(calls == [], "restart: nothing fired on refusal")

# 3) a stored 'running' flag WITHOUT a live turn does not block (stale flag)
drivers.turn_active = lambda tid: False
r = daemonctl.restart(runner=runner)
check(r["ok"] is True and calls == [["schtasks", "/Run", "/TN", "HelmDeckRestart"]],
      "restart: stale running flag ignored - fires exactly the task run")

# 4) force overrides a live turn, and the fired record carries the turns
calls.clear()
drivers.turn_active = lambda tid: True
r = daemonctl.restart(force=True, runner=runner)
check(r["ok"] is True and r["forced"] is True and r["turns"] == ["c1"] and len(calls) == 1,
      "restart: force fires despite the live turn and reports which")

# 5) missing task -> created first, then run
calls.clear()
daemonctl._task_present = lambda: False
drivers.turn_active = lambda tid: False
r = daemonctl.restart(runner=runner)
check(r["ok"] is True and len(calls) == 2 and calls[0][:4] == ["schtasks", "/Create", "/TN", "HelmDeckRestart"]
      and "restart_helmdeck.ps1" in calls[0][-1] and calls[1][1] == "/Run",
      "restart: a missing task is created (pointing at ops/tools) and then run")

# 6) runner failure is reported, not swallowed
calls.clear()
daemonctl._task_present = lambda: True
r = daemonctl.restart(runner=lambda argv: (1, "ERROR: Access is denied."))
check(r["ok"] is False and r["reason"] == "task_run_failed" and "denied" in r["detail"],
      "restart: a failed schtasks run comes back as the reason")

# 7) the routes exist and gate on role - a client never restarts the daemon
from spine.http.routes import routes_system
sent = []
class _H:
    path = "/admin/restart"
    def _send(self, code, body): sent.append((code, body))
check("/admin/daemon" in routes_system.GET_ROUTES and "/admin/restart" in routes_system.POST_ROUTES,
      "routes: /admin/daemon (GET) and /admin/restart (POST) are mounted")
routes_system.admin_restart_post(_H(), {"role": "client", "name": "c"}, {})
check(sent and sent[-1][0] == 403, "routes: a client gets 403 on restart")
routes_system.admin_daemon_get(_H(), {"role": "operator", "name": "o"})
check(sent and sent[-1][0] == 200 and '"stale"' in sent[-1][1], "routes: an operator can read the status")
drivers.turn_active = lambda tid: True
routes_system.admin_restart_post(_H(), {"role": "owner", "name": "own"}, {})
check(sent and sent[-1][0] == 409 and "turn_active" in sent[-1][1],
      "routes: owner restart while a turn is live -> 409 turn_active (no force)")

# 8) Henry's broker verb "restart" is THIS verb, not a shell command
from cells.copilot.broker import henry_broker as hb
fired = []
saved = daemonctl.restart
daemonctl.restart = lambda force=False, actor="owner", runner=None: fired.append(actor) or {"ok": True}
class _E:
    notes = []
    def record_note(self, i, n): self.notes.append(n)
hb.escalations = _E()
try:
    ok = hb._execute("restart", "", "", "", {"id": "e1"})
finally:
    daemonctl.restart = saved
check(ok is True and fired == ["henry"], "broker: action restart calls daemonctl.restart(actor=henry)")
daemonctl.restart = lambda force=False, actor="owner", runner=None: {"ok": False, "reason": "turn_active", "detail": "x"}
try:
    ok = hb._execute("restart", "", "", "", {"id": "e2"})
finally:
    daemonctl.restart = saved
check(ok is False and any("turn_active" in n for n in hb.escalations.notes),
      "broker: a refused restart stays open with the reason noted")

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails))
    sys.exit(1)
print("daemonctl: all pinned - PASS")
