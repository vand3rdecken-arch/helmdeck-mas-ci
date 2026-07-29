# -*- coding: utf-8 -*-
"""Driver layer - a card's work can be executed by ANY agent runtime, not just
Claude Code. A driver takes (config, track, prompt) and returns
(session_id, reply, meta) where meta = {usage, cost_usd, models}.

Drivers are declared in settings.json under "drivers"; a track picks one by
name (its "driver" field, default "claude"). Built-in types:

  claude - Claude Code CLI in the card's worktree, resumable sessions.
           opts: perm ("acceptEdits"...), model, allowed_tools (list of tool
           patterns pre-authorized for the headless session - e.g.
           ["mcp__windows-mcp__*"] lets it drive Windows/the browser through
           the globally-configured windows-mcp server; headless sessions cannot
           answer permission prompts, so unlisted tools stay unusable),
           record (bool: flight-record the screen for every turn).

  http   - POST to any agent API (Paseo, a custom orchestrator, n8n, ...).
           opts: url, headers {}. Request JSON:
             {"track": id, "worktree": path, "prompt": text, "session_id": prior}
           Expected response JSON:
             {"reply": text, "session_id"?: continue-key,
              "usage"?: {...}, "cost_usd"?: n, "models"?: [..]}

  cmd    - any CLI: opts: command (string, run with shell in the worktree),
           prompt on stdin, stdout is the reply. Stateless unless the command
           manages its own state.

The default settings ship "claude" and "claude-desktop" (windows-mcp allowed +
screen recording on). Point a card at "claude-desktop" and its agent can drive
apps/browser on this PC with the whole turn recorded - the flight-recorder
promise, now per-card."""
import json, os, shutil, subprocess, threading, time as _time
import urllib.request

CLAUDE = (os.environ.get("SWARMDECK_CLAUDE") or shutil.which("claude")
          or r"C:\Program Files\nodejs\claude.cmd")

# live subprocesses by track id, so the composer's Stop button can really kill a
# running turn (not just look like it). cancel() terminates; the driver returns a
# clean "(cancelled)" turn rather than raising.
_running = {}
_cancelled = set()


def cancel(tid):
    """Terminate the track's in-flight turn if one is running. Idempotent.
    Kills the whole process TREE - `p` is the `cmd /c claude` wrapper, so
    p.terminate() alone leaves the real claude/node child running (a ~10s+
    stop). taskkill /T /F on Windows takes the tree down immediately."""
    _cancelled.add(tid)
    p = _running.get(tid)
    if p:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                               capture_output=True, timeout=10)
            else:
                p.terminate()
        except Exception:
            try:
                p.terminate()
            except Exception:
                pass
    return bool(p)


def _env(cfg):
    """The environment the agent's shell inherits.

    A card runs in an isolated worktree, which keeps cards from trampling each
    other - but isolation alone does not give the agent a BUILD environment. The
    daemon is usually started from a bare shell (or by the desktop app), so
    JAVA_HOME / ANDROID_HOME / SDK paths are simply absent and any gradle,
    xcode or dotnet build fails before it starts. Declare them once per driver
    in settings.json:

        "drivers": {"claude": {"type": "claude", "env": {
            "JAVA_HOME": "C:/Program Files/Android/Android Studio/jbr",
            "ANDROID_HOME": "C:/Users/you/AppData/Local/Android/Sdk"}}}

    Values are layered over the daemon's own environment, and PATH entries can
    be prepended with the "PATH+" key so the toolchain wins without discarding
    the inherited PATH.
    """
    env = dict(os.environ)
    extra = cfg.get("env") or {}
    prepend = extra.get("PATH+")
    for k, v in extra.items():
        if k != "PATH+":
            env[k] = str(v)
    if prepend:
        env["PATH"] = str(prepend) + os.pathsep + env.get("PATH", "")
    return env


def run(cfg, t, prompt):
    kind = cfg.get("type", "claude")
    if kind == "claude":
        return _claude(cfg, t, prompt)
    if kind == "http":
        return _http(cfg, t, prompt)
    if kind == "cmd":
        return _cmd(cfg, t, prompt)
    raise RuntimeError("unknown driver type: " + kind)

# Every card agent gets the same standing orientation: what it CAN do, what
# the BOARD does, and how to hand off - so hitting a boundary produces a
# pointer to the workflow instead of a dead-end "I cannot do that".
_CARD_BRIEF = (
    "You are working ONE SwarmDeck card in an isolated git worktree. "
    "You CAN: edit files, run commands/tests/builds, and commit on THIS branch. "
    "You CANNOT (by design): merge to main, access secrets (.env/keys), or deploy - "
    "the owner accepts the card on the board, and accepting runs the repo deploy hook. "
    "Therefore NEVER end with just 'I cannot do X'. When your work is done and "
    "verified, end with a short DELIVERED summary and the sentence: "
    "'Ready for Review - move the card to Review; accepting it deploys.' "
    "If something truly blocks you, name the exact blocker and what the owner "
    "must change (a setting, a secret, a decision)."
)

