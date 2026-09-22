# -*- coding: utf-8 -*-
"""Codex native driver (ops/docs/multi-engine-support.md §6.6.1, build plan
Card 6). One persistent `codex app-server` process per card, same isolation
shape as drivers.py's _ClaudeSession (tree-kill, PID registration, one turn
at a time) - Codex's own process model has no shared-server conflict the
way OpenCode's default does.

NOT LIVE-VERIFIED (owner decree 2026-08-24, "test accounts later"): no
`codex` CLI is installed on this box and no OpenAI/Codex account exists to
authenticate one. Unlike omp_driver.py (which was built AND proven against
the real binary), every mechanic below is read from Paseo's ACTUAL source at
C:\\Users\\Tien Duy Vo\\Downloads\\_paseo_src (codex-app-server-agent.ts,
providers/codex/tool-call-mapper.ts) with file:line citations kept in this
docstring, not invented or ported from memory. Treat this module as
protocol-correct-per-specification, unverified-in-practice, until Card 6's
owner-account step happens and it gets the same live-probe treatment omp
did (which caught two real bugs specification-reading alone would have
missed - see omp_driver.py's own history for why this distinction matters).

PROTOCOL (codex-app-server-agent.ts, verified 2026-08-24):

Spawn: `codex app-server` (`+ --enable goals` if the installed codex clears
CODEX_GOALS_MIN_VERSION - skipped here, not worth guessing a version gate
for unverified code). No cwd at spawn (:6277-6305) - cwd is a per-turn
param instead.

Handshake (:3234-3235): `initialize` REQUEST with
`{clientInfo:{name:"codex_app_server_daemon",...}, capabilities:
{experimentalApi:true, mcpServerOpenaiFormElicitation:true}}`, then an
`initialized` NOTIFICATION (no response awaited) - Codex reads the client
name to decide who "originates" a model request (:130-137), so this name
must be sent verbatim, not invented.

Session (:4506-4529, :3564-3602): `thread/start {cwd?, approvalPolicy,
sandboxPolicy, developerInstructions?}` -> `response.thread.id`. A NEW
PROCESS resuming an existing thread calls `thread/resume {threadId,
developerInstructions?}` instead - guarded in Paseo by `thread/loaded/list`
first, skipped here because a HelmDeck respawn is always a genuinely fresh
process (never two live resume attempts racing on one thread).

Turn (:3676-3745): `turn/start {threadId, input:[{type:"text",text}],
approvalPolicy, sandboxPolicy, developerInstructions?}` - THE BRIEF IS
PER-TURN, not persisted at thread level (measured: buildTurnStartParams
recomputes developerInstructions from composeSystemPromptParts every call),
so it is resent on every turn/start here, unlike claude's per-spawn
--append-system-prompt.

UNATTENDED MODE (:265-278, the "full-access" preset): `approvalPolicy:
"never", sandboxPolicy:{type:"danger-full-access", networkAccess:true}` -
Codex never emits an approval request in this mode, matching HelmDeck's
`perm` "acceptEdits"-class cards (headless, no human to answer a prompt).
Inbound approval REQUESTS (item/commandExecution/requestApproval etc.,
:3475-3488) are still handled defensively below in case a future Codex
version or a stricter perm mapping needs them, resolved `{"decision":
"accept"}` (:4061,:542) rather than left to hang the turn forever.

Turn-end (:1986-2001, :5297-5333): `turn/completed` NOTIFICATION (not a
request/response - Codex tells us, we do not ask), `params.turn.status` a
bare string (`completed|failed|interrupted` observed), `params.turn.error.
message` optional. turnId for cancel comes from the EARLIER `turn_started`
notification (:5284-5294), not from turn/start's own response.

Cancel (:4253-4266): `turn/interrupt {threadId, turnId}`.

Reply text (:1789-1798, tool-call-mapper.ts): `item_completed` notification
where `item.type == "agentMessage"` carries the reply in `item.text` -
NOT in turn/completed itself. `item.type == "reasoning"` is the thinking
equivalent. Tool calls: `commandExecution|fileChange|mcpToolCall|webSearch`
item types (tool-call-mapper.ts:1035-1043), status normalized through the
SAME shared vocabulary OpenCode's own mapper uses (failed/canceled/
completed/running - analysis doc §4.3) - only commandExecution ("shell",
the common case: command/cwd/aggregatedOutput/exitCode,
tool-call-mapper.ts:693-720) is mapped here; fileChange/mcpToolCall/
webSearch fall back to a generic tool step rather than guessing their
exact field shapes unverified.

Cost: tokens only (`thread/tokenUsage/updated`, `toAgentUsage`,
codex-app-server-agent.ts:884-901) - `usage.last.{inputTokens,
cachedInputTokens,outputTokens}`, CamelCase (unlike claude's snake_case).
No cost field exists at all for Codex, native or not - the "n/a, never a
fabricated 0" rule applies exactly as it does for the ACP path.
"""
import json
import os
import shutil
import subprocess
import threading
import time as _time

