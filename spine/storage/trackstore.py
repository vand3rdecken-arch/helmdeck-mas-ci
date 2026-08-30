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
from spine.storage import db as _db

from daemon.paths import DAEMON_ROOT as ROOT
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


def _slug_tail(s, limit=40):
    """A slug that never truncates away the END. _slug cuts head-first at 32
    chars - right for a card id (its unique timestamp LEADS) and wrong for a
    card branch (its unique card token TRAILS). _worktree_for maps a branch to
    a directory through a slug, so a head-only cut silently threw the
    uniqueness back away and landed two distinct branches in the SAME worktree
    directory. Keep head AND tail."""
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    if len(s) <= limit:
        return s or "track"
    return (s[:max(1, limit - 16)].strip("-") + "-" + s[-15:]).strip("-") or "track"


# German requests are the norm here, and _slug maps every umlaut to a separator
# ("Aenderung" reads, "-nderung" does not). Fold them before slugging.
_DE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
                     "Ä": "ae", "Ö": "oe", "Ü": "ue"})

# Branch names handed out but not yet persisted (see _card_branch).
_reserved_branches = set()
_reserve_guard = _threading.Lock()


def _card_branch(repo, raw, tid):
    """THE card branch name: <slug of the request>-<card id timestamp>, proven
    free against both the track store and the repo's refs before it is handed out.

    Callers used to derive a branch from the first ~24 characters of the TASK
    TEXT alone. Two cards whose requests START THE SAME WAY - routine here,
    every PRD card opens with the same sentence - therefore got the SAME branch,
    and since _worktree_for maps branch -> directory, the same WORKTREE. On
    2026-08-30 that cost a card its whole session: accepting card
    20260830-065545 reclaimed the shared 'chat-nur-prd-schreiben-kein' tree out
    from under card 20260830-194212, which was live inside it.

    The card id is the one guaranteed-unique thing a card owns at this point, so
    the branch carries it. The freeness loop is not belt-and-braces: the id's own
    suffix is a truncated slug that can collide back into the same string, and a
    branch outlives the card that made it (reclaim keeps unmerged branches), so
    "free" is VERIFIED against both registries rather than assumed from the id.

    The check and the claim happen under _reserve_guard together. Without it the
    lookup is check-then-act: new_track computes the branch BEFORE it saves the
    card, so two cards filed in the same second with the same opening sentence
    both read a store in which neither exists yet - and land on one branch and
    one worktree again, i.e. the exact bug, merely narrowed to a race window.
    The daemon is the only process that files cards, so an in-process
    reservation closes it. Reservations are never released: a name this function
    handed out must stay spent even if that card is later deleted, because its
    branch and worktree can outlive it."""
    from spine.git.gitutil import _branch_exists
    stem = re.sub(r"[^a-z0-9]+", "-", (raw or "").translate(_DE).lower()).strip("-")[:24].strip("-")
    base = ((stem + "-" + tid[:15]) if stem else tid[:15]).strip("-")
    with _reserve_guard:
        taken = {t.get("branch") for t in _load()} | _reserved_branches
        cand, n = base, 2
        while cand in taken or _branch_exists(repo, cand):
            cand, n = "%s-%d" % (base, n), n + 1
        _reserved_branches.add(cand)
    return cand


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
