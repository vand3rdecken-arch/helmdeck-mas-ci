# -*- coding: utf-8 -*-
"""Transcript-part formatting - extracted from claude_sessions.py (god-file
breakup, see spine/registry/debt.py daemon-god-files).

Pure text: turns a raw tool-call/result part from a session .jsonl into a
readable label (Paseo's tool-call-detail-parser, server-side) - a human verb
+ a concise subject instead of dumping the raw input. No dependency on
claude_sessions.py's own session-management functions (read_transcript/
read_transcript_live import these, not the other way round), so this has no
lazy-import-to-avoid-cycle need - a clean leaf module."""
import os
import re

_TOOL_KEYS = ("command", "file_path", "path", "url", "pattern", "query",
              "prompt", "description", "notebook_path", "old_string")


def _tool_summary(inp):
    inp = inp or {}
    for k in _TOOL_KEYS:
        v = inp.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()[:160]
    return ", ".join(list(inp.keys())[:3])


# -- readable action labels (Paseo's tool-call-detail-parser, server-side) ----
# Paseo maps every tool call to a human verb + a concise subject instead of
# dumping the raw input ("PowerShell $job = Start-Job { & \"C:\\Program F...").
# Same here: label = what happened, text = the one thing that identifies it
# (file basename, search pattern, the agent's own description of a command).
# The raw tool name stays in step["tool"] for icons; the label rides beside it.

def _base(p):
    return os.path.basename((p or "").rstrip("/\\")) or (p or "")


def _first_line(s):
    return (s or "").strip().splitlines()[0][:120] if (s or "").strip() else ""


def _tool_label(name, inp):
    """(label, text) - a human verb for the action and its concise subject."""
    from spine.registry import i18n
    inp = inp or {}
    n = (name or "").strip()
    if n.startswith("mcp__"):
        # mcp__windows-mcp__Click -> "PC · Click"; other servers "server · tool"
        parts = n.split("__")
        server = parts[1] if len(parts) > 1 else "mcp"
        tool = parts[2] if len(parts) > 2 else ""
        if server == "windows-mcp":
            return i18n.t("tool.pc", tool=tool), _tool_summary(inp)
        return "%s · %s" % (server, tool), _tool_summary(inp)
    if n in ("Read", "NotebookRead"):
        return i18n.t("tool.read"), _base(inp.get("file_path") or inp.get("path")
                                          or inp.get("notebook_path"))
    if n in ("Edit", "MultiEdit", "NotebookEdit"):
        return i18n.t("tool.edit"), _base(inp.get("file_path") or inp.get("notebook_path"))
    if n == "Write":
        return i18n.t("tool.write"), _base(inp.get("file_path"))
    if n in ("Bash", "PowerShell", "Shell"):
        # the agent's own description reads best; else the command's first line
        return i18n.t("tool.run"), (inp.get("description")
                                    or _first_line(inp.get("command")))
    if n in ("Grep", "Glob", "Search", "LS"):
        return i18n.t("tool.search"), (inp.get("pattern") or inp.get("query")
                                       or inp.get("path") or "")
    if n in ("WebFetch", "WebSearch"):
        return i18n.t("tool.web"), (inp.get("url") or inp.get("query") or "")
    if n in ("Task", "Agent"):
        return i18n.t("tool.agent"), (inp.get("description")
                                      or _first_line(inp.get("prompt")))
    if n == "AskUserQuestion":
        return i18n.t("tool.ask"), ""
    if n == "TodoWrite":
        return i18n.t("tool.plan"), ""
    return n, _tool_summary(inp)


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


def _notif_label(text):
    """Claude Code injects background-task + harness notifications as role=user
    messages (that is how the runtime feeds them to the model), so they rendered
    as the OWNER's own right-aligned message. They are plumbing, not the human
    talking. A task-notification -> a short neutral note; a bare system-reminder
    is pure context injection and is dropped from the feed (returns None)."""
    t = text.lstrip()
    if t.startswith("<task-notification>") or t.startswith("[SYSTEM NOTIFICATION"):
        m = re.search(r"<status>(.*?)</status>", t, re.S)
        st = m.group(1).strip() if m else ""
        return "⚙ Hintergrund-Task" + (" (" + st + ")" if st else "")
    return None   # <system-reminder> and friends -> drop as context noise


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


def _clean_text(text):
    """Everything that must come OFF an author/agent message before the owner
    reads it: the injected desktop-context block (_strip_ctx) and the worker's
    machine-readable question block, which is rendered as real option buttons
    instead (ask.py). Leaving the raw <helmdeck-ask> JSON in the feed would show
    the owner the protocol rather than the question."""
    from spine.ops import ask
    out = ask.strip(_strip_ctx(text))
    # NOQUESTION is the ask-repair protocol's decline token ("I wasn't really
    # asking") - an internal handshake, never a reply. As a bubble it read like
    # the worker answered the owner with the word "NOQUESTION" ("Questions also
    # broken"). The record stays in the .jsonl; only the chrome hides it.
    if out.strip() == ask.NO_QUESTION:
        return ""
    return out


def _result_text(part):
    c = part.get("content")
    if isinstance(c, str):
        return c.strip()
    if isinstance(c, list):
        return " ".join(p.get("text", "") for p in c if isinstance(p, dict)).strip()
    return ""
