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
import json, os, re as _re, shutil, subprocess, threading, time as _time, uuid
import urllib.request

_re_bg_done = _re.compile(r"<tool-use-id>(.*?)</tool-use-id>", _re.S)

import ask   # the typed question channel taught to every worker (Phase 2.4)

CLAUDE = (os.environ.get("HELMDECK_CLAUDE") or shutil.which("claude")
          or r"C:\Program Files\nodejs\claude.cmd")

# Persistent Claude sessions by track id - modelled on Paseo's provider/claude
# agent (see _paseo_src packages/server/.../claude/agent.ts). A card holds ONE
# long-lived `claude --input-format stream-json` process across turns: a steer is
# a message PUSHED onto its stdin, a background pump thread owns the single stdout
# reader, and every teardown TREE-KILLS the whole process tree (claude + MCP/node
# children) the way Paseo's terminateWithTreeKill does - so a stalled turn can
# never hold a lock forever and killed daemons never leak orphan claude.exe.
_sessions = {}
_sessions_guard = threading.Lock()
_cancelled = set()

# --- process-tree kill + orphan reaping (Paseo: utils/tree-kill.ts) ---------

def _pid_table():
    """[(pid, ppid, exe)] for every live process (Windows), via a ctypes
    Toolhelp32 snapshot - no subprocess, no PATH dependency (PowerShell is NOT
    guaranteed to be on PATH: this very dev box lacks it), and the only reliable
    way to know a tree BEFORE we start killing it."""
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD),
                    ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_char * 260)]

    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)     # TH32CS_SNAPPROCESS
    if snap in (None, wintypes.HANDLE(-1).value):
        return []
    out = []
    try:
        e = PROCESSENTRY32()
        e.dwSize = ctypes.sizeof(PROCESSENTRY32)
        ok = k32.Process32First(snap, ctypes.byref(e))
        while ok:
            out.append((int(e.th32ProcessID), int(e.th32ParentProcessID),
                        e.szExeFile.decode("mbcs", "replace")))
            ok = k32.Process32Next(snap, ctypes.byref(e))
    finally:
        k32.CloseHandle(snap)
    return out


def _descendants(pid):
    """All live descendant pids of `pid`, snapshotted BEFORE the kill. taskkill
    /T walks the tree at kill time - if the parent died first (polite pass), it
    can no longer see the children, which is exactly how MCP/node orphans leak."""
    try:
        table = _pid_table()
    except Exception:
        return []
    kids = {}
    for p, pp, _exe in table:
        kids.setdefault(pp, []).append(p)
    out, stack, seen = [], [pid], {pid}
    while stack:
        for c in kids.get(stack.pop(), []):
            if c not in seen:
                seen.add(c)
                out.append(c)
                stack.append(c)
    return out


def _tree_kill(proc, grace=2.0):
    """Take the whole process tree down, escalating (Paseo tree-kill parity):
    polite signal -> grace -> force -> CONFIRM the descendants are gone. `proc`
    is the `cmd /c claude` wrapper, so terminate() alone leaves the real
    claude/node child (and its MCP children) running. The polite pass gives
    claude a chance to flush its session .jsonl; the confirm pass reaps MCP
    orphans whose parent died first (invisible to taskkill /T by then)."""
    if proc is None:
        return
    try:
        if proc.poll() is not None:
            _forget_pid(proc.pid)
            return
    except Exception:
        pass
    pid = proc.pid
    try:
        if os.name == "nt":
            family = _descendants(pid)                      # snapshot BEFORE killing
            subprocess.run(["taskkill", "/T", "/PID", str(pid)],   # polite (WM_CLOSE)
                           capture_output=True, timeout=10)
            try:
                proc.wait(timeout=grace)
            except Exception:
                pass
            if proc.poll() is None:                          # ignored -> force
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                               capture_output=True, timeout=10)
            # confirm: reap surviving descendants one by one. Guarded by the
            # image check so a recycled pid can never hit an innocent process.
            try:
                alive = {p for p, _pp, _exe in _pid_table()}
            except Exception:
                alive = set()
            for cp in family:
                if cp in alive and _is_agent_pid(cp):
                    subprocess.run(["taskkill", "/F", "/PID", str(cp)],
                                   capture_output=True, timeout=10)
        else:
            proc.terminate()                                 # SIGTERM
            try:
                proc.wait(timeout=grace)
            except Exception:
                proc.kill()                                  # SIGKILL
        try:
            proc.wait(timeout=5)                             # confirm the wrapper died
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    _forget_pid(pid)


_PIDFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "driver_pids.json")
_pid_lock = threading.Lock()


