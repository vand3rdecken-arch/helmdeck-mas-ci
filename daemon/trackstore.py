# -*- coding: utf-8 -*-
"""Track store - the daemon's data-layer SERVICE, extracted from sessions.py.
load/save/find + _unique_id + _slug, and _mutate (THE one legal write path:
lock -> fresh load -> fn(t) -> save, one owner). A clean leaf: depends only on
db + stdlib, nothing reaches back into sessions. Every higher module borrows
these instead of re-implementing them, so this is the first real SERVICE the
orchestrator (and its plugins) sit on top of. sessions.py re-imports the names;
the tests patch trackstore._db (moved here with the layer it fakes).
"""
import os
import re
import threading as _threading
import time
import db as _db

ROOT = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(ROOT, "tracks.json")


def _load():
    return _db.tracks_all()

def _save(tracks):
    _db.tracks_replace(tracks)

def _save_track(t):
    _db.track_put(t)

def _find(tracks, tid):
    for t in tracks:
        if t["id"] == tid:
            return t
    return None

def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:32] or "track"

def _unique_id(suffix):
    """Card ids are <timestamp>-<suffix>, and the id is also the PRIMARY KEY and
    the run_dir name. Two cards filed in the SAME SECOND with the same suffix
    used to produce the same id - and track_put is INSERT OR REPLACE, so the
    first card was silently overwritten (its audit + economics gone, its flight
    recorder shared). That is reachable in normal use: every machine task uses
    the branch '(machine)', and the chat can file two in one second. Take the
    next free id instead."""
    base = time.strftime("%Y%m%d-%H%M%S") + "-" + suffix
    tid, n = base, 2
    while _db.track_get(tid) is not None:
        tid = "%s-%d" % (base, n)
        n += 1
    return tid


_mutate_locks = {}
_mutate_locks_guard = _threading.Lock()

def _mutate_lock_for(tid):
    with _mutate_locks_guard:
        if tid not in _mutate_locks:
            _mutate_locks[tid] = _threading.Lock()
        return _mutate_locks[tid]

def _mutate(tid, fn):
    """Atomically edit one track: lock -> fresh load -> fn(t) -> save -> return t.
    fn gets the CURRENT stored track (never a caller's stale snapshot) and may
    return False to skip the save (the no-op / lost-the-race case). Returns the
    track (fresh), or None if the track does not exist. fn must be QUICK - no
    model turns, no subprocesses; compute those before calling _mutate."""
    with _mutate_lock_for(tid):
        t = _find(_load(), tid)
        if t is None:
            return None
        if fn(t) is False:
            return t
        t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save_track(t)
        return t