def _claude(cfg, t, prompt):
    # stream-json so the turn streams token-by-token: the session_id arrives in
    # the first `system/init` event (so the UI can stream from turn 1) and text
    # deltas are written to run_dir/live_partial.txt as they land. The final
    # `result` event carries the SAME fields as the old buffered json
    # (result/total_cost_usd/usage/modelUsage) - economics & the gate are
    # unaffected: we read them from that one event exactly as before.
    cmd = ["cmd", "/c", CLAUDE, "-p", "--output-format", "stream-json",
           "--include-partial-messages", "--verbose",
           "--permission-mode", cfg.get("perm", t.get("perm", "acceptEdits")),
           "--append-system-prompt", _CARD_BRIEF]
    if cfg.get("model"):
        cmd += ["--model", cfg["model"]]
    for pat in cfg.get("allowed_tools") or []:
        cmd += ["--allowedTools", pat]
    if t.get("session_id"):
        cmd += ["--resume", t["session_id"]]
        # An adopted card still pointing at its SOURCE session must not write
        # into the desktop's live conversation: fork into a fresh session id
        # on the first steer. Afterwards the ids differ and this never fires.
        if t.get("adopted_source") and t.get("adopted_source") == t["session_id"]:
            cmd += ["--fork-session"]
    timeout = cfg.get("timeout", 1800 if cfg.get("allowed_tools") else 600)
    tid = t["id"]
    _cancelled.discard(tid)
    run_dir = t.get("run_dir") or "."
    live_path = os.path.join(run_dir, "live_partial.txt")
    sid_path = os.path.join(run_dir, "live_session.txt")
    for pth in (live_path, sid_path):
        try:
            if os.path.exists(pth):
                os.remove(pth)
        except OSError:
            pass
    p = subprocess.Popen(cmd, cwd=t["worktree"], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         env=_env(cfg),
                         text=True, encoding="utf-8", errors="replace", bufsize=1)
    _running[tid] = p
    err_tail = []

    def _drain_err():
        try:
            for ln in p.stderr:
                err_tail.append(ln)
                if len(err_tail) > 40:
                    del err_tail[0]
        except Exception:
            pass

    def _feed_in():
        try:
            p.stdin.write(prompt)
        except Exception:
            pass
        finally:
            try:
                p.stdin.close()
            except Exception:
                pass

    threading.Thread(target=_drain_err, daemon=True).start()
    threading.Thread(target=_feed_in, daemon=True).start()

    session_id = t.get("session_id")
    result_obj = None
    parts = []
    last_flush = [0.0]

    def _flush():
        try:
            with open(live_path, "w", encoding="utf-8") as f:
                f.write("".join(parts))
        except OSError:
            pass

    try:
        for line in p.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            typ = ev.get("type")
            if typ == "system":
                sid = ev.get("session_id")
                if sid and sid != session_id:
                    session_id = sid
                    try:
                        with open(sid_path, "w", encoding="utf-8") as f:
                            f.write(session_id)
                    except OSError:
                        pass
            elif typ == "result":
                result_obj = ev
            elif typ == "assistant":
                # a full assistant message just landed in the session .jsonl -
                # clear the live partial so the transcript (read from .jsonl)
                # shows it instead, with no double render.
                parts.clear()
                _flush()
            elif typ == "stream_event":
                e = ev.get("event") or {}
                if e.get("type") == "content_block_delta":
                    dl = e.get("delta") or {}
                    if dl.get("type") == "text_delta":
                        parts.append(dl.get("text", ""))
                        now = _time.time()
                        if now - last_flush[0] > 0.15:
                            last_flush[0] = now
                            _flush()
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            p.kill()
        except Exception:
            pass
    finally:
        _running.pop(tid, None)
        for pth in (live_path, sid_path):
            try:
                if os.path.exists(pth):
                    os.remove(pth)
            except OSError:
                pass

    if tid in _cancelled:                 # Stop was pressed - clean, not an error
        _cancelled.discard(tid)
        return session_id, "(turn cancelled by you)", \
            {"usage": {}, "cost_usd": None, "models": []}
    if not result_obj:
        raise RuntimeError("claude stream: no result event: " + "".join(err_tail).strip()[:300])
    d = result_obj
    meta = {"usage": d.get("usage") or {}, "cost_usd": d.get("total_cost_usd"),
            "models": list((d.get("modelUsage") or {}).keys())}
    return session_id or d.get("session_id"), d.get("result", ""), meta

def _http(cfg, t, prompt):
    body = {"track": t["id"], "worktree": t.get("worktree", ""),
            "prompt": prompt, "session_id": t.get("session_id")}
    req = urllib.request.Request(cfg["url"], data=json.dumps(body).encode(),
        headers=dict({"Content-Type": "application/json"}, **(cfg.get("headers") or {})))
    with urllib.request.urlopen(req, timeout=cfg.get("timeout", 1800)) as resp:
        d = json.loads(resp.read() or b"{}")
    meta = {"usage": d.get("usage") or {}, "cost_usd": d.get("cost_usd"),
            "models": d.get("models") or []}
    return d.get("session_id") or t.get("session_id"), d.get("reply", ""), meta

def _cmd(cfg, t, prompt):
    r = subprocess.run(cfg["command"], cwd=t.get("worktree") or ".", shell=True,
                       input=prompt, capture_output=True, text=True,
                       env=_env(cfg),
                       encoding="utf-8", errors="replace",
                       timeout=cfg.get("timeout", 1800))
    out = r.stdout.strip() or r.stderr.strip()
    return t.get("session_id"), out, {"usage": {}, "cost_usd": None, "models": []}