def _read_pids():
    """driver_pids.json maps "<pid>" -> spawn epoch. Tolerates the legacy plain
    list format (no timestamps) by converting it to timestamp-less entries."""
    try:
        with open(_PIDFILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    if isinstance(data, list):
        return {str(p): None for p in data}
    return {str(k): v for k, v in (data or {}).items()}


def _write_pids(pids):
    try:
        tmp = _PIDFILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(pids, f)
        os.replace(tmp, _PIDFILE)
    except Exception:
        pass


def _record_pid(pid, spawn_time=None):
    with _pid_lock:
        pids = _read_pids()
        pids[str(pid)] = spawn_time
        _write_pids(pids)


def _forget_pid(pid):
    with _pid_lock:
        pids = _read_pids()
        if pids.pop(str(pid), "absent") != "absent":
            _write_pids(pids)


def _proc_start_epoch(pid):
    """OS-reported start time (UTC epoch seconds) of a live pid, or None.
    ctypes GetProcessTimes, not PowerShell: powershell.exe is not guaranteed on
    PATH (this dev box lacks it), and a silently-failing subprocess here would
    degrade the pid-reuse guard to the weaker image check without anyone noticing."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        k32.OpenProcess.restype = wintypes.HANDLE
        h = k32.OpenProcess(0x1000, False, int(pid))   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return None
        try:
            created, exited, kern, user = (wintypes.FILETIME(), wintypes.FILETIME(),
                                           wintypes.FILETIME(), wintypes.FILETIME())
            if not k32.GetProcessTimes(h, ctypes.byref(created), ctypes.byref(exited),
                                       ctypes.byref(kern), ctypes.byref(user)):
                return None
            t100 = (created.dwHighDateTime << 32) | created.dwLowDateTime
            return t100 / 1e7 - 11644473600.0          # FILETIME (1601) -> epoch (1970)
        finally:
            k32.CloseHandle(h)
    except Exception:
        return None


def _is_agent_pid(pid):
    """Weaker fallback guard: the pid is still a claude/node/cmd image."""
    if os.name != "nt":
        return True
    try:
        for p, _pp, exe in _pid_table():
            if p == pid:
                img = (exe or "").lower()
                return any(n in img for n in ("claude", "node", "cmd"))
        return False
    except Exception:
        return False


def _is_ours(pid, spawn_time):
    """Pid-reuse-safe identity check. If we recorded a spawn time AND the OS can
    report this pid's start time, require them to MATCH (a recycled pid would show
    a later start time). Only when the start time is unavailable do we fall back
    to the weaker claude/node/cmd image guard."""
    started = _proc_start_epoch(pid)
    if started is not None and spawn_time:
        return abs(started - float(spawn_time)) <= 6.0
    return _is_agent_pid(pid)


def reap_orphans():
    """On daemon start, tree-kill driver processes left running by a PREVIOUS
    daemon (crash/restart) so orphaned claude+MCP trees don't accumulate. Only
    PIDs WE recorded (and that pass the pid-reuse identity check) are touched -
    never a blanket claude.exe kill that would hit the desktop's own session."""
    with _pid_lock:
        rec = _read_pids()
        _write_pids({})
    killed = 0
    for pid_s, spawn in rec.items():
        try:
            pid = int(pid_s)
            if not _is_ours(pid, spawn):
                continue
            if os.name == "nt":
                r = subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                                   capture_output=True, timeout=10)
                if r.returncode == 0:
                    killed += 1
            else:
                os.kill(pid, 9)
                killed += 1
        except Exception:
            pass
    return killed


def cancel(tid):
    """Stop the track's in-flight turn (composer Stop). Unblocks the waiting turn
    with a clean '(cancelled)' and tree-kills the session; the next steer respawns
    and `--resume`s the session id, so no conversation is lost. Idempotent."""
    _cancelled.add(tid)
    with _sessions_guard:
        s = _sessions.get(tid)
    if s:
        s.cancel()
        return True
    return False


def has_session(tid):
    """True while this daemon holds a live worker session for the track. A track
    flagged status=running WITHOUT one is a zombie - its turn died with a prior
    daemon process (see sessions.sweep_zombies)."""
    with _sessions_guard:
        return tid in _sessions


def turn_active(tid):
    """True only while a TURN is actually in flight: the worker session exists,
    its subprocess is alive, and a turn is mutating state (_cur set).

    This is Paseo's lifecycle model made explicit (agent-manager.ts: a
    ManagedAgentRunning EXISTS only with an active foreground turn - "running"
    is a derived observation, never a remembered flag). has_session() is
    deliberately weaker: a persistent worker survives BETWEEN turns for
    `--resume` - most visibly after a soft cancel, which by design keeps the
    process for the next steer. Using has_session as the reconciler's liveness
    test therefore made an idle-after-cancel worker look busy FOREVER, so a
    card whose status write raced ('running' resurrected by a stale snapshot)
    froze with a spinner no sweep would ever clear."""
    with _sessions_guard:
        s = _sessions.get(tid)
    if s is None:
        return False
    try:
        return bool(s.alive() and s._cur is not None)
    except Exception:
        return False


