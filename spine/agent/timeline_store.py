# -*- coding: utf-8 -*-
"""Event-time card-feed store - the driver's own pump folds each stream event
into this AS IT HAPPENS, instead of the feed being reconstructed later by
re-parsing Claude Code's private ~/.claude/projects/**.jsonl
(claude_sessions.read_transcript). Pays the debt registered at
spine/registry/debt.py:card-feed-is-claude-private-jsonl - and follows
the SAME fold-at-event-time discipline already proven in this codebase by
drivers.py's _scan_bg/_bg_open (background-task registry) and
sessions.record_bg: derived from the runtime's own signal, one owner, never
reconstructed by re-scanning an artifact afterward.

STORE (state-into-db phase F, 2026-09-12): the `timeline` table, one row per
patch, scoped by run_id = the run directory's basename (a card's id). Ledger
step 9 imported every recordings/<run>/timeline.jsonl (82k lines, 54.6 MB -
the largest file store this tree had). The read is O(delta) by construction
now: the fold cache remembers the last `seq` it folded and asks the table
for rows past it.

FORMAT: append-only, one row per write - (step_id, patch). A step's FIRST
write carries its full TStep-shaped fields (the SAME shape claude_sessions.
read_transcript already produces; surfaces/app/src/ui/card_transcript.tsx's
TStep interface is the unchanged contract). A LATER write with the SAME
step_id is a PARTIAL PATCH (e.g. a running tool call receiving its result) -
read() folds every row sharing a step_id via dict.update, in seq order, so a
patch only needs to carry the fields that changed. This is why it stays
genuinely append-only: the update is a new row, not a mutation of the old one.
"""
import threading

from spine.ops.runs import run_id_of

_lock = threading.Lock()

# Incremental fold cache: {run_id: {"seq", "order", "folded"}}. A live card's
# long-poll re-reads this every ~0.35s while a turn is producing; the cache
# folds only rows past the last seen seq. Kept for the life of the daemon
# process, one entry per run ever read - bounded in practice (one per card).
_cache = {}


def append(run_dir, step_id, patch):
    """Append one patch row for step_id. Best-effort: a feed write must
    never break a turn - callers are inside the driver's hot event path."""
    rid = run_id_of(run_dir)
    if not rid or not step_id:
        return
    try:
        from spine.storage import db
        db.timeline_append(rid, step_id, dict(patch))
    except Exception:                                            # noqa: BLE001
        pass


def read(run_dir, limit=400):
    """All steps, folded: every row sharing a step_id is dict.update()'d in
    seq order into one record, so a later partial patch only overrides the
    fields it carries. A step keeps its FIRST-SEEN position (a running tool
    does not jump to the bottom of the feed when it completes).

    Incremental: a per-run cache remembers the last seq already folded, so a
    live tick only reads APPENDED rows - same fold semantics, O(delta)
    instead of O(history)."""
    rid = run_id_of(run_dir)
    if not rid:
        return []
    from spine.storage import db
    with _lock:
        entry = _cache.get(rid)
        if entry is None:
            entry = {"seq": 0, "order": [], "folded": {}}
        try:
            rows = db.timeline_since(rid, entry["seq"])
        except Exception:                                        # noqa: BLE001
            rows = []
        for seq, sid, rec in rows:
            if sid not in entry["folded"]:
                entry["order"].append(sid)
                entry["folded"][sid] = {}
            entry["folded"][sid].update(rec)
            entry["seq"] = seq
        _cache[rid] = entry
        # Slice BEFORE copying: the cache holds the run's whole history, and
        # copying every step on every tick would silently reintroduce an
        # O(history) cost on the return path - callers only ever want the
        # last `limit` anyway.
        sel = entry["order"][-limit:] if limit else entry["order"]
        # shallow copies: callers (claude_sessions.read_transcript_store)
        # mutate returned step dicts in place (the abandoned-tool relabel) -
        # handing out the cache's own dicts would let that mutation leak
        # into the next read instead of staying a per-call view.
        steps = [dict(entry["folded"][sid]) for sid in sel]
    return steps


def forget(run_dir):
    """Drop the fold cache for a run (tests that reuse a run id across
    sandboxes; a card whose rows were cleared)."""
    with _lock:
        _cache.pop(run_id_of(run_dir), None)
