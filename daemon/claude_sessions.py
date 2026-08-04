# -*- coding: utf-8 -*-
"""Read the user's EXISTING Claude Code sessions from ~/.claude/projects so
HelmDeck can list and continue them - the Paseo 'session import' idea. A real
Claude Code session is a <uuid>.jsonl transcript under
~/.claude/projects/<encoded-cwd>/; `claude --resume <uuid>` continues it. We
surface: id (uuid), cwd, project label, first user message, last activity.
Nothing here mutates the sessions - it only reads them."""
import json, os, re, time

HOME = os.path.expanduser("~")
PROJECTS = os.path.join(HOME, ".claude", "projects")
HEAD_LINES = 60          # enough to find cwd + the first user message
MAX = 40                 # most-recent sessions
# Per-step content caps. Author/agent messages and plans are bounded by the
# model's context, so cap them high enough to never clip a real message (the
# old 8000 chopped long answers). Tool results can be genuinely huge (file
# dumps, command output) and the whole transcript is refetched per tick, so
# keep a generous-but-finite cap - the tool card is scrollable/expandable.
MAX_TEXT = 200_000
MAX_THINK = 60_000
# tool results are re-sent on every live tick and sit behind an expander, so
# keep them moderate - the whole transcript is refetched while a turn runs.
MAX_RESULT = 8_000
# HelmDeck's own spawned sessions (copilot, process designer) - not the user's
# coding sessions, so hide them from the import list.
_INTERNAL = ("You are the HelmDeck board copilot", "You are a process designer")


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
    """All Claude Code sessions, most-recently-active first. Skips HelmDeck's
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
            if cwd and "helmdeck-worktrees" in cwd.replace("/", "\\"):
                continue                # HelmDeck-managed - already a card
            if first and first.startswith(_INTERNAL):
                continue                # HelmDeck's own copilot/process session
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


def live_session_id(track):
    """The session whose transcript is CURRENT for this card.

    While a turn RUNS, `claude --resume` has already rotated to a new session
    id (written to live_session.txt by the driver) - the recorded session_id
    still points at the previous file, which contains neither the user's new
    message nor any of the new steps. Reading the old file made a running
    steer look frozen. So: running turn -> live file first; otherwise the
    recorded id (with the live file as the turn-1 fallback)."""
    run_dir = (track or {}).get("run_dir") or ""
    live = None
    if run_dir:
        try:
            with open(os.path.join(run_dir, "live_session.txt"), encoding="utf-8") as f:
                live = f.read().strip() or None
        except OSError:
            pass
    if (track or {}).get("status") == "running" and live:
        return live
    return (track or {}).get("session_id") or live


def transcript_version(track):
    """A change token for the card's live FEED: bytes of the current session
    .jsonl + the driver's live_partial.txt + the flight recorder's
    actions.jsonl. It bumps whenever the agent flushes a block, streams a
    token, OR the harness records a lifecycle note. This is the long-poll key
    that lets the phone get PUSH latency over the sealed relay (which can't
    carry SSE): the /transcript/live endpoint blocks until this changes.

    actions.jsonl is in the token because the card feed WEAVES those notes in
    (see the client's feed memo). Keyed on agent output alone, a lane move -
    gate verdict, merge, bounce - changed nothing the poll could see, so the
    notes sat on disk until the screen was remounted. All three files only
    ever grow, so summing sizes stays monotonic."""
    run_dir = (track or {}).get("run_dir") or ""
    sid = live_session_id(track)
    jp = _find_transcript(sid) if sid else None
    js = os.path.getsize(jp) if jp and os.path.exists(jp) else 0
    lp = os.path.join(run_dir, "live_partial.txt") if run_dir else None
    ls = os.path.getsize(lp) if lp and os.path.exists(lp) else 0
    ap = os.path.join(run_dir, "actions.jsonl") if run_dir else None
    as_ = os.path.getsize(ap) if ap and os.path.exists(ap) else 0
    return js + ls + as_


def read_transcript_live(track, limit=400):
    """read_transcript + the in-flight streaming text (driver's live_partial.txt)
    appended as a streaming step, so a turn streams token-by-token before its
    block is flushed to the .jsonl."""
    sid = live_session_id(track)
    steps = read_transcript(sid, limit) if sid else []
    run_dir = (track or {}).get("run_dir") or ""
    if run_dir:
        try:
            with open(os.path.join(run_dir, "live_partial.txt"), encoding="utf-8") as f:
                partial = f.read()
            if partial.strip():
                steps.append({"role": "assistant", "kind": "text",
                              "text": partial[:MAX_TEXT], "streaming": True, "ts": ""})
        except OSError:
            pass
    return steps


def _tool_summary(inp):
    inp = inp or {}
    for k in _TOOL_KEYS:
        v = inp.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()[:160]
    return ", ".join(list(inp.keys())[:3])


def _tool_detail(name, inp):
    """Structured input for file-mutating tools, so the UI can render a real
    diff (Edit/MultiEdit) or the written content (Write) instead of raw text."""
    inp = inp or {}
    cap = 8000
    if name == "Edit":
        return {"type": "edit", "file": inp.get("file_path", ""),
                "old": str(inp.get("old_string", ""))[:cap], "new": str(inp.get("new_string", ""))[:cap]}
    if name == "MultiEdit":
        return {"type": "multiedit", "file": inp.get("file_path", ""),
                "edits": [{"old": str(e.get("old_string", ""))[:cap], "new": str(e.get("new_string", ""))[:cap]}
                          for e in (inp.get("edits") or [])[:20] if isinstance(e, dict)]}
    if name == "Write":
        return {"type": "write", "file": inp.get("file_path", ""),
                "content": str(inp.get("content", ""))[:cap]}
    return None


def _short_ts(iso):
    # The session .jsonl timestamps are UTC (…Z); the actionlog uses LOCAL time.
    # Convert to local + HH:MM:SS so the transcript and the woven lifecycle notes
    # sort together (a 2h skew + minute-only granularity was scrambling the feed).
    if not isinstance(iso, str) or "T" not in iso:
        return ""
    try:
        from datetime import datetime
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%H:%M:%S")
    except Exception:
        return iso.split("T")[1][:8]


def _epoch(iso):
    # Absolute POSIX seconds for the session .jsonl UTC timestamp. This is the
    # sound sort key for weaving the transcript with the actionlog notes
    # (`ta`); `ts` is date-less HH:MM:SS and scrambles across midnight/days.
    if not isinstance(iso, str) or "T" not in iso:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _cmd_label(text):
    """A Claude Code local-command envelope (recorded as role=user) -> a short
    neutral label for a SYSTEM note, so it stays visible but isn't attributed to
    the human. e.g. '/model claude-haiku-4-5' or 'Set model to ...'."""
    name = re.search(r"<command-name>(.*?)</command-name>", text, re.S)
    if name:
        n = name.group(1).strip().lstrip("/")
        args = re.search(r"<command-args>(.*?)</command-args>", text, re.S)
        a = args.group(1).strip() if args else ""
        return ("⌘ /" + n + (" " + a if a else "")).strip()
    out = re.search(r"<local-command-stdout>(.*?)</local-command-stdout>", text, re.S)
    if out and out.group(1).strip():
        return out.group(1).strip()
    return None


_CTX_SEP = "\n\n---\n\n"
def _strip_ctx(text):
    """The daemon prepends review/merge context to a steer prompt (sessions.
    _pending_context); the session records the AUGMENTED text. Show only the
    human's actual instruction in the feed, not the injected block."""
    if isinstance(text, str) and text.lstrip().startswith("[Desktop context since your last turn"):
        i = text.find(_CTX_SEP)
        if i != -1:
            return text[i + len(_CTX_SEP):].lstrip()
    return text


def _result_text(part):
    c = part.get("content")
    if isinstance(c, str):
        return c.strip()
    if isinstance(c, list):
        return " ".join(p.get("text", "") for p in c if isinstance(p, dict)).strip()
    return ""


def read_transcript(session_id, limit=400):
    """Parse a session's jsonl into ordered steps for the card's agent view -
    the full Paseo-style turn view. Steps:
      {kind:text|thinking, role, text, ts}
      {kind:tool, tool, text(summary), result, ok, ts}   (tool_use paired to its result)
      {kind:todos, todos:[{content,status}], ts}          (from TodoWrite)
      {kind:plan, text, ts}                                (from ExitPlanMode)
    """
    path = _find_transcript(session_id)
    if not path:
        return []
    parsed = []
    for line in _tail_lines(path):
        line = line.strip()
        if not line:
            continue
        try:
            parsed.append(json.loads(line))
        except ValueError:
            continue

    # pass 1: tool_use_id -> result, so each tool call carries its own output
    results = {}
    for d in parsed:
        m = d.get("message")
        c = m.get("content") if isinstance(m, dict) else None
        if not isinstance(c, list):
            continue
        for part in c:
            if isinstance(part, dict) and part.get("type") == "tool_result":
                results[part.get("tool_use_id")] = {
                    "text": _result_text(part)[:MAX_RESULT], "ok": not part.get("is_error")}

    # pass 2: emit steps in order
    steps = []
    for d in parsed:
        if d.get("type") not in ("user", "assistant"):
            continue
        # Skip synthetic records that are NOT author/agent turns: Claude Code
        # injects meta messages (skill/system prompts, command wrappers) as
        # role=user and records sub-agent (Task) internals as sidechain.
        if d.get("isMeta") or d.get("isSidechain"):
            continue
        m = d.get("message")
        if not isinstance(m, dict):
            continue
        role = m.get("role") or d.get("type")
        ts = _short_ts(d.get("timestamp"))
        ta = _epoch(d.get("timestamp"))
        content = m.get("content")
        _lead = content if isinstance(content, str) else (next(
            (p.get("text", "") for p in content
             if isinstance(p, dict) and p.get("type") == "text"), "")
            if isinstance(content, list) else "")
        # Slash-command plumbing: Claude Code records /model (and other local
        # commands) as role=user WITHOUT isMeta - only the caveat is meta. So the
        # <command-name>/<command-args>/<local-command-stdout> envelopes leaked
        # into the feed as the HUMAN's own messages ("Set model to ..."). Keep
        # them visible but RE-ATTRIBUTE as a neutral system note (sorted by time
        # like everything else) - they are plumbing, not the human talking.
        if role == "user" and _lead.lstrip().startswith((
                "<command-name>", "<command-message>", "<command-args>",
                "<local-command-stdout>", "<local-command-stderr>")):
            lbl = _cmd_label(_lead)
            if lbl:
                steps.append({"kind": "system", "text": lbl, "ts": ts, "ta": ta})
            continue
        # Compaction: a session that ran out of context writes a summary as a
        # role=user message (flagged isCompactSummary, or the plain continuation
        # summary on resume). Render it as ONE small marker (Paseo-style), never
        # the raw summary text; dedupe consecutive ones.
        if d.get("isCompactSummary") or (role == "user" and _lead.lstrip().startswith(
                "This session is being continued from a previous conversation")):
            if not (steps and steps[-1].get("kind") == "compaction"):
                steps.append({"kind": "compaction", "ts": ts, "ta": ta})
            continue
        if isinstance(content, str):
            if content.strip():
                steps.append({"role": role, "kind": "text", "text": _strip_ctx(content.strip())[:MAX_TEXT], "ts": ts, "ta": ta})
            continue
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            pt = part.get("type")
            if pt == "text" and (part.get("text") or "").strip():
                steps.append({"role": role, "kind": "text", "text": _strip_ctx(part["text"].strip())[:MAX_TEXT], "ts": ts, "ta": ta})
            elif pt == "thinking" and (part.get("thinking") or "").strip():
                steps.append({"role": role, "kind": "thinking", "text": part["thinking"].strip()[:MAX_THINK], "ts": ts, "ta": ta})
            elif pt == "tool_use":
                name = part.get("name") or "tool"
                inp = part.get("input") if isinstance(part.get("input"), dict) else {}
                if name == "TodoWrite":
                    todos = [{"content": str(td.get("content", ""))[:220], "status": str(td.get("status", ""))}
                             for td in (inp.get("todos") or []) if isinstance(td, dict)]
                    if todos:
                        steps.append({"kind": "todos", "todos": todos, "ts": ts, "ta": ta})
                    continue
                if name == "ExitPlanMode":
                    steps.append({"kind": "plan", "text": str(inp.get("plan", ""))[:MAX_TEXT], "ts": ts, "ta": ta})
                    continue
                res = results.get(part.get("id"))
                step = {"role": role, "kind": "tool", "tool": name,
                        "text": _tool_summary(inp), "result": (res or {}).get("text", ""),
                        "ok": (res or {}).get("ok", True),
                        "running": res is None, "ts": ts, "ta": ta}
                detail = _tool_detail(name, inp)
                if detail:
                    step["detail"] = detail
                steps.append(step)
            # tool_result already folded into its tool step in pass 1
    return steps[-limit:]