# --- idle eviction + shutdown (Paseo: collectIdleAgents / closeAllAgents) ----
# A card holds ONE persistent worker, but keeping ALL touched cards' workers
# alive forever would leak memory on a busy board. So, like Paseo, a worker only
# lives for a short idle window after its last turn; the sweeper tree-kills it,
# and the next steer transparently respawns + `--resume`s (conversation is on
# disk, keyed by session id). There is deliberately NO concurrency cap - as in
# Paseo, live worker count is bounded by this idle eviction, not a semaphore.

_IDLE_TTL_DEFAULT = 300.0      # seconds a worker may sit idle before it's reaped
_SWEEP_INTERVAL = 15.0         # Paseo polls its idle collector this often
_sweeper_started = False


def _idle_ttl():
    try:
        import events
        v = events.settings().get("idle_session_ttl_s")
        if v:
            return float(v)
    except Exception:
        pass
    return _IDLE_TTL_DEFAULT


def _running_cards():
    """Track ids whose session must NOT be evicted.

    (a) status=running: a steer flips the flag BEFORE its turn reaches
        run_turn's lock, so for a moment the card is running while the session
        still looks idle - evicting in that window would tree-kill the process
        under the spawning turn.
    (b) waiting_on=background: the worker's background task is a CHILD of this
        session's process tree, so evicting the idle session would tree-kill the
        very task the card is waiting for (Phase 2.5). A background build easily
        outlives the 5-minute idle TTL, so without this the feature would kill
        its own subject - the session stays until the task is done."""
    try:
        import sessions
        return {t.get("id") for t in sessions._load()
                if t.get("status") == "running" or t.get("waiting_on") == "background"}
    except Exception:
        return set()


def sweep_idle(ttl=None):
    """One eviction pass: tree-kill sessions idle longer than ttl. Eviction takes
    the RUNTIME only - the conversation stays on disk keyed by session id, so the
    next steer transparently resumes it. Multi-condition guard (Paseo's
    collectIdleAgents): a session is reaped only when ALL hold -
      - past the idle TTL,
      - its card is not flagged running in the store,
      - no pending control-plane request (an interrupt/set_model in flight),
      - not marked protected (driver opts `protect_idle` in settings.json),
      - no turn holds its lock and no turn state is live.
    Returns the list of evicted track ids."""
    ttl = _idle_ttl() if ttl is None else ttl
    now = _time.time()
    running = _running_cards()
    evicted = []
    with _sessions_guard:
        for tid, s in list(_sessions.items()):
            if now - s.last_used < ttl:
                continue
            if tid in running:
                continue
            if s._ctrl:
                continue
            if (s.cfg or {}).get("protect_idle"):
                continue
            # only reap a session with no turn in flight - non-blocking acquire
            if not s._turn_lock.acquire(blocking=False):
                continue
            try:
                if s._cur is not None:
                    continue
                del _sessions[tid]
                evicted.append((tid, s))
            finally:
                s._turn_lock.release()
    for tid, s in evicted:
        try:
            s.kill()
        except Exception:
            pass
    return [tid for tid, _ in evicted]


def start_idle_sweeper(interval=None):
    """Start the background idle-eviction loop (idempotent)."""
    global _sweeper_started
    if _sweeper_started:
        return
    _sweeper_started = True
    iv = _SWEEP_INTERVAL if interval is None else interval

    def loop():
        while True:
            _time.sleep(iv)
            try:
                gone = sweep_idle()
                if gone:
                    print("DRIVERS: reaped %d idle agent session(s): %s"
                          % (len(gone), ", ".join(gone)))
            except Exception as e:
                print("idle sweep error:", e)

    threading.Thread(target=loop, daemon=True).start()


def shutdown_all():
    """Tree-kill every live session - registered for daemon shutdown so a clean
    stop doesn't orphan worker trees (complements reap_orphans on the next boot).
    Conversations survive: each card resumes by session id on the next steer."""
    with _sessions_guard:
        items = list(_sessions.items())
        _sessions.clear()
    for tid, s in items:
        try:
            s.kill()
        except Exception:
            pass
    return len(items)


# Daemon-internal control keys the AGENT process must not inherit (Paseo's
# RUNTIME_CONTROL_ENV_KEYS split: internal env = the daemon's own, external
# env = sanitized for every spawned process). TLS material paths and the
# daemon's claude-binary override are supervision config, not build env; and
# BASH_ENV could rewrite the env behind our back in every shell the agent runs
# (Paseo strips it in createStringCommandShellEnv for the same reason).
_CONTROL_ENV_KEYS = ("HELMDECK_TLS_CERT", "HELMDECK_TLS_KEY", "HELMDECK_TLS_PORT",
                     "HELMDECK_CLAUDE", "BASH_ENV")


