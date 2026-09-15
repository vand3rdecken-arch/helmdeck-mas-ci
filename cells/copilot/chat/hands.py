# -*- coding: utf-8 -*-
"""HENRY'S HANDS - a one-shot sub-agent with the machine tools, spawned by the
daemon on Henry's request (owner decree 2026-09-13: "Henry kann auch machen,
aber dann neuer Subagent-Spawn als schnelle Alternative zur Karte").

The three tiers, and why this one exists:
  chat   = Henry's persistent port, LEAN: no MCP servers (harness.cli_args
           gives it --setting-sources '' so the user's ~/.claude.json servers
           never load), warm, seconds.
  hands  = THIS: a fresh claude -p with the machine-card MCP bridge
           (windows-mcp, helmdeck-browser via agentcli._mcp_config_arg), a
           scratch cwd, the card guard hook, one bounded job, no card.
  card   = worktree / lane / gate / accept for real work.

Henry's own Agent tool cannot do this: a CLI sub-agent inherits the parent's
MCP configuration, and the parent is lean on purpose.

INVARIANTS (CLAUDE.md laws): the process is registered in driver_pids.json
(proctable) so a restart waits for it; every spawn and every end is an
append-only event (kind "hands"); the result lands in the owner's transcript
as an act row and in Henry's next turn (_pending_actions) - never invisible.
State here is an in-memory descriptor table mutated at exactly one owner
(this module) from the child's own stream; the UI reads it through
copilot.history()["followups"] as the same BgTask shape a card uses."""
import json
import os
import subprocess
import threading
import time
import uuid

from daemon.paths import DAEMON_ROOT

_lock = threading.Lock()
_tasks = {}          # id -> {title, status, since, updated, detail, result, pid, user, skey, card}
SILENCE_S = 600      # no stream output for this long = hung -> tree-kill (turn idle-watchdog parity)
MCP_GRANTS = ["mcp__windows-mcp__*", "mcp__helmdeck-browser__*"]


def tasks(closed_within_s=3600):
    """BgTask-shaped descriptors for the chat's background line."""
    now = time.time()
    out = {}
    with _lock:
        for hid, t in _tasks.items():
            if t["status"] != "running" and now - t["updated"] > closed_within_s:
                continue
            out[hid] = {"title": t["title"], "status": t["status"], "since": t["since"],
                        "updated": t["updated"], "detail": t["detail"], "result": t["result"]}
    return out


def running_ids():
    with _lock:
        return [k for k, t in _tasks.items() if t["status"] == "running"]


def spawn(user, task, skey, card=None, why=""):
    """Start the hands process for `task` and return its id immediately."""
    from cells.copilot.chat import copilot
    from spine.agent import drivers, proctable
    from spine.agent.agentcli import _mcp_config_arg
    from spine.agent.spawnenv import tool_path
    from spine.registry import harness
    from spine.storage import events

    hid = time.strftime("%Y%m%d-%H%M%S") + "-hands-" + uuid.uuid4().hex[:6]
    scratch = os.path.join(DAEMON_ROOT, "state", "hands", hid)
    os.makedirs(scratch, exist_ok=True)
    title = (task or "").strip().splitlines()[0][:90] if (task or "").strip() else hid
    brief = harness.brief("hands") + "\n\nTASK (from Henry" + (", because: " + why if why else "") + "):\n" + task.strip() + "\n"
    argv = [copilot.CLAUDE, "-p", "--output-format", "stream-json", "--verbose",
            "--permission-mode", copilot.henry_pmode(),
            "--append-system-prompt-file", copilot._brief_file(brief)]
    argv += harness.cli_args("machine-worker")
    argv += _mcp_config_arg({"allowed_tools": MCP_GRANTS}, capper=True)
    env = tool_path()
    env["HELMDECK_TOOL_SCOPE"] = "hands"
    # the card guard confines file edits to HELMDECK_WORKTREE - for hands that
    # is the scratch folder (the brief says the same in prose; this is code)
    env["HELMDECK_WORKTREE"] = scratch
    env["MCP_TIMEOUT"] = env.get("MCP_TIMEOUT") or "60000"
    p = subprocess.Popen(drivers._cmd_line(argv), cwd=scratch, stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                         text=True, encoding="utf-8", errors="replace")
    with _lock:
        _tasks[hid] = {"title": title, "status": "running", "since": time.time(), "updated": time.time(),
                       "detail": task.strip()[:600], "result": "", "pid": p.pid, "user": user,
                       "skey": skey, "card": card}
    proctable._record_pid(p.pid, time.time())
    events.emit("hands", card or "-", action="spawned", id=hid, actor=user, task=title, why=why[:200])
    threading.Thread(target=_pump, args=(hid, p), daemon=True, name="hands-" + hid).start()
    return hid


