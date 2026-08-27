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
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, default=str) + "\n")
    except OSError:
        pass


def read(run_dir, limit=400):
    """All steps, folded: every line sharing an _id is dict.update()'d in
    file order into one record, so a later partial patch only overrides the
    fields it carries. A step keeps its FIRST-SEEN position (a running tool
    does not jump to the bottom of the feed when it completes). Strips the
    internal _id before returning - callers see pure TStep dicts."""
    path = _path(run_dir)
    if not path or not os.path.exists(path):
        return []
    order = []
    folded = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                sid = rec.pop("_id", None)
                if sid is None:
                    continue
                if sid not in folded:
                    order.append(sid)
                    folded[sid] = {}
                folded[sid].update(rec)
    except OSError:
        return []
    steps = [folded[sid] for sid in order]
    return steps[-limit:]