def _card_env(t):
    """Per-card overlay for the agent env (Paseo resolveWorktreeRuntimeEnv):
    where the card lives and its reserved dev port, so build/test scripts can
    bind HELMDECK_DEV_PORT instead of fighting siblings over the project's
    default port. Deliberately NOT exposed: the source checkout path (Paseo's
    PASEO_SOURCE_CHECKOUT_PATH) - that is where the secrets live that the
    worktree was isolated away from."""
    if not t:
        return {}
    out = {}
    if t.get("dev_port"):
        out["HELMDECK_DEV_PORT"] = str(t["dev_port"])
    if t.get("worktree"):
        out["HELMDECK_WORKTREE"] = str(t["worktree"])
    if t.get("branch") and not t.get("machine"):
        out["HELMDECK_BRANCH"] = str(t["branch"])
    return out


def _env(cfg, card=None):
    """The environment the agent's shell inherits (the EXTERNAL env model -
    the daemon's own os.environ stays the internal one).

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
    for k in _CONTROL_ENV_KEYS:
        env.pop(k, None)
    # Bash tool timeouts (Paseo-parity: bound the TOOL, not the turn). Without
    # these a single runaway command - a stuck `adb`, an endless poll - hung the
    # whole turn until the 30-min turn kill or a human hit Stop. Paseo relies on
    # the agent CLI's own per-tool timeout instead: a command that exceeds its
    # bound is killed at the TOOL layer and returns an error to the agent, which
    # then adapts (shorter polls) - no manual Stop needed. A silence/inactivity
    # watchdog would be wrong here: a legitimate long command (waiting on a
    # download) also emits no output while it runs, so you cannot tell hung from
    # busy by silence - only a tool bound distinguishes them. setdefault so the
    # daemon's own env and a driver's `env` in settings.json still win.
    env.setdefault("BASH_DEFAULT_TIMEOUT_MS", "120000")   # 2 min default / command
    env.setdefault("BASH_MAX_TIMEOUT_MS", "300000")       # 5 min ceiling the agent can't exceed
    if card:
        env.update(card)                                  # per-card overlay (_card_env)
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
    "You are working ONE HelmDeck card in an isolated git worktree. "
    "You CAN: edit files, run commands/tests/builds, and commit on THIS branch. "
    "If you start a dev server, bind the port reserved for THIS card in "
    "$HELMDECK_DEV_PORT (when set) - not the project default - so parallel "
    "cards never fight over a port. "
    "You CANNOT (by design): merge to main, access secrets (.env/keys), or deploy - "
    "the owner accepts the card on the board, and accepting runs the repo deploy hook. "
    "Therefore NEVER end with just 'I cannot do X'. When your work is done and "
    "verified, end with a short DELIVERED summary and the sentence: "
    "'Ready for Review - move the card to Review; accepting it deploys.' "
    "If something truly blocks you, name the exact blocker and what the owner "
    "must change (a setting, a secret, a decision).\n\n" + ask.BRIEF
)

# A MACHINE card has no worktree and no branch - its workplace is a real folder
# on the owner's own PC. The card brief above would make such an agent refuse
# ("I'm sandboxed in a worktree, I can't touch your machine"), which is the same
# dead-end the board chat used to hit. This is its counterpart.
_MACHINE_BRIEF = (
    "You are running ONE HelmDeck MACHINE task for the OWNER, on the owner's own "
    "Windows PC, in the working directory you were started in. This is not a git "
    "worktree and there is no branch. "
    "You CAN: run commands and PowerShell, start and control applications, read "
    "and write files, inspect and fix the system - this is the owner's machine and "
    "he asked for this task through his authenticated board. "
    "You SHOULD: prefer the reversible form of an action, say plainly what you "
    "changed, and never touch HelmDeck's own secrets (settings.json, users.json, "
    "helmdeck.db, tokens) or its git history. "
    "Ask for nothing you can find out yourself - look it up on the machine. "
    "NEVER end with just 'I cannot do X': if one route is blocked, try another, "
    "and if you are truly stuck, name the exact blocker and the one thing the "
    "owner must decide or provide. When it is done, end with a short DELIVERED "
    "summary of what actually changed on the machine.\n\n" + ask.BRIEF
)


def _cmd_line(argv):
    """Windows can't spawn a .cmd/.bat directly (claude ships as claude.cmd), so
    we route through cmd.exe. `cmd /c "<a>" "<b>"` is a TRAP: cmd strips the
    outermost quote pair, so a spaced executable path (C:\\Program Files\\...)
    breaks the moment the last arg is also quoted. `cmd /s /c "<whole line>"`
    strips ONLY the wrapping quotes and runs the inner verbatim - the documented-
    correct form. On non-Windows, return the argv list unchanged."""
    if os.name != "nt":
        return argv
    return 'cmd /s /c "%s"' % subprocess.list2cmdline(argv)


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


def _opts_sig(cfg, t):
    """The launch options that, if changed, require a fresh query (Paseo's
    queryRestartNeeded). A steer with a different model/mode/tool-grant can't be
    fed to a process already launched with the old ones."""
    return (cfg.get("perm", t.get("perm", "acceptEdits")),
            cfg.get("model") or t.get("model") or "",
            tuple(cfg.get("allowed_tools") or []))


class _ClaudeSession:
    """One long-lived `claude` stream-json process for a card, reused across
    turns. Faithful port of Paseo's persistent SDK query: turns are messages
    pushed onto stdin, a single pump thread drains stdout, and teardown always
    tree-kills. run_turn() is BOUNDED (kills on timeout) so it can never hold the
    caller's per-card lock forever - the deadlock the old per-turn Popen caused."""

    def __init__(self, cfg, t):
        self.tid = t["id"]
        self.cfg = cfg
        self.worktree = t.get("worktree") or "."
        self.card_env = _card_env(t)     # HELMDECK_DEV_PORT etc., fixed at spawn
        self.brief = _MACHINE_BRIEF if t.get("machine") else _CARD_BRIEF
        self.sig = _opts_sig(cfg, t)
        self.session_id = t.get("session_id")
        self.adopted_source = t.get("adopted_source")
        self.run_dir = t.get("run_dir") or ""
        self.proc = None
        self._drop_results = 0           # stale-result suppression after an interrupt
        self.err_tail = []
        self._alive = False
        self._cur = None                 # current turn's mutable state, or None
        self._turn_lock = threading.Lock()  # one turn at a time on this session
        self.last_used = _time.time()    # for the idle sweeper (Paseo idle TTL)
        self._ctrl = {}                  # request_id -> {"ev":Event,"resp":dict} (control plane)
        self.spawn_time = 0.0            # wall-clock at spawn, for pid-reuse-safe reaping
        # FIRST-CLASS background-task registry (Paseo's ProviderSubagentStore
        # principle): maintained AT EVENT TIME by the pump, persisted on the
        # track - never reconstructed by re-scanning transcripts.
        self._bg_candidates = {}         # tool_use id -> desc (Task/Agent or run_in_background, result pending)
        self._bg_open = {}               # tool_use id -> desc (confirmed running in background)
        self._spawn()

    # -- lifecycle -------------------------------------------------------
    def _spawn(self):
        if self.session_id:
            # Stale-resume degradation: if the session's .jsonl transcript is
            # gone (cleanup, moved profile), `--resume` would hard-fail the whole
            # spawn. Degrade to a FRESH session and leave a visible note in the
            # card feed instead of a dead card.
            try:
                import claude_sessions
                lost = claude_sessions._find_transcript(self.session_id) is None
            except Exception:
                lost = False
            if lost:
                note = ("Session-Transcript %s… nicht mehr auffindbar - starte eine "
                        "frische Session (alter Gesprächskontext ist verloren)."
                        % self.session_id[:8])
                self.session_id = None
                self.adopted_source = None
                if self.run_dir:
                    try:
                        from actionlog import ActionLog
                        ActionLog(self.run_dir).log("note", note)
                    except Exception:
                        pass
        argv = [CLAUDE, "-p",
                "--output-format", "stream-json", "--input-format", "stream-json",
                "--include-partial-messages", "--verbose",
                "--permission-mode", self.cfg.get("perm", "acceptEdits"),
                "--append-system-prompt", self.brief]
        if self.cfg.get("model"):
            argv += ["--model", self.cfg["model"]]
        for pat in self.cfg.get("allowed_tools") or []:
            argv += ["--allowedTools", pat]
        if self.session_id:
            argv += ["--resume", self.session_id]
            # An adopted card still pointing at its SOURCE session must not write
            # into the desktop's live conversation: fork into a fresh session id
            # on the first turn. Afterwards the ids differ and this never fires.
            if self.adopted_source and self.adopted_source == self.session_id:
                argv += ["--fork-session"]
        self.proc = subprocess.Popen(_cmd_line(argv), cwd=self.worktree,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, env=_env(self.cfg, self.card_env),
                                     text=True, encoding="utf-8", errors="replace",
                                     bufsize=1)
        self.spawn_time = _time.time()
        _record_pid(self.proc.pid, self.spawn_time)
        self.err_tail = []
        self._drop_results = 0     # a fresh process can't emit stale frames
        self._alive = True
        threading.Thread(target=self._drain_err, daemon=True).start()
        threading.Thread(target=self._pump, daemon=True).start()

    def alive(self):
        try:
            return self._alive and self.proc is not None and self.proc.poll() is None
        except Exception:
            return False

    def cancel(self, ack_timeout=2.0, grace=8.0):
        """Stop the in-flight turn, Paseo-style: send a SOFT `interrupt` control
        request and await its ACK ~2s (Paseo awaits query.interrupt() the same
        way). Acked -> claude winds the turn down and emits a terminal result;
        the process stays ALIVE and the session resumes on the next steer. No
        ack -> the stream is wedged: hard tree-kill (still resumable via
        --resume). Acked but the result doesn't land within `grace` -> release
        the waiter, KEEP the process, and flag the eventual late result as
        stale so it can't falsely complete the NEXT turn."""
        _cancelled.add(self.tid)   # so run_turn returns the clean '(cancelled)' sentinel
        cur = self._cur
        if not self.alive() or cur is None:
            # nothing running - just make sure any waiter is released, then kill
            if cur and not cur["done"].is_set():
                cur["done"].set()
            self.kill()
            return
        req_id = self._send_control("interrupt")
        if not req_id:
            self.kill()
            return

        def _escort():
            slot = self._ctrl.get(req_id)
            acked = slot["ev"].wait(ack_timeout) if slot else False
            resp = (slot or {}).get("resp") or {}
            self._ctrl.pop(req_id, None)
            if not (acked and resp.get("subtype") == "success"):
                # interrupt not acknowledged - the stream is hung, kill the tree
                if not cur["done"].is_set():
                    cur["done"].set()
                self.kill()
                return
            if not cur["done"].wait(grace):
                # acked but the terminal result is dragging (a tool winding
                # down). Don't kill - the soft path's whole point is a live,
                # resumable process. Release the waiter and drop the turn's
                # late result frame when it finally arrives (stale-result
                # suppression - see _on_event).
                self._drop_results = 1
                if cur.get("result") is not None:
                    # the frame landed in the race window and was consumed
                    # normally - nothing stale is coming, don't eat the next
                    # turn's real result.
                    self._drop_results = 0
                if not cur["done"].is_set():
                    cur["done"].set()
        threading.Thread(target=_escort, daemon=True).start()

    def kill(self):
        self._alive = False
        _tree_kill(self.proc)

    # -- control plane (Paseo: query.interrupt / setModel / setPermissionMode) --
    def _send_control(self, subtype, **fields):
        """Fire a control_request onto the live stdin. Returns the request_id, or
        None if the write failed."""
        req_id = "sd-" + uuid.uuid4().hex[:12]
        self._ctrl[req_id] = {"ev": threading.Event(), "resp": None}
        body = {"type": "control_request", "request_id": req_id,
                "request": dict({"subtype": subtype}, **fields)}
        try:
            self.proc.stdin.write(json.dumps(body) + "\n")
            self.proc.stdin.flush()
            return req_id
        except Exception:
            self._ctrl.pop(req_id, None)
            return None

    def _control(self, subtype, timeout=3.0, **fields):
        """Send a control_request and wait for its control_response. Returns True
        on subtype:success (Paseo's awaitWithTimeout is likewise 3s)."""
        req_id = self._send_control(subtype, **fields)
        if not req_id:
            return False
        slot = self._ctrl.get(req_id)
        ok = slot["ev"].wait(timeout) if slot else False
        resp = (slot or {}).get("resp") or {}
        self._ctrl.pop(req_id, None)
        return bool(ok) and resp.get("subtype") == "success"

    def apply_opts(self, cfg, t):
        """Adopt a steer's model/permission-mode change on the LIVE process via
        the control plane instead of respawning (Paseo's setModel/setPermissionMode).
        A tool-grant change or a failed control op needs a fresh query -> False so
        the caller respawns; True means the live session now matches the new opts."""
        new_sig = _opts_sig(cfg, t)
        if new_sig == self.sig:
            self.cfg = cfg            # non-launch opts (e.g. timeout) may still differ
            return True
        if not self.alive():
            return False
        old_perm, old_model, old_tools = self.sig
        new_perm, new_model, new_tools = new_sig
        if new_tools != old_tools:
            return False              # allowed-tools grant can't change live - restart
        ok = True
        if new_model != old_model:
            ok = ok and self._control("set_model", model=(cfg.get("model") or "default"))
        if ok and new_perm != old_perm:
            ok = ok and self._control("set_permission_mode", mode=new_perm)
        if not ok:
            return False
        self.cfg = cfg
        self.sig = new_sig
        return True

    # -- pump: the single stdout reader (Paseo's query pump) -------------
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
            # stdout closed => process exited. Unblock any turn waiting on it so
            # run_turn returns (with no result) instead of hanging to its timeout.
            self._alive = False
            cur = self._cur
            if cur and not cur["done"].is_set():
                cur["done"].set()

    # -- background-task registry (event-time, Paseo ProviderSubagentStore) ---
    def _scan_bg(self, ev):
        """Fold ONE stream event into the background registry: a Task/Agent or
        run_in_background tool_use becomes a candidate; its tool_result confirms
        it ("Async agent launched") or clears it (a sync result); a
        <task-notification> closes it. On any change the open set is persisted
        onto the TRACK, so the waiting_on/eviction guard and the auto-continue
        watcher read first-class state - no transcript re-scans, and a session
        ROTATION cannot lose a start."""
        m = ev.get("message") or {}
        c = m.get("content")
        changed = False
        if isinstance(c, list):
            for p in c:
                if not isinstance(p, dict):
                    continue
                if p.get("type") == "tool_use":
                    inp = p.get("input") if isinstance(p.get("input"), dict) else {}
                    if inp.get("run_in_background") or p.get("name") in ("Task", "Agent"):
                        self._bg_candidates[p.get("id")] = str(
                            inp.get("description") or inp.get("command")
                            or p.get("name") or "task")[:80]
                elif p.get("type") == "tool_result":
                    uid = p.get("tool_use_id")
                    if uid in self._bg_candidates:
                        txt = p.get("content")
                        if not isinstance(txt, str):
                            txt = " ".join(str(x.get("text", "")) for x in txt
                                           if isinstance(x, dict)) if isinstance(txt, list) else ""
                        desc = self._bg_candidates.pop(uid)
                        if "Async agent launched" in (txt or "") or "run_in_background" in (txt or "") \
                           or "background" in (txt or "")[:200].lower():
                            self._bg_open[uid] = desc
                            changed = True
                elif p.get("type") == "text" and isinstance(p.get("text"), str) \
                        and p["text"].lstrip().startswith("<task-notification>"):
                    hit = _re_bg_done.search(p["text"])
                    if hit and self._bg_open.pop(hit.group(1).strip(), None) is not None:
                        changed = True
        if changed:
            try:
                import sessions
                sessions.record_bg(self.tid, dict(self._bg_open))
            except Exception:
                pass

    def _on_event(self, ev):
        cur = self._cur
        typ = ev.get("type")
        if typ in ("assistant", "user"):
            try:
                self._scan_bg(ev)
            except Exception:
                pass                     # registry is best-effort, never the turn
        if typ == "control_response":
            resp = ev.get("response") or {}
            slot = self._ctrl.get(resp.get("request_id"))
            if slot:
                slot["resp"] = resp
                slot["ev"].set()
            return
        if typ == "system":
            sid = ev.get("session_id")
            if sid:
                self.session_id = sid
                if cur:
                    cur["session_id"] = sid
                    _write(cur["sid_path"], sid)
        elif typ == "result":
            if self._drop_results > 0:
                # terminal frame of an ALREADY-RETURNED interrupted turn (its
                # waiter was released after the interrupt ack). stdout frames
                # are ordered, so this stale frame always precedes the next
                # turn's real result - swallow it instead of letting it falsely
                # complete that turn.
                self._drop_results -= 1
                return
            if cur:
                cur["result"] = ev
                cur["done"].set()
        elif typ == "assistant":
            # a full assistant message landed in the session .jsonl - clear the
            # live partial so the transcript (read from .jsonl) shows it instead.
            if cur:
                cur["parts"].clear()
                _flush_cur(cur)
                # Context meter source (Paseo: read the LAST message's usage).
                # Each assistant message carries the usage of ITS OWN API call,
                # whose input side (input+cache) = the actual context size at
                # that moment. The terminal result event instead SUMS usage over
                # every call of the turn - a 40-call turn reads as millions of
                # "context" tokens (the 6634k/100% meter) and falsely trips the
                # auto-compact threshold on every long turn. Keep the last one.
                u = (ev.get("message") or {}).get("usage")
                if isinstance(u, dict) and u:
                    cur["ctx_usage"] = u
        elif typ == "stream_event":
            e = ev.get("event") or {}
            if e.get("type") == "content_block_delta" and cur:
                dl = e.get("delta") or {}
                if dl.get("type") == "text_delta":
                    cur["parts"].append(dl.get("text", ""))
                    now = _time.time()
                    if now - cur["last_flush"] > 0.15:
                        cur["last_flush"] = now
                        _flush_cur(cur)

    # -- one turn: push a message, wait bounded for its result ----------
    def run_turn(self, prompt, run_dir):
        with self._turn_lock:
            self.last_used = _time.time()      # mark active so the idle sweeper skips us
            try:
                return self._run_turn_locked(prompt, run_dir)
            finally:
                self.last_used = _time.time()

    def _run_turn_locked(self, prompt, run_dir):
        _cancelled.discard(self.tid)
        if not self.alive():
            # session died (crash/cancel/opts-restart/idle-evict) - respawn & --resume.
            _tree_kill(self.proc)
            self._spawn()
        live_path = os.path.join(run_dir, "live_partial.txt")
        sid_path = os.path.join(run_dir, "live_session.txt")
        _rm(live_path); _rm(sid_path)
        cur = {"parts": [], "result": None, "session_id": self.session_id,
               "done": threading.Event(), "live_path": live_path,
               "sid_path": sid_path, "last_flush": 0.0}
        self._cur = cur
        msg = json.dumps({"type": "user",
                          "message": {"role": "user", "content": prompt}})
        try:
            self.proc.stdin.write(msg + "\n")
            self.proc.stdin.flush()
        except Exception as e:
            self._cur = None
            self.kill()
            raise RuntimeError("claude session write failed: %s" % e)
        timeout = self.cfg.get("timeout", 1800 if self.cfg.get("allowed_tools") else 600)
        finished = cur["done"].wait(timeout)
        self._cur = None
        _rm(live_path); _rm(sid_path)

        if self.tid in _cancelled:            # Stop was pressed - clean, not error
            _cancelled.discard(self.tid)
            # `canceled` is the structured signal (Paseo turn_canceled): the turn
            # ended by the owner's hand, not by an error - the lifecycle event
            # stream renders it as its own typed item, never a failure.
            return self.session_id, "(turn cancelled by you)", \
                {"usage": {}, "cost_usd": None, "models": [], "canceled": True}
        if not finished:
            # hung turn: tree-kill the session; the next steer resumes it.
            self.kill()
            raise RuntimeError(
                "claude turn exceeded %ss - session killed; steer again to resume. %s"
                % (timeout, "".join(self.err_tail).strip()[-200:]))
        d = cur["result"]
        if not d:
            # pump ended with no result: the process died mid-turn.
            self.kill()
            raise RuntimeError("claude stream ended with no result: "
                               + "".join(self.err_tail).strip()[:300])
        meta = {"usage": d.get("usage") or {}, "cost_usd": d.get("total_cost_usd"),
                "models": list((d.get("modelUsage") or {}).keys()),
                # structured failure signal read straight off the result event
                # (Paseo branches on subtype instead of grepping the prose reply).
                "subtype": d.get("subtype"), "is_error": bool(d.get("is_error")),
                "error": _result_error(d),
                # the LAST assistant call's usage = the real context size (the
                # result event's usage sums every call of the turn - see _on_event)
                "ctx_usage": cur.get("ctx_usage") or {}}
        return self.session_id or d.get("session_id"), d.get("result", ""), meta


