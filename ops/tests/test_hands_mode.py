# -*- coding: utf-8 -*-
"""Henry picks his own permission mode (owner decree 2026-09-12) - through
the REAL action dispatch (copilot_actions._run_action) and the real rule
store, so what the chat verb writes is exactly what henry_pmode() reads for
the next chat/broker spawn. Admin-gated; bad modes refused; sandboxed db.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

SANDBOX = tempfile.mkdtemp(prefix="hd-handsmode-")
from spine.storage import db  # noqa: E402
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events  # noqa: E402
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from cells.copilot.chat import copilot, copilot_actions  # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


start = copilot.henry_pmode()
check(start == "bypassPermissions", "default mode is bypassPermissions (decree 2026-09-12), got %r" % start)

r = copilot_actions._run_action({"type": "hands_mode", "mode": "plan"}, actor="c", role="client")
check("hands_mode" in r and ("nicht" in r.lower() or "denied" in r.lower() or "erlaubt" in r.lower()),
      "a client-role chat cannot change Henry's hands: %r" % r[:80])
check(copilot.henry_pmode() == start, "denied call left the mode untouched")

r = copilot_actions._run_action({"type": "hands_mode", "mode": "root"}, actor="owner", role="owner")
check("muss einer von" in r, "an unknown mode is refused with the allowed list")
check(copilot.henry_pmode() == start, "refused call left the mode untouched")

r = copilot_actions._run_action({"type": "hands_mode", "mode": "plan"}, actor="owner", role="owner")
check("bypassPermissions -> plan" in r, "owner drops Henry to plan: %r" % r[:90])
check(copilot.henry_pmode() == "plan", "henry_pmode() now reads plan - the next spawn gets it")

r = copilot_actions._run_action({"type": "hands_mode", "mode": "bypassPermissions"}, actor="owner", role="owner")
check(copilot.henry_pmode() == "bypassPermissions", "and back to full hands")

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails))
    sys.exit(1)
print("hands-mode: all pinned - PASS")
