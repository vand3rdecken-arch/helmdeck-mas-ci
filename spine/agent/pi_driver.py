# -*- coding: utf-8 -*-
"""Pi native driver - the deferred half of Card 8
(ops/docs/multi-engine-build-plan.md; the omp half shipped 2026-08-24 as
omp_driver.py, live-verified against a real account).

NOT LIVE-VERIFIED (no `pi` CLI on this box, no account - owner decree
2026-08-24, "test accounts later"). Deliberately modeled CLOSELY on
omp_driver.py's structure rather than written from scratch, because omp's
measurement work already proved something Paseo's own TS source did not
warn about: a single submitted prompt can produce MULTIPLE internal
turn_start/turn_end pairs when tool calls are involved, and only agent_end
(not the first turn_end) is the reliable completion signal. Pi and omp
share the same `PI_*`-prefixed env var family and the identical REQUEST
shape (`{"type":"prompt","message":str}` matches Paseo's own
`PiAgentRunRequest` in pi/rpc-types.ts:130 verbatim - confirmed by grep,
not assumed) - close enough that applying the SAME hard-won lesson here
proactively is more defensible than trusting the TS spec alone a second
time. This is a documented judgement call, not a proven fact: pi and omp
are "close cousins", not confirmed byte-identical. Card 8's remaining
verify step (a real pi account) either confirms this or finds pi's own
surprise, the same way omp had one - do not skip that step.

ONE MEASURED DIFFERENCE FROM omp, kept deliberately: Paseo's own default
launch mode for pi is `--mode rpc` (pi/runtime.ts:85: `protocolMode ??
"rpc"`), NOT `rpc-ui`. This driver uses `--mode rpc-ui` anyway - the ONE
protocol variant that has actually been proven end-to-end (on omp, a
closely related binary), rather than the spec-default variant that has
never been run against a real process at all. If Pi's `rpc` and `rpc-ui`
modes turn out to speak materially different event shapes, Card 8's
verification will surface that immediately (the same way it would for any
other assumption in this file).

Not refactored into a shared base class with omp_driver.py despite the
near-duplication: the shipped, live-verified omp driver should not be
put at risk to accommodate a not-yet-verified second engine. Worth
revisiting ONCE pi is also live-verified - two independently PROVEN
similar things are the right moment to unify, not two things where only
one has been checked against reality.

Session identity: a FILE PATH (`--session <path>`), same as omp - proven
live for omp, assumed (not yet proven) to work identically for pi given
they share the same launch-arg convention (pi/runtime.ts:122-131:
`--no-session` / `--session <path>`, matching exactly what omp's
`--help` documented and what was then measured to actually work).

Pi-specific launch args Paseo documents (pi/runtime.ts:110-138) that omp's
measured `--help` did not surface: `--thinking <level>`, `--mcp-config
<path>`, `--extension <path>` (repeatable). Supported here as optional,
cfg-driven additions - never assumed necessary, never hardcoded on.
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
from spine.agent import spawnenv   # worker_creationflags: ONE owner of the priority flag

_TL_MAX_TEXT = 200_000
_TL_MAX_THINK = 60_000
_TL_MAX_RESULT = 8_000

PI = shutil.which("pi") or "pi"

_sessions = {}
_sessions_guard = threading.Lock()
_cancelled = set()


def build_argv(cfg, worktree, run_dir, brief=None):
    """THE assembly point for a pi argv - one owner, mirrors omp_driver.
    build_argv. `--mode rpc-ui` is a deliberate choice, not the spec
    default - see module docstring."""
    argv = [cfg.get("exe") or PI, "--mode", "rpc-ui", "--cwd", worktree,
            "--session", os.path.join(run_dir, "pi_session")]
    if cfg.get("model"):
        argv += ["--model", cfg["model"]]
    if cfg.get("thinking"):
        argv += ["--thinking", cfg["thinking"]]
    if cfg.get("mcp_config"):
        argv += ["--mcp-config", cfg["mcp_config"]]
    for ext in cfg.get("extensions") or []:
        argv += ["--extension", ext]
    if brief:
        argv += ["--append-system-prompt", brief]
    return argv


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


class _PiSession:
    """One long-lived `pi --mode rpc-ui` process per card - identical
    lifecycle discipline to omp_driver's _OmpSession (tree-kill, PID
    registration, one turn at a time)."""

    def __init__(self, cfg, t):
        self.tid = t["id"]
        self.cfg = cfg
        self.worktree = t.get("worktree") or "."
        self.run_dir = t.get("run_dir") or "."
        self.proc = None
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
        argv = build_argv(self.cfg, self.worktree, self.run_dir, self.brief)
        self.proc = subprocess.Popen(argv, cwd=self.worktree,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
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
        """`{"type":"abort"}` - matches omp's proven shape AND Paseo's own
        pi/rpc-types.ts:133 (`{id?, type:"abort"}`), so this one is
        source-confirmed on both sides, not just an omp-borrowed guess."""
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

    def _fold_message(self, msg, role, ts, ta):
        content = msg.get("content") or []
        for p in content:
            pt = p.get("type")
            if pt == "text":
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
                timeline_store.append(self.run_dir, "tool:" + uid,
                    {"role": role, "kind": "tool", "tool": name, "label": name,
                     "text": str(args)[:160], "result": "", "ok": True,
                     "status": "running", "error": None, "running": True,
                     "ts": ts, "ta": ta})

    def _fold_stats(self, stats):
        """pi/cli-runtime.ts:171-201 - get_session_stats -> stats.cost, with
        a version-compat fallback to get_state.contextUsage this driver does
        NOT implement (unverified how that fallback's shape differs; Card 8
        should confirm get_session_stats exists on the installed pi version
        before relying on it, same as Paseo's own fallback exists precisely
        because it sometimes doesn't)."""
        cur = self._cur
        cost = stats.get("cost")
        if cur is not None and isinstance(cost, (int, float)):
            cur["cost_usd"] = round(cur.get("cost_usd", 0.0) + float(cost), 6)

    def _on_event(self, ev):
        cur = self._cur
        typ = ev.get("type")
        if cur is not None:
            cur["last_event"] = _time.time()
        ts, ta = _time.strftime("%H:%M:%S", _time.localtime()), _time.time()
        if typ == "message_end":
            m = ev.get("message") or {}
            role = m.get("role")
            if role in ("user", "assistant") and m.get("content"):
                self._fold_message(m, role, ts, ta)
        elif typ == "tool_execution_end":
            uid = ev.get("toolCallId")
            if not uid:
                return
            result = ev.get("result") or {}
            texts = [c.get("text", "") for c in (result.get("content") or [])
                    if isinstance(c, dict)]
            text = "\n".join(t for t in texts if t)
            is_err = bool(ev.get("isError"))
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
            # NOT the completion signal - see module + omp_driver.py
            # docstrings for the measured reason (applied here proactively,
            # unverified for pi specifically).
            if cur is not None:
                cur["result"] = ev.get("message") or {}
        elif typ == "agent_end":
            if cur is not None:
                msgs = ev.get("messages") or []
                last_assistant = [m for m in msgs if m.get("role") == "assistant"]
                if last_assistant:
                    cur["result"] = last_assistant[-1]
                cur["done"].set()
        elif typ == "response":
            if ev.get("command") == "get_session_stats" and ev.get("success"):
                self._fold_stats(ev.get("data") or {})
            if ev.get("success") is False and cur is not None:
                cur["rpc_error"] = ev.get("error")

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
            raise RuntimeError("pi session write failed: %s" % e)
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
                "pi turn stalled (%s) - session killed; steer again to resume. %s"
                % (why, "".join(self.err_tail).strip()[-200:]))
        d = cur["result"]
        if not d:
            self.kill()
            raise RuntimeError("pi stream ended with no result: "
                               + "".join(self.err_tail).strip()[:300])
        if d.get("stopReason") == "aborted":
            return None, "(turn cancelled by you)", \
                {"usage": {}, "cost_usd": None, "models": [], "canceled": True}
        reply = "".join(p.get("text", "") for p in (d.get("content") or [])
                        if p.get("type") == "text")
        meta = {"usage": {}, "cost_usd": cur["cost_usd"] if cur["cost_usd"] else None,
                "models": [d.get("model")] if d.get("model") else [],
                "is_error": bool(d.get("error")), "error": str(d.get("error") or "")[:500]}
        return None, reply, meta


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
            s = _PiSession(cfg, t)
            _sessions[tid] = s
        return s


def run(cfg, t, prompt):
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