def _flush_cur(cur):
    try:
        with open(cur["live_path"], "w", encoding="utf-8") as f:
            f.write("".join(cur["parts"]))
    except OSError:
        pass


def _result_error(d):
    """A structured error string off a result event, or "" for a clean turn. The
    CLI carries either an `errors` array or an error `result` body on failure
    subtypes; success turns have neither."""
    if not d.get("is_error") and d.get("subtype") in (None, "success"):
        return ""
    errs = d.get("errors")
    if isinstance(errs, list) and errs:
        return "; ".join(str(e) for e in errs)[:500]
    return (d.get("result") or d.get("subtype") or "error")[:500]


def _get_session(cfg, t):
    """Get the card's live session, or (re)spawn one. A model/permission-mode
    change is applied LIVE via the control plane (Paseo's setModel/setPermissionMode);
    only a tool-grant change, a failed control op, or a dead process forces a fresh
    query, resuming the same conversation via the track's session_id."""
    tid = t["id"]
    sig = _opts_sig(cfg, t)
    with _sessions_guard:
        s = _sessions.get(tid)
        if s is not None:
            if not s.alive():
                s = None
            elif s.sig != sig and not s.apply_opts(cfg, t):
                try:
                    s.kill()
                except Exception:
                    pass
                s = None
        if s is None:
            s = _ClaudeSession(cfg, t)
            _sessions[tid] = s
        return s


def _claude(cfg, t, prompt):
    # A card holds ONE long-lived stream-json process across turns (Paseo's
    # persistent query). The session_id arrives in the first `system/init` event
    # and text deltas stream to run_dir/live_partial.txt; the `result` event
    # carries the SAME economics fields as before (result/total_cost_usd/usage/
    # modelUsage) so the gate and metrics are unchanged.
    s = _get_session(cfg, t)
    return s.run_turn(prompt, t.get("run_dir") or ".")


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
                       env=_env(cfg, _card_env(t)),
                       encoding="utf-8", errors="replace",
                       timeout=cfg.get("timeout", 1800))
    out = r.stdout.strip() or r.stderr.strip()
    return t.get("session_id"), out, {"usage": {}, "cost_usd": None, "models": []}
