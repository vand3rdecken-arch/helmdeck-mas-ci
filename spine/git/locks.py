# -*- coding: utf-8 -*-
"""Runtime coordination SERVICE - extracted from sessions.py. The per-track
turn lock, per-cwd direct-build locks, the per-cwd gate singleton, and the
steer epoch (interrupt-and-replace last-wins). All state is private here;
sessions.py re-imports the functions.

The DESKTOP is deliberately NOT here any more (2026-09-22): the single
per-turn cursor lock serialized every machine card (see the docstring of
spine/git/desktop_lease.py, which replaced it with a per-call lease taken by
the card's own guard hook).
"""
import os
import re as _re
import threading as _threading
import time as _time


_turn_locks = {}
_turn_locks_guard = _threading.Lock()

def _lock_for(tid):
    with _turn_locks_guard:
        if tid not in _turn_locks:
            _turn_locks[tid] = _threading.Lock()
        return _turn_locks[tid]

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


# GATE SINGLETON (measured 2026-08-20, Display-Glasses card): a worker blind to
# WHY its gate was slow (box at 100% from a build it couldn't see) started a
# SECOND full gate in the same worktree - two suites then starved each other.
# Same primitive as the direct-build lock, keyed the same way: one lock per
# normalized worktree path, held for the gate's synchronous run, so a second
# request BLOCKS (never stacks beside the first) and then runs its own fresh
# check once the first is done - never two gate subprocesses racing the same
# tree's CPU/disk at once.
_gate_locks = {}
_gate_locks_guard = _threading.Lock()

def _gate_lock_for(cwd):
    key = os.path.normcase(os.path.abspath(cwd or ""))
    with _gate_locks_guard:
        return _gate_locks.setdefault(key, _threading.Lock())


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


# LOAD-AWARE ADMISSION holder registry (ops/docs/backlog/load-aware-admission): the
# desktop lock's pattern generalized from mutual EXCLUSION (only one card may
# drive the cursor) to mutual AWARENESS (several heavy ops may run at once if
# the box has headroom - lanemachine._admit_heavy decides that from OBSERVED
# CPU load, never a stored "busy" flag). This registry's only job is letting a
# QUEUED op's chat note say who it is waiting for, the same courtesy the
# desktop lock's wait note already gives - it holds no lock semantics of its
# own. Pure in-process state, no settings/events dependency, same boundary as
# the rest of this module.
_heavy_holders = {}                 # token -> {"kind", "card", "since"}
_heavy_holders_guard = _threading.Lock()


def _register_heavy(token, kind, card):
    with _heavy_holders_guard:
        _heavy_holders[token] = {"kind": kind, "card": card, "since": _time.time()}


def _release_heavy(token):
    with _heavy_holders_guard:
        _heavy_holders.pop(token, None)


def _heavy_holder_desc():
    """Who is currently burning the box, for a queued op's wait note. A holder
    that just freed only means the waiter's next load sample admits it -
    naming is a courtesy for the owner reading the chat, not a lock, so a
    stale/empty snapshot is never wrong enough to guard against."""
    with _heavy_holders_guard:
        names = ["%s (%s)" % (h["kind"], h["card"]) for h in _heavy_holders.values()]
    return ", ".join(names) if names else "unbekannt/extern (nicht von HelmDeck verfolgt)"


def list_heavy_holders():
    """Snapshot of the registry for observers (Henry's system snapshot) -
    copies, so a reader can never mutate a holder record."""
    with _heavy_holders_guard:
        return [dict(h) for h in _heavy_holders.values()]
