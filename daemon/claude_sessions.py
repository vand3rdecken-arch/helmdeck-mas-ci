# -*- coding: utf-8 -*-
"""Read the user's EXISTING Claude Code sessions from ~/.claude/projects so
SwarmDeck can list and continue them - the Paseo 'session import' idea. A real
Claude Code session is a <uuid>.jsonl transcript under
~/.claude/projects/<encoded-cwd>/; `claude --resume <uuid>` continues it. We
surface: id (uuid), cwd, project label, first user message, last activity.
Nothing here mutates the sessions - it only reads them."""
import json, os, time

HOME = os.path.expanduser("~")
PROJECTS = os.path.join(HOME, ".claude", "projects")
HEAD_LINES = 60          # enough to find cwd + the first user message
MAX = 40                 # most-recent sessions
# SwarmDeck's own spawned sessions (copilot, process designer) - not the user's
# coding sessions, so hide them from the import list.
_INTERNAL = ("You are the SwarmDeck board copilot", "You are a process designer")


def _first_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                return part.get("text") or ""
    return ""


def _peek(path):
    """Read the head of a transcript for cwd + first user message (cheap)."""
    cwd, first = None, None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= HEAD_LINES and cwd and first:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                cwd = cwd or d.get("cwd")
                m = d.get("message")
                if first is None and isinstance(m, dict) and m.get("role") == "user":
                    t = _first_text(m.get("content")).strip()
                    if t and not t.startswith("<"):     # skip tool/system envelopes
                        first = t
    except OSError:
        pass
    return cwd, first


def list_sessions(limit=MAX):
    """All Claude Code sessions, most-recently-active first. Skips SwarmDeck's
    own worktree sessions (those are already cards)."""
    out = []
    if not os.path.isdir(PROJECTS):
        return out
    for proj in os.listdir(PROJECTS):
        pdir = os.path.join(PROJECTS, proj)
        if not os.path.isdir(pdir):
            continue
        for fn in os.listdir(pdir):
            if not fn.endswith(".jsonl"):
                continue
            path = os.path.join(pdir, fn)
            try:
                mtime = os.path.getmtime(path)
                size = os.path.getsize(path)
            except OSError:
                continue
            if size < 200:              # empty/aborted transcript
                continue
            cwd, first = _peek(path)
            if cwd and "swarmdeck-worktrees" in cwd.replace("/", "\\"):
                continue                # SwarmDeck-managed - already a card
            if first and first.startswith(_INTERNAL):
                continue                # SwarmDeck's own copilot/process session
            out.append({
                "id": fn[:-6],          # strip .jsonl -> the session uuid
                "cwd": cwd or "",
                "project": os.path.basename(cwd) if cwd else proj,
                "first": (first or "")[:160],
                "last_active": time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime)),
                "mtime": mtime,
            })
    out.sort(key=lambda s: s["mtime"], reverse=True)
    return out[:limit]


# --- full turn-by-turn transcript of a session (the Paseo agent view) --------
_TOOL_KEYS = ("command", "file_path", "path", "url", "pattern", "query",
              "prompt", "description", "notebook_path", "old_string")


def _find_transcript(session_id):
    if not session_id or not os.path.isdir(PROJECTS):
        return None
    for proj in os.listdir(PROJECTS):
        cand = os.path.join(PROJECTS, proj, session_id + ".jsonl")
        if os.path.exists(cand):
            return cand
    return None


def _tail_lines(path, max_bytes=1_200_000):
    """Read only the last ~max_bytes so a huge transcript doesn't blow up polls."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        if size > max_bytes:
            f.seek(size - max_bytes)
        data = f.read()
    lines = data.decode("utf-8", "replace").split("\n")
    return lines[1:] if size > max_bytes else lines   # drop the partial first line


def _tool_summary(inp):
    inp = inp or {}
    for k in _TOOL_KEYS:
        v = inp.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()[:160]
    return ", ".join(list(inp.keys())[:3])


def read_transcript(session_id, limit=400):
    """Parse a session's jsonl into ordered steps for the card's agent view:
    each is {role, kind: text|thinking|tool|result, text?, tool?}. Human steers,
    the agent's replies, and every tool call/result - like Paseo's turn view."""
    path = _find_transcript(session_id)
    if not path:
        return []
    steps = []
    for line in _tail_lines(path):
        line = line.strip()
        if not line:
            continue
        try:
            d = __import__("json").loads(line)
        except ValueError:
            continue
        if d.get("type") not in ("user", "assistant"):
            continue
        m = d.get("message")
        if not isinstance(m, dict):
            continue
        role = m.get("role") or d.get("type")
        content = m.get("content")
        if isinstance(content, str):
            if content.strip():
                steps.append({"role": role, "kind": "text", "text": content.strip()[:4000]})
            continue
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            pt = part.get("type")
            if pt == "text" and (part.get("text") or "").strip():
                steps.append({"role": role, "kind": "text", "text": part["text"].strip()[:4000]})
            elif pt == "thinking" and (part.get("thinking") or "").strip():
                steps.append({"role": role, "kind": "thinking", "text": part["thinking"].strip()[:1200]})
            elif pt == "tool_use":
                steps.append({"role": role, "kind": "tool", "tool": part.get("name") or "tool",
                              "text": _tool_summary(part.get("input"))})
            elif pt == "tool_result":
                c = part.get("content")
                txt = c if isinstance(c, str) else (
                    " ".join(p.get("text", "") for p in c if isinstance(p, dict)) if isinstance(c, list) else "")
                steps.append({"role": "user", "kind": "result", "text": (txt or "").strip()[:600]})
    return steps[-limit:]