from spine.agent import timeline_store
from spine.agent.proctable import _tree_kill, _record_pid, _forget_pid

_TL_MAX_TEXT = 200_000
_TL_MAX_THINK = 60_000
_TL_MAX_RESULT = 8_000

CODEX = shutil.which("codex") or "codex"

CODEX_CLIENT_INFO = {
    "name": "codex_app_server_daemon",
    "title": "HelmDeck Codex Driver",
    "version": "0.0.0",
}

_sessions = {}
_sessions_guard = threading.Lock()
_cancelled = set()


def _write(path, text):
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass


def build_argv(cfg):
    """THE assembly point for a codex argv - one owner. No cwd/session flags
    here (both are per-RPC-call params, not argv - see module docstring)."""
    return [cfg.get("exe") or CODEX, "app-server"]


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


class _CodexRpc:
    """Bidirectional JSON-RPC 2.0 framing over stdio. Unlike omp's simpler
    typed-request protocol, Codex is genuinely bidirectional: it can send US
    a `method`-bearing REQUEST (an approval ask) that expects OUR response,
    not just notifications. Three inbound shapes, dispatched in _pump:
      - {"id": N, "result"/"error": ...}   a response to OUR request
      - {"method": ..., "params": ...}      a notification (no id)
      - {"id": N, "method": ..., "params": ...}  a REQUEST needing our reply
    """

    def __init__(self, proc):
        self.proc = proc
        self._next_id = 1
        self._pending = {}
        self._lock = threading.Lock()
        self.on_notification = None    # set by _CodexSession
        self.on_request = None         # set by _CodexSession -> returns a result dict

    def request(self, method, params=None, timeout=30.0):
        with self._lock:
            rid = self._next_id
            self._next_id += 1
        ev = threading.Event()
        self._pending[rid] = {"ev": ev, "resp": None}
        msg = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        ok = ev.wait(timeout)
        slot = self._pending.pop(rid, None)
        if not ok or slot is None or slot["resp"] is None:
            raise RuntimeError("codex request timed out: %s" % method)
        resp = slot["resp"]
        if "error" in resp and resp["error"]:
            raise RuntimeError("codex error on %s: %s" % (method, resp["error"]))
        return resp.get("result")

    def notify(self, method, params=None):
        msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def _respond(self, rid, result):
        msg = {"jsonrpc": "2.0", "id": rid, "result": result}
        try:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
        except Exception:
            pass

    def handle_line(self, obj):
        if "id" in obj and "method" not in obj:
            slot = self._pending.get(obj["id"])
            if slot:
                slot["resp"] = obj
                slot["ev"].set()
            return
        if "id" in obj and "method" in obj:
            result = {"decision": "accept"}
            if self.on_request:
                try:
                    result = self.on_request(obj["method"], obj.get("params") or {}) or result
                except Exception:
                    pass
            self._respond(obj["id"], result)
            return
        if "method" in obj:
            if self.on_notification:
                try:
                    self.on_notification(obj["method"], obj.get("params") or {})
                except Exception:
                    pass


_TOOL_ITEM_TYPES = {"commandExecution", "fileChange", "mcpToolCall", "webSearch"}
_FAILED_STATUS = {"failed", "failure", "error", "errored", "rejected", "denied"}
_CANCELED_STATUS = {"canceled", "cancelled", "interrupted", "aborted"}
_COMPLETED_STATUS = {"completed", "complete", "done", "success", "succeeded"}


def _normalize_tool_status(raw, has_error):
    """Same shared vocabulary OpenCode's own mapper uses (analysis §4.3) -
    Codex's tool-call-mapper.ts calls the identical-shaped
    normalizeToolCallStatus helper, not a Codex-only one."""
    if has_error:
        return "failed"
    n = (raw or "").strip().lower()
    if n in _FAILED_STATUS:
        return "failed"
    if n in _CANCELED_STATUS:
        return "canceled"
    if n in _COMPLETED_STATUS:
        return "completed"
    return "running"


