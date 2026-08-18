# -*- coding: utf-8 -*-
"""Runtime coordination SERVICE - extracted from sessions.py. The per-track
turn lock, the single global desktop-control lock, per-cwd direct-build
locks, the desktop-control classifier (_uses_desktop_control), and the
steer epoch (interrupt-and-replace last-wins). All state is private here;
sessions.py re-imports the functions + _desktop_lock (its _turn acquires it,
and test_desktop_lock_* read sessions._desktop_lock - the same object).
"""
import os
import re as _re
import threading as _threading


_turn_locks = {}
_turn_locks_guard = _threading.Lock()

def _lock_for(tid):
    with _turn_locks_guard:
        if tid not in _turn_locks:
            _turn_locks[tid] = _threading.Lock()
        return _turn_locks[tid]

# Only one card may hold real Windows desktop control (mouse/keyboard/screen)
# at a time - two windows-mcp turns racing would fight over the same cursor.
# A plain in-process lock is the right primitive: _turn() blocks synchronously
# for a whole turn, so the lock's held state IS the running desktop turn -
# never a stored flag that could drift from reality.
_desktop_lock = _threading.Lock()

# windows-mcp tools that only OBSERVE the screen (read pixels/inventory) and
# never move the cursor or type. A card whose ONLY windows-mcp grants are these
# does not contend for the one physical cursor, so it must NOT take the exclusive
# desktop lock - otherwise a passive Screenshot card would starve a real driver.
_WINDOWS_MCP_READONLY = frozenset({
    "Screenshot", "Snapshot", "Scrape", "DisplayInventory",
})

# DIRECT build cards (new_direct_task) edit the repo's LIVE working tree with no
# worktree isolation - two turns on the same tree at once would edit blind over
# each other. Same primitive and same queue semantics as the desktop lock: one
# lock per normalized tree path, held for the synchronous turn, contenders wait
# bounded then bounce visibly. The registry only ever grows by distinct repo
# paths the owner direct-builds in - a handful, never reaped.
_direct_locks = {}
_direct_locks_guard = _threading.Lock()

def _direct_lock_for(cwd):
    key = os.path.normcase(os.path.abspath(cwd or ""))
    with _direct_locks_guard:
        return _direct_locks.setdefault(key, _threading.Lock())


def _uses_desktop_control(cfg):
    """True iff this card can physically drive mouse/keyboard/screen and so must
    hold the single global _desktop_lock. Read-only screen tools (Screenshot,
    Snapshot, ...) are exempted. FAIL-SAFE: a wildcard windows-mcp grant, or any
    tool not on the read-only allowlist, locks - so a new/unknown control tool
    can never silently bypass the guard and race the cursor."""
    for pat in (cfg.get("allowed_tools") or []):
        s = str(pat)
        if "windows-mcp" not in s:
            continue
        tail = s.rsplit("__", 1)[-1]        # tool name after mcp__windows-mcp__
        if "*" in tail:                     # wildcard: could be any tool -> lock
            return True
        if tail not in _WINDOWS_MCP_READONLY:   # a control tool -> lock
            return True
    return False

# INTERRUPT-AND-REPLACE (Paseo parity). A steer that arrives mid-turn must take
# effect NOW - Paseo's replaceAgentRun soft-interrupts the live turn and starts
# the new prompt on the same session. HelmDeck used to QUEUE it behind the whole
# running turn (the per-card _lock_for), so a second message only landed minutes
# later. This epoch collapses a burst of steers to LAST-WINS: each steer bumps
# it, and only the newest actually runs its turn - the rest bail after the
# interrupt fires. (The soft interrupt itself is drivers.cancel, the P1 port.)
_steer_epoch = {}
_steer_pending = {}                 # tid -> [text, ...] of the burst (nothing lost)
_steer_epoch_guard = _threading.Lock()


def _bump_steer_epoch(tid, text=None):
    """Bump the epoch AND register this steer's text atomically. A superseded
    steer's text stays in the pending list, so the WINNING steer bundles every
    instruction into its one turn - a burst collapses without a single command
    silently disappearing ("why did my command disappear")."""
    with _steer_epoch_guard:
        _steer_epoch[tid] = _steer_epoch.get(tid, 0) + 1
        if text is not None:
            _steer_pending.setdefault(tid, []).append(text)
        return _steer_epoch[tid]


def _steer_epoch_current(tid):
    with _steer_epoch_guard:
        return _steer_epoch.get(tid, 0)


def _drain_steer_texts(tid):
    with _steer_epoch_guard:
        return _steer_pending.pop(tid, [])
