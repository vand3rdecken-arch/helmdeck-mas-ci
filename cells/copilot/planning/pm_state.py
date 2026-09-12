# -*- coding: utf-8 -*-
"""PM presence/loopstate SERVICE - extracted from pm.py. touch() (every
authenticated request marks presence - the loop yields to a human who is
looking), the loopstate file (loop.json), and the window/idle predicates
(_in_window/_board_idle) that gate whether the daily loop may run at all.
Depends on sessions.list_tracks (lazy, no cycle). pm.py re-imports the
names; pm.touch() (called from server.py on every authenticated request)
is unchanged since that call is module-qualified.
"""
import time

# The loop state is the runtime_doc row "pm_loop" (state-into-db phase D,
# 2026-09-12; ledger step 7 imported daemon/pm/loop.json). It used to be a
# file read-modify-written by every ladder step from several threads - the
# race registered as debt pm-loopstate-races. A row written in one
# transaction has no such window; a caller that must fold (read+write) uses
# update_loopstate().
_LOOP_KEY = "pm_loop"
_last_touch = 0.0


def touch():
    """Every authenticated request calls this - any surface you look at (phone,
    desktop, glasses) counts as presence, so the loop yields to you."""
    global _last_touch
    _last_touch = time.time()


def _loopstate():
    from spine.storage import db
    return db.doc_get(_LOOP_KEY, {}) or {}


def _save_loopstate(s):
    from spine.storage import db
    db.doc_put(_LOOP_KEY, s)


def update_loopstate(fn):
    """fn(state) -> state, applied inside ONE write transaction."""
    from spine.storage import db
    return db.doc_update(_LOOP_KEY, fn, default={})


def _today():
    return time.strftime("%Y%m%d")


def _in_window(pm):
    w = (pm.get("window") or "").strip().lower()
    if w in ("", "always"):
        return True
    try:
        a, b = w.split("-")
        now = time.strftime("%H:%M")
        return a <= now < b if a <= b else (now >= a or now < b)
    except ValueError:
        return False


def _board_idle(pm):
    """Idle = nothing running and no presence for idle_minutes. The gate that
    makes the loop non-competitive: it never runs while you are around."""
    from cells.engineer.cards import sessions
    for t in sessions.list_tracks():
        if t.get("status") == "running":
            return False
    return time.time() - _last_touch >= pm.get("idle_minutes", 20) * 60
