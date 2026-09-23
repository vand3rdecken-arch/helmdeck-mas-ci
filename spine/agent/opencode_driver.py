# -*- coding: utf-8 -*-
"""OpenCode native driver, DEDICATED-server mode (ops/docs/multi-engine-support.md
§6.6.2, build plan Card 7). ONE private `opencode serve` process per card -
not Paseo's shared-by-default pool, which would break HelmDeck's per-card
tree-kill isolation law (see this module's own history in the analysis doc
for why). This is the mode Paseo itself uses whenever a session needs its
own launch env (`acquireDedicated`, server-manager.ts:147-159) - HelmDeck's
per-card env overlay makes every card qualify, so every card gets its own
server, never a shared one.

NOT LIVE-VERIFIED (owner decree 2026-08-24, "test accounts later"): no
`opencode` binary is installed on this box. Two DIFFERENT confidence levels
in this module, kept explicit rather than blurred together:

  GROUNDED IN PASEO'S OWN SOURCE (read directly, file:line cited, same
  standard as codex_driver.py/omp_driver.py): the spawn argv and cwd
  (`opencode serve --port <p>`, a NEUTRAL home dir, never the card's
  worktree - server-manager.ts:285-304), the "listening on" stdout
  ready-signal (:371), the dedicated-vs-shared acquisition trigger
  (opencode-agent.ts:1291-1293: `launchContext?.env ? acquireDedicated :
  acquireCurrent`), the SSE consume shape (`client.global.event({signal,
  sseMaxRetryAttempts:0})`, opencode-agent.ts:3495-3509), delta/full
  dedup by partID (:2489-2502), cost accumulation from `part.cost`
  (:808-858), the interrupt-then-poll-idle-before-next-turn sequence
  (:3009-3110), and turn-end being `session.idle` on the EVENT BUS, not
  an HTTP response (`session.promptAsync` is fire-and-forget).

  INFERRED, NOT CONFIRMED: the exact REST endpoint PATHS. Paseo talks to
  OpenCode through `@opencode-ai/sdk` (a third-party TS package, not
  vendored in this checkout), so calls like `client.session.create(...)`
  are visible as SDK METHOD NAMES, never as raw HTTP - `client.session.
  create` almost certainly maps to `POST /session`, `client.global.event`
  to `GET /event` or `GET /global/event`, by OpenCode's own documented
  convention, but this is the ONE part of this module a real account can
  disprove. Every such call is isolated in _OpenCodeClient below so a
  correction stays local to one class, not scattered through the driver.

Scope cut, matching the other native drivers' documented narrowing: no
question.asked handling, no multi-session-per-server demux (moot - this
server serves exactly one session), no extension_ui widgets. Core turn/
tool/cost/cancel path only.

ONE MORE UNCONFIRMED ASSUMPTION, named explicitly rather than left silent:
whether OpenCode echoes the human's own submitted text back on the SSE bus
as a `message.part.updated` (role="user") event. The generic fold path
below (_fold_part) would catch it correctly IF so - no special-casing
needed, since it reads `part.get("role")` off whatever the event says. If
OpenCode does NOT echo it (matching claude's behaviour, not omp's), the
card's own steer text will be silently missing from its feed, and this
needs the SAME submission-time-fold fix drivers.py's _run_turn_locked
applies for claude (Card 2's own history) - Card 7's live-turn verification
must check for this specifically, the way compare_timeline.py caught it
for claude.
"""
import json
import os
import shutil
import socket
import subprocess
import threading
import time as _time
import urllib.error
import urllib.request

from spine.agent import timeline_store
from spine.agent.proctable import _tree_kill, _record_pid, _forget_pid
from spine.agent.claude_transcript_fmt import _clean_text
from spine.agent import spawnenv   # worker_creationflags: ONE owner of the priority flag

_TL_MAX_TEXT = 200_000
_TL_MAX_THINK = 60_000
_TL_MAX_RESULT = 8_000

OPENCODE = shutil.which("opencode") or "opencode"

_sessions = {}
_sessions_guard = threading.Lock()
_cancelled = set()

