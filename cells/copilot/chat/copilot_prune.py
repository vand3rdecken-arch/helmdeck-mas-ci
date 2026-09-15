# -*- coding: utf-8 -*-
"""Henry's session .jsonl carries every tool_result it has ever produced.
The built-in /compact (copilot.py's _maybe_compact) throws away TEXT by
summarizing, but it reads the WHOLE transcript to write that summary - old,
big tool_result blocks ride along and are the reason Henry's post-compact
floor is still ~100k tokens (measured 2026-09-15) instead of the ~25k the
snapshot+persona+tools actually cost.

This is the SECOND, INDEPENDENT cleanup card 'chat-henry-kontext-pruning'
asked for: shrink old, big tool_result blocks IN PLACE, between turns, long
before a session is anywhere near the compaction mark. Pure/testable logic
lives here (god-file breakup precedent: copilot_stats.py); the scheduling
that touches the live warm process and the turn lock stays in copilot.py,
same split.

NO MONKEY PATCHES: this module never guesses a token count from a byte
count. It only ever reports what it actually did (blocks pruned, bytes
freed) - the ctx_tokens meter's one owner stays copilot_stats._fold_stats,
fed by the runtime's own next usage event.
"""
import json
import os
import shutil

MARK_CTX = 60_000     # only worth running once the session is at least this big
TURN_AGE = 6          # a tool_result younger than this (in turns) stays whole
MIN_BYTES = 2_000     # ...and only if it was big enough to matter


def _turn_index(records):
    """One turn number per record. Bumps BEFORE any user record that is a
    NEW instruction - not a tool_result being submitted back to continue the
    SAME turn (stream-json submits those as role=user too)."""
    idx = -1
    out = []
    for d in records:
        if isinstance(d, dict) and d.get("type") == "user":
            c = (d.get("message") or {}).get("content")
            is_submit = isinstance(c, list) and bool(c) and all(
                isinstance(p, dict) and p.get("type") == "tool_result" for p in c)
            if not is_submit:
                idx += 1
        out.append(idx)
    return out


def _tool_result_size(content):
    """Byte size of ONE tool_result's content, whatever shape it is (a plain
    string, or a list of text/image blocks)."""
    if isinstance(content, str):
        return len(content.encode("utf-8", "replace"))
    try:
        return len(json.dumps(content, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        return 0


def prune_records(records, turn_age=TURN_AGE, min_bytes=MIN_BYTES):
    """(records, n_pruned, bytes_saved). Only tool_result blocks older than
    `turn_age` turns AND bigger than `min_bytes` are touched; every user/
    assistant TEXT record, and every tool_result that doesn't clear both
    bars, comes back byte-identical. Records are copied, never mutated in
    place, so a caller holding the original list sees no side effect."""
    turns = _turn_index(records)
    now_turn = turns[-1] if turns else 0
    tool_names = {}      # tool_use_id -> name, read off the assistant's own call
    for d in records:
        if not isinstance(d, dict):
            continue
        content = (d.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for p in content:
            if isinstance(p, dict) and p.get("type") == "tool_use":
                tool_names[p.get("id")] = p.get("name") or "tool"

    n_pruned, bytes_saved = 0, 0
    out = []
    for d, t in zip(records, turns):
        if (not isinstance(d, dict) or d.get("type") != "user"
                or now_turn - t <= turn_age):
            out.append(d)
            continue
        m = d.get("message")
        content = m.get("content") if isinstance(m, dict) else None
        if not isinstance(content, list):
            out.append(d)
            continue
        changed, new_parts = False, []
        for p in content:
            if isinstance(p, dict) and p.get("type") == "tool_result":
                size = _tool_result_size(p.get("content"))
                if size > min_bytes:
                    tool = tool_names.get(p.get("tool_use_id")) or "tool"
                    placeholder = "[gekürzt: %s, %dkb, Turn %d]" % (
                        tool, max(1, round(size / 1024)), t)
                    bytes_saved += size - len(placeholder.encode("utf-8"))
                    p = dict(p, content=placeholder)
                    n_pruned += 1
                    changed = True
            new_parts.append(p)
        out.append(dict(d, message=dict(m, content=new_parts)) if changed else d)
    return out, n_pruned, bytes_saved


def prune_session_file(path, turn_age=TURN_AGE, min_bytes=MIN_BYTES):
    """Rewrite ONE session .jsonl in place. (n_pruned, bytes_saved) on a
    write, or None if the file couldn't be read. Writing zero pruned blocks
    is a no-op (no backup, no replace) - most calls above the ctx mark find
    nothing new to do, and that must stay cheap.

    ATOMIC WITH BACKUP, same discipline as every other file this repo
    rewrites in place (copilot.py's _ports_update: tmp + os.replace) plus
    ONE extra step this file's stakes justify - a `path + '.pre-prune'` copy
    made BEFORE the replace, so a bad rewrite of Henry's own memory is one
    `shutil.copy2` away from undone, not a bug report away.

    KNOWN CEILING: the backup is ONE generation. A second prune run
    overwrites it with the file as THIS prune leaves it (already carrying
    the earlier run's placeholders), so recovery only ever reaches back to
    the last prune, not the raw original beyond that."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = [ln for ln in f.read().split("\n") if ln.strip()]
    except OSError:
        return None
    slots = []             # (line_index, record) for every line that parsed
    for i, ln in enumerate(lines):
        try:
            slots.append((i, json.loads(ln)))
        except ValueError:
            continue        # an unparseable line is left exactly as it was
    pruned, n, saved = prune_records([r for _, r in slots], turn_age, min_bytes)
    if n == 0:
        return (0, 0)
    # only rewrite lines that ACTUALLY changed (identity check against the
    # original record) - re-serializing an untouched record through
    # json.dumps can reformat it slightly differently from however Claude
    # Code itself wrote the line, which would silently grow the file instead
    # of shrinking it and breaks the "everything else comes back
    # byte-identical" promise.
    for (i, orig), rec in zip(slots, pruned):
        if rec is not orig:
            lines[i] = json.dumps(rec, ensure_ascii=False)
    shutil.copy2(path, path + ".pre-prune")
    tmp = path + ".tmp-prune"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)
    return (n, saved)
