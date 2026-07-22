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
import json, os, shutil, subprocess
import urllib.request

CLAUDE = (os.environ.get("SWARMDECK_CLAUDE") or shutil.which("claude")
          or r"C:\Program Files\nodejs\claude.cmd")

# live subprocesses by track id, so the composer's Stop button can really kill a
# running turn (not just look like it). cancel() terminates; the driver returns a
# clean "(cancelled)" turn rather than raising.
_running = {}
_cancelled = set()


def cancel(tid):
    """Terminate the track's in-flight turn if one is running. Idempotent."""
    _cancelled.add(tid)
    p = _running.get(tid)
    if p:
        try:
            p.terminate()
        except Exception:
            pass
    return bool(p)


def run(cfg, t, prompt):
    kind = cfg.get("type", "claude")
    if kind == "claude":
        return _claude(cfg, t, prompt)
    if kind == "http":
        return _http(cfg, t, prompt)
    if kind == "cmd":
        return _cmd(cfg, t, prompt)
    raise RuntimeError("unknown driver type: " + kind)

def _claude(cfg, t, prompt):
    cmd = ["cmd", "/c", CLAUDE, "-p", "--output-format", "json",
           "--permission-mode", cfg.get("perm", t.get("perm", "acceptEdits"))]
    if cfg.get("model"):
        cmd += ["--model", cfg["model"]]
    for pat in cfg.get("allowed_tools") or []:
        cmd += ["--allowedTools", pat]
    if t.get("session_id"):
        cmd += ["--resume", t["session_id"]]
    timeout = cfg.get("timeout", 1800 if cfg.get("allowed_tools") else 600)
    tid = t["id"]
    _cancelled.discard(tid)
    # encoding="utf-8" so claude's UTF-8 output isn't mangled to cp1252 mojibake
    p = subprocess.Popen(cmd, cwd=t["worktree"], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, encoding="utf-8", errors="replace")
    _running[tid] = p
    try:
        out, err = p.communicate(input=prompt, timeout=timeout)
    finally:
        _running.pop(tid, None)
    if tid in _cancelled:                 # Stop was pressed - clean, not an error
        _cancelled.discard(tid)
        return t.get("session_id"), "(turn cancelled by you)", \
            {"usage": {}, "cost_usd": None, "models": []}
    if not (out or "").strip():
        raise RuntimeError("claude no output: " + (err or "").strip()[:300])
    d = json.loads(out)
    meta = {"usage": d.get("usage") or {}, "cost_usd": d.get("total_cost_usd"),
            "models": list((d.get("modelUsage") or {}).keys())}
    return d.get("session_id"), d.get("result", ""), meta

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
                       encoding="utf-8", errors="replace",
                       timeout=cfg.get("timeout", 1800))
    out = r.stdout.strip() or r.stderr.strip()
    return t.get("session_id"), out, {"usage": {}, "cost_usd": None, "models": []}
