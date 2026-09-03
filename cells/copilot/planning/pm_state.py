# -*- coding: utf-8 -*-
"""PM presence/loopstate SERVICE - extracted from pm.py. touch() (every
authenticated request marks presence - the loop yields to a human who is
looking), the loopstate file (loop.json), and the window/idle predicates
(_in_window/_board_idle) that gate whether the daily loop may run at all.
Depends on sessions.list_tracks (lazy, no cycle). pm.py re-imports the
names; pm.touch() (called from server.py on every authenticated request)
is unchanged since that call is module-qualified.
"""
import os
import json
import time

# same source-of-truth as pm.{ROOT,PLANS} - process-idempotent directory
# join, safe to compute independently rather than importing pm (would cycle).
from daemon.paths import DAEMON_ROOT as ROOT
PLANS = os.path.join(ROOT, "pm")


LOOPSTATE = os.path.join(PLANS, "loop.json")
_last_touch = 0.0


def touch():
    """Every authenticated request calls this - any surface you look at (phone,
    desktop, glasses) counts as presence, so the loop yields to you."""
    global _last_touch
    _last_touch = time.time()


def _loopstate():
    try:
        with open(LOOPSTATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_loopstate(s):
    os.makedirs(PLANS, exist_ok=True)
    with open(LOOPSTATE, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=1)


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
