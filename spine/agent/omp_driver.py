# -*- coding: utf-8 -*-
"""OMP native driver - JSONL-RPC over stdio (docs/multi-engine-support.md
§6.6.3, docs/multi-engine-build-plan.md Card 8). One persistent `omp --mode
rpc-ui` process per card, mirroring drivers.py's _ClaudeSession model exactly
(tree-kill teardown, PID registration, one turn at a time, folds into the
SAME timeline_store Card 2 built) - the process/isolation shape Paseo's own
Pi/OMP adapter uses too (one child per session, no shared-server conflict
the way OpenCode has - see the analysis doc §6.6.2 for that one).

PROTOCOL - measured live against the real omp.exe (v16.1.10) 2026-08-24, not
ported from Paseo's TS source unread: every fact below was proven by spawning
omp.exe with a real Anthropic OAuth token and reading its actual stdout.

Client -> server requests (JSONL, one object per line):
  {"type": "prompt", "message": str}   - submit a turn
  {"type": "abort"}                     - cancel the in-flight turn
  {"type": "get_session_stats"}         - cumulative session usage/cost

Server -> client events, in order, for one turn:
  response(command="prompt", success=true)
  -> agent_start -> turn_start
  -> message_start / message_end (role="user" - the ECHOED prompt; unlike
     claude, omp mirrors what we sent, so the human's own text is folded
     from THIS event, no submission-time workaround needed)
  -> message_start (role="assistant", content=[], usage all-zero - a
     placeholder opening frame, ignored)
  -> message_update (assistantMessageEvent: thinking_start/delta/end,
     text_start/delta/end, toolcall_start/delta/end - streaming deltas,
     ignored here the same way claude's content_block_delta is: the
     COMPLETE block arrives again on message_end)
  -> tool_execution_start {toolCallId, toolName, args, intent}
  -> tool_execution_end {toolCallId, toolName, result, isError}
  -> message_end (role="assistant", COMPLETE content array - thinking/text/
     toolCall parts - and message.usage with a REAL usage.cost.total in USD)
  -> turn_end (the SAME message as the last message_end)
  -> agent_end (the whole conversation so far - not folded, redundant with
     what message_end already delivered incrementally)

A CANCELLED turn's terminal message carries stopReason:"aborted" with empty
content - the structured signal (mirrors claude's meta["canceled"], ACP's
stopReason:"cancelled") - proven live: sent `abort` mid-tool-wait, the very
next message_end/turn_end carried stopReason:"aborted".

SESSION IDENTITY is a FILE PATH, not a uuid the caller passes back - proven
live: the SAME `--session <path>` across two SEPARATE process spawns
correctly recalled turn-1 context in turn 2. HelmDeck derives this path from
run_dir (stable, unique per card already) rather than storing anything
fragile in the track - resume is then automatic and free, no field to keep
in sync. The runtime keeps its OWN uuid internally (visible in
get_session_stats' sessionId) - HelmDeck never needs it.

AUTH: ANTHROPIC_OAUTH_TOKEN takes precedence over ANTHROPIC_API_KEY (proven:
`omp --help`'s own env-var table). Defaults to turnopts._oauth_token() - the
SAME ~/.claude/.credentials.json read HelmDeck's own model-discovery already
does - so a card drives omp on the owner's EXISTING Claude subscription with
zero new login, unless the driver's settings.json env overrides it with a
different key/token for a different backend.

BRIEF DELIVERY: `--append-system-prompt` is a real, native omp flag (proven:
`omp --help`) - unlike the ACP path (docs/multi-engine-support.md §6.3),
there is no brief-delivery blocker here at all.
"""
import json
import os
import shutil
import subprocess
import threading
import time as _time

from spine.agent import timeline_store
from spine.agent.proctable import _tree_kill, _record_pid, _forget_pid
from spine.agent.claude_transcript_fmt import _clean_text

