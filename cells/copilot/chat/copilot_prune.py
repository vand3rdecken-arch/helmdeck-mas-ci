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

AGE IS COUNTED IN OWNER TURNS, not user records. Measured on the real board
transcript (101 MB, 2026-09-15): 732 real owner turns sat next to 497
keepalive systemcheck pings, 150 meta records and ~100 slash-command
envelopes - all `type=user`. A counter that took every user record as a
turn would have called a tool result "6 turns old" after ~3 real questions
plus twenty idle minutes. claude_sessions._is_steer is the ONE owner of
"is this a human turn" (meta, sidechain, envelopes, tool submissions all
excluded); the hidden ping text is passed in by copilot.py, which owns it.

STREAMING, because that same file is 101 MB: only lines that can matter
are json-parsed (user records, and assistant records carrying a tool_use
for the placeholder's tool name), transiently; everything else passes
through as the raw bytes it came in as.

NO MONKEY PATCHES: this module never guesses a token count from a byte
count. It only ever reports what it actually did (blocks pruned, bytes
freed) - the ctx_tokens meter's one owner stays copilot_stats._fold_stats,
fed by the runtime's own next usage event.
"""
import json
import os
import re
import shutil

MARK_CTX = 60_000     # only worth running once the session is at least this big
TURN_AGE = 6          # a tool_result younger than this (in owner turns) stays whole
MIN_BYTES = 2_000     # ...and only if it was big enough to matter

# Cheap pre-filters so a 100 MB transcript is not fully parsed on every
# pass. Whitespace-tolerant on purpose: Claude Code writes compact JSON
# today, but a serialization change must not silently turn pruning into a
# no-op (it would look exactly like "nothing to prune").
_USER_LINE = re.compile(r'"type"\s*:\s*"user"')
_ASSISTANT_LINE = re.compile(r'"type"\s*:\s*"assistant"')
_TOOL_USE = '"tool_use"'


def _tool_result_size(content):
    """Byte size of ONE tool_result's content, whatever shape it is (a plain
    string, or a list of text/image blocks)."""
    if isinstance(content, str):
        return len(content.encode("utf-8", "replace"))
    try:
        return len(json.dumps(content, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        return 0


def _load(line):
    try:
        d = json.loads(line)
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def _is_tool_submit(content):
    return isinstance(content, list) and bool(content) and all(
        isinstance(p, dict) and p.get("type") == "tool_result" for p in content)


def prune_lines(lines, turn_age=TURN_AGE, min_bytes=MIN_BYTES, hidden=()):
    """(lines, n_pruned, bytes_saved) over raw .jsonl lines. Only tool_result
    blocks older than `turn_age` OWNER turns AND bigger than `min_bytes` are
    touched; every other line comes back as the identical string it went in
    as. `hidden` = text prefixes of harness turns that must not count as an
    owner turn (copilot.py passes its keepalive ping)."""
    from spine.agent.claude_sessions import _is_steer, _first_text
    hidden = tuple(hidden)
    tool_names = {}       # tool_use_id -> name, read off the assistant's own call
    turn = -1
    cands = []            # (line index, owner turn, record) of big tool submissions
    for i, ln in enumerate(lines):
        if _USER_LINE.search(ln):
            d = _load(ln)
            if d is None or d.get("type") != "user":
                continue
            c = (d.get("message") or {}).get("content")
            if _is_tool_submit(c):
                if any(_tool_result_size(p.get("content")) > min_bytes for p in c):
                    cands.append((i, turn, d))
            elif _is_steer(d) and not (hidden and _first_text(c).lstrip().startswith(hidden)):
                turn += 1
        elif _TOOL_USE in ln and _ASSISTANT_LINE.search(ln):
            d = _load(ln)
            c = (d.get("message") or {}).get("content") if d else None
            for p in c if isinstance(c, list) else []:
                if isinstance(p, dict) and p.get("type") == "tool_use":
                    tool_names[p.get("id")] = p.get("name") or "tool"
    out = list(lines)
    n_pruned, bytes_saved = 0, 0
    for i, t, d in cands:
        if turn - t <= turn_age:
            continue
        m = d["message"]
        parts = []
        for p in m["content"]:
            size = _tool_result_size(p.get("content"))
            if size > min_bytes:
                placeholder = "[gekürzt: %s, %dkb, Turn %d]" % (
                    tool_names.get(p.get("tool_use_id")) or "tool", max(1, round(size / 1024)), t)
                bytes_saved += size - len(placeholder.encode("utf-8"))
                p = dict(p, content=placeholder)
                n_pruned += 1
            parts.append(p)
        out[i] = json.dumps(dict(d, message=dict(m, content=parts)), ensure_ascii=False)
    return out, n_pruned, bytes_saved


def prune_session_file(path, turn_age=TURN_AGE, min_bytes=MIN_BYTES, hidden=()):
    """Rewrite ONE session .jsonl in place. (n_pruned, bytes_saved) on a
    write, or None if the file couldn't be read. Writing zero pruned blocks
    is a no-op (no backup, no replace) - most calls above the ctx mark find
    nothing new to do, and that must stay cheap.

    ATOMIC WITH BACKUP, same discipline as every other file this repo
    rewrites in place (copilot.py's _ports_update: tmp + os.replace) plus
    ONE extra step this file's stakes justify - a `path + '.pre-prune'` copy
    made BEFORE the replace, so a bad rewrite of Henry's own memory is one
    `shutil.copy2` away from undone, not a bug report away. Measured
    2026-09-15: an idle warm `claude -p` process holds no handle on its
    transcript, so the replace succeeds under it and its next turn appends
    to the new file on the same session id.

    KNOWN CEILING: the backup is ONE generation. A second prune run
    overwrites it with the file as THIS prune leaves it (already carrying
    the earlier run's placeholders), so recovery only ever reaches back to
    the last prune, not the raw original beyond that."""
    # Line by line, never one f.read(): CPython widens a str to 4 bytes per
    # char if ANY char needs it, so one emoji anywhere turned the 101 MB
    # board transcript into a ~400 MB string (measured: 708 MB peak). Per
    # line, only the lines that carry such a char pay for it.
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = [ln.rstrip("\r\n") for ln in f if ln.strip()]
    except OSError:
        return None
    lines, n, saved = prune_lines(lines, turn_age, min_bytes, hidden)
    if n == 0:
        return (0, 0)
    shutil.copy2(path, path + ".pre-prune")
    tmp = path + ".tmp-prune"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        for ln in lines:                  # same reason as the read: no giant join
            f.write(ln)
            f.write("\n")
    os.replace(tmp, path)
    return (n, saved)