def _pump(hid, p):
    from spine.agent import proctable
    try:
        p.stdin.write("Do the TASK in your system prompt now."); p.stdin.close()
    except Exception:                                    # noqa: BLE001
        pass
    last = time.time()
    result, is_error, steps = "", False, 0
    watchdog = {"stop": False}

    def _watch():
        while not watchdog["stop"]:
            if time.time() - last > SILENCE_S:
                try:
                    proctable._tree_kill(p)
                except Exception:                        # noqa: BLE001
                    pass
                return
            time.sleep(10)
    threading.Thread(target=_watch, daemon=True).start()
    for line in p.stdout:
        last = time.time()
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "assistant":
            for b in ((ev.get("message") or {}).get("content") or []):
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    steps += 1
                    with _lock:
                        if hid in _tasks:
                            _tasks[hid]["result"] = "%d Schritte, zuletzt %s" % (steps, b.get("name"))
                            _tasks[hid]["updated"] = time.time()
        elif ev.get("type") == "result":
            result = str(ev.get("result") or "")
            is_error = bool(ev.get("is_error"))
    watchdog["stop"] = True
    err = ""
    try:
        err = (p.stderr.read() or "")[:400]
    except Exception:                                    # noqa: BLE001
        pass
    rc = p.wait()
    proctable._forget_pid(p.pid)
    if not result:
        result = ("FAILED - no report (rc=%s) %s" % (rc, err.strip())).strip()
        is_error = True
    head = result.strip().splitlines()[0].upper() if result.strip() else ""
    status = "failed" if (is_error or head.startswith("FAILED")) else "completed"
    with _lock:
        t = _tasks.get(hid)
        if t:
            t["status"], t["result"], t["updated"] = status, result[:2000], time.time()
    _land(hid, status, result, steps)


def _land(hid, status, result, steps):
    """The report reaches the owner (transcript row) AND Henry (next turn)."""
    from cells.copilot.chat import copilot
    from spine.storage import events
    with _lock:
        t = dict(_tasks.get(hid) or {})
    if not t:
        return
    user, skey, card, title = t.get("user"), t.get("skey"), t.get("card"), t.get("title")
    # Henry gets the WHOLE report (owner 2026-09-15: the 700-char cut fed him
    # a DM-failure report ending mid-sentence at "The TASK block didn'", so
    # he never saw the passcode/permission lines and invented a still-open
    # browser window); the chat act row stays a readable excerpt.
    full = result.strip()[:4000]
    short = result.strip()[:1500]
    events.emit("hands", card or "-", action=status, id=hid, actor=user, steps=steps,
                result=short[:300])
    try:
        with copilot._pending_lock:
            copilot._pending_actions.setdefault(skey, []).append(
                "HANDS %s (%s): %s\n%s" % (status.upper(), hid, title, full))
    except Exception:                                    # noqa: BLE001
        pass
    line = "Hände %s: %s\n%s" % ("fertig" if status == "completed" else "fehlgeschlagen", title, short)
    try:
        if card:
            from spine.agent import timeline_store
            from cells.engineer.cards import sessions
            tr = sessions.get_track(card) or {}
            if tr.get("run_dir"):
                timeline_store.append(tr["run_dir"], "s:" + uuid.uuid4().hex,
                                      {"kind": "note", "text": line, "byKind": "henry",
                                       "ts": time.strftime("%H:%M:%S"), "ta": time.time()})
        else:
            copilot._append_log(user, [{"cls": "act", "text": line, "ts": time.strftime("%H:%M")}])
    except Exception:                                    # noqa: BLE001
        pass