class _CodexSession:
    """One long-lived `codex app-server` process for a card, reused across
    turns - the same persistent-process, single-pump-thread, tree-kill-on-
    teardown model as drivers.py's _ClaudeSession and omp_driver's
    _OmpSession."""

    def __init__(self, cfg, t):
        self.tid = t["id"]
        self.cfg = cfg
        self.worktree = t.get("worktree") or "."
        self.run_dir = t.get("run_dir") or "."
        self.thread_id = t.get("session_id")
        self.proc = None
        self.rpc = None
        self._alive = False
        self._cur = None
        self._turn_lock = threading.Lock()
        self.last_used = _time.time()
        self.spawn_time = 0.0
        self.err_tail = []
        from spine.registry import harness
        agent = "machine-worker" if t.get("machine") else "card-worker"
        self.brief = harness.brief(agent)
        self._spawn()

    def _spawn(self):
        argv = build_argv(self.cfg)
        self.proc = subprocess.Popen(argv, cwd=self.worktree,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, env=_env(self.cfg),
                                     text=True, encoding="utf-8", errors="replace",
                                     bufsize=1,
                                     # no console: the daemon runs under pythonw,
                                     # so without this the agent gets its own
                                     # (empty) console window that steals focus
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.spawn_time = _time.time()
        _record_pid(self.proc.pid, self.spawn_time)
        self.err_tail = []
        self._alive = True
        self.rpc = _CodexRpc(self.proc)
        self.rpc.on_notification = self._on_notification
        self.rpc.on_request = self._on_request
        threading.Thread(target=self._drain_err, daemon=True).start()
        threading.Thread(target=self._pump, daemon=True).start()
        try:
            self.rpc.request("initialize", {
                "clientInfo": CODEX_CLIENT_INFO,
                "capabilities": {"experimentalApi": True,
                                 "mcpServerOpenaiFormElicitation": True},
            })
            self.rpc.notify("initialized", {})
        except Exception as e:
            self.err_tail.append("initialize failed: %s\n" % e)
            self._alive = False
            return
        if self.thread_id:
            try:
                self.rpc.request("thread/resume",
                    {"threadId": self.thread_id, "developerInstructions": self.brief})
            except Exception as e:
                # STALE-RESUME DEGRADATION (matches drivers.py _spawn's own
                # rule for claude): a thread the server no longer has -> a
                # fresh one, with a visible note, never a hard spawn failure.
                self.err_tail.append("thread/resume failed, starting fresh: %s\n" % e)
                self.thread_id = None
                if self.run_dir:
                    try:
                        from spine.ops.actionlog import ActionLog
                        ActionLog(self.run_dir).log("note",
                            "Codex Thread nicht mehr auffindbar - starte frische Session.")
                    except Exception:
                        pass

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
        _cancelled.add(self.tid)
        cur = self._cur
        if not self.alive() or cur is None:
            if cur and not cur["done"].is_set():
                cur["done"].set()
            return
        turn_id = cur.get("turn_id")
        if not turn_id or not self.thread_id:
            # can't interrupt before turn/started names the turn (measured
            # Codex constraint, :4253-4257) - hard-kill, still resumable
            # via thread/resume on the next steer.
            self.kill()
            if not cur["done"].is_set():
                cur["done"].set()
            return
        try:
            self.rpc.request("turn/interrupt",
                {"threadId": self.thread_id, "turnId": turn_id}, timeout=5.0)
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
                    obj = json.loads(line)
                except ValueError:
                    continue
                self.rpc.handle_line(obj)
        except Exception:
            pass
        finally:
            self._alive = False
            cur = self._cur
            if cur and not cur["done"].is_set():
                cur["done"].set()

    def _on_request(self, method, params):
        """Inbound approval asks. UNATTENDED mode (approvalPolicy:"never")
        should mean these never fire - handled defensively anyway so an
        unexpected one can never hang a turn forever."""
        return {"decision": "accept"}

    def _on_notification(self, method, params):
        cur = self._cur
        if cur is not None:
            cur["last_event"] = _time.time()
        ts, ta = _time.strftime("%H:%M:%S", _time.localtime()), _time.time()
        if method == "turn/started":
            turn = params.get("turn") or {}
            if cur is not None:
                cur["turn_id"] = turn.get("id") or params.get("turnId")
        elif method == "turn/completed":
            turn = params.get("turn") or {}
            if cur is not None:
                cur["status"] = turn.get("status")
                cur["error"] = (turn.get("error") or {}).get("message")
                cur["done"].set()
        elif method == "thread/tokenUsage/updated":
            u = (params.get("tokenUsage") or {}).get("last") or {}
            inp = int(u.get("inputTokens") or 0)
            cache = int(u.get("cachedInputTokens") or 0)
            out = int(u.get("outputTokens") or 0)
            if inp or cache or out:
                timeline_store.append(self.run_dir, "s:" + _uid(),
                    {"kind": "usage", "tokIn": inp, "tokOut": out,
                     "cacheRead": cache, "cacheWrite": 0, "ctx": inp + cache,
                     "ts": ts, "ta": ta})
        elif method in ("item/started", "item/completed",
                       "codex/event/item_started", "codex/event/item_completed"):
            item = params.get("item") or (params.get("msg") or {}).get("item") or {}
            self._fold_item(item, method.endswith("completed"), ts, ta)

    def _fold_item(self, item, is_completed, ts, ta):
        from spine.agent.claude_transcript_fmt import _clean_text
        itype = item.get("type")
        iid = item.get("id")
        if itype == "agentMessage":
            if not is_completed:
                return
            text = _clean_text((item.get("text") or "").strip())
            if text:
                timeline_store.append(self.run_dir, "s:" + _uid(),
                    {"role": "assistant", "kind": "text", "text": text[:_TL_MAX_TEXT],
                     "ts": ts, "ta": ta})
        elif itype == "reasoning":
            if not is_completed:
                return
            text = (item.get("text") or item.get("summary") or "").strip()
            if text:
                timeline_store.append(self.run_dir, "s:" + _uid(),
                    {"role": "assistant", "kind": "thinking", "text": text[:_TL_MAX_THINK],
                     "ts": ts, "ta": ta})
        elif itype in _TOOL_ITEM_TYPES and iid:
            has_error = item.get("error") is not None
            status = _normalize_tool_status(item.get("status"), has_error)
            if itype == "commandExecution":
                name, label = "shell", "Befehl"
                cmd = item.get("command")
                cmd_text = cmd if isinstance(cmd, str) else json.dumps(cmd) if cmd else ""
                sub = cmd_text[:160]
                out = item.get("aggregatedOutput") or ""
            else:
                name, label = itype, itype
                sub = ""
                out = ""
            if not is_completed:
                timeline_store.append(self.run_dir, "tool:" + iid,
                    {"role": "assistant", "kind": "tool", "tool": name, "label": label,
                     "text": sub, "result": "", "ok": True, "status": "running",
                     "error": None, "running": True, "ts": ts, "ta": ta})
            else:
                err_text = None
                if has_error:
                    e = item.get("error")
                    err_text = str(e if isinstance(e, str) else json.dumps(e))[:500]
                timeline_store.append(self.run_dir, "tool:" + iid,
                    {"result": str(out)[:_TL_MAX_RESULT], "ok": status != "failed",
                     "status": status, "error": err_text, "running": False})

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
        if not self.alive():
            raise RuntimeError("codex session failed to start: %s"
                               % "".join(self.err_tail).strip()[-300:])
        cur = {"turn_id": None, "status": None, "error": None,
               "done": threading.Event(), "last_event": _time.time()}
        self._cur = cur
        try:
            if not self.thread_id:
                approval = {"approvalPolicy": "never",
                           "sandboxPolicy": {"type": "danger-full-access",
                                            "networkAccess": True}}
                result = self.rpc.request("thread/start",
                    dict(approval, cwd=self.worktree, developerInstructions=self.brief))
                thread = (result or {}).get("thread") or {}
                self.thread_id = thread.get("id")
                if not self.thread_id:
                    raise RuntimeError("codex thread/start did not return a thread id")
            params = {"threadId": self.thread_id,
                      "input": [{"type": "text", "text": prompt}],
                      "approvalPolicy": "never",
                      "sandboxPolicy": {"type": "danger-full-access", "networkAccess": True},
                      "developerInstructions": self.brief}
            if self.cfg.get("model"):
                params["model"] = self.cfg["model"]
            self.rpc.request("turn/start", params, timeout=15.0)
        except Exception as e:
            self._cur = None
            self.kill()
            raise RuntimeError("codex turn/start failed: %s" % e)
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
            return self.thread_id, "(turn cancelled by you)", \
                {"usage": {}, "cost_usd": None, "models": [], "canceled": True}
        if not finished:
            self.kill()
            raise RuntimeError(
                "codex turn stalled (%s) - session killed; steer again to resume. %s"
                % (why, "".join(self.err_tail).strip()[-200:]))
        status = cur.get("status")
        if status == "interrupted":
            return self.thread_id, "(turn cancelled by you)", \
                {"usage": {}, "cost_usd": None, "models": [], "canceled": True}
        # The final reply text is whatever the LAST agentMessage item folded
        # into the store during this turn - turn/completed itself carries no
        # text (measured, see module docstring). Read it back from the
        # store rather than tracking it separately in `cur`, since the fold
        # (_fold_item) is already the one place that parses item content.
        steps = timeline_store.read(run_dir)
        reply = ""
        for st in reversed(steps):
            if st.get("kind") == "text" and st.get("role") == "assistant":
                reply = st.get("text") or ""
                break
        meta = {"usage": {}, "cost_usd": None, "models": [self.cfg.get("model")]
                if self.cfg.get("model") else [],
                "is_error": status == "failed", "error": (cur.get("error") or "")[:500]}
        return self.thread_id, reply, meta


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
            s = _CodexSession(cfg, t)
            _sessions[tid] = s
        return s


def run(cfg, t, prompt, by=None):
    # `by` accepted for signature parity with drivers.run, not yet folded
    # into this driver's own transcript - see debt `alt-driver-by-wiring`.
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
