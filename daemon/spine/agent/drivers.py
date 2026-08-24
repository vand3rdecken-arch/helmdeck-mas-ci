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
import hashlib, json, os, re as _re, shutil, subprocess, threading, time as _time, uuid
import urllib.request
from daemon.spine.agent.spawnenv import _card_env, _env
from daemon.spine.agent.proctable import (_pid_table, _descendants, _tree_kill, _read_pids, _write_pids, _record_pid, _forget_pid, _proc_start_epoch, _is_agent_pid, _is_ours, reap_orphans)
from daemon.spine.agent.agentcli import (CLAUDE, _real_claude_exe, _cmd_line, argv_form_safe, _opts_sig, _user_mcp_servers, _resolve_cmd, _mcp_config_arg)
from daemon.spine.agent import timeline_store
from daemon.spine.agent.claude_transcript_fmt import (
    _tool_label, _tool_detail, _tool_summary, _result_text, _clean_text)

_re_bg_done = _re.compile(r"<tool-use-id>(.*?)</tool-use-id>", _re.S)

# Caps mirroring claude_sessions.py's MAX_TEXT/MAX_THINK/MAX_RESULT - the same
# per-step content ceilings, applied here because _fold_timeline writes the
# SAME TStep shape from the live stream instead of a re-parsed transcript.
_TL_MAX_TEXT = 200_000
_TL_MAX_THINK = 60_000
_TL_MAX_RESULT = 8_000


def _text_of(content):
    """Flatten a stream part's `content` (a str, or a list of {text} blocks) to
    plain text - background scanning reads tool_result / task-notification text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(x.get("text", "")) for x in content if isinstance(x, dict))
    return ""


from daemon.spine.ops import ask  # the typed question channel taught to every worker (Phase 2.4)
from daemon.spine.registry import harness  # briefs + settings layers as data (harness/), never raises

# CLAUDE comes from agentcli.py now (the single source - see its module
# docstring); still a real name in THIS module's namespace via the import
# above, so `drivers.CLAUDE = ...` monkeypatching in tests is unchanged.

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



# Every NATIVE driver module beyond claude (this module) - each owns its
# OWN {tid: session} registry + guard, same reasoning as claude_sessions.py
# being its own module: one driver, one owner of its session state. Lazy-
# imported so a claude-only board never loads any of them. Add a new native
# driver here (one line) and cancel/has_session/turn_active/drop_session all
# pick it up - a caller only ever has a tid, not the track's driver type, so
# the alternative is pushing a driver-type lookup onto every one of the
# 12+ call sites instead of this one list.
_NATIVE_DRIVER_MODULES = ("omp_driver", "codex_driver", "opencode_driver", "pi_driver")


def _native_registries():
    """[(sessions_dict, guard), ...] for every native driver module that
    actually imports cleanly (a module with a missing/broken optional
    dependency degrades to "no sessions there", never breaks the claude
    path these functions all serve first)."""
    out = []
    for name in _NATIVE_DRIVER_MODULES:
        try:
            mod = __import__("daemon.spine.agent." + name, fromlist=[name])
            out.append((mod._sessions, mod._sessions_guard))
        except Exception:
            continue
    return out


def cancel(tid):
    """Stop the track's in-flight turn (composer Stop). Unblocks the waiting turn
    with a clean '(cancelled)' and tree-kills the session; the next steer respawns
    and `--resume`s the session id, so no conversation is lost. Idempotent.
    Checks EVERY registry (claude's own, then each native driver's) - see
    _native_registries' docstring for why the lookup lives here once."""
    _cancelled.add(tid)
    with _sessions_guard:
        s = _sessions.get(tid)
    if s:
        s.cancel()
        return True
    for reg, guard in _native_registries():
        with guard:
            s = reg.get(tid)
        if s:
            s.cancel()
            return True
    return False


def has_session(tid):
    """True while this daemon holds a live worker session for the track. A track
    flagged status=running WITHOUT one is a zombie - its turn died with a prior
    daemon process (see sessions.sweep_zombies)."""
    with _sessions_guard:
        if tid in _sessions:
            return True
    for reg, guard in _native_registries():
        with guard:
            if tid in reg:
                return True
    return False


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
        for reg, guard in _native_registries():
            with guard:
                s = reg.get(tid)
            if s is not None:
                break
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
_BURN_REPEATS = 5              # identical consecutive tool calls that look like a loop
_sweeper_started = False


