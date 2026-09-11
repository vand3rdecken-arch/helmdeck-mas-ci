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

DUAL-WRITE STAGE (ops/docs/multi-engine-build-plan.md Card 2): drivers.py calls
append() from _ClaudeSession._on_event/_fold_timeline; nothing reads this
store in production yet. /transcript still serves claude_sessions.
read_transcript_live(). Cutover happens only after ops/tools/compare_timeline.py
shows N clean live turns with an empty diff.

FORMAT: append-only JSONL, one line per write - `{"_id": step_id, **patch}`.
A step's FIRST write carries its full TStep-shaped fields (the SAME shape
claude_sessions.read_transcript already produces; surfaces/app/src/ui/card_transcript.
tsx's TStep interface is the unchanged contract). A LATER write with the SAME
_id is a PARTIAL PATCH (e.g. a running tool call receiving its result) -
read() folds every line sharing an _id via dict.update, in file order, so a
patch only needs to carry the fields that changed. This is why it stays
genuinely append-only (like events.jsonl/actionlog) instead of needing an
in-place file rewrite to represent "this tool call finished": the update is
a new line, not a mutation of the old one.
"""
import json
import os
import threading

FILENAME = "timeline.jsonl"
_lock = threading.Lock()

# Incremental fold cache (chat-load-latency phase B): {path: {"offset", "order",
# "folded"}}, one entry per run_dir's timeline.jsonl. A live card's long-poll
# re-reads this file every ~0.35s while a turn is producing (the SAME file
# every tick), and the file itself grows to 1-2+ MB over a long turn - a full
# re-parse on every tick was the O(history) cost this pays down to O(delta).
# Kept for the life of the daemon process, one entry per run_dir ever read -
# no eviction. That is bounded in practice (one entry per card, and cards are
# finite), but a daemon that never restarts across a very long history will
# hold a folded transcript in memory for every card anyone has ever opened,
# not just active ones. Fine for now (matches the "no debt entry" call in the
# card doc); revisit if that ever shows up as real memory pressure.
_cache = {}


def _path(run_dir):
    return os.path.join(run_dir, FILENAME) if run_dir else None


def append(run_dir, step_id, patch):
    """Append one patch line for step_id. Best-effort: a feed write must
    never break a turn - callers are inside the driver's hot event path."""
    path = _path(run_dir)
    if not path or not step_id:
        return
    rec = dict(patch)
    rec["_id"] = step_id
    try:
        with _lock:
            # run_dir can go missing out from under a live card (found live
            # 2026-08-27: an external wipe of daemon/recordings/ left this
            # swallowing every subsequent write via the bare `except OSError`
            # below - the turn kept running with no error, but the feed was
            # silently gone from that point on). Recreate it so recording
            # resumes instead of vanishing quietly.
            os.makedirs(run_dir, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, default=str) + "\n")
    except OSError:
        pass


def read(run_dir, limit=400):
    """All steps, folded: every line sharing an _id is dict.update()'d in
    file order into one record, so a later partial patch only overrides the
    fields it carries. A step keeps its FIRST-SEEN position (a running tool
    does not jump to the bottom of the feed when it completes). Strips the
    internal _id before returning - callers see pure TStep dicts.

    Incremental (chat-load-latency phase B): a per-path cache remembers the
    byte offset already folded, so a live tick only parses APPENDED bytes,
    not the whole file - same fold semantics, O(delta) instead of
    O(history). A file that shrank (truncated/recreated - e.g. an external
    wipe of the run_dir, see the recordings-wipe-root-cause incident) is
    rebuilt from byte 0, same as a cold cache."""
    path = _path(run_dir)
    if not path or not os.path.exists(path):
        return []
    with _lock:
        try:
            size = os.path.getsize(path)
        except OSError:
            return []
        entry = _cache.get(path)
        if entry is None or size < entry["offset"]:
            entry = {"offset": 0, "order": [], "folded": {}}
        if size > entry["offset"]:
            try:
                with open(path, "rb") as f:
                    f.seek(entry["offset"])
                    chunk = f.read()
            except OSError:
                chunk = b""
            pos = 0
            while True:
                nl = chunk.find(b"\n", pos)
                if nl == -1:
                    break   # incomplete tail line (writer mid-flush) - leave
                             # it unconsumed, the next read picks it up whole
                line = chunk[pos:nl].decode("utf-8", errors="replace").strip()
                pos = nl + 1
                if line:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        rec = None
                    if rec is not None:
                        sid = rec.pop("_id", None)
                        if sid is not None:
                            if sid not in entry["folded"]:
                                entry["order"].append(sid)
                                entry["folded"][sid] = {}
                            entry["folded"][sid].update(rec)
            entry["offset"] += pos
        _cache[path] = entry
        # Slice BEFORE copying: the cache holds the run's whole history, and
        # copying every step on every tick would silently reintroduce an
        # O(history) cost on the return path even with the fold itself now
        # O(delta) - callers only ever want the last `limit` anyway.
        sel = entry["order"][-limit:] if limit else entry["order"]
        # shallow copies: callers (claude_sessions.read_transcript_store)
        # mutate returned step dicts in place (the abandoned-tool relabel) -
        # handing out the cache's own dicts would let that mutation leak
        # into the next read instead of staying a per-call view.
        steps = [dict(entry["folded"][sid]) for sid in sel]
    return steps