_TL_MAX_TEXT = 200_000
_TL_MAX_THINK = 60_000
_TL_MAX_RESULT = 8_000

OMP = shutil.which("omp") or r"C:\Users\%USERNAME%\AppData\Local\omp\omp.exe"

_sessions = {}
_sessions_guard = threading.Lock()
_cancelled = set()


def _oauth_token():
    """The daemon's own Claude OAuth token, reused for omp - see module
    docstring. Lazy import: turnopts.py is a leaf module already, but this
    keeps the dependency explicit and avoids any import-order surprise."""
    from spine.agent.turnopts import _oauth_token as _tok
    return _tok()


def _write(path, text):
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass


def _rm(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _env(cfg):
    """External env for the omp child - same sanitized-copy-plus-overlay
    shape as drivers.py's _env, minus the parts (Bash/MCP tool timeouts,
    per-card dev port) that are claude-specific plumbing omp doesn't use."""
    env = dict(os.environ)
    extra = cfg.get("env") or {}
    if "ANTHROPIC_OAUTH_TOKEN" not in extra and "ANTHROPIC_API_KEY" not in extra:
        tok = _oauth_token()
        if tok:
            env["ANTHROPIC_OAUTH_TOKEN"] = tok
    prepend = extra.get("PATH+")
    for k, v in extra.items():
        if k != "PATH+":
            env[k] = str(v)
    if prepend:
        env["PATH"] = str(prepend) + os.pathsep + env.get("PATH", "")
    return env


def build_argv(cfg, worktree, run_dir, brief=None):
    """THE assembly point for an omp argv - one owner, mirrors drivers.
    build_argv's role for claude."""
    argv = [OMP, "--mode", "rpc-ui", "--cwd", worktree,
            "--session", os.path.join(run_dir, "omp_session"),
            "--auto-approve"]
    if cfg.get("model"):
        argv += ["--model", cfg["model"]]
    if brief:
        argv += ["--append-system-prompt", brief]
    return argv


class _OmpSession:
    """One long-lived `omp --mode rpc-ui` process for a card, reused across
    turns - the same persistent-process, single-pump-thread, tree-kill-on-
    teardown model as drivers.py's _ClaudeSession."""

    def __init__(self, cfg, t):
        self.tid = t["id"]
        self.cfg = cfg
        self.worktree = t.get("worktree") or "."
        self.run_dir = t.get("run_dir") or "."
        # Same brief source as drivers.py's _ClaudeSession (harness/agents/
        # *.md) - the agent id selection is drivers._agent_for's own 1-line
        # ternary, inlined rather than cross-imported for something this small.
        from spine.registry import harness
        agent = "machine-worker" if t.get("machine") else "card-worker"
        self.brief = harness.brief(agent)
        self.proc = None
        self._alive = False
        self._cur = None
        self._turn_lock = threading.Lock()
        self.last_used = _time.time()
        self.spawn_time = 0.0
        self.err_tail = []
        self._spawn()

    def _spawn(self):
        argv = build_argv(self.cfg, self.worktree, self.run_dir, self.brief)
        self.proc = subprocess.Popen(argv, cwd=self.worktree,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, env=_env(self.cfg),
                                     text=True, encoding="utf-8", errors="replace",
                                     bufsize=1)
        self.spawn_time = _time.time()
        _record_pid(self.proc.pid, self.spawn_time)
        self.err_tail = []
        self._alive = True
        threading.Thread(target=self._drain_err, daemon=True).start()
        threading.Thread(target=self._pump, daemon=True).start()

    def alive(self):
        try:
            return self._alive and self.proc is not None and self.proc.poll() is None
        except Exception:
            return False

    def kill(self):
        self._alive = False
        _tree_kill(self.proc)
        try:
            _forget_pid(self.proc.pid)
        except Exception:
            pass

    def cancel(self):
        """Best-effort cooperative cancel: send `abort`, let the pump's
        stopReason:"aborted" handling release the waiter (no separate ack/
        grace escort like claude's control plane - omp's abort is a plain
        typed request, not a distinct control channel)."""
        _cancelled.add(self.tid)
        cur = self._cur
        if not self.alive() or cur is None:
            if cur and not cur["done"].is_set():
                cur["done"].set()
            return
        try:
            self.proc.stdin.write(json.dumps({"type": "abort"}) + "\n")
            self.proc.stdin.flush()
        except Exception:
            self.kill()
            if not cur["done"].is_set():
                cur["done"].set()

    def _drain_err(self):
        try:
            for ln in self.proc.stderr:
                self.err_tail.append(ln)
                if len(self.err_tail) > 40:
                    del self.err_tail[0]
        except Exception:
            pass

    def _pump(self):
        try:
            for line in self.proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                self._on_event(ev)
        except Exception:
            pass
        finally:
            self._alive = False
            cur = self._cur
            if cur and not cur["done"].is_set():
                cur["done"].set()

    # -- event-time card feed (same TStep shape as drivers.py._fold_timeline) --
    def _fold_message(self, msg, role):
        ts, ta = _time.strftime("%H:%M:%S", _time.localtime()), _time.time()
        content = msg.get("content") or []
        for p in content:
            pt = p.get("type")
            if pt == "text":
                # _clean_text strips the <helmdeck-ask> protocol block (the
                # harness brief teaches omp the SAME wire protocol claude
                # gets - both read from harness.brief()) and NOQUESTION -
                # same rule as drivers.py's _fold_timeline for claude.
                text = _clean_text((p.get("text") or "").strip())
                if text:
                    timeline_store.append(self.run_dir, "s:" + _uid(),
                        {"role": role, "kind": "text", "text": text[:_TL_MAX_TEXT],
                         "ts": ts, "ta": ta})
            elif pt == "thinking":
                think = (p.get("thinking") or "").strip()
                if think:
                    timeline_store.append(self.run_dir, "s:" + _uid(),
                        {"role": role, "kind": "thinking", "text": think[:_TL_MAX_THINK],
                         "ts": ts, "ta": ta})
            elif pt == "toolCall":
                uid = p.get("id")
                if not uid:
                    continue
                name = p.get("name") or "tool"
                args = p.get("arguments") if isinstance(p.get("arguments"), dict) else {}
                lbl, sub = _tool_label(name, args)
                timeline_store.append(self.run_dir, "tool:" + uid,
                    {"role": role, "kind": "tool", "tool": name, "label": lbl,
                     "text": sub, "result": "", "ok": True, "status": "running",
                     "error": None, "running": True, "ts": ts, "ta": ta})

    def _fold_usage(self, msg):
        u = msg.get("usage")
        if not isinstance(u, dict):
            return
        inp = int(u.get("input") or 0)
        out = int(u.get("output") or 0)
        cr = int(u.get("cacheRead") or 0)
        cc = int(u.get("cacheWrite") or 0)
        if not ((inp + cr + cc) or out):
            return
        cost = (u.get("cost") or {}).get("total")
        timeline_store.append(self.run_dir, "s:" + _uid(),
            {"kind": "usage", "tokIn": inp, "tokOut": out, "cacheRead": cr,
             "cacheWrite": cc, "ctx": inp + cr + cc,
             "ts": _time.strftime("%H:%M:%S", _time.localtime()), "ta": _time.time()})
        cur = self._cur
        if cur is not None and isinstance(cost, (int, float)):
            cur["cost_usd"] = round(cur.get("cost_usd", 0.0) + float(cost), 6)

    def _on_event(self, ev):
        cur = self._cur
        typ = ev.get("type")
        if cur is not None:
            cur["last_event"] = _time.time()
        if typ == "message_end":
            m = ev.get("message") or {}
            role = m.get("role")
            if role == "user":
                self._fold_message(m, "user")
            elif role == "assistant":
                if m.get("content"):
                    self._fold_message(m, "assistant")
                    self._fold_usage(m)
        elif typ == "tool_execution_end":
            uid = ev.get("toolCallId")
            if not uid:
                return
            result = ev.get("result") or {}
            texts = [c.get("text", "") for c in (result.get("content") or [])
                    if isinstance(c, dict)]
            text = "\n".join(t for t in texts if t)
            is_err = bool(ev.get("isError"))
            # An abort's own tool call reports isError:true with "[Command
            # cancelled]" - proven live 2026-08-24 (sent `abort` mid-Bash-
            # sleep). The 4-state model (Paseo parity, same rule the claude
            # driver applies to its own interrupt sentinel) says this is
            # CANCELED, not failed - the owner's hand, not a tool error.
            canceled = is_err and "cancel" in text.lower()
            if canceled:
                status, ok, err = "canceled", True, None
            elif is_err:
                status, ok, err = "failed", False, text[:500]
            else:
                status, ok, err = "completed", True, None
            timeline_store.append(self.run_dir, "tool:" + uid,
                {"result": text[:_TL_MAX_RESULT], "ok": ok, "status": status,
                 "error": err, "running": False})
        elif typ == "turn_end":
            # NOT the completion signal - measured live 2026-08-24: a single
            # prompt that needs tool calls produces MULTIPLE internal
            # turn_start/turn_end pairs (one per model round-trip), and the
            # FIRST one carries the model's "I'll do X now" narration, not
            # the final answer (proven: two turn_end events for one prompt,
            # the first's text was "I'll read probe.txt and then create
            # result.txt", the second's was the real final summary). Keep the
            # LATEST one as the best-known result so far; only agent_end
            # (below) is the true "the whole prompt cycle is done" signal.
            if cur is not None:
                cur["result"] = ev.get("message") or {}
        elif typ == "agent_end":
            # THE completion signal (fires for a normal end AND after abort -
            # proven live both ways). Prefer the last assistant message from
            # the full conversation array over the latest turn_end capture -
            # same content in practice (measured: byte-identical text on a
            # multi-turn tool-calling prompt) but this is the authoritative
            # source, not an inference from turn_end's ambiguous granularity.
            if cur is not None:
                msgs = ev.get("messages") or []
                last_assistant = [m for m in msgs if m.get("role") == "assistant"]
                if last_assistant:
                    cur["result"] = last_assistant[-1]
                cur["done"].set()
        elif typ == "response":
            if ev.get("success") is False and cur is not None:
                cur["rpc_error"] = ev.get("error")

    # -- one turn: push a prompt, wait bounded for turn_end ----------------
    def run_turn(self, prompt, run_dir):
        with self._turn_lock:
            self.last_used = _time.time()
            try:
                return self._run_turn_locked(prompt, run_dir)
            finally:
                self.last_used = _time.time()

    def _run_turn_locked(self, prompt, run_dir):
        _cancelled.discard(self.tid)
        if not self.alive():
            _tree_kill(self.proc)
            self._spawn()
        cur = {"result": None, "cost_usd": 0.0, "done": threading.Event(),
               "last_event": _time.time()}
        self._cur = cur
        try:
            self.proc.stdin.write(json.dumps({"type": "prompt", "message": prompt}) + "\n")
            self.proc.stdin.flush()
        except Exception as e:
            self._cur = None
            self.kill()
            raise RuntimeError("omp session write failed: %s" % e)
        idle = self.cfg.get("idle_timeout", 900)
        poll = min(5.0, max(0.5, idle / 4.0))
        start = _time.time()
        finished, why = False, ""
        while True:
            if cur["done"].wait(poll):
                finished = True
                break
            now = _time.time()
            if now - cur.get("last_event", start) > idle:
                why = "no output for %ds" % idle
                break
        self._cur = None
        if self.tid in _cancelled:
            _cancelled.discard(self.tid)
            return None, "(turn cancelled by you)", \
                {"usage": {}, "cost_usd": None, "models": [], "canceled": True}
        if not finished:
            self.kill()
            raise RuntimeError(
                "omp turn stalled (%s) - session killed; steer again to resume. %s"
                % (why, "".join(self.err_tail).strip()[-200:]))
        d = cur["result"]
        if not d:
            self.kill()
            raise RuntimeError("omp stream ended with no result: "
                               + "".join(self.err_tail).strip()[:300])
        if d.get("stopReason") == "aborted":
            return None, "(turn cancelled by you)", \
                {"usage": {}, "cost_usd": None, "models": [], "canceled": True}
        reply = "".join(p.get("text", "") for p in (d.get("content") or [])
                        if p.get("type") == "text")
        u = d.get("usage") or {}
        meta = {"usage": {"input_tokens": u.get("input", 0),
                          "output_tokens": u.get("output", 0),
                          "cache_read_input_tokens": u.get("cacheRead", 0),
                          "cache_creation_input_tokens": u.get("cacheWrite", 0)},
                "cost_usd": cur["cost_usd"] if cur["cost_usd"] else None,
                "models": [d.get("model")] if d.get("model") else [],
                "is_error": bool(d.get("error")),
                "error": str(d.get("error") or "")[:500]}
        return None, reply, meta


def _uid():
    import uuid
    return uuid.uuid4().hex


_TOOL_LABELS = {
    "read": ("Lesen", lambda a: a.get("path", "")),
    "write": ("Schreiben", lambda a: a.get("path", "")),
    "edit": ("Bearbeiten", lambda a: a.get("path", "")),
    "bash": ("Befehl", lambda a: a.get("i") or a.get("command", "")),
    "grep": ("Suche", lambda a: a.get("pattern", "")),
    "glob": ("Suche", lambda a: a.get("pattern", "")),
    "ls": ("Auflisten", lambda a: a.get("path", "")),
    "webfetch": ("Web", lambda a: a.get("url", "")),
    "websearch": ("Web", lambda a: a.get("query", "")),
}


def _tool_label(name, args):
    """Human label for an omp tool call - omp's own tool-name vocabulary
    (lowercase: read/write/edit/bash/...) differs from claude's
    (Read/Write/Edit/Bash), so this is its own small table rather than a
    forced reuse of claude_transcript_fmt._tool_label."""
    n = (name or "").strip().lower()
    entry = _TOOL_LABELS.get(n)
    if entry:
        lbl, sub_fn = entry
        return lbl, str(sub_fn(args or {}))[:160]
    return name, ", ".join(list((args or {}).keys())[:3])


def _get_session(cfg, t):
    tid = t["id"]
    with _sessions_guard:
        s = _sessions.get(tid)
        if s is not None and not s.alive():
            s = None
        if s is None:
            s = _OmpSession(cfg, t)
            _sessions[tid] = s
        return s


def run(cfg, t, prompt):
    """Entry point matching drivers.run's per-type dispatch shape:
    (session_id, reply, meta)."""
    s = _get_session(cfg, t)
    sid, reply, meta = s.run_turn(prompt, t.get("run_dir") or ".")
    return t.get("session_id"), reply, meta


def cancel(tid):
    with _sessions_guard:
        s = _sessions.get(tid)
    if s:
        s.cancel()
        return True
    return False


def has_session(tid):
    with _sessions_guard:
        return tid in _sessions


def turn_active(tid):
    with _sessions_guard:
        s = _sessions.get(tid)
    if s is None:
        return False
    try:
        return bool(s.alive() and s._cur is not None)
    except Exception:
        return False


def drop_session(tid):
    with _sessions_guard:
        s = _sessions.get(tid)
        if s is None:
            return False
        if not s._turn_lock.acquire(blocking=False):
            return False
        try:
            if s._cur is not None:
                return False
            del _sessions[tid]
        finally:
            s._turn_lock.release()
    try:
        s.kill()
    except Exception:
        pass
    return True