def _idle_ttl():
    try:
        from daemon.spine.storage import events
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
        from daemon.cells.engineer import sessions
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


def drop_session(tid):
    """Tear down a card's IDLE worker so its next turn respawns fresh. Used when a
    launch-time property that can't be hot-swapped changed between turns - most
    concretely a DRIVER swap (claude <-> claude-desktop), whose tool grant is
    baked into the argv at spawn (build_argv) and which apply_opts refuses to
    change on a live process. Without this, the old-grant process lingers idle
    until the next turn's _get_session notices the signature drift and kills it -
    correct, but it means a driver flip has no visible effect until you send a
    message. Dropping it here makes the flip take hold immediately and eagerly.

    Same safety as sweep_idle: only a session with NO turn in flight is reaped
    (non-blocking lock + _cur check), and the conversation survives on disk keyed
    by session id, so the next steer resumes it. Returns True if a session was
    dropped. Idempotent - a no-op when the card has no live session.

    Checks EVERY registry (see cancel's docstring) - a driver swap FROM one
    native engine TO another (or to/from claude) must drop whichever one is
    actually live, not just claude's."""
    for registry, guard in ((_sessions, _sessions_guard), *_native_registries()):
        with guard:
            s = registry.get(tid)
            if s is None:
                continue
            if not s._turn_lock.acquire(blocking=False):
                return False        # a turn holds it - leave it to _get_session
            try:
                if s._cur is not None:
                    return False    # turn in flight - never yank it mid-run
                del registry[tid]
            finally:
                s._turn_lock.release()
        try:
            s.kill()
        except Exception:
            pass
        return True
    return False


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


def run(cfg, t, prompt):
    kind = cfg.get("type", "claude")
    if kind == "claude":
        return _claude(cfg, t, prompt)
    if kind == "http":
        return _http(cfg, t, prompt)
    if kind == "cmd":
        return _cmd(cfg, t, prompt)
    if kind == "omp":
        # Native OMP driver (docs/multi-engine-build-plan.md Card 8) - its
        # own persistent-session module, same shape as _ClaudeSession but a
        # different wire protocol (JSONL-RPC, not stream-json). LIVE-VERIFIED
        # against a real account. Lazy import: no reason to load for a
        # claude-only board.
        from daemon.spine.agent import omp_driver
        return omp_driver.run(cfg, t, prompt)
    if kind == "codex":
        # Native Codex driver (build plan Card 6) - JSON-RPC over stdio.
        # NOT LIVE-VERIFIED (owner decree 2026-08-24, "test accounts later")
        # - protocol-correct-per-Paseo's-source, unproven against the real
        # binary. See codex_driver.py's own module docstring.
        from daemon.spine.agent import codex_driver
        return codex_driver.run(cfg, t, prompt)
    if kind == "opencode":
        # Native OpenCode driver, DEDICATED-server mode (build plan Card 7,
        # analysis §6.6.2) - one private `opencode serve` per card, never
        # Paseo's shared-by-default pool. NOT LIVE-VERIFIED - see
        # opencode_driver.py's own module docstring, including which REST
        # paths are inferred rather than source-confirmed.
        from daemon.spine.agent import opencode_driver
        return opencode_driver.run(cfg, t, prompt)
    if kind == "pi":
        # Native Pi driver - the deferred half of Card 8 (omp shipped and
        # is live-verified; pi is not). See pi_driver.py's own module
        # docstring for exactly what's borrowed from omp's proven structure
        # vs. genuinely unverified even by relation.
        from daemon.spine.agent import pi_driver
        return pi_driver.run(cfg, t, prompt)
    raise RuntimeError("unknown driver type: " + kind)

