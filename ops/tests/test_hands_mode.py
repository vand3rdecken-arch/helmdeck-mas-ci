# -*- coding: utf-8 -*-
"""The OWNER picks Henry's permission mode from the composer's Mode row
(owner 2026-09-12: "ich will bypass auswaehlen, warum soll das Henry
machen") - Henry has no verb to change it himself. This pins the one writer
(copilot.set_hands_mode) and that henry_pmode() reads the pick back for the
next spawn. Sandboxed db with a default repo (the rule is per-project).
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
events.save_settings({"default_repo": SANDBOX}, actor="test")
from cells.copilot.chat import copilot, copilot_actions  # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


check(copilot.henry_pmode() == "auto", "default is auto (owner 2026-09-12: nur fragen wenn notwendig)")
before, err = copilot.set_hands_mode("root", actor="owner")
check(err and "muss einer von" in err, "unknown mode refused")
before, err = copilot.set_hands_mode("plan", actor="owner")
check(err is None and before == "auto", "owner sets plan: no error, before reported")
check(copilot.henry_pmode() == "plan", "henry_pmode() reads the pick back (project-aware resolve)")
before, err = copilot.set_hands_mode("bypassPermissions", actor="owner")
check(copilot.henry_pmode() == "bypassPermissions", "and back to full hands")
r = copilot_actions._run_action({"type": "hands_mode", "mode": "plan"}, actor="owner", role="owner")
before, err = copilot.set_hands_mode("auto", actor="owner")
check(copilot.henry_pmode() == "auto",
      "Henry has NO hands_mode verb - an attempt changes nothing (%r)" % r[:60])

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails))
    sys.exit(1)
print("hands-mode: all pinned - PASS")