_FAILED_STATUS = {"failed", "failure", "error", "errored", "rejected", "denied"}
_CANCELED_STATUS = {"canceled", "cancelled", "interrupted", "aborted"}
_COMPLETED_STATUS = {"completed", "complete", "done", "success", "succeeded"}


def _normalize_tool_status(raw, error, output):
    """Same vocabulary as codex_driver's (analysis §4.3 - a genuinely shared
    cross-provider convention, not coincidence)."""
    if error is not None:
        return "failed"
    n = (raw or "").strip().lower() if isinstance(raw, str) else ""
    if n in _FAILED_STATUS:
        return "failed"
    if n in _CANCELED_STATUS:
        return "canceled"
    if n in _COMPLETED_STATUS:
        return "completed"
    return "completed" if output is not None else "running"


def _free_port():
    """Ephemeral port allocation - bind-to-0 then release, same trick
    server-manager.ts's `portAllocator` performs (Node's net.createServer
    ().listen(0)); this is its stdlib-socket equivalent."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _opencode_home():
    """A NEUTRAL cwd for the server process - launching from the card's
    worktree would make OpenCode index it as the default workspace
    (measured by Paseo, server-manager.ts:290-292); the actual workspace is
    passed as `directory` on every call instead."""
    home = os.path.join(os.path.expanduser("~"), ".helmdeck-opencode-home")
    os.makedirs(home, exist_ok=True)
    return home


def _env(cfg):
    env = dict(os.environ)
    extra = cfg.get("env") or {}
    prepend = extra.get("PATH+")
    for k, v in extra.items():
        if k != "PATH+":
            env[k] = str(v)
    if prepend:
        env["PATH"] = str(prepend) + os.pathsep + env.get("PATH", "")
    return env


class _OpenCodeClient:
    """The REST/SSE surface. See module docstring - REST PATHS here are the
    one inferred (not source-confirmed) part of this driver. Bare
    urllib.request, matching drivers.py's own _http driver's dependency
    footprint (no new library for one card type)."""

    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")

    def _post(self, path, body, timeout=30.0):
        data = json.dumps(body or {}).encode("utf-8")
        req = urllib.request.Request(self.base_url + path, data=data, method="POST",
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        return json.loads(raw) if raw else {}

    def create_session(self, directory, timeout=10.0):
        resp = self._post("/session", {"directory": directory}, timeout=timeout)
        sid = (resp or {}).get("id") or (resp or {}).get("data", {}).get("id")
        if not sid:
            raise RuntimeError("opencode session.create returned no session id: %r" % resp)
        return sid

    def prompt_async(self, session_id, directory, parts, model=None, system=None):
        # `system` is its OWN field, not concatenated into `parts` - measured
        # in Paseo (opencode-agent.ts:3257-3273: `...(systemPrompt ? {system:
        # systemPrompt} : {})` alongside `parts`, not folded into them). Doing
        # this by concatenation instead would show the owner's feed the
        # entire harness brief prepended to every single turn's visible text.
        body = {"sessionID": session_id, "directory": directory, "parts": parts}
        if model:
            body["model"] = model
        if system:
            body["system"] = system
        self._post("/session/%s/message" % session_id, body, timeout=15.0)

    def abort(self, session_id, directory, timeout=5.0):
        try:
            self._post("/session/%s/abort" % session_id, {"directory": directory},
                       timeout=timeout)
        except Exception:
            pass

    def permission_reply(self, request_id, directory, reply="once"):
        try:
            self._post("/permission/%s/reply" % request_id,
                       {"directory": directory, "reply": reply}, timeout=5.0)
        except Exception:
            pass

    def session_status(self, session_id, timeout=5.0):
        req = urllib.request.Request(self.base_url + "/session/%s/status" % session_id)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read() or b"{}")
        except Exception:
            return {}

    def open_event_stream(self):
        """GET the global SSE bus. Returns a file-like object whose lines
        are read by _sse_lines. No `signal`/cancellation param exists in
        urllib - the caller closes the underlying socket via the response
        object to stop the stream (see _OpenCodeSession._pump)."""
        req = urllib.request.Request(self.base_url + "/event",
            headers={"Accept": "text/event-stream"})
        return urllib.request.urlopen(req, timeout=None)


def _sse_lines(resp):
    """Minimal SSE frame parser: accumulate `data: ...` lines until a blank
    line, yield the JSON-decoded payload. No `event:` field handling -
    OpenCode's own event `type` is inside the JSON payload itself
    (translateOpenCodeEvent switches on event.type, not the SSE event
    name), matching every event dump this module's sibling omp_driver.py
    measurement work has seen from adjacent tools."""
    buf = []
    for raw in resp:
        line = raw.decode("utf-8", "replace").rstrip("\n").rstrip("\r")
        if not line:
            if buf:
                payload = "\n".join(buf)
                buf = []
                try:
                    yield json.loads(payload)
                except ValueError:
                    continue
            continue
        if line.startswith("data:"):
            buf.append(line[5:].lstrip())


class _OpenCodeSession:
    """One DEDICATED `opencode serve` process + one session on it, per card.
    Same tree-kill/PID-registration/turn-lock discipline as the other native
    drivers; the SSE pump thread plays the role _pump plays for
    stdio-framed engines."""

    def __init__(self, cfg, t):
        self.tid = t["id"]
        self.cfg = cfg
        self.worktree = t.get("worktree") or "."
        self.run_dir = t.get("run_dir") or "."
        self.session_id = t.get("session_id")
        self.proc = None
        self.client = None
        self.port = None
        self._alive = False
        self._cur = None
        self._turn_lock = threading.Lock()
        self.last_used = _time.time()
        self.spawn_time = 0.0
        self.err_tail = []
        self._stream_resp = None
        self._streamed_keys = set()
        from spine.registry import harness
        agent = "machine-worker" if t.get("machine") else "card-worker"
        self.brief = harness.brief(agent)
        self._spawn()

    def _spawn(self):
        self.port = _free_port()
        argv = [self.cfg.get("exe") or OPENCODE, "serve", "--port", str(self.port)]
        home = _opencode_home()
        self.proc = subprocess.Popen(argv, cwd=home,
                                     stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, env=_env(self.cfg),
                                     text=True, encoding="utf-8", errors="replace",
                                     bufsize=1,
                                     # no console: the daemon runs under pythonw,
                                     # so without this the agent gets its own
                                     # (empty) console window that steals focus
                                     creationflags=spawnenv.worker_creationflags())
        self.spawn_time = _time.time()
        _record_pid(self.proc.pid, self.spawn_time)
        self.err_tail = []
        self._alive = True
        threading.Thread(target=self._drain_err, daemon=True).start()
        if not self._wait_ready(timeout=30.0):
            self._alive = False
            raise RuntimeError("opencode serve did not report ready within 30s: %s"
                               % "".join(self.err_tail).strip()[-300:])
        self.client = _OpenCodeClient("http://127.0.0.1:%d" % self.port)
        threading.Thread(target=self._sse_pump, daemon=True).start()
        if not self.session_id:
            self.session_id = self.client.create_session(self.worktree)

    def _wait_ready(self, timeout):
        """Blocks on the SAME signal Paseo waits for - "listening on" in
        stdout (server-manager.ts:371) - not a port-probe, matching the
        measured-correct approach exactly."""
        deadline = _time.time() + timeout
        buf = []
        while _time.time() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                if self.proc.poll() is not None:
                    return False
                continue
            buf.append(line)
            if len(buf) > 40:
                del buf[0]
            if "listening on" in line:
                self.err_tail = buf
                return True
        self.err_tail = buf
        return False

    def alive(self):
        try:
            return self._alive and self.proc is not None and self.proc.poll() is None
        except Exception:
            return False

    def kill(self):
        self._alive = False
        try:
            if self._stream_resp:
                self._stream_resp.close()
        except Exception:
            pass
        _tree_kill(self.proc)
        try:
            _forget_pid(self.proc.pid)
        except Exception:
            pass

    def cancel(self):
        """Local-then-remote abort, capped - matches opencode-agent.ts:
        3009-3052's own "cap the wait so the user-visible cancel lands
        quickly" reasoning (measured: OpenCode 1.14.42+ blocks abort until
        the running tool actually stops)."""
        _cancelled.add(self.tid)
        cur = self._cur
        if not self.alive() or cur is None or not self.session_id:
            if cur and not cur["done"].is_set():
                cur["done"].set()
            return
        try:
            self.client.abort(self.session_id, self.worktree, timeout=2.0)
        except Exception:
            pass
        # synthesize canceled for any still-running tool step, same rule the
        # claude/omp/codex drivers apply on their own interrupt paths.
        for uid in list(cur.get("running_tools") or []):
            timeline_store.append(self.run_dir, "tool:" + uid,
                {"result": "[interrupted]", "ok": True, "status": "canceled",
                 "error": None, "running": False})
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

    def _sse_pump(self):
        try:
            self._stream_resp = self.client.open_event_stream()
            for ev in _sse_lines(self._stream_resp):
                self._on_event(ev)
        except Exception:
            pass
        finally:
            self._alive = False
            cur = self._cur
            if cur and not cur["done"].is_set():
                cur["done"].set()

    def _event_session_id(self, ev):
        props = ev.get("properties") or {}
        return (props.get("sessionID") or props.get("sessionId")
               or (props.get("info") or {}).get("sessionID")
               or (props.get("part") or {}).get("sessionID"))

    def _on_event(self, ev):
        cur = self._cur
        if cur is not None:
            cur["last_event"] = _time.time()
        etype = ev.get("type")
        props = ev.get("properties") or {}
        sid = self._event_session_id(ev)
        if sid is not None and sid != self.session_id:
            return    # not our session (belongs to a different card's - moot
                       # in dedicated mode, kept for defensive correctness
        if etype == "message.part.delta":
            self._fold_delta(props)
        elif etype == "message.part.updated":
            self._fold_part(props, is_delta=False)
        elif etype == "session.idle":
            if cur is not None:
                cur["status"] = "completed"
                cur["done"].set()
        elif etype == "session.error":
            if cur is not None:
                cur["status"] = "failed"
                cur["error"] = str(props.get("error") or "")[:500]
                cur["done"].set()
        elif etype == "permission.asked":
            # unattended: auto-approve immediately, matching opencode-agent.
            # ts:4299-4345's tryAutoApproveToolPermission - never surfaced
            # to the (nonexistent, headless) owner.
            req_id = props.get("id")
            if req_id:
                self.client.permission_reply(req_id, self.worktree, "once")

    def _fold_delta(self, props):
        """Dedup bookkeeping only - claude's driver clears its live partial
        on the settled frame; OpenCode instead needs the settled
        message.part.updated to SKIP re-emitting what a delta already
        streamed (opencode-agent.ts:2489-2502). Deltas themselves are not
        folded as their own steps - only the settled part is, exactly like
        claude's stream_event deltas are display-only."""
        part_id = props.get("partID") or props.get("id")
        field = props.get("field") or "text"
        if part_id:
            self._streamed_keys.add("%s:%s" % (field, part_id))

    def _fold_part(self, props, is_delta):
        part = props.get("part") or props
        ptype = part.get("type")
        part_id = part.get("id") or props.get("partID")
        key = "%s:%s" % (ptype, part_id) if part_id else None
        if key and key in self._streamed_keys:
            self._streamed_keys.discard(key)
            return
        ts, ta = _time.strftime("%H:%M:%S", _time.localtime()), _time.time()
        cur = self._cur
        if ptype == "text":
            role = part.get("role") or "assistant"
            text = _clean_text((part.get("text") or "").strip())
            if text:
                timeline_store.append(self.run_dir, "s:" + _uid(),
                    {"role": role, "kind": "text", "text": text[:_TL_MAX_TEXT],
                     "ts": ts, "ta": ta})
        elif ptype == "reasoning":
            text = (part.get("text") or "").strip()
            if text:
                timeline_store.append(self.run_dir, "s:" + _uid(),
                    {"role": "assistant", "kind": "thinking", "text": text[:_TL_MAX_THINK],
                     "ts": ts, "ta": ta})
        elif ptype == "tool":
            self._fold_tool(part, ts, ta, cur)
        elif ptype == "step-finish":
            self._fold_cost(part, ts, ta, cur)

    def _fold_tool(self, part, ts, ta, cur):
        uid = part.get("id") or part.get("callID")
        if not uid:
            return
        name = part.get("tool") or part.get("name") or "tool"
        state = part.get("state") or {}
        status = _normalize_tool_status(state.get("status"), state.get("error"),
                                        state.get("output"))
        if status == "running":
            if cur is not None:
                cur.setdefault("running_tools", set()).add(uid)
            timeline_store.append(self.run_dir, "tool:" + uid,
                {"role": "assistant", "kind": "tool", "tool": name, "label": name,
                 "text": str(state.get("input") or "")[:160], "result": "",
                 "ok": True, "status": "running", "error": None, "running": True,
                 "ts": ts, "ta": ta})
        else:
            if cur is not None:
                (cur.get("running_tools") or set()).discard(uid)
            err = state.get("error")
            timeline_store.append(self.run_dir, "tool:" + uid,
                {"result": str(state.get("output") or "")[:_TL_MAX_RESULT],
                 "ok": status != "failed", "status": status,
                 "error": str(err)[:500] if err else None, "running": False})

    def _fold_cost(self, part, ts, ta, cur):
        tokens = part.get("tokens") or {}
        inp = int(tokens.get("input") or 0)
        out = int(tokens.get("output") or 0)
        cache = tokens.get("cache") or {}
        cr = int(cache.get("read") or 0)
        cw = int(cache.get("write") or 0)
        cost = part.get("cost")
        if inp or out or cr or cw:
            timeline_store.append(self.run_dir, "s:" + _uid(),
                {"kind": "usage", "tokIn": inp, "tokOut": out, "cacheRead": cr,
                 "cacheWrite": cw, "ctx": inp + cr + cw, "ts": ts, "ta": ta})
        if cur is not None and isinstance(cost, (int, float)) and cost:
            cur["cost_usd"] = round(cur.get("cost_usd", 0.0) + float(cost), 6)

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
            self.kill()
            self._spawn()
        cur = {"status": None, "error": None, "cost_usd": 0.0, "running_tools": set(),
               "done": threading.Event(), "last_event": _time.time()}
        self._cur = cur
        try:
            text = _clean_text((prompt or "").strip())
            parts = [{"type": "text", "text": text}] if text else []
            self.client.prompt_async(self.session_id, self.worktree, parts,
                                     model=self.cfg.get("model"), system=self.brief)
        except Exception as e:
            self._cur = None
            self.kill()
            raise RuntimeError("opencode session.promptAsync failed: %s" % e)
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
            return self.session_id, "(turn cancelled by you)", \
                {"usage": {}, "cost_usd": None, "models": [], "canceled": True}
        if not finished:
            self.kill()
            raise RuntimeError(
                "opencode turn stalled (%s) - session killed; steer again to resume. %s"
                % (why, "".join(self.err_tail).strip()[-200:]))
        steps = timeline_store.read(run_dir)
        reply = ""
        for st in reversed(steps):
            if st.get("kind") == "text" and st.get("role") == "assistant":
                reply = st.get("text") or ""
                break
        meta = {"usage": {}, "cost_usd": cur["cost_usd"] if cur["cost_usd"] else None,
                "models": [self.cfg.get("model")] if self.cfg.get("model") else [],
                "is_error": cur.get("status") == "failed",
                "error": (cur.get("error") or "")[:500]}
        return self.session_id, reply, meta


def _uid():
    import uuid
    return uuid.uuid4().hex


def _get_session(cfg, t):
    tid = t["id"]
    with _sessions_guard:
        s = _sessions.get(tid)
        if s is not None and not s.alive():
            s = None
        if s is None:
            s = _OpenCodeSession(cfg, t)
            _sessions[tid] = s
        return s


def run(cfg, t, prompt):
    s = _get_session(cfg, t)
    sid, reply, meta = s.run_turn(prompt, t.get("run_dir") or ".")
    return sid or t.get("session_id"), reply, meta


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
