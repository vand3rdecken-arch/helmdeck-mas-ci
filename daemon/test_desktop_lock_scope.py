# -*- coding: utf-8 -*-
"""Pins the scope of the single global desktop lock (narrowed 2026-08-17).

The lock (_desktop_lock in sessions._turn) is the mutual-exclusion for real
Windows cursor/keyboard/screen control: only one card may drive it at a time.
It used to be armed by a raw substring test - ANY allowed_tools pattern
containing 'windows-mcp' locked, so even a passive `mcp__windows-mcp__Screenshot`
card took the exclusive cursor lock and could starve a real driver for the whole
turn. `_uses_desktop_control` now exempts read-only screen tools while staying
FAIL-SAFE: a wildcard grant, or any tool not on the read-only allowlist, still
locks so an unknown/new control tool can never silently bypass the guard.

Run: py -3.12 daemon/test_desktop_lock_scope.py
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cells.engineer import sessions

D = sessions._uses_desktop_control

def cfg(*tools):
    return {"allowed_tools": list(tools)}

def check(desc, expected, got):
    assert got == expected, f"{desc}: expected {expected}, got {got}"
    print(f"  ok: {desc}")

# --- non-desktop cards never lock -----------------------------------------
check("no allowed_tools", False, D({}))
check("code card (no windows-mcp)", False, D(cfg("Bash", "Edit", "Read")))

# --- control grants lock ---------------------------------------------------
check("wildcard windows-mcp locks", True, D(cfg("mcp__windows-mcp__*")))
check("Click locks", True, D(cfg("mcp__windows-mcp__Click")))
check("Type locks", True, D(cfg("mcp__windows-mcp__Type")))
check("mixed read + control locks", True,
      D(cfg("mcp__windows-mcp__Screenshot", "mcp__windows-mcp__Click")))

# --- read-only-only cards do NOT lock -------------------------------------
check("Screenshot only does not lock", False,
      D(cfg("mcp__windows-mcp__Screenshot")))
check("read-only set does not lock", False,
      D(cfg("mcp__windows-mcp__Snapshot", "mcp__windows-mcp__Scrape",
            "mcp__windows-mcp__DisplayInventory")))
check("read-only alongside non-desktop tools does not lock", False,
      D(cfg("Read", "mcp__windows-mcp__Screenshot")))

# --- fail-safe: unknown/new windows-mcp tool locks ------------------------
check("unknown windows-mcp tool locks (fail-safe)", True,
      D(cfg("mcp__windows-mcp__SomeNewControlTool")))

print("PASS test_desktop_lock_scope")