# THE BRIEFS ARE DATA NOW - harness/agents/*.md, loaded by daemon/harness.py.
#
# Every card agent gets the same standing orientation: what it CAN do, what the
# BOARD does, and how to hand off - so hitting a boundary produces a pointer to
# the workflow instead of a dead-end "I cannot do that". A MACHINE card gets its
# counterpart: it has no worktree and no branch (its workplace is a real folder
# on the owner's PC), and the card brief would make such an agent refuse.
#
# Both texts used to be string constants here. They are policy, not harness -
# the owner may reword them - so they moved to harness/agents/{card,machine}-worker.md.
# harness.py keeps the identical text as its built-in fallback and never raises,
# so a mangled file costs the wording, never the spawn. The <helmdeck-ask>
# protocol is still owned by ask.py and spliced in by harness.py: it is coupled
# to ask.parse()'s regex, so prompt and parser must ship together.
CARD_AGENT = "card-worker"
MACHINE_AGENT = "machine-worker"


def _agent_for(t):
    return MACHINE_AGENT if (t or {}).get("machine") else CARD_AGENT




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




def build_argv(agent, cfg, brief, session_id=None, adopted_source=None, exe=None):
    """THE assembly point for a card/machine `claude` argv. ONE owner.

    This is a function rather than inline code in _spawn() because /harness's
    spawn-preview must show what ACTUALLY runs. A preview that re-listed these
    flags would be a heuristic reconstruction of the spawn - it would drift the
    first time a flag moved, and would then confidently lie about a command it
    no longer describes. CLAUDE.md forbids exactly that (NO MONKEY PATCHES:
    load-bearing state is derived, mutated at exactly ONE owner). So the preview
    calls this, and the preview is correct by construction.

    THE SETTINGS LAYER (harness/agents/<agent>.md -> setting_sources + settings).
    Without it a card loads the OPERATOR'S PERSONAL ~/.claude/settings.json,
    because cwd is his machine: an `rtk hook claude` PreToolUse hook on every
    Bash call (296 observed failures inside card transcripts), a pinned
    `model: claude-fable-5[1m]` silently overriding the card's own model, and
    ~150 personal skillOverrides. A sandboxed worker can neither use nor fix any
    of it. `--setting-sources project` drops that layer while KEEPING the repo's
    own .claude/settings.json build-loop hooks, which the card does want.
    Measured, not assumed - daemon/probe_harness_settings.py against the real
    CLI 2.1.207 (--help text is not proof). Empty list when harness/ is absent,
    which is exactly the old inherit-everything behaviour.
    """
    argv = [exe or CLAUDE, "-p",
            "--output-format", "stream-json", "--input-format", "stream-json",
            "--include-partial-messages", "--verbose",
            "--permission-mode", cfg.get("perm", "acceptEdits"),
            "--append-system-prompt", brief]
    argv += harness.cli_args(agent)
    if cfg.get("model"):
        argv += ["--model", cfg["model"]]
    for pat in cfg.get("allowed_tools") or []:
        argv += ["--allowedTools", pat]
    # A grant pre-authorises tools; this REGISTERS the server that owns them,
    # because --setting-sources project drops the user layer it normally lives
    # in (see _mcp_config_arg). Without it windows-mcp was a ghost the card
    # could never reach.
    argv += _mcp_config_arg(cfg)
    if session_id:
        argv += ["--resume", session_id]
        # An adopted card still pointing at its SOURCE session must not write
        # into the desktop's live conversation: fork into a fresh session id
        # on the first turn. Afterwards the ids differ and this never fires.
        if adopted_source and adopted_source == session_id:
            argv += ["--fork-session"]
    return argv


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
        self.agent = _agent_for(t)       # which harness/agents/*.md speaks to it
        self.brief = harness.brief(self.agent)
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
        # resume-attachment evidence (Paseo: session identity is manager state
        # verified from the runtime's own events, never assumed):
        self._spawn_resumed = None       # the session id --resume asked for, or None
        self._resume_echo = False        # init event echoed that id -> attach certain
        self._first_turn_after_spawn = True
        self._spawn()

    # -- lifecycle -------------------------------------------------------
    def _spawn(self):
        # finishAll (Paseo sidechain-tracker): a fresh SUBPROCESS means every
        # background task the prior one launched is a dead child (tree-killed on
        # timeout/restart/crash) - reconcile them to 'canceled' so a dead build
        # never lingers as a phantom the card waits on. Skipped on the very
        # first spawn of a brand-new card (no bg_tasks yet -> a cheap no-op).
        # In-memory candidates/open reset too: this process starts them clean.
        self._bg_candidates = {}
        self._bg_open = {}
        try:
            from daemon.cells.engineer import sessions
            sessions.reconcile_bg(self.tid)
        except Exception:
            pass
        if self.session_id:
            # Stale-resume degradation: if the session's .jsonl transcript is
            # gone (cleanup, moved profile), `--resume` would hard-fail the whole
            # spawn. Degrade to a FRESH session and leave a visible note in the
            # card feed instead of a dead card.
            try:
                from daemon.spine.agent import claude_sessions
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
                        from daemon.spine.ops.actionlog import ActionLog
                        ActionLog(self.run_dir).log("note", note)
                    except Exception:
                        pass
        # Re-read the brief HERE, not once in __init__: a respawn (restart after a
        # timeout, an options change) is the natural moment to pick up an edited
        # harness/agents/*.md, and it costs one stat() when nothing changed.
        self.brief = harness.brief(self.agent)
        # ONE builder, shared with /harness's spawn preview - see build_argv.
        argv = build_argv(self.agent, self.cfg, self.brief,
                          self.session_id, self.adopted_source)
        # SPAWN FORENSICS: audit whether this worker resumes or starts fresh.
        # A card once answered with a fresh mind despite a valid session_id and
        # a CLI-verified resumable transcript ("Voellig falscher Kontext") - and
        # nothing recorded what the spawn actually did. Now every spawn leaves
        # the truth in the card feed, so that class is diagnosable in seconds.
        if self.run_dir:
            try:
                from daemon.spine.ops.actionlog import ActionLog
                ActionLog(self.run_dir).log("note", "SESSION spawn: %s%s" % (
                    ("resume " + self.session_id[:8]) if self.session_id else "FRESH (kein Kontext)",
                    " +fork" if ("--fork-session" in argv) else ""))
            except Exception:
                pass
        self.proc = subprocess.Popen(_cmd_line(argv), cwd=self.worktree,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, env=_env(self.cfg, self.card_env),
                                     text=True, encoding="utf-8", errors="replace",
                                     bufsize=1)
        self.spawn_time = _time.time()
        self._spawn_resumed = self.session_id
        self._resume_echo = False
        self._first_turn_after_spawn = True
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
        if not isinstance(c, list):
            return
        from daemon.cells.engineer import sessions
        for p in c:
            if not isinstance(p, dict):
                continue
            if p.get("type") == "tool_use":
                inp = p.get("input") if isinstance(p.get("input"), dict) else {}
                if inp.get("run_in_background") or p.get("name") in ("Task", "Agent"):
                    title = str(inp.get("description") or p.get("name") or "task")[:80]
                    detail = str(inp.get("command") or inp.get("prompt")
                                 or inp.get("description") or "")[:600]
                    self._bg_candidates[p.get("id")] = (title, detail)
            elif p.get("type") == "tool_result":
                uid = p.get("tool_use_id")
                if uid in self._bg_candidates:
                    txt = _text_of(p.get("content"))
                    title, detail = self._bg_candidates.pop(uid)
                    if "Async agent launched" in txt or "run_in_background" in txt \
                       or "background" in txt[:200].lower():
                        self._bg_open[uid] = title
                        try:
                            sessions.bg_upsert(self.tid, uid, title=title,
                                               detail=detail, status="running")
                        except Exception:
                            pass
            elif p.get("type") == "text" and isinstance(p.get("text"), str) \
                    and p["text"].lstrip().startswith("<task-notification>"):
                hit = _re_bg_done.search(p["text"])
                if hit:
                    uid = hit.group(1).strip()
                    if self._bg_open.pop(uid, None) is not None:
                        try:
                            sessions.bg_upsert(self.tid, uid, status="completed",
                                               result=_text_of(p["text"])[:400])
                        except Exception:
                            pass

    # -- event-time card feed (Card 2, DUAL-WRITE STAGE - see timeline_store.py) -
    def _fold_timeline(self, ev):
        """Fold ONE stream event into the card's event-time feed store, in the
        SAME TStep shape claude_sessions.read_transcript already produces from
        a re-parsed .jsonl - but derived here from the LIVE stream, at the
        moment each block completes. DUAL-WRITE ONLY: nothing reads this store
        in production yet (docs/multi-engine-build-plan.md Card 2). Best-
        effort, same discipline as _scan_bg - a feed write must never disturb
        a turn.

        `ts`/`ta` are stamped at FOLD time (wall-clock), not read back off a
        persisted-file timestamp the way read_transcript does - the more
        literal reading of "derived from the runtime's own signal, folded in
        AT EVENT TIME" (CLAUDE.md's law), and it is what a live feed actually
        wants: the moment the daemon SAW the block, not whenever Claude Code
        later flushed it to disk. An UPDATE patch (a tool's result arriving)
        deliberately does not restamp ts/ta - a step keeps the time it was
        first seen, matching read_transcript's own per-part timestamping.

        Deliberately narrower than read_transcript for now (documented scope
        cut, not a silent gap): plain role=user text is folded as a bare text
        step without read_transcript's envelope re-attribution (command-label
        rewriting, harness-tag notes, notification labels, compaction dedup).
        tools/compare_timeline.py knows about this and reports those as
        accepted differences, not failures.

        MEASURED LIMIT (not a bug to fix - there is no live signal that carries
        the corrected number): a usage step's tokOut can read LOWER than the
        SAME message's output_tokens in the persisted .jsonl. Proven live
        2026-08-24: a message split across two stream events (msg id shared
        across a 'thinking' and a 'tool_use' frame) reported usage.output_
        tokens=2 on BOTH live frames while the settled file later held 152 for
        that exact message id - the wire delivers an early/interim count, only
        the file gets corrected. tokIn/cacheRead/cacheWrite (and therefore ctx,
        which is input+cache only) are unaffected - proven identical live vs.
        file on the same turns - and ctx is the ONLY usage field econ.py's
        context meter actually reads (econ._record_econ never touches
        output_tokens). tools/compare_timeline.py excludes tokOut from its
        usage comparison for exactly this reason."""
        m = ev.get("message") or {}
        role = m.get("role") or ev.get("type")
        c = m.get("content")
        typ = ev.get("type")
        ts, ta = _time.strftime("%H:%M:%S", _time.localtime()), _time.time()
        if typ == "assistant" and isinstance(c, list):
            for p in c:
                if not isinstance(p, dict):
                    continue
                pt = p.get("type")
                if pt == "text":
                    text = _clean_text((p.get("text") or "").strip())
                    if text:
                        timeline_store.append(self.run_dir, "s:" + uuid.uuid4().hex,
                            {"role": role, "kind": "text", "text": text[:_TL_MAX_TEXT],
                             "ts": ts, "ta": ta})
                elif pt == "thinking":
                    think = (p.get("thinking") or "").strip()
                    if think:
                        timeline_store.append(self.run_dir, "s:" + uuid.uuid4().hex,
                            {"role": role, "kind": "thinking", "text": think[:_TL_MAX_THINK],
                             "ts": ts, "ta": ta})
                elif pt == "tool_use":
                    name = p.get("name") or "tool"
                    inp = p.get("input") if isinstance(p.get("input"), dict) else {}
                    uid = p.get("id")
                    if name == "TodoWrite":
                        todos = [{"content": str(td.get("content", ""))[:220],
                                  "status": str(td.get("status", ""))}
                                 for td in (inp.get("todos") or []) if isinstance(td, dict)]
                        if todos and uid:
                            timeline_store.append(self.run_dir, "todos:" + uid,
                                {"kind": "todos", "todos": todos, "ts": ts, "ta": ta})
                        continue
                    if name == "ExitPlanMode":
                        if uid:
                            timeline_store.append(self.run_dir, "plan:" + uid,
                                {"kind": "plan", "text": str(inp.get("plan", ""))[:_TL_MAX_TEXT],
                                 "ts": ts, "ta": ta})
                        continue
                    if not uid:
                        continue
                    lbl, sub = _tool_label(name, inp)
                    step = {"role": role, "kind": "tool", "tool": name, "label": lbl,
                            "text": sub or _tool_summary(inp), "result": "",
                            "ok": True, "status": "running", "error": None,
                            "running": True, "ts": ts, "ta": ta}
                    detail = _tool_detail(name, inp)
                    if detail:
                        step["detail"] = detail
                    timeline_store.append(self.run_dir, "tool:" + uid, step)
            u = m.get("usage")
            if isinstance(u, dict):
                inp_t = int(u.get("input_tokens") or 0)
                out_t = int(u.get("output_tokens") or 0)
                cr = int(u.get("cache_read_input_tokens") or 0)
                cc = int(u.get("cache_creation_input_tokens") or 0)
                if (inp_t + cr + cc) or out_t:
                    timeline_store.append(self.run_dir, "s:" + uuid.uuid4().hex,
                        {"kind": "usage", "tokIn": inp_t, "tokOut": out_t,
                         "cacheRead": cr, "cacheWrite": cc, "ctx": inp_t + cr + cc,
                         "ts": ts, "ta": ta})
        elif typ == "user" and isinstance(c, list):
            for p in c:
                if not isinstance(p, dict):
                    continue
                if p.get("type") == "tool_result":
                    uid = p.get("tool_use_id")
                    if not uid:
                        continue
                    text = _result_text(p)
                    interrupted = text.lstrip().startswith("[Request interrupted by user")
                    if interrupted:
                        status, err, ok = "canceled", None, True
                    elif p.get("is_error"):
                        status, err, ok = "failed", (text or "error")[:500], False
                    else:
                        status, err, ok = "completed", None, True
                    timeline_store.append(self.run_dir, "tool:" + uid,
                        {"result": text[:_TL_MAX_RESULT], "ok": ok, "status": status,
                         "error": err, "running": False})
        # NOTE: role=user PLAIN TEXT (the human's own steer) never arrives here -
        # measured, not assumed: Claude Code's `type:"user"` output-stream frames
        # are only tool_result echoes, never a mirror of what we submitted. That
        # is folded directly at submission time in _run_turn_locked instead (see
        # the comment there) - this method only ever sees list-content user
        # frames (tool_result), never string content.

    def _burn_watch(self, ev, cur):
        """Loop detector (the token-burn signal). A worker stuck in a loop keeps
        STREAMING - so the inactivity watchdog never fires - and burns tokens
        until Stop. Only the driver sees the frames, so it FOLDS the signal here
        (never judges): count identical consecutive tool_use calls (name + input
        hash); at the threshold, and again at each doubling (5, 10, 20 - not
        every frame), hand it to sessions.flag_burn, which persists it and lets
        the PM decide whether it's a legit retry or a real loop. Best-effort:
        any error here must never disturb the turn."""
        if ev.get("type") != "assistant":
            return
        try:
            for p in ((ev.get("message") or {}).get("content") or []):
                if not isinstance(p, dict) or p.get("type") != "tool_use":
                    continue
                blob = json.dumps(p.get("input"), sort_keys=True, default=str)
                sig = "%s:%s" % (p.get("name"), hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12])
                if sig == cur.get("burn_sig"):
                    cur["burn_n"] = cur.get("burn_n", 1) + 1
                else:
                    cur["burn_sig"], cur["burn_n"], cur["burn_fired"] = sig, 1, 0
                n = cur["burn_n"]
                level = _BURN_REPEATS if not cur.get("burn_fired") else cur["burn_fired"] * 2
                if n >= level:
                    cur["burn_fired"] = level
                    try:
                        from daemon.cells.engineer import sessions
                        sessions.flag_burn(self.tid, {
                            "n": n, "name": p.get("name"), "sig": sig, "sample": blob[:200]})
                    except Exception:
                        pass
        except Exception:
            pass

    def _on_event(self, ev):
        cur = self._cur
        if cur is not None:
            # Liveness heartbeat for the inactivity watchdog: ANY frame from the
            # CLI (a token, a tool_use, a tool_result, a control response) means
            # the turn is making progress. run_turn bounds SILENCE, not wall-
            # clock, so a long-but-productive turn (a big machine card: many
            # tool calls, gradle builds) is never killed mid-run - only a truly
            # wedged process (no frame for the whole idle window) is.
            cur["last_event"] = _time.time()
            self._burn_watch(ev, cur)
        typ = ev.get("type")
        if typ in ("assistant", "user"):
            try:
                self._scan_bg(ev)
            except Exception:
                pass                     # registry is best-effort, never the turn
            try:
                self._fold_timeline(ev)
            except Exception:
                pass                     # dual-write only - never the turn (Card 2)
        if typ == "system" and ev.get("subtype") == "task_notification":
            # MEASURED 2026-08-24 (card 20260824-140559 + a probe run): a
            # background task finishing BETWEEN turns reaches the stream as
            # this system event - `{tool_use_id, status, summary}` - never as
            # a user message (the "<task-notification>" user record exists
            # only in the transcript, which the pump does not read). The old
            # code routed only assistant/user frames to _scan_bg, so idle-time
            # completions were invisible: the registry stayed "running", the
            # auto-continue sweep never saw "clear", and the card sat parked
            # until the 6h give-up. Fold the completion here, at event time.
            uid = ev.get("tool_use_id") or ""
            if uid:
                self._bg_open.pop(uid, None)
                st = ev.get("status") or "completed"
                if st not in ("completed", "failed", "canceled"):
                    st = "completed"
                try:
                    from daemon.cells.engineer import sessions
                    sessions.bg_upsert(self.tid, uid, status=st,
                                       result=str(ev.get("summary") or "")[:400])
                except Exception:
                    pass                 # registry is best-effort, never the turn
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
                # resume-attachment evidence: a successful --resume ECHOES the
                # asked-for id in the init event (verified against the real
                # CLI). A different id here does NOT prove detachment (forks
                # and rotate-with-context exist) - the echo only ever CONFIRMS.
                if (ev.get("subtype") == "init" and self._spawn_resumed
                        and sid == self._spawn_resumed):
                    self._resume_echo = True
                self.session_id = sid
                if cur:
                    cur["session_id"] = sid
                    _write(cur["sid_path"], sid)
        elif typ == "result":
            # NULL-result guard: resuming a session whose previous turn was
            # HARD-KILLED (tree-kill on timeout/restart) makes the CLI emit the
            # dead turn's leftover result almost immediately - empty text, no
            # usage, no error. Taking that as THIS turn's result ended the turn
            # after ~6s with an empty reply while the real work ran on OWNERLESS
            # until the idle sweeper reaped it ("Broke up in the middle",
            # 2026-08-10 18:35). Evidence, not timing: a REAL model turn always
            # carries usage (input_tokens > 0); a frame with zero usage, zero
            # text and no error carries nothing - drop it and keep waiting.
            u = ev.get("usage") or {}
            if (self._first_turn_after_spawn and self._spawn_resumed
                    and not ev.get("is_error")
                    and not str(ev.get("result") or "").strip()
                    and not any(v for v in u.values() if isinstance(v, (int, float)))):
                if cur is not None:
                    cur["null_results"] = cur.get("null_results", 0) + 1
                return
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
                    # the FIRST call's usage is the resume-continuity witness: a
                    # real continuation carries >= the prior conversation's
                    # context; a silent fresh start carries only the brief.
                    cur.setdefault("ctx_first", u)
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
               "sid_path": sid_path, "last_flush": 0.0, "last_event": _time.time()}
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
        # Card 2 dual-write: the human's OWN steer text never arrives back on
        # the OUTPUT stream (measured - `_on_event`'s `type:"user"` frames are
        # only tool_result echoes; Claude Code does not mirror what WE just
        # wrote to stdin). read_transcript instead reads it off the PERSISTED
        # file afterward. We already know it with certainty right here - it is
        # what we just sent - so fold it now, at the moment of the real event
        # (submission), not by waiting for something that never arrives.
        #
        # HARNESS-INJECTED prompts (ask-repair, the background-continue nudge)
        # are ALSO submitted right here, so - unlike the command-envelope/
        # notification cases (those originate inside Claude Code's own
        # runtime, never as a `prompt` this driver sends, so they stay a
        # permanent OLD-reader-only case) - this one IS reachable and is
        # re-attributed exactly like read_transcript does (ask.harness_tag +
        # claude_sessions._HARNESS_NOTE), not left as a stray text bubble.
        # Measured live 2026-08-24: an un-repaired ask-repair turn showed up
        # as raw "[[helmdeck:ask-repair]]..." protocol text before this fix.
        try:
            from daemon.spine.agent import claude_sessions
            tag = ask.harness_tag(prompt)
            tsv, tav = _time.strftime("%H:%M:%S", _time.localtime()), _time.time()
            if tag:
                timeline_store.append(run_dir, "s:" + uuid.uuid4().hex,
                    {"kind": "system",
                     "text": claude_sessions._HARNESS_NOTE.get(tag, "⚙ Harness-Hinweis"),
                     "ts": tsv, "ta": tav})
            else:
                text = _clean_text((prompt or "").strip())
                if text:
                    timeline_store.append(run_dir, "s:" + uuid.uuid4().hex,
                        {"role": "user", "kind": "text", "text": text[:_TL_MAX_TEXT],
                         "ts": tsv, "ta": tav})
        except Exception:
            pass
        # INACTIVITY watchdog, not a wall-clock cap (Paseo bounds the TOOL, not
        # the turn). A fixed 1800s wall-clock killed long-but-PRODUCTIVE turns
        # mid-run ("killed during run" on a machine card doing gradle builds +
        # many tool calls). A single tool cannot run longer than the tool cap
        # (BASH_MAX_TIMEOUT_MS, 5 min - see _env), so once no frame at all has
        # arrived for `idle` seconds the process is genuinely wedged, not busy.
        # `idle` sits well above the tool cap; `hard` is an OPTIONAL absolute
        # ceiling (0/None = none) for a degenerate turn that dribbles output
        # forever. Poll in slices so a cancel is noticed promptly.
        idle = self.cfg.get("idle_timeout", 900)     # 15 min of TOTAL silence = hung
        hard = self.cfg.get("timeout")               # optional absolute cap; default none
        # Poll finer than the idle window so silence is noticed promptly, but
        # never hot-spin: a few seconds in production, sub-second when a test
        # dials idle right down. The poll serves ONLY the idle/hard checks:
        # completion and cancel both release via cur["done"] (the result frame,
        # the cancel escort's ack/grace branches, or the pump's exit path - all
        # bounded). There is deliberately NO `tid in _cancelled` early-break
        # here: releasing the waiter on that flag BEFORE the interrupted turn's
        # terminal frame landed, without arming _drop_results, let the next
        # turn consume the OLD turn's result as its own (stale-result race);
        # only the escort knows whether suppression must be armed, so only the
        # escort may release a cancelled waiter early.
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
            if hard and now - start > hard:
                why = "exceeded hard cap %ss" % hard
                break
        self._cur = None
        _rm(live_path); _rm(sid_path)

        if self.tid in _cancelled:            # Stop was pressed - clean, not error
            _cancelled.discard(self.tid)
            # `canceled` is the structured signal (Paseo turn_canceled): the turn
            # ended by the owner's hand, not by an error - the lifecycle event
            # stream renders it as its own typed item, never a failure.
            # Card 2 dual-write: the ONE turn-lifecycle step read_transcript
            # derives (from the '[Request interrupted by user...]' sentinel
            # string) - folded here instead from the PROGRAMMATIC signal, which
            # is the more precise source the same way ACP's stopReason beats
            # string-sniffing a result frame (docs/multi-engine-support.md §4.3).
            try:
                timeline_store.append(run_dir, "s:" + uuid.uuid4().hex,
                    {"kind": "turn", "event": "canceled",
                     "ts": _time.strftime("%H:%M:%S", _time.localtime()), "ta": _time.time()})
            except Exception:
                pass
            return self.session_id, "(turn cancelled by you)", \
                {"usage": {}, "cost_usd": None, "models": [], "canceled": True}
        if not finished:
            # wedged turn: tree-kill the session; the next steer resumes it.
            self.kill()
            raise RuntimeError(
                "claude turn stalled (%s) - session killed; steer again to resume. %s"
                % (why, "".join(self.err_tail).strip()[-200:]))
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
        # resume-attachment evidence for the FIRST turn after a --resume spawn:
        # sessions._finish_turn refuses to move the session pointer to a session
        # that demonstrably does NOT contain the conversation.
        if self._first_turn_after_spawn:
            self._first_turn_after_spawn = False
            if self._spawn_resumed:
                meta["resumed_from"] = self._spawn_resumed
                meta["resume_echo"] = self._resume_echo
                meta["ctx_first"] = cur.get("ctx_first") or {}
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
