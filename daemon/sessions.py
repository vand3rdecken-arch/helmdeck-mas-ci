# -*- coding: utf-8 -*-
"""The orchestrator - HelmDeck's Paseo half. A TRACK is a git branch, isolated in its own
worktree, bound to a RESUMABLE coding session (Claude Code --resume <session_id>). You select
a track and continue its context; history is never rebuilt. Each steer is recorded into the
flight recorder (actionlog) so what the session did stays reviewable.

Store: tracks.json (one list). Worktrees: <repo>/../helmdeck-worktrees/<repo-hash>/<branch>
(the 8-char repo hash proves OWNERSHIP by path shape - see _owned_worktree).
Permission mode is per-track and defaults to acceptEdits - the worktree is the blast-radius
control. Escalate a track to bypassPermissions only deliberately (owner decision)."""
import json, os, re, shutil, subprocess, time
from runs import REC

ROOT = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(ROOT, "tracks.json")
DEFAULT_PERM = os.environ.get("HELMDECK_PERM", "acceptEdits")
CLAUDE = (os.environ.get("HELMDECK_CLAUDE") or shutil.which("claude")
          or r"C:\Program Files\nodejs\claude.cmd")

import db as _db

def _load():
    return _db.tracks_all()

def _save(tracks):
    _db.tracks_replace(tracks)

def _save_track(t):
    _db.track_put(t)

def _find(tracks, tid):
    for t in tracks:
        if t["id"] == tid:
            return t
    return None

def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:32] or "track"

def _unique_id(suffix):
    """Card ids are <timestamp>-<suffix>, and the id is also the PRIMARY KEY and
    the run_dir name. Two cards filed in the SAME SECOND with the same suffix
    used to produce the same id - and track_put is INSERT OR REPLACE, so the
    first card was silently overwritten (its audit + economics gone, its flight
    recorder shared). That is reachable in normal use: every machine task uses
    the branch '(machine)', and the chat can file two in one second. Take the
    next free id instead."""
    base = time.strftime("%Y%m%d-%H%M%S") + "-" + suffix
    tid, n = base, 2
    while _db.track_get(tid) is not None:
        tid = "%s-%d" % (base, n)
        n += 1
    return tid

def _git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), r.stderr.strip()))
    return r.stdout.strip()

def _checkpoint(worktree):
    """A rewindable anchor for the worktree's CURRENT state - a dangling commit
    that snapshots ALL files (tracked AND untracked, minus .gitignore), built in
    a TEMP index so neither history nor the real index is touched. (git stash
    create skips untracked files, which are exactly the ones an agent creates -
    so it can't be used here.) Rewinding restores files from this commit."""
    import tempfile
    # a git worktree's .git is a FILE, so the temp index must live OUTSIDE the
    # worktree (a normal repo would tolerate .git/, a worktree won't).
    fd, idx = tempfile.mkstemp(suffix=".ckptindex")
    os.close(fd)
    try:
        env = dict(os.environ, GIT_INDEX_FILE=idx)

        def g(*a, check=True):
            r = subprocess.run(["git", "-C", worktree, *a], env=env,
                               capture_output=True, text=True)
            if check and r.returncode != 0:
                raise RuntimeError(r.stderr.strip())
            return r.stdout.strip()

        head = _git(worktree, "rev-parse", "HEAD")
        g("read-tree", head)               # seed temp index from HEAD
        g("add", "-A")                     # stage every worktree file into it
        tree = g("write-tree")
        # commit-tree uses the object db, not the index - real env is fine
        commit = _git(worktree, "commit-tree", tree, "-p", head, "-m", "helmdeck checkpoint")
        return commit or None
    except Exception:
        return None
    finally:
        try:
            os.remove(idx)
        except OSError:
            pass

def _seed_worktree(repo, wt):
    """Copy the un-versioned files a build needs into a fresh worktree.

    A worktree only contains TRACKED files, so anything git-ignored is missing -
    and that is exactly where local toolchain config lives (local.properties
    points at the Android SDK, .env holds local settings). Without them a card
    cannot build what the same repo builds fine by hand.

    Configure in settings.json; defaults deliberately carry NO signing material,
    because handing an agent a release keystore should be a decision, not a
    side effect:

        "worktree_seed": ["apk/local.properties", ".env"]
    """
    import events
    patterns = events.settings().get("worktree_seed")
    if patterns is None:
        patterns = ["apk/local.properties", "local.properties"]
    copied = []
    for rel in patterns:
        src = os.path.join(repo, rel)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(wt, rel)
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            copied.append(rel)
        except OSError:
            pass
    return copied


def _branch_exists(repo, branch):
    r = subprocess.run(["git", "-C", repo, "rev-parse", "--verify", branch],
                       capture_output=True, text=True)
    return r.returncode == 0

def is_git_repo(path):
    """Intake check: dispatch needs `git worktree add`, so a non-repo path must
    be rejected when the card is filed, not discovered mid-dispatch."""
    if not path or not os.path.isdir(path):
        return False
    r = subprocess.run(["git", "-C", path, "rev-parse", "--git-dir"],
                       capture_output=True, text=True)
    return r.returncode == 0

WORKTREE_DIRNAME = "helmdeck-worktrees"


def _repo_hash(repo):
    """8-char base36 fingerprint of the repo IDENTITY (Paseo
    deriveWorktreeProjectHash): sha256 over the realpath of the repo ROOT,
    resolved via `git rev-parse --git-common-dir` so a worktree of the repo
    hashes the same as the repo itself. First 8 digest bytes -> base36 -> 8
    chars. Falls back to hashing the given path when git is unreachable -
    the hash must be computable even over a broken checkout."""
    import hashlib
    try:
        rc, out, _ = _git_try(repo, "rev-parse", "--git-common-dir")
        if rc != 0 or not out:
            raise RuntimeError(out)
        common = os.path.realpath(out if os.path.isabs(out)
                                  else os.path.join(repo, out))
        root = os.path.dirname(common) if os.path.basename(common) == ".git" else common
    except Exception:
        root = os.path.realpath(repo)
    n = int.from_bytes(hashlib.sha256(root.encode("utf-8")).digest()[:8], "big")
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    s = ""
    while n:
        n, r = divmod(n, 36)
        s = digits[r] + s
    return s.zfill(13)[:8]


def _worktree_for(repo, branch):
    base = os.path.abspath(os.path.join(repo, "..", WORKTREE_DIRNAME))
    wt = os.path.join(base, _repo_hash(repo), _slug(branch))
    os.makedirs(os.path.dirname(wt), exist_ok=True)
    return wt


def _owned_worktree(path):
    """Ownership by PATH SHAPE alone (Paseo isPaseoOwnedWorktreeCwd): may this
    directory be rm'd even when git has forgotten it? Owned iff it sits at
    <...>/helmdeck-worktrees/<8-char-base36-hash>/<name> - that prefix is
    HelmDeck-private, nothing else writes there, so the shape is sufficient
    proof even with git broken. Pre-hash FLAT trees (<...>/helmdeck-worktrees/
    <name>) are NOT owned: only git may manage those (they could be anything)."""
    p = os.path.realpath(path)
    parent = os.path.dirname(p)                    # the <hash> dir
    grand = os.path.dirname(parent)                # the helmdeck-worktrees dir
    return bool(os.path.basename(p)) \
        and os.path.basename(grand) == WORKTREE_DIRNAME \
        and re.fullmatch(r"[0-9a-z]{8}", os.path.basename(parent)) is not None


def _git_state_broken(wt):
    """True when a worktree's link to its repo is severed (the class 4.1
    reclaims): .git missing, unreadable, or pointing at an admin dir that no
    longer exists (half-removed tree, pruned admin dir, moved repo). A .git
    DIRECTORY means a full repo - never 'broken', never ours to judge."""
    gitfile = os.path.join(wt, ".git")
    if os.path.isdir(gitfile):
        return False
    if not os.path.exists(gitfile):
        return True
    try:
        with open(gitfile, encoding="utf-8", errors="replace") as f:
            m = re.search(r"gitdir:\s*(.+)", f.read())
    except OSError:
        return True
    if not m:
        return True
    gd = m.group(1).strip()
    if not os.path.isabs(gd):
        gd = os.path.join(wt, gd)
    return not os.path.isdir(gd)


# -- per-card dev port (Paseo PASEO_WORKTREE_PORT) ----------------------------
# Parallel cards each start "the" dev server on the project's default port and
# fight over it - the second card's server dies or, worse, tests silently hit
# the FIRST card's build. Paseo reserves a port per worktree and persists it in
# the worktree metadata; HelmDeck persists it on the track (tracks.json IS the
# card's durable metadata - a worktree can be reclaimed and regenerated, the
# card cannot). Allocated once at dispatch, sticky for the card's life, handed
# to the agent as HELMDECK_DEV_PORT (drivers._env).

DEV_PORT_RANGE = (3401, 3999)   # settings.json "dev_port_range": [lo, hi] overrides


def _alloc_dev_port(exclude_tid=None):
    """A free port no OTHER card has claimed (Paseo's range allocator: random
    start, scan the whole range wrapping around, skip reserved, bind-check
    each candidate). Returns None when the range is exhausted - the card still
    runs, it just gets no reserved port."""
    import socket, random, events
    rng = events.settings().get("dev_port_range") or DEV_PORT_RANGE
    try:
        lo, hi = int(rng[0]), int(rng[1])
    except Exception:
        lo, hi = DEV_PORT_RANGE
    if lo > hi:
        lo, hi = hi, lo
    taken = {t.get("dev_port") for t in _load()
             if t.get("dev_port") and t.get("id") != exclude_tid}
    span = hi - lo + 1
    start = random.randrange(span)
    for i in range(span):
        port = lo + (start + i) % span
        if port in taken:
            continue
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            continue
        finally:
            s.close()
        return port
    return None


def _base_ref(repo):
    """The commit a NEW card branch starts from (Paseo
    resolveBaseBranchForWorktree + normalizeRequiredBaseBranch). Explicit
    instead of implicit: `worktree add -b` with no start point bases the card
    on whatever HEAD happens to be - mid-rebase or detached, that is the wrong
    code. So: name the base branch (rebase-guarded _current_branch), REJECT
    detached/unborn, and prefer origin/<base> only when it is ahead-or-equal
    of the local base. (Paseo always prefers origin because the remote is its
    source of truth; HelmDeck merges cards into the LOCAL checkout, so a stale
    origin must never win over local commits.) The caller passes --no-track so
    the card branch never claims that base as upstream."""
    base = _current_branch(repo)
    if not base or base == "HEAD":
        raise RuntimeError("cannot create the card branch: the repo checkout is "
                           "detached (no base branch) - checkout the base branch first")
    if _git_try(repo, "rev-parse", "--verify", "-q", base)[0] != 0:
        raise RuntimeError("cannot create the card branch: base branch '%s' has "
                           "no commits yet - make an initial commit first" % base)
    origin = "origin/" + base
    if (_git_try(repo, "rev-parse", "--verify", "-q", origin)[0] == 0
            and _git_try(repo, "merge-base", "--is-ancestor", base, origin)[0] == 0):
        return origin
    return base


def _worktree_of_branch(repo, branch):
    """Path of an EXISTING worktree that already has `branch` checked out, or
    None. git refuses to check the same branch out twice, so if a stale worktree
    holds it (e.g. a swarmdeck->helmdeck rename left ../swarmdeck-worktrees),
    dispatch must REUSE that path instead of failing on `git worktree add`."""
    r = subprocess.run(["git", "-C", repo, "worktree", "list", "--porcelain"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    path = None
    for line in r.stdout.splitlines():
        if line.startswith("worktree "):
            path = line[9:].strip()
        elif line.startswith("branch ") and path and line[7:].strip() == "refs/heads/" + branch:
            return path
    return None

import threading as _threading
_turn_locks = {}
_turn_locks_guard = _threading.Lock()

def _lock_for(tid):
    with _turn_locks_guard:
        if tid not in _turn_locks:
            _turn_locks[tid] = _threading.Lock()
        return _turn_locks[tid]

# Only one card may hold real Windows desktop control (mouse/keyboard/screen)
# at a time - two windows-mcp turns racing would fight over the same cursor.
# A plain in-process lock is the right primitive: _turn() blocks synchronously
# for a whole turn, so the lock's held state IS the running desktop turn -
# never a stored flag that could drift from reality.
_desktop_lock = _threading.Lock()

# windows-mcp tools that only OBSERVE the screen (read pixels/inventory) and
# never move the cursor or type. A card whose ONLY windows-mcp grants are these
# does not contend for the one physical cursor, so it must NOT take the exclusive
# desktop lock - otherwise a passive Screenshot card would starve a real driver.
_WINDOWS_MCP_READONLY = frozenset({
    "Screenshot", "Snapshot", "Scrape", "DisplayInventory",
})

def _uses_desktop_control(cfg):
    """True iff this card can physically drive mouse/keyboard/screen and so must
    hold the single global _desktop_lock. Read-only screen tools (Screenshot,
    Snapshot, ...) are exempted. FAIL-SAFE: a wildcard windows-mcp grant, or any
    tool not on the read-only allowlist, locks - so a new/unknown control tool
    can never silently bypass the guard and race the cursor."""
    for pat in (cfg.get("allowed_tools") or []):
        s = str(pat)
        if "windows-mcp" not in s:
            continue
        tail = s.rsplit("__", 1)[-1]        # tool name after mcp__windows-mcp__
        if "*" in tail:                     # wildcard: could be any tool -> lock
            return True
        if tail not in _WINDOWS_MCP_READONLY:   # a control tool -> lock
            return True
    return False

# INTERRUPT-AND-REPLACE (Paseo parity). A steer that arrives mid-turn must take
# effect NOW - Paseo's replaceAgentRun soft-interrupts the live turn and starts
# the new prompt on the same session. HelmDeck used to QUEUE it behind the whole
# running turn (the per-card _lock_for), so a second message only landed minutes
# later. This epoch collapses a burst of steers to LAST-WINS: each steer bumps
# it, and only the newest actually runs its turn - the rest bail after the
# interrupt fires. (The soft interrupt itself is drivers.cancel, the P1 port.)
_steer_epoch = {}
_steer_pending = {}                 # tid -> [text, ...] of the burst (nothing lost)
_steer_epoch_guard = _threading.Lock()


def _bump_steer_epoch(tid, text=None):
    """Bump the epoch AND register this steer's text atomically. A superseded
    steer's text stays in the pending list, so the WINNING steer bundles every
    instruction into its one turn - a burst collapses without a single command
    silently disappearing ("why did my command disappear")."""
    with _steer_epoch_guard:
        _steer_epoch[tid] = _steer_epoch.get(tid, 0) + 1
        if text is not None:
            _steer_pending.setdefault(tid, []).append(text)
        return _steer_epoch[tid]


def _steer_epoch_current(tid):
    with _steer_epoch_guard:
        return _steer_epoch.get(tid, 0)


def _drain_steer_texts(tid):
    with _steer_epoch_guard:
        return _steer_pending.pop(tid, [])


_BG_HISTORY_CAP = 12       # terminal tasks kept for the app; running ones never dropped
BG_TERMINAL = ("completed", "failed", "canceled")


def bg_upsert(tid, uid, title=None, detail=None, status="running", result=None):
    """Fold ONE background-task LIFECYCLE event onto the track - Paseo's
    ProviderSubagentStore.apply(): a descriptor per task with an explicit status
    (running -> completed|failed|canceled), maintained at EVENT TIME by the pump,
    never reconstructed by transcript forensics. A launch upserts 'running', a
    <task-notification> 'completed'; reconcile_bg cancels survivors of a dead
    process. Terminal tasks are kept (bounded) so the app can show what the
    worker did and how it ended - clickable, like Paseo."""
    if not uid:
        return
    def _apply(t):
        tasks = dict(t.get("bg_tasks") or {})
        cur = dict(tasks.get(uid) or {})
        now = time.time()
        cur.setdefault("since", now)
        cur.setdefault("title", title or "task")
        if title:
            cur["title"] = title[:80]
        if detail:
            cur["detail"] = detail[:600]
        cur["status"] = status
        if result is not None:
            cur["result"] = str(result)[:2000]
        cur["updated"] = now
        tasks[uid] = cur
        # bound the TERMINAL history (last N by finish time); a running task is
        # never evicted - it is load-bearing for the waiting_on gate.
        terminal = sorted(((u, v) for u, v in tasks.items()
                           if v.get("status") in BG_TERMINAL),
                          key=lambda kv: kv[1].get("updated", 0))
        for u, _v in terminal[:max(0, len(terminal) - _BG_HISTORY_CAP)]:
            tasks.pop(u, None)
        t["bg_tasks"] = tasks
    _mutate(tid, _apply)


def reconcile_bg(tid, status="canceled", why="Prozess beendet, bevor der Task meldete"):
    """finishAll (Paseo sidechain-tracker.finishAll): a background task is a CHILD
    of the worker process, so when that process dies - a timeout tree-kill, a
    daemon restart, a crash - every still-running task died with it and can never
    report. Transition them to a terminal status so a dead build never lingers as
    a phantom the card waits on forever (the 'wartet auf N Hintergrund-Task' that
    only ever grew). Returns how many were reconciled."""
    box = {}
    def _apply(t):
        tasks = t.get("bg_tasks")
        if not isinstance(tasks, dict):
            return False
        n = 0
        for v in tasks.values():
            if v.get("status", "running") == "running":
                v["status"] = status
                v["updated"] = time.time()
                v.setdefault("result", why)
                v.setdefault("title", v.get("desc") or "task")   # migrate pre-P2 entries
                n += 1
        if not n:
            return False
        box["n"] = n
    _mutate(tid, _apply)
    return box.get("n", 0)

# -- THE one legal write path for existing tracks (Paseo's one-owner principle) --
# Tracks are whole JSON dicts, and they used to be read+written from >=4 threads
# at once (steer, cancel, the reconciler, lane moves, answers, archive). Each
# writer did load -> edit its copy -> save: last-writer-wins, so a stale snapshot
# could resurrect 'running' and freeze a card (incident 2026-08-07 16:09, 164min).
# Paseo cannot have this bug because every lifecycle transition runs in ONE
# stream-event handler (agent-manager.ts ~3600): one owner, no competing writers.
# _mutate is that owner made explicit: a SHORT per-card mutation lock (NOT
# _lock_for - that one is held for a whole turn), a FRESH load, fn(t), save.
# Nothing outside _mutate may write status/gate_report/question/waiting_on/
# background on an existing track (invariant I1, pinned by test_status_store.py).

_mutate_locks = {}
_mutate_locks_guard = _threading.Lock()

def _mutate_lock_for(tid):
    with _mutate_locks_guard:
        if tid not in _mutate_locks:
            _mutate_locks[tid] = _threading.Lock()
        return _mutate_locks[tid]

def _mutate(tid, fn):
    """Atomically edit one track: lock -> fresh load -> fn(t) -> save -> return t.
    fn gets the CURRENT stored track (never a caller's stale snapshot) and may
    return False to skip the save (the no-op / lost-the-race case). Returns the
    track (fresh), or None if the track does not exist. fn must be QUICK - no
    model turns, no subprocesses; compute those before calling _mutate."""
    with _mutate_lock_for(tid):
        t = _find(_load(), tid)
        if t is None:
            return None
        if fn(t) is False:
            return t
        t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save_track(t)
        return t

def flag_burn(tid, evidence):
    """The driver saw N identical consecutive tool calls (a likely loop that is
    burning tokens - drivers._burn_watch). NEVER auto-kill: a retry-with-backoff
    can be legitimate. Persist the signal First-Class (one owner, event time) and
    hand the JUDGEMENT to the PM, which knows the card + goal and escalates to
    the owner only if its own correction doesn't take."""
    box = {}

    def _set(tt):
        if tt.get("status") != "running":
            return False                 # the turn already ended - nothing to correct
        cur = dict(tt.get("burn") or {})
        cur.update(evidence)
        cur["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
        cur.setdefault("corrections", 0)
        tt["burn"] = cur
        box["ok"] = True
    t = _mutate(tid, _set)
    if t is None or not box.get("ok"):
        return
    try:
        from actionlog import ActionLog
        ActionLog(t["run_dir"]).log(
            "note", "⚠ Worker wiederholt denselben Schritt (%dx %s) - PM prueft"
            % (evidence.get("n", 0), evidence.get("name", "")))
    except Exception:
        pass
    import events
    events.emit("burn", tid, n=evidence.get("n"), name=evidence.get("name"))
    try:
        import pm
        pm.review_burn(tid)
    except Exception:
        pass


def _turn(t, prompt, model=None, perm=None, idle_timeout=None):
    """One turn through the track's DRIVER (drivers.py) - Claude Code by default,
    but any agent runtime configured in settings. Handles the flight-recorder
    hook: a driver with record:true gets its whole turn screen-captured into the
    track's run_dir (screen.mp4 + live.jpg glance feed). Per-turn `model` and
    `perm` overrides (from the chat composer's model + mode controls) win over
    the driver's configured values. `idle_timeout` overrides the driver's
    900s-of-silence watchdog for callers who know their own turn is bounded
    (e.g. _maybe_compact - see there for why)."""
    import drivers, events
    # Pre-P4 cards were dispatched without a reserved dev port - claim one on
    # their next turn so HELMDECK_DEV_PORT is always there (sticky afterwards).
    if not t.get("machine") and t.get("worktree") and not t.get("dev_port"):
        port = _alloc_dev_port(exclude_tid=t["id"])
        if port:
            def _claim(tt):
                tt.setdefault("dev_port", port)
            t = _mutate(t["id"], _claim) or t
    name = t.get("driver") or "claude"
    cfg = events.settings().get("drivers", {}).get(name) or {"type": "claude"}
    model = model or t.get("model")      # card's chosen model (from New Request) unless overridden
    # NO turn may fall through to the CLI's global default. Only steer()'s
    # composer path used to resolve "auto"; every harness-initiated turn
    # (dispatch, auto-continue after a background task, the ask-repair call)
    # passed no model, so the spawned CLI ran on whatever the OWNER'S OWN
    # interactive `/model` was last set to - measured live 2026-08-14: cards
    # believed to be on Auto (sonnet-tier) silently billed fable-5 turns
    # because the owner's terminal happened to be set there. Auto is resolved
    # HERE, at the one choke point every turn passes through, from the card's
    # own facts - deliberate routing always, global leak never. An explicit
    # model (composer pick or the card's stored choice) still wins untouched.
    if not model or model == "auto":
        import turnopts
        model, _ = turnopts.resolve_model("auto", prompt, signals={
            "value": t.get("value"), "priority": t.get("priority"),
            "turns": t.get("turns"), "failed": bool(t.get("gate_failed")),
            "fails": events.consecutive_gate_fails(t["id"])})
    if model:
        cfg = {**cfg, "model": model}
    if perm:
        cfg = {**cfg, "perm": perm}
    if idle_timeout:
        cfg = {**cfg, "idle_timeout": idle_timeout}
    rec = None
    if cfg.get("record"):
        try:
            import wincap
            rec = wincap.start(t["run_dir"])
        except Exception as e:
            print("recorder failed to start:", e)
    desktop = _uses_desktop_control(cfg)
    if desktop and not _desktop_lock.acquire(blocking=False):
        raise RuntimeError(
            "Desktop control (windows-mcp) is already in use by another card - "
            "only one card may drive the mouse/keyboard/screen at a time. "
            "Wait for that turn to finish, then retry.")
    try:
        with _lock_for(t["id"]):   # one turn per card at a time - pays turn-locks debt
            return drivers.run(cfg, t, prompt)
    finally:
        if desktop:
            _desktop_lock.release()
        if rec:
            import wincap
            wincap.stop(rec)
            from actionlog import ActionLog
            ActionLog(t["run_dir"]).log("note", "screen recording captured for this turn")

def _repair_question(t, log):
    """Convert a turn that parked on a PROSE question into a typed one.

    Measured against the real CLI: teaching the protocol in the system prompt
    alone is not enough - a worker that needs a decision reliably writes prose
    and stops (that is exactly the trap Phase 2.4 exists to close). Asking for
    the block as the IMMEDIATE instruction does work, so when a turn parks on
    what looks like a question the harness spends ONE short turn on the same
    session to have it restated in protocol form.

    Bounded by construction: called only from _settle_reply, never recursive
    (its own result is parsed, not re-repaired), and the worker can decline with
    NOQUESTION. Switch it off with policy.ask_repair=false."""
    import ask, events
    try:
        _sid, out, meta = _turn(t, ask.REPAIR)
    except Exception as e:
        # a repair is a convenience, never a reason to fail a finished turn
        log.log("note", "Frage-Reparatur fehlgeschlagen: %s" % str(e)[:200])
        return None
    # measured economics: this turn is billed too. Through _mutate (it runs a
    # whole model turn, so it is only ever called OUTSIDE the mutation lock).
    _mutate(t["id"], lambda tt: (_record_econ(tt, meta), None)[1])
    if ask.NO_QUESTION in (out or "")[:200]:
        return None                # worker says it was not actually asking
    question, _ = ask.parse(out or "")
    if question:
        events.emit("askrepair", t["id"], ok=True)
    return question


def _ask_repair_on(t):
    """policy.ask_repair (default on). Off => a prose question parks the card
    exactly as it did before Phase 2.4 - no repair turn, no extra cost."""
    import events
    pol = events.settings().get("policy") or {}
    return bool(pol.get("ask_repair", True))


def is_delivered(t):
    """True when a parked card is really HANDING WORK BACK, as opposed to
    sitting on `needs_you` for some other reason.

    Every automation that treats "status == needs_you" as "the worker is done"
    needs this. Since Phase 2 a card can be parked because it is ASKING the
    owner a question, or because it is waiting on a background task it started -
    neither is finished work. Auto-accepting those would merge an unfinished
    branch and throw the question away, and announcing them as "delivered" is
    simply wrong. (Both cases existed before; they were just indistinguishable.)"""
    t = t or {}
    return (t.get("status") == "needs_you"
            and not t.get("question")
            and t.get("waiting_on") != "background")


# Why a card is blocked on the human. One vocabulary, so a surface can rank or
# ICON the blocker instead of re-reading raw status/report fields:
#   question  - the worker asked and is parked on the answer
#   delivered - finished work, parked for your accept
#   review    - gate green, resting on Review for your accept
#   gate      - the quality gate came back red
#   conflict  - the branch cannot land (merge conflict / blocked merge)
#   failed    - dispatch died, a turn was swept, or you bounced it back
BLOCKER_REASONS = ("question", "delivered", "review", "gate", "conflict", "failed")


def _blocker_text(v, n=160):
    """One short SINGLE-LINE reason. Bounce reports arrive as a list of gate
    problems, as a paragraph, or not at all; a badge and a 600x600 glasses
    display can render exactly one line of it.

    Whitespace is COLLAPSED, not truncated at the first newline the way the
    card's compact `punch` is: a gate problem's first line is only the name of
    the check ("tests/test_x.py:") and the assertion that actually failed sits
    on the line below it. At a glance the second line is the whole point."""
    if isinstance(v, (list, tuple)):
        v = " | ".join(str(x) for x in v if x)
    return " ".join(str(v or "").split())[:n]


def blocker(t):
    """The ONE derivation of "nothing moves on this card until the OWNER acts",
    and WHY. Returns None when the card is nobody's move but the machine's -
    running, gating, queued, landed, archived, or waiting on its own background
    task - else {"reason": one of BLOCKER_REASONS, "detail": short text}.

    Every surface that answers "what needs me" reads this instead of re-deriving
    it from `status`, because re-deriving is exactly what let the surfaces
    drift: the glasses feed listed `needs_you` only, so a card held by a RED
    GATE, an open merge conflict, a failed dispatch or a swept zombie - every
    one of them stuck until the owner acts - showed up nowhere, and neither did
    a card resting on Review for an accept. Three surfaces, three different
    answers to one question.

    Pass the card through present() first when the answer must be live: a
    phantom `running` (its turn died) is the owner's move, and only present()
    knows that.

    The bounce REPORTS are read most-specific-first, which is sound because the
    writers keep exactly one current report on a bounced card - _gatefail pops
    merge_report, _mergefail and _markers pop gate_report.

    Where the line is drawn, deliberately: a card nobody has started is not
    BLOCKED, it is unstarted. A `queued` backlog card the PM will never dispatch
    on its own (mode human/teach/cowork, or a quota-paused day) is the owner's
    WORK, not his decision - it belongs on a board, and putting it here would
    bury the six cards that really are stuck under fifty that merely wait."""
    t = t or {}
    if t.get("archived"):
        return None
    s = t.get("status")
    if s == "submitted":
        return {"reason": "review", "detail": _blocker_text(t.get("review_report"))}
    if s == "bounced":
        if t.get("gate_report"):
            return {"reason": "gate", "detail": _blocker_text(t["gate_report"])}
        if t.get("merge_report"):
            return {"reason": "conflict" if t.get("merge_kind") == "conflict" else "failed",
                    "detail": _blocker_text(t["merge_report"])}
        # A bounce with no report of its own - the owner dragged it back, a
        # dispatch died, a turn was swept. If that card is ALSO holding an
        # unanswered question, the question is the actionable half and reporting
        # only "failed" would drop it: answering it is what unsticks the card.
        if not t.get("question"):
            return {"reason": "failed", "detail": _blocker_text(t.get("last_reply"))}
    elif s != "needs_you" or t.get("waiting_on") == "background":
        return None
    if t.get("question"):
        try:
            import ask
            detail = ask.summary(t["question"])
        except Exception:
            detail = ""            # a summary is never worth failing a read
        return {"reason": "question", "detail": _blocker_text(detail)}
    return {"reason": "delivered", "detail": _blocker_text(t.get("last_reply"))}


# Modes the machine STRUCTURALLY refuses to start: every auto-dispatch path
# excludes them (pm._backlog, pm._chain_ready, pm.activity's todo list,
# processes._advance), and teach/human get no driver at all (MODE_DRIVER). A
# `do` card in the backlog is waiting its TURN; one of these is waiting for a
# human, forever, and nothing anywhere used to say so.
MANUAL_MODES = ("human", "teach", "cowork")


def manual_backlog(tracks):
    """Un-started cards only the OWNER can ever start, as [(card, why)].

    Deliberately NOT part of blocker(): these are not stuck work, they are
    unstarted work, and merging them into "what is blocked on me" would bury a
    red gate under a backlog. They are their own bucket with their own count -
    complete information, in the right order of alarm.

    An ordinary `do` card in the backlog is absent on purpose: the PM will get
    to it. These it will never get to."""
    out = []
    for t in tracks or ():
        t = t or {}
        if t.get("archived") or t.get("status") != "queued":
            continue
        if t.get("mode") in MANUAL_MODES:
            out.append((t, {"reason": "yours", "mode": t.get("mode"),
                            "detail": _blocker_text(t.get("description")
                                                    or t.get("task"))}))
    return out


def owner_blockers(tracks):
    """THE surface entry point: every card on `tracks` that is blocked on the
    human, as a list of (card, blocker) - the card as PRESENTED, so a phantom
    `running` (its turn died) counts from the moment it is read rather than
    whenever the reconciler next runs.

    blocker() alone is deliberately pure - it decides from the fields it is
    handed and touches no process table or disk. Pairing it with present() is
    the half every surface would otherwise have to remember, and forgetting it
    is a silent gap: the card is stuck, its stored status says `running`, and
    nothing anywhere says the owner has to act."""
    out = []
    for t in tracks or ():
        t = present(t)
        b = blocker(t)
        if b:
            out.append((t, b))
    return out


def waits_for_owner(t):
    """True when the card wants something from the HUMAN right now - finished
    work to accept, a question to answer, or a bounce/red gate to unstick. A
    background wait is excluded: it is the one parked state that is nobody's
    move but the machine's. Thin predicate over owner_blockers(), so there is
    one derivation and not a second one drifting alongside it."""
    return bool(owner_blockers([t] if t else []))


def _settle_reply_compute(t, result, log):
    """The SLOW half of interpreting a finished turn's reply - runs OUTSIDE the
    mutation lock (the question-repair is a whole model turn, the background
    probe reads the transcript from disk). Pure compute: touches nothing on the
    stored track. Returns (question, cleaned, bg)."""
    import ask
    question, cleaned = ask.parse(result or "")
    if not question and _ask_repair_on(t) and ask.looks_like_question(cleaned):
        question = _repair_question(t, log)
    bg = None
    if not question:
        # A turn may not be waiting on the OWNER: one that ended while a
        # background task it launched is still running is waiting on THAT
        # (Phase 2.5). Saying "waiting for you" there parked cards in limbo.
        import claude_sessions
        try:
            bg = claude_sessions.background_wait(t)
        except Exception:
            bg = None                    # a cue is never worth failing a turn
    return question, cleaned, bg


def _settle_reply_apply(t, question, cleaned, bg, log):
    """The WRITE half - runs INSIDE _mutate as part of the one atomic
    end-of-turn commit (_finish_turn). Together with _settle_reply_compute this
    is still the one place a reply is interpreted, so the three turn sites
    (dispatch, machine dispatch, steer) cannot drift apart. The machine block is
    stripped from BOTH the audit line and last_reply: the owner reads those, and
    raw protocol JSON in them is noise - the parsed question carries the same
    information in typed form. Returns the notify reason."""
    import ask, events
    log.log("reply", cleaned[:2000])
    t["last_reply"] = cleaned[:2000]
    if not question:
        # A turn that does not ask supersedes any older pending question -
        # leaving a stale one would show buttons for a decision the worker has
        # already moved past.
        t.pop("question", None)
        if bg:
            t["waiting_on"] = "background"
            # keep the ORIGINAL start time across turns, so the watcher's
            # give-up window measures the wait, not the last poll
            bg["since"] = (t.get("background") or {}).get("since") or time.time()
            t["background"] = bg
            log.log("note", "wartet auf %d Hintergrund-Task(s): %s"
                    % (bg["n"], ", ".join(bg["names"])[:200]))
            return "background"
        t["waiting_on"] = "you"
        t.pop("background", None)
        return "needs_you"
    t["waiting_on"] = "you"
    t.pop("background", None)
    t["question"] = question
    log.log("note", "FRAGE an dich: " + ask.summary(question))
    # NB: events.emit's own first parameter is called `kind`, so the question's
    # type travels as `qkind` - `kind=` here is a TypeError, not an override.
    events.emit("question", t["id"], qkind=question["kind"],
                n=len(question["questions"]))
    return "question"


def _record_econ(t, meta):
    """Fold ONE model call's spend into the card + the event log.

    Split out of _record_turn because not every model call is a card turn: the
    question-repair call (_repair_question) is real spend on the owner's account
    and the 'measured economics' law admits no unbilled calls - but it is not a
    turn of the conversation, so it must not move the failure signal or drop a
    rewind checkpoint."""
    import events
    u = meta.get("usage") or {}
    cost = events.price_turn(meta.get("models"), u, meta.get("cost_usd"))
    t["ai_cost"] = round(t.get("ai_cost", 0.0) + cost, 6)
    t["tokens_in"] = t.get("tokens_in", 0) + u.get("input_tokens", 0) \
        + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)
    t["tokens_out"] = t.get("tokens_out", 0) + u.get("output_tokens", 0)
    # CONTEXT METER (Paseo-parity: contextWindowUsedTokens). tokens_in above is
    # CUMULATIVE across turns - useless for "how full is the window". And the
    # result event's `usage` SUMS every API call of the turn - a long multi-call
    # turn read as millions of "context" tokens (the 6634k/100% meter) and
    # falsely tripped auto-compact. The truthful source is the LAST assistant
    # call's own usage (meta.ctx_usage, captured by the driver, Paseo-style):
    # its input side = the context size at that moment. No fallback to the
    # summed value - a missing reading means NO update, never a wrong one.
    cu = meta.get("ctx_usage") or {}
    ctx = (cu.get("input_tokens", 0) + cu.get("cache_creation_input_tokens", 0)
           + cu.get("cache_read_input_tokens", 0))
    if ctx:
        t["ctx_tokens"] = ctx
    for m in meta.get("models") or []:
        if m not in t.setdefault("models", []):
            t["models"].append(m)
    # CONTEXT WINDOW - derived from the runtime's own evidence, never assumed.
    # The meter divided by a hardcoded 200k, so a card on a 1M model showed
    # "97% - Kontext fast voll" at a real ~23% (the Tester card carried a
    # 230k call through fine while the banner cried overflow). Two witnesses,
    # both from the CLI itself: the model id carries the window (the "[1m]"
    # suffix in modelUsage), and any SUCCESSFUL call's context proves a lower
    # bound (a window cannot be smaller than what it just held).
    win = 1_000_000 if any("[1m]" in m for m in (t.get("models") or [])) else _CTX_WINDOW
    # A call that PROVED more context than the standard window is itself window
    # evidence: no 200k window could have held it, so the session runs on the 1M
    # tier even when the model id lacks the "[1m]" suffix. Without this the old
    # max(win, ctx) lower-bound pinned the meter at exactly 100% forever (478k
    # of "478k") while the CLI - which knows its real window - sat at ~48% and
    # correctly refused to compact: a red meter nothing would ever clear.
    if (t.get("ctx_tokens") or 0) > _CTX_WINDOW:
        win = 1_000_000
    t["ctx_window"] = max(win, t.get("ctx_window") or 0, t.get("ctx_tokens") or 0)
    events.emit("turn", t["id"], cost=round(cost, 6), usage=u, models=meta.get("models") or [])
    return cost


def _settle_reply(t, result, log):
    """Compose the two halves on the CALLER's dict (no store write). Production
    goes through _finish_turn, which runs the compute half outside and the
    apply half inside the mutation lock; this seam exists for the settle tests
    and any caller that manages its own persistence via _mutate."""
    question, cleaned, bg = _settle_reply_compute(t, result, log)
    return _settle_reply_apply(t, question, cleaned, bg, log)


def _record_turn(t, meta, cp_commit=None):
    """Fold one turn's economics into the track and the event log. Runs INSIDE
    _mutate; the rewind checkpoint (a git subprocess) is computed by the caller
    BEFORE the lock and handed in as `cp_commit`. Returns the turn's cost."""
    # structured failure signal off the driver's result event (not the prose
    # reply) - the night shift reads this instead of grepping last_reply.
    t["last_subtype"] = meta.get("subtype")
    t["last_error"] = meta.get("error") or ""
    cost = _record_econ(t, meta)
    if cp_commit:
        t.setdefault("checkpoints", []).append(
            {"turn": t.get("turns"), "commit": cp_commit,
             "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "reply": (t.get("last_reply") or "")[:80]})
    return cost


def _turn_checkpoint(t):
    """Per-turn rewind anchor: snapshot the worktree so a message can be rewound
    to (files restored to this point) later. Non-fatal if git isn't available.
    NOT for machine cards: their "worktree" is a real folder on the owner's PC
    (often his home), and snapshotting every file in it each turn is both slow
    and none of our business - rewind is a code-worktree feature. Runs OUTSIDE
    the mutation lock (a snapshot can take seconds on a big tree)."""
    if t.get("worktree") and not t.get("machine") and os.path.isdir(t["worktree"]):
        return _checkpoint(t["worktree"])
    return None


def resume_detached(prev_ctx, meta):
    """True when the FIRST turn after a --resume spawn demonstrably did NOT
    continue the conversation (the CLI silently started fresh). Evidence, not
    assumption (Paseo: session identity is verified from the runtime's own
    signals): the init event ECHOES the resumed id on a certain attach
    (resume_echo -> never detached), and a real continuation's FIRST API call
    carries at least the prior context - a fresh boot carries only the brief.
    Floors keep small histories and CLI-side compaction out of the verdict."""
    if not meta.get("resumed_from") or meta.get("resume_echo"):
        return False
    if (prev_ctx or 0) < 25_000:
        return False                     # too small a history to judge safely
    cf = meta.get("ctx_first") or {}
    first_ctx = (cf.get("input_tokens", 0) + cf.get("cache_creation_input_tokens", 0)
                 + cf.get("cache_read_input_tokens", 0))
    if not first_ctx:
        return False                     # no witness - never flag on absence
    return first_ctx < 0.5 * prev_ctx


def _finish_turn(tid, sid, result, meta, log):
    """ONE atomic commit per finished turn (Paseo's one-owner turn-completed
    handler): session rotation + turn count + reply/question/waiting_on +
    status=needs_you + economics land together under the mutation lock, so no
    concurrent cancel/sweep snapshot can resurrect 'running' or tear the
    result apart. Shared by dispatch, machine dispatch and steer. Also emits
    the typed turn-lifecycle record (turn completed/failed/canceled + usage)
    into the flight recorder - Phase 3.2's own-event stream, not a flat step.
    Returns (track, notify_reason)."""
    t = _find(_load(), tid)
    if t is None:
        return None, "needs_you"
    # slow half first, outside the lock: question repair (a model turn), the
    # background probe (disk), the rewind snapshot (git).
    question, cleaned, bg = _settle_reply_compute(t, result, log)
    cp_commit = _turn_checkpoint(t)
    box = {}

    def _commit(tt):
        # session rotation - GUARDED (the invariant): the pointer only moves
        # forward to a session that demonstrably CONTAINS the conversation. A
        # silent fresh start (--resume ignored) once moved the pointer onto an
        # empty thread and the card lost its whole context ("Voellig falscher
        # Kontext"); now that rotation is REFUSED - the next steer resumes the
        # real conversation, and the stray thread is kept in the chain.
        if sid and tt.get("session_id") and sid != tt["session_id"]:
            old = tt["session_id"]
            chain = [s for s in (tt.get("session_chain") or []) if s != old]
            chain.append(old)
            tt["session_chain"] = chain[-6:]         # bounded - last 6 prior sessions
            tt["session_id"] = sid
            if resume_detached(tt.get("ctx_tokens"), meta):
                # --resume did NOT re-attach: the CLI silently started a FRESH
                # session for this turn (a compacted/overflowed tip that plain
                # --resume can't continue). The conversation's LIVE HEAD is now
                # this new session - it holds THIS turn's steer + reply, proven
                # by the result we just read off it - so the pointer FOLLOWS it
                # (Paseo accept-and-rebind: agent.ts handleSystemMessage accepts
                # the changed session id, emits a visible notice, never fails the
                # turn). The old head drops into the chain, where
                # read_transcript_live still renders it as prior history.
                #
                # This SUPERSEDES the old "refuse to advance, keep pointer on the
                # old head" rule. That rule predated chain-rendering and, once the
                # chain rendered, actively HID the turn: the pointer stayed on the
                # old session, so THIS turn's steer was drawn at the TOP as
                # ancient chain history (out of order - the owner's message looked
                # lost), and every future steer re-resumed the same unattachable
                # session, spawning orphan after orphan. Context (the worker's
                # in-memory history) was already gone the moment resume failed;
                # advancing loses nothing further and restores chronology.
                log.log("note", "⚠ Kontext verloren: die Session liess sich nicht "
                        "fortsetzen (%s…), der Worker hat frisch begonnen (%s…). "
                        "Der bisherige Verlauf bleibt sichtbar; ab hier baut er "
                        "auf der neuen Session auf." % (str(old)[:8], str(sid)[:8]))
        else:
            tt["session_id"] = sid or tt.get("session_id")
        tt["turns"] = tt.get("turns", 0) + 1
        box["reason"] = _settle_reply_apply(tt, question, cleaned, bg, log)
        tt["status"] = "needs_you"
        # A successful turn makes any stale interrupt/zombie note obsolete -
        # otherwise the card keeps reading "daemon restarted mid-turn" from a
        # PAST bounce when the turn just ended cleanly.
        gr = tt.get("gate_report")
        if isinstance(gr, list) and any(ZOMBIE_NOTE in x or RESUME_NOTE in x for x in gr):
            tt.pop("gate_report", None)
        # A turn that ended CLEANLY (real reply, not an error) broke out of any
        # loop, so the burn signal is stale - clear it. A looping turn never
        # reaches a clean end (the PM's correction interrupts it, or it errors),
        # so its `corrections` count survives to drive escalation.
        if tt.get("burn") and not meta.get("is_error") and not meta.get("canceled"):
            tt.pop("burn", None)
        box["cost"] = _record_turn(tt, meta, cp_commit)

    t = _mutate(tid, _commit) or t
    # the turn's lifecycle as its OWN typed event (Paseo turn_completed/
    # turn_failed/turn_canceled + usage), woven into the card feed by `ta`.
    _log_turn_end(log, meta, box.get("cost"))
    return t, box.get("reason", "needs_you")


def _log_turn_end(log, meta, cost=None):
    """Typed turn-lifecycle record for the card feed (Phase 3.2). failed <=>
    error != null, a Stop is canceled, everything else completed + usage."""
    u = meta.get("usage") or {}
    usage = {k: u.get(k, 0) for k in ("input_tokens", "output_tokens",
                                      "cache_creation_input_tokens",
                                      "cache_read_input_tokens")} if u else {}
    try:
        if meta.get("canceled"):
            log.log("turn", "Turn abgebrochen", event="canceled")
        elif meta.get("error") or meta.get("is_error"):
            log.log("turn", "Turn fehlgeschlagen", event="failed",
                    error=(meta.get("error") or meta.get("subtype") or "error")[:500],
                    usage=usage, cost=cost)
        else:
            log.log("turn", "Turn abgeschlossen", event="completed",
                    usage=usage, cost=cost)
    except Exception:
        pass                     # the feed record must never fail the turn

# -- lanes: the kanban IS the company structure, just relabeled ----------
# backlog = request filed (client needs ABC; nothing started, no session yet)
# working = dispatched      (agent session live on its branch)
# review  = submitted       (work + recording handed back for acceptance)
# done    = accepted        (deliverable taken; branch ready to merge)
LANES = ("backlog", "working", "review", "done")

# -- the lane/gate flow, AS DATA -----------------------------------------
# This lives here, next to move_lane(), because move_lane IS this machine: every
# node and edge below is a branch of it. It used to be re-typed by hand in
# server.py's /loop/map handler, which is how that copy came to describe a board
# nobody had shipped for months.
#
# `kind` is the load-bearing column:
#   fixed  - harness law (CLAUDE.md). Not configurable, shown read-only.
#   policy - data. `settings` names the exact key that governs the node, so the
#            UI can link a node straight to the knob instead of describing it.
#   why    - why it is fixed / what exactly is adjustable. Same argument as
#            loop_state.LOOP_STATES: the module that decides a node is fixed owns
#            the reason. Without it the map could only draw a padlock, which
#            reads as "arbitrarily locked" rather than "deliberately fixed".
#
# Every lane's NAME is renameable (policy.lane_labels) regardless of `kind` -
# that is a label, not a rule, which is why flow() resolves it for the UI.
LANE_FLOW = {
    "nodes": [
        {"key": "backlog", "default_label": "Backlog", "kind": "policy",
         "settings": ["policy.auto_dispatch_priority", "capacity.wip_limit"],
         "instruction": "Karten warten. Ab der Priorität in policy.auto_dispatch_priority "
                        "starten sie sich selbst - aber nur im WIP-Rahmen (capacity.wip_limit).",
         "why": "Du entscheidest, was sich von selbst startet: ab welcher Priorität und "
                "wie viele Karten gleichzeitig laufen dürfen."},
        {"key": "working", "default_label": "In Arbeit", "kind": "fixed",
         "settings": [],
         "instruction": "Ein Agent arbeitet in einem ISOLIERTEN git-worktree (Harness-Gesetz: "
                        "worktree-Isolation). Jeder Turn ist gemessen (Kosten/Token -> Audit).",
         "why": "Fix, weil ohne Worktree-Isolation zwei Karten sich gegenseitig "
                "überschreiben und ohne Messung kein Ergebnis zurechenbar wäre."},
        {"key": "review", "default_label": "Review", "kind": "fixed",
         "settings": [],
         "instruction": "Beim Eintritt läuft der Quality-Gate (gate-before-review, FIX). "
                        "Rot -> die Karte wird zurückgebounced mit sichtbarem Grund.",
         "why": "Fix, weil sonst ungeprüfte Arbeit zur Abnahme käme - der Gate ist "
                "die einzige Stelle, die 'grün' beweist statt behauptet."},
        {"key": "done", "default_label": "Fertig", "kind": "policy",
         "settings": ["policy.auto_accept_green"],
         "instruction": "Merge + Deploy. Nichts merged sich selbst - außer "
                        "policy.auto_accept_green ist an. Der Prozess-Chain rückt "
                        "einen Schritt vor.",
         "why": "Standard ist: nichts merged sich selbst. Ob grüne Karten automatisch "
                "durchgehen, entscheidest du mit policy.auto_accept_green."},
    ],
    "edges": [
        {"from": "backlog", "to": "working", "verb": "dispatch", "kind": "policy",
         "settings": ["policy.auto_dispatch_priority", "policy.auto_dispatch_modes"],
         "instruction": "Der Agent wird gestartet (idempotent - eine laufende Karte "
                        "nimmt ihre Position wieder auf)."},
        {"from": "working", "to": "review", "verb": "submit", "kind": "fixed",
         "settings": [],
         "instruction": "Aufräumen + Commit, dann der Gate. Danach wird der Merge nur "
                        "KLASSIFIZIERT (dry-run) - die Karte bleibt mit dem Befund auf Review."},
        {"from": "review", "to": "working", "verb": "bounce", "kind": "fixed",
         "settings": [],
         "instruction": "Der Mensch schickt die Karte zurück - als 'bounce' in der "
                        "Ökonomie verbucht."},
        {"from": "review", "to": "done", "verb": "accept", "kind": "policy",
         "settings": ["policy.auto_accept_green"],
         "instruction": "Der bewusste Zug nach Done merged wirklich und fährt den "
                        "Deploy-Hook. Idempotent: eine gelandete Karte wird nie erneut "
                        "gegatet oder gemerged."},
    ],
    "gate": {"key": "gate", "default_label": "Quality Gate", "kind": "fixed",
             "between": ["working", "review"], "settings": [],
             "instruction": "Gate-before-review ist ein fixes Harness-Gesetz: kein Review "
                            "ohne bestandenen Gate. Das Ergebnis geht append-only ins "
                            "Audit-Log.",
             "why": "Fix, weil eine Abnahme sonst nur eine Meinung wäre. Das Ergebnis "
                    "wird append-only protokolliert und kann nicht nachträglich "
                    "geschönt werden."},
}


def flow(lane_labels=None):
    """The lane/gate machine as data, with the owner's lane renames applied.

    `label` resolves policy.lane_labels over the built-in default, so the UI never
    has to know that renaming is a thing - it just renders `label`."""
    ll = lane_labels or {}
    out = {"nodes": [], "edges": [dict(e) for e in LANE_FLOW["edges"]],
           "gate": dict(LANE_FLOW["gate"])}
    # file:line for every node, read out of THIS file - see loop_state._decl_lines
    # for why it is derived rather than written down.
    try:
        import sys as _sys
        _tools = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
        if _tools not in _sys.path:
            _sys.path.insert(0, _tools)
        from loop_state import _decl_lines
        src = _decl_lines([n["key"] for n in LANE_FLOW["nodes"]] + [LANE_FLOW["gate"]["key"]],
                          path=os.path.abspath(__file__), rel="daemon/sessions.py")
    except Exception:                                        # noqa: BLE001
        src = {}
    for n in LANE_FLOW["nodes"]:
        n = dict(n)
        n["label"] = ll.get(n["key"], n["default_label"])
        n["source"] = src.get(n["key"], "daemon/sessions.py")
        out["nodes"].append(n)
    out["gate"]["label"] = out["gate"]["default_label"]
    out["gate"]["source"] = src.get(LANE_FLOW["gate"]["key"], "daemon/sessions.py")
    return out


# -- public API ----------------------------------------------------------

def list_tracks():
    return _load()

def get_track(tid):
    return _find(_load(), tid)

def new_track(repo, branch, task, perm=DEFAULT_PERM, lane="working", client="",
              value=None, driver="claude", actor="owner", priority="medium", due="",
              model="", attachments=None, project_id=None, billing="fixed", rate=None,
              description=""):
    """File a request. lane=backlog stores it un-started (no worktree, no session);
    lane=working starts the branch session immediately. value = what the
    deliverable is worth (settings default when omitted) - set at intake so
    margin is computable at acceptance. project_id assigns the card to a
    fixed-price/T&M project (projects.py); its own `value` then stops feeding
    the totals - the project's billing does (events.metrics)."""
    import events, turnopts
    repo = os.path.abspath(repo)
    tracks = _load()
    tid = _unique_id(_slug(branch))
    run_dir = os.path.join(REC, tid)
    os.makedirs(run_dir, exist_ok=True)
    # attachments filed with the request are saved now; the first run reads them.
    # model chosen in the composer becomes the card's execution model (Auto too).
    att_paths = turnopts.save_attachments(run_dir, attachments)
    # Auto routing sees the card's own facts (value/priority); an explicit model
    # from the composer still wins (resolve_model only routes for "auto").
    cli_model, _ = turnopts.resolve_model(model, task, bool(att_paths),
        signals={"value": value, "priority": priority})
    t = {"id": tid, "repo": repo, "branch": branch, "worktree": "", "task": task,
         "dev_port": None,     # reserved at dispatch (_alloc_dev_port), sticky
         # task = the one-line title (Jira summary); description = the long body
         # (Jira/Plane description). Both editable; the agent reads title+desc+files.
         "description": description or "",
         "client": client, "session_id": None, "perm": perm, "lane": "backlog",
         "status": "queued", "turns": 0, "run_dir": run_dir, "last_reply": "",
         "value": float(value) if value is not None else events.settings()["value_per_card"],
         "driver": driver or "claude", "priority": priority or "medium", "due": due or "",
         "rank": None, "model": cli_model or "", "attachments": att_paths,
         "project_id": project_id or None,
         # billing (per card): fixed = `value` is the agreed price, recognized on
         # done; tm = worked hours (time_in_work) x `rate`, accrues live; none =
         # internal/unbilled (contributes 0). A card is billed on its own; a
         # process groups cards into one SoW rollup (events.metrics).
         "billing": billing if billing in ("fixed", "tm", "none") else "fixed",
         "rate": float(rate) if rate is not None else None,
         "ai_cost": 0.0, "tokens_in": 0, "tokens_out": 0, "models": [],
         "created": time.strftime("%Y-%m-%d %H:%M:%S"),
         "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
    from actionlog import ActionLog
    ActionLog(run_dir).log("note", "REQUEST filed: %s (branch %s)" % (task, branch))
    events.emit("filed", tid, branch=branch, value=t["value"], actor=actor, driver=t["driver"])
    _save_track(t)
    if lane == "working":
        t = _start(tid)
    return t

def _dispatch_failed(t, e):
    """Dispatch runs on a background thread, so an uncaught exception is
    invisible - the card must carry the error itself: status=bounced,
    the failure in last_reply, a note in the flight recorder, an event."""
    import events
    err = "DISPATCH FAILED: %s" % e
    from actionlog import ActionLog
    try:
        log = ActionLog(t["run_dir"])
        log.log("note", err[:2000])
        log.log("turn", "Turn fehlgeschlagen", event="failed", error=str(e)[:500])
    except Exception:
        pass
    events.emit("error", t["id"], where="dispatch", detail=str(e)[:600])

    def _fail(tt):
        tt["status"] = "bounced"
        tt["last_reply"] = err[:2000]
    _mutate(t["id"], _fail)

def _start(tid):
    """Dispatch a backlog request: create the worktree + open its coding session."""
    tracks = _load()
    t = _find(tracks, tid)
    if not t:
        raise RuntimeError("no such track: " + tid)
    if t["session_id"]:
        return t
    try:
        return _start_inner(t)
    except Exception as e:
        _dispatch_failed(t, e)
        raise

def _ensure_worktree(t):
    """Make sure the card's worktree EXISTS, (re)creating it from the branch if
    needed, and return its path. The worktree is regenerable state (the branch
    holds the commits) - so a missing directory must never be a hard error:
    dispatch uses this, and steer SELF-HEALS through it instead of dying with
    WinError 267 (spawn cwd invalid) when the tree is gone (reclaimed, cleaned
    by hand, or never created because a bad branch name broke dispatch).

    A path existing is NOT proof it is a working worktree: `git worktree add`
    can be interrupted after it creates the directory but before it finishes
    (or something else mkdir'd the slot first), leaving a plain folder that was
    never `git init`'d into a worktree. Dispatching an agent into that folder
    lets every git command inside the turn fail with 'not a git repository' -
    the failure surfaces deep in the turn, not here, so it looked unrelated
    until traced back. _git_state_broken is the same check reclaim already
    trusts to judge a worktree's git link; reuse it here so a broken/never-init
    slot gets rebuilt before dispatch instead of handed out as-is."""
    wt = _worktree_for(t["repo"], t["branch"])
    existing = _worktree_of_branch(t["repo"], t["branch"])
    if existing and os.path.isdir(existing):
        return existing                     # reuse a prior checkout (e.g. legacy dir)
    if os.path.exists(wt) and _owned_worktree(wt) and _git_state_broken(wt):
        _git_try(t["repo"], "worktree", "remove", "--force", wt)
        if os.path.isdir(wt):
            shutil.rmtree(wt, ignore_errors=True)
    if not os.path.exists(wt):
        _git_try(t["repo"], "worktree", "prune")   # drop a stale registration of this path
        if _branch_exists(t["repo"], t["branch"]):
            _git(t["repo"], "worktree", "add", wt, t["branch"])
        else:
            # Explicit base + --no-track (Paseo): never branch off whatever HEAD
            # happens to be, and never let the card branch claim an upstream.
            _git(t["repo"], "worktree", "add", wt,
                 "-b", t["branch"], "--no-track", _base_ref(t["repo"]))
        _seed_worktree(t["repo"], wt)
    return wt


def _start_inner(t):
    if t.get("machine"):
        return _start_machine(t)
    tid = t["id"]
    wt = _ensure_worktree(t)
    from actionlog import ActionLog
    log = ActionLog(t["run_dir"])
    log.log("note", "DISPATCHED -> branch %s" % t["branch"])
    log.log("steer", t["task"])
    log.log("turn", "Turn gestartet", event="started")
    import events
    events.emit("lane", tid, frm=t.get("lane"), to="working")

    port = t.get("dev_port") or _alloc_dev_port(exclude_tid=tid)

    def _begin(tt):
        tt["worktree"] = wt; tt["lane"] = "working"; tt["status"] = "running"
        if port:
            tt["dev_port"] = port
    t = _mutate(tid, _begin) or t
    prompt = t["task"]
    if t.get("description"):              # the long-form body (Jira-style)
        prompt += "\n\n" + t["description"]
    if t.get("attachments"):             # files filed with the request
        prompt += "\n\nAttached files (read them as needed): " + ", ".join(t["attachments"])
    sid, result, meta = _turn(t, prompt)
    t, reason = _finish_turn(tid, sid, result, meta, log)
    import notify
    notify.card_event(t, reason)
    return t


# -- MACHINE tasks: the board reaches the PC, not just the repo --------------
# A machine card is a card whose workplace is a REAL directory on this Windows
# machine instead of a git worktree - the shape adopt_session(mode="continue")
# already used, made first-class so the chat can DELEGATE anything that isn't
# repo work ("open X", "sort these files", "why is the printer offline") instead
# of refusing it. The chat still executes nothing itself; it dispatches the
# agent that does, exactly like resolve_conflict dispatches a worker to edit.
#
# What is deliberately NOT weakened: auth (owner-gated at the chat action),
# audit (filed/turn/done events + the flight recorder, same as any card),
# economics (every turn priced), and gate-before-review - a machine card has no
# branch and NEVER merges to main, so the code-landing gate is untouched. Its
# gate is the owner's own accept, which is the stricter human one.

MACHINE_BRANCH = "(machine)"


def machine_policy():
    """Owner policy for machine tasks. Defaults are permissive-for-the-owner by
    design (it is his own PC, and a blocked chat is the bug we are fixing);
    house rules may RESTRICT - never the other way round, per the charter.
      policy.machine {enabled, roles, roots, perm}
        enabled: false switches the capability off entirely
        roles:   who may dispatch machine work (default owner only)
        roots:   [] = the whole machine; else allowed parent directories
        perm:    driver permission mode (headless needs bypassPermissions to be
                 able to run commands at all - an unanswerable prompt IS a block)"""
    import events
    p = dict((events.settings().get("policy") or {}).get("machine") or {})
    p.setdefault("enabled", True)
    p.setdefault("roles", ["owner"])
    p.setdefault("roots", [])
    p.setdefault("perm", "bypassPermissions")
    return p


def machine_root_ok(cwd):
    """(ok, reason). Empty roots = the whole PC is in scope (the default)."""
    roots = machine_policy().get("roots") or []
    if not roots:
        return True, ""
    c = os.path.normcase(os.path.abspath(cwd))
    for r in roots:
        r = os.path.normcase(os.path.abspath(r))
        if c == r or c.startswith(r + os.sep):
            return True, ""
    return False, ("'%s' liegt ausserhalb der erlaubten Ordner (policy.machine.roots: %s)"
                   % (cwd, ", ".join(roots)))


def new_machine_task(cwd, task, actor="owner", priority="medium", description="",
                     dispatch=True, driver="claude-desktop", value=None, model=""):
    """File (and by default start) a task that runs ON THIS MACHINE in `cwd`.
    Same card, same audit, same economics - only the workplace differs.

    Driver defaults to claude-desktop (windows-mcp + screen-recording), NOT plain
    claude: a machine task's whole point is to control this PC/browser, so the
    agent MUST have the GUI/browser tools. With the plain `claude` driver it can
    only read/write files and ends up talking instead of acting - exactly how the
    "open Chrome, log into Play Console, upload the AAB" card drifted and stuck."""
    import events
    pol = machine_policy()
    if not pol.get("enabled", True):
        raise RuntimeError("machine tasks are switched off (policy.machine.enabled=false)")
    # a machine task with a driver that lacks windows-mcp is toolless by
    # construction; fall back to claude-desktop rather than silently strand it.
    dcfg = (events.settings().get("drivers") or {}).get(driver) or {}
    if "mcp__windows-mcp__*" not in (dcfg.get("allowed_tools") or []):
        driver = "claude-desktop"
    cwd = os.path.abspath(os.path.expandvars(os.path.expanduser(cwd or os.path.expanduser("~"))))
    if not os.path.isdir(cwd):
        raise RuntimeError("no such directory on this machine: %s" % cwd)
    ok, why = machine_root_ok(cwd)
    if not ok:
        raise RuntimeError(why)
    t = new_track(cwd, MACHINE_BRANCH, task, lane="backlog", actor=actor,
                  priority=priority, description=description, driver=driver,
                  value=value, model=model, perm=pol.get("perm", "bypassPermissions"))
    def _mark(tt):
        tt["machine"] = True
        tt["worktree"] = cwd         # the driver's cwd - a real folder, no worktree
    cur = _mutate(t["id"], _mark) or t
    from actionlog import ActionLog
    ActionLog(cur["run_dir"]).log("note", "MACHINE task filed - workplace %s (by %s)" % (cwd, actor))
    events.emit("machine", cur["id"], action="filed", cwd=cwd, actor=actor)
    if dispatch:
        return move_lane(cur["id"], "working", actor=actor)
    return cur


def _start_machine(t):
    """Dispatch a machine card: no worktree, no branch - just open the session in
    its directory and run the first turn there."""
    import events
    tid = t["id"]
    cwd = t.get("worktree") or t.get("repo")
    if not cwd or not os.path.isdir(cwd):
        raise RuntimeError("machine task has no working directory: %r" % cwd)
    from actionlog import ActionLog
    log = ActionLog(t["run_dir"])
    log.log("note", "DISPATCHED (machine) -> %s" % cwd)
    log.log("steer", t["task"])
    log.log("turn", "Turn gestartet", event="started")
    events.emit("lane", tid, frm=t.get("lane"), to="working")

    def _begin(tt):
        tt["worktree"] = cwd; tt["lane"] = "working"; tt["status"] = "running"
    t = _mutate(tid, _begin) or t
    prompt = t["task"]
    if t.get("description"):
        prompt += "\n\n" + t["description"]
    if t.get("attachments"):
        prompt += "\n\nAttached files (read them as needed): " + ", ".join(t["attachments"])
    sid, result, meta = _turn(t, prompt)
    t, reason = _finish_turn(tid, sid, result, meta, log)
    import notify
    notify.card_event(t, reason)
    return t


# -- the card's RESULT, persisted at accept -----------------------------------
# The snapshot only surfaced last_reply while a card was needs_you; once
# accepted, its result text vanished from the PM's view - so an owner decision
# the card's final reply had long answered resurfaced as "open" in the plan
# triage. Folded into the track at EVENT TIME (the accept) by the two accept
# mutators (move_lane / _accept_machine) - the one place a card finishes.
_DELIVERED_RE = re.compile(r"\bDELIVERED\b[:\s*-]*", re.I)
# The brief's fixed hand-off sentence ("Ready for Review - ...") is board
# choreography, not a result - strip it and everything after.
_READY_TAIL_RE = re.compile(r"ready for review\b.*", re.I | re.S)

def extract_outcome(reply):
    """A 1-2 line result sentence from a card's final reply: the agent's
    DELIVERED summary (harness/agents/card-worker.md convention, same anchor ask.py keys
    off) when present, else the reply's first lines. '' when nothing usable."""
    text = (reply or "").strip()
    if not text:
        return ""
    m = _DELIVERED_RE.search(text)
    for cand in ([text[m.end():]] if m else []) + [text]:
        lines = [l.strip(" \t*-#") for l in _READY_TAIL_RE.sub("", cand).splitlines()]
        lines = [l for l in lines if l]
        if lines:
            return " ".join(lines[:2])[:240]
    return ""


def _record_outcome(tt):
    """Runs INSIDE the accept mutators. Keeps an existing outcome when the
    final reply yields nothing (e.g. a re-accept after a silent lane fix)."""
    out = extract_outcome(tt.get("last_reply"))
    if out:
        tt["outcome"] = out


# Pays debt [legacy-outcome-on-read]. Cards accepted BEFORE the outcome field
# existed never ran _record_outcome, so their result must be reconstructed from
# the frozen last_reply ONCE (daemon start) instead of re-derived on every
# snapshot read. extract_outcome demonstrably misfires on multi-sentence
# replies - a reply that OPENS with an aside stamps the aside as the result
# (the chatfork card led with "Verstanden fuer naechstes Mal..." instead of
# the actual answer). So this backfill was NOT adopted blindly: an agent
# reviewed ALL 44 legacy done cards against their full final replies
# (2026-08-12, card chat-fix--sessions-extract-ou). Where the heuristic hit
# the core, its value is used; the misses below carry a hand-written outcome.
# "" = the reply holds no result at all (cancelled turn, usage-limit banner,
# lost context) - better an empty line than a nonsense one.
_OUTCOME_BACKFILL_REVIEWED = {
    "20260811-153456-chatfork":
        "Kailashs Tester-Zusage steht: seine Gruppe appclosedtesting@googlegroups.com "
        "ist neben helmdeck-testers in der Play Console eingetragen und zur "
        "Google-Pruefung eingereicht; Opt-in-Link fuer seine 63 Tester verschickt "
        "(bis zu 91 Tester gesamt).",
    "20260728-232103-req-zombie-running-status":
        "Startup zombie sweep shipped (b69c141, e9e6698): sessions.sweep_zombies + "
        "drivers.has_session clear stale 'running' cards on daemon start, with test.",
    "20260728-205508-night-pay-debt-nightshift":
        "Limit-signal fix prepared in the worktree (driver signal patch, debt flip, "
        "tests, workorder); python/git were permission-gated in that session, so "
        "verify+commit were handed to the owner/harness.",
    "20260728-095049-req-dispatch-failure-is-invi":
        "Dispatch failure is visible now: filing a card against a non-git folder "
        "returns an immediate 'repo is not a git repository' error instead of a "
        "silent backlog fallback (7a4c9e7, test_dispatch_visibility.py green).",
    "20260728-094539-req-add-headless-unit-tests":
        "Driver unit tests rewritten against the streaming _ClaudeSession (new "
        "stream-events fixture, stale one removed), committed 1260272; "
        "pytest tests/unit -> 35 passed, fully headless.",
    "20260727-220243-adopt-34656ce4":
        "Kartenansicht auf Overview-first umgebaut: Tab 'Overview' (Status-Chips, "
        "Description zuerst, Worker-Digest, editierbare Felder + Rewind), Tab 'Chat' "
        "mit Transkript+Composer; der APK-Build blieb permission-blockiert.",
    "20260728-094539-req-confirm-legacy-8140-fal":
        "Legacy :8140 UI is a pure redirect now: /, /classic, /recorder, /dashboard "
        "all 302 to the :3300 web UI, old templates deleted, auth intact (/tracks "
        "still 401); merge conflicts resolved marker-free.",
    "20260728-094539-req-one-command-check-script":
        "tools/check_all.sh mirrors the loop in one command (compile+tsc+lint+unit, "
        "8 checks green), repointed at app/ after the Expo cutover; test_drivers.py "
        "conflict resolved by taking expo-migration's superset (482e0ec).",
    "20260803-222549-chat-pm-coordinator-resilienc":
        "PM coordinator resilience shipped: on a blocker/bounce the PM classifies, "
        "delegates a fix and re-submits (2 tries) before escalating with an unblock "
        "proposal; closing debt.py conflict resolved (7b467c2, gate PASS).",
    "20260803-004026-pm-relay-pairing-hardening":
        "Relay pairing hardening landed: deterministic pairing-code lifecycle + "
        "reconnect/backoff, pinned by the pairing-lifecycle suite (gate 6/6 on the "
        "merged tree); final merge with main was a semantic no-op, resolved marker-free.",
    "20260728-094539-req-remove-committed-google":
        "Assessment: the committed Google service-account key is a live, non-expiring "
        "credential in git history since 2024-05-23; repo is private (3 collaborators) "
        "and nothing references it, but it must be revoked in GCP IAM.",
    "20260803-212935-pm-launch-karten-auf-mode-a":
        "Root cause: same-second card-id collision - INSERT OR REPLACE silently "
        "overwrote the first card (audit + economics lost). Fixed via "
        "sessions._unique_id (9297069); the 'unresolved conflict' was gate "
        "flakiness from that bug, gate now PASS (9).",
    "20260803-233536-pm-store-listing-paket-date":
        "Store listing package intact (docs/store/* + privacy page in relay.py); "
        "chat.tsx conflict resolved by combining main's ChatBody structure with the "
        "i18n fix, 5 merged-in untranslated strings fixed; i18n lint 699 keys PASS, "
        "gate 14/14.",
    "20260804-090522-pm-mode-wert-an-die-policy":
        "Refused as written, with proof: rewriting mode on accepted cards would "
        "falsify the measured automation ratio, and the premise was a misdiagnosis "
        "(shown from the event log) - 'auto' is a completion statistic, not a "
        "dispatch mode. Gate PASS (14).",
    "20260806-190555-paseo-p1-runtime":
        "P1 Runtime-Haertung geliefert (c770ef8); die vier Gate-Bounces entlarvten "
        "einen Harness-Bug: gate_failed wird nie persistiert, darum erreichte der "
        "Gate-Output den Worker strukturell nie (betrifft auch merge_report und "
        "Modell-Eskalation).",
    "20260806-190555-paseo-p2-notify":
        "P2 notify shipped (41fa92a); self-review fixed 4 more defects: auto-accept "
        "could merge a still-asking card (now sessions.is_delivered), PM push "
        "bypassed the presence policy, injected prompts rendered as owner messages, "
        "bg watcher ran inline.",
    "20260803-002954-stream-backend": "",
    "20260808-053628-req-fix-dashboard-zu-berf": "",
    "20260808-160412-machine": "",
}


def backfill_outcomes():
    """One-shot outcome backfill for pre-outcome done cards, run at daemon
    start (next to apply_board_directives - same repo-data-applied-once shape).
    KEY PRESENCE marks a migrated card, so '' is a valid stamped outcome and
    each card is visited exactly once across restarts. Reviewed overrides beat
    the heuristic; everything else takes extract_outcome(last_reply). New
    accepts persist their outcome at event time and are never touched here."""
    stamped = 0
    for t in _load():
        if t.get("lane") != "done" or "outcome" in t:
            continue
        tid = t["id"]
        out = _OUTCOME_BACKFILL_REVIEWED.get(tid)
        if out is None:
            out = extract_outcome(t.get("last_reply"))

        def _stamp(tt):
            if "outcome" in tt:
                return False   # lost the race to an accept mutator - theirs wins
            tt["outcome"] = out
        if _mutate(tid, _stamp) is not None:
            stamped += 1
    return stamped


def _accept_machine(t, lane, actor, log):
    """Review/Done for a machine card. There is no branch to gate or merge, so
    Review RESTS it for the owner to judge and Done records the acceptance
    economics. The repo deploy hook does NOT run (nothing landed in a repo)."""
    import events
    if lane == "review":
        log.log("note", "REVIEW (machine): erledigt auf dem Rechner - wartet auf deine Abnahme.")

        def _submit(tt):
            tt["status"] = "submitted"; tt["lane"] = "review"
            tt["review_report"] = ("Maschinen-Aufgabe - kein Branch, kein Merge. Pruefe das "
                                   "Ergebnis auf dem Rechner und nimm die Karte ab.")
        t = _mutate(t["id"], _submit) or t
        _say_card(t, _i18n.t("say.machineReview"))
        return dict(t, review_preview=True, merge_kind="machine")
    events.emit("touch", t["id"], touch="review", actor=actor)
    te = [e for e in events.read_events() if e.get("track") == t["id"]]
    mode = events._completion_mode(te, t.get("turns"))
    events.emit("done", t["id"], mode=mode, ai_cost=t.get("ai_cost", 0.0),
                value=t.get("value"), models=t.get("models", []),
                tokens_in=t.get("tokens_in", 0), tokens_out=t.get("tokens_out", 0))
    events.emit("machine", t["id"], action="accepted", cwd=t.get("worktree") or "", actor=actor)
    log.log("note", "ACCEPTED (machine, %s) - AI $%.4f, value %s"
            % (mode, t.get("ai_cost", 0.0), t.get("value")))

    def _accept(tt):
        tt["status"] = "accepted"; tt["mode"] = mode; tt["lane"] = "done"
        _record_outcome(tt)
    t = _mutate(t["id"], _accept) or t
    events.emit("lane", t["id"], frm="review", to="done")
    _say_card(t, _i18n.t("say.machineAccepted"))
    import notify; notify.card_event(t, "done")
    try:
        import pm; pm.on_card_done(t["id"])   # re-judge the golden triangle at event time
    except Exception:
        pass
    return t


# -- the review gate: work may only reach the client when it is green ----

# tools/run_gate.py's own success sentinels ("gate: PASS (34 checks)" or the
# no-checks-on-this-branch case) - the ground truth for _gate()'s exit-code
# cross-check below.
_GATE_PASS_RE = re.compile(r"gate: (PASS \(\d+ checks\)|nothing to run on this branch - PASS)")

def _gate(t):
    """Quality gate run when a card is submitted for review. Checks: (1) the
    worktree exists and its work is committed; (2) if the repo declares its own
    gate (a `helmdeck.gate` file holding a shell command - the harness's
    standard), it must exit 0. Returns (ok, problems)."""
    problems = []
    wt = t.get("worktree")
    if not wt or not os.path.exists(wt):
        return False, ["never dispatched - nothing to submit"]
    # A RECLAIMED worktree leaves the directory behind but empty and unlinked
    # from git: reclaim_worktree deletes the contents, and on Windows the
    # now-empty dir often survives because a shell still holds it open ("WORKTREE
    # nicht entfernbar (gesperrt?)"). os.path.exists then still says yes, so
    # without this check the gate command runs inside an empty dir and reports
    # "can't open file ...: No such file or directory" once per test - a punch
    # list that reads like a catastrophic code failure but only means the tree
    # is gone. Say what actually happened.
    if not os.path.exists(os.path.join(wt, ".git")):
        return False, ["worktree reclaimed (no .git at %s) - nothing to gate. A card "
                       "whose work already landed needs no re-accept; otherwise "
                       "re-dispatch it so the tree is rebuilt from the branch." % wt]
    try:
        dirty = _git(wt, "status", "--porcelain")
        if dirty:
            problems.append("uncommitted changes:\n" + dirty[:400])
    except Exception as e:
        problems.append("git status failed: %s" % e)
    # The gate command is defined by the REPO (main) - authoritative, so EVERY
    # card is verified with the current gate even on an old branch - and it is run
    # by the DAEMON (full command access), so the agent's permission mode never
    # blocks the tests. Fall back to the worktree's own gate file if main has none.
    gate_file = os.path.join(t.get("repo") or wt, "helmdeck.gate")
    if not os.path.exists(gate_file):
        gate_file = os.path.join(wt, "helmdeck.gate")
    if os.path.exists(gate_file):
        with open(gate_file, encoding="utf-8") as f:
            cmd = f.read().strip()
        if cmd:
            # Run in the worktree (cwd = the code under test), but expose the MAIN
            # checkout as %HELMDECK_REPO% so the gate can invoke the CURRENT gate
            # script from main - old branches don't carry tools/run_gate.py.
            genv = dict(os.environ, HELMDECK_REPO=t.get("repo") or wt)
            r = subprocess.run(cmd, cwd=wt, shell=True, capture_output=True,
                               text=True, timeout=600, env=genv)
            # Observed on the live board (card 20260812-164257): a `py -3.12`
            # gate run via shell=True on Windows can come back with a nonzero
            # r.returncode while its OWN stdout is a clean tools/run_gate.py
            # verdict - every check "ok", ending "gate: PASS (34 checks)" - a
            # shell/launcher exit-code hiccup downstream of the script's own
            # sys.exit(0), not a real failure. Root cause not pinned (no
            # AutoRun hook, reproduces clean when replayed by hand) - see debt
            # [gate-exit-code-vs-stdout-verdict]. run_gate.py's own verdict
            # line is a REAL signal (the process that printed it did finish
            # its checks), so prefer it over a returncode that contradicts it;
            # still hard-fail whenever the verdict itself is missing or red.
            out = (r.stdout + "\n" + r.stderr).strip()
            if r.returncode != 0 and (_GATE_PASS_RE.search(out) and "=== GATE FAILED (" not in out):
                print("GATE: returncode %d disagreed with the script's own PASS verdict for %s "
                      "- trusting the verdict (see debt gate-exit-code-vs-stdout-verdict)"
                      % (r.returncode, t.get("id")))
            elif r.returncode != 0:
                # Lead with the ACTUAL error, not the command - the command alone
                # (truncated on mobile) is the "ominous, unresolvable" message. An
                # empty output means the command couldn't even start (missing
                # interpreter/tool); say so with the exit code instead of nothing.
                detail = out[-1200:] if out else "(no output - command could not run; exit %d)" % r.returncode
                problems.append("gate FAILED:\n%s\n\n(gate command: %s)" % (detail, cmd[:120]))
    return (not problems), problems

def _merge_to_main(t):
    """Land an accepted card: CLASSIFY it, then merge its branch into the repo's
    MAIN checkout. Runs in t['repo'] (the daemon's checkout, which holds the
    secrets the worktree never sees), NOT in the agent's worktree.

    Returns (accept_ok, kind, message):
      accept_ok True  -> the card may be accepted/closed:
        already_merged        - branch's work is already fully in main (redundant
                                / superseded); nothing to land.
        redundant_uncommitted - same, but the worktree still holds uncommitted
                                changes that were therefore NOT included (warned).
        merged                - real commits landed on main.
      accept_ok False -> the card is bounced with a clear reason:
        conflict              - branch conflicts with main; the conflicting files
                                and a resolve path are reported. Main is left
                                exactly as found (merge --abort).
        blocked               - can't even attempt (no repo / detached / on branch).

    A dirty tree is NOT pre-refused: real project repos keep tracked runtime output
    perpetually 'modified' and git merges into them fine unless the merge touches
    those files - so we let git decide."""
    repo = t.get("repo"); branch = t.get("branch"); wt = t.get("worktree")
    if not repo or not os.path.isdir(repo):
        return False, "blocked", "card has no repo checkout to merge into"
    if not branch:
        return False, "blocked", "card has no branch"
    try:
        cur = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    except Exception as e:
        return False, "blocked", "repo is not a git checkout: %s" % e
    if cur == "HEAD":
        return False, "blocked", "main checkout is in detached HEAD - checkout the base branch first"
    if cur == branch:
        return False, "blocked", "main checkout is ON the card branch (%s) - switch it to the base branch" % branch
    # how many committed commits does the branch add that main lacks?
    try:
        ahead = int(_git(repo, "rev-list", "--count", "HEAD..%s" % branch) or "0")
    except Exception as e:
        return False, "blocked", "cannot compare branch to main: %s" % e
    if ahead == 0:
        # branch content already in main -> nothing to land (redundant/superseded)
        dirty = ""
        if wt and os.path.isdir(wt):
            try:
                dirty = _git(wt, "status", "--porcelain")
            except Exception:
                dirty = ""
        if dirty:
            n = len(dirty.splitlines())
            return True, "redundant_uncommitted", (
                "Redundant: der Branch bringt nichts Neues nach main - die Arbeit ist "
                "bereits enthalten. %d uncommittete Worktree-Aenderung(en) wurden NICHT "
                "uebernommen (nie committet); falls noch gebraucht: committen und neu "
                "einreichen:\n%s" % (n, dirty[:200]))
        return True, "already_merged", (
            "Redundant/erledigt: die Arbeit ist bereits vollstaendig in main - nichts zu mergen.")
    # real work to land
    try:
        _git(repo, "merge", "--no-ff", branch, "-m",
             "HelmDeck accept: %s (%s)" % (branch, t.get("id", "")))
        return True, "merged", "%d Commit(s) sauber nach main (%s) gemergt." % (ahead, cur)
    except Exception as e:
        conflicts = ""
        try:
            conflicts = _git(repo, "diff", "--name-only", "--diff-filter=U")
        except Exception:
            pass
        try:
            _git(repo, "merge", "--abort")   # leave main exactly as found
        except Exception:
            pass
        files = conflicts or (str(e)[:200])
        return False, "conflict", (
            "Merge-Konflikt mit main - main hat sich weiterbewegt und aendert dieselben "
            "Stellen. Konfliktdateien:\n%s\nAufloesen: steuere den Agenten mit "
            "\"merge main in deinen Branch und loese die Konflikte, dann committen\" und "
            "reiche neu ein (der Worktree bleibt die sichere Sandbox)." % files)


def _git_try(repo, *args):
    """Run git, return (returncode, stdout, stderr) without raising."""
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _current_branch(repo):
    """Name of the checked-out branch, with Paseo's rebase-HEAD guard
    (checkout-git.ts getRebaseHeadBranch): during a rebase `rev-parse
    --abbrev-ref HEAD` says just 'HEAD' (the rebase detaches), which callers
    would misread as 'no base branch' and bounce dispatch/reclaim mid-rebase.
    Recover the branch actually being rebased from rebase-merge/head-name or
    rebase-apply/head-name. Genuinely detached -> 'HEAD' (callers already
    treat that as blocked)."""
    rc, out, _ = _git_try(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0:
        # UNBORN branch (fresh repo, no commit): rev-parse has no commit to
        # abbreviate, but symbolic-ref still names the branch - _base_ref then
        # reports 'no commits yet' instead of a misleading 'detached'.
        rc2, name, _ = _git_try(repo, "symbolic-ref", "--short", "HEAD")
        return name if rc2 == 0 else ""
    if out != "HEAD":
        return out
    for rel in ("rebase-merge/head-name", "rebase-apply/head-name"):
        rc2, p, _ = _git_try(repo, "rev-parse", "--git-path", rel)
        if rc2 != 0 or not p:
            continue
        fp = p if os.path.isabs(p) else os.path.join(repo, p)
        try:
            with open(fp, encoding="utf-8") as f:
                name = f.read().strip()
        except OSError:
            continue
        if name:
            return name[len("refs/heads/"):] if name.startswith("refs/heads/") else name
    return out


# -- WORKTREE RECLAMATION (the second half of the isolation law) --------------
# HelmDeck's charter gives every card its own git worktree+branch so parallel
# cards never collide - a real edge over Paseo, which runs one agent in one
# shared directory. But isolation with no RECLAIM just piles up dead trees:
# accepted/archived cards left 25 orphaned worktrees behind ("System too full").
# Paseo stays clean only because it never makes worktrees at all. So we close the
# loop: when a card reaches a terminal state its tree goes back to the pool.

def reclaim_worktree(t, log=None, force=False):
    """Give ONE finished card's worktree (and branch) back. Called on a terminal
    transition (accepted/archived): the work is already in the integration
    branch, so the tree and branch are safe to drop. Never touches the primary
    checkout, and KEEPS any tree that still has modified TRACKED files unless
    force (nothing uncommitted is ever lost - untracked build noise doesn't
    count). Best-effort: a git hiccup never breaks the accept/archive."""
    repo, wt, br = t.get("repo"), t.get("worktree"), t.get("branch")
    if not repo or not wt or not os.path.isdir(wt):
        return False
    if os.path.abspath(wt) == os.path.abspath(repo):
        return False                       # never the main checkout
    if not force:
        rc, out, _ = _git_try(wt, "status", "--porcelain", "--untracked-files=no")
        if rc == 0 and out:
            if log:
                log.log("note", "WORKTREE behalten - uncommittete Aenderungen in %s" % wt)
            return False
    _git_try(repo, "worktree", "remove", "--force", wt)
    if os.path.isdir(wt) and _owned_worktree(wt):
        # git refused (admin dir already gone, repo moved, broken .git file).
        # Ownership is proven by the PATH SHAPE, so the reclaim survives broken
        # git state (Paseo deletePaseoWorktree: rm falls through when `worktree
        # remove` fails). The dirty check above already ran its veto.
        shutil.rmtree(wt, ignore_errors=True)
    if os.path.isdir(wt):                   # remove refused (locked?) - leave it be
        if log:
            log.log("note", "WORKTREE nicht entfernbar (gesperrt?): %s" % wt)
        return False
    integ = _current_branch(repo)
    if br and br not in ("main", "master") and integ != br:
        # Delete the branch ONLY if it is merged into the integration branch -
        # an archived-but-unmerged card keeps its branch so its commits survive
        # (the worktree is regenerable from the branch; unmerged commits are not).
        if integ and _git_try(repo, "merge-base", "--is-ancestor", br, integ)[0] == 0:
            _git_try(repo, "branch", "-D", br)
        elif log:
            log.log("note", "BRANCH behalten - nicht gemergt: %s (Worktree entfernt, Commits bleiben)" % br)
    _git_try(repo, "worktree", "prune")
    if log:
        log.log("note", "WORKTREE zurueckgeholt: %s (branch %s) - Arbeit ist gelandet." % (wt, br))
    return True


def sweep_worktrees():
    """Startup backstop + one-shot cleanup: reclaim EVERY merged, clean card
    worktree across the repos we know. Complements the per-card reclaim by
    catching trees left by builds from before reclamation existed.

    NOT independent of card status (despite what this docstring used to
    claim - found live 2026-08-14, a real data-loss bug): a branch can be
    merged (an earlier commit landed, e.g. via fast-track) while its CARD is
    still open on the board and actively being steered - this git-only check
    tore an in-progress COWORK card's live worktree out from under it
    (deregistered .git, deleted most files, orphaned a live eas-cli/Chrome
    process's locked files as an empty app/ husk) while the owner was mid-
    conversation with it. reclaim_worktree (the per-card path, called only on
    accept/archive) was always correctly scoped; this backstop was not.
    A worktree currently referenced by a NON-terminal card (not archived, not
    in the done lane) is now kept regardless of git's merge verdict - "is
    anyone still using this" is the daemon's own fact, and it must win over
    what git alone can see. Returns the number reclaimed."""
    tracks = _load()
    repos = {t.get("repo") for t in tracks if t.get("repo")}
    referenced = {os.path.realpath(t["worktree"]) for t in tracks if t.get("worktree")}
    # path -> is this card still ACTIVE (open, non-terminal)? Only paths NOT
    # in this set (or mapped to False) are eligible for reclaim below.
    active_by_path = {}
    for t in tracks:
        if not t.get("worktree"):
            continue
        p = os.path.realpath(t["worktree"])
        terminal = bool(t.get("archived")) or t.get("lane") == "done"
        active_by_path[p] = active_by_path.get(p, False) or not terminal
    n = 0
    for repo in repos:
        if not repo or not os.path.isdir(repo):
            continue
        integ = _current_branch(repo)
        rc, out, _ = _git_try(repo, "worktree", "list", "--porcelain")
        if rc != 0:
            continue
        wt, pairs = None, []
        for line in out.splitlines():
            if line.startswith("worktree "):
                wt = line[len("worktree "):].strip()
            elif line.startswith("branch "):
                pairs.append((line[len("branch "):].strip().replace("refs/heads/", ""), wt))
        for br, path in pairs:
            if (not path or not br or br in ("main", "master", integ)
                    or os.path.abspath(path) == os.path.abspath(repo)):
                continue
            if active_by_path.get(os.path.realpath(path)):
                continue                    # a non-terminal card still owns this tree - keep
            if _git_try(repo, "merge-base", "--is-ancestor", br, integ)[0] != 0:
                continue                    # not merged - keep
            rc3, dirty, _ = _git_try(path, "status", "--porcelain", "--untracked-files=no")
            if rc3 == 0 and dirty:
                continue                    # dirty tracked - keep
            _git_try(repo, "worktree", "remove", "--force", path)
            if not os.path.isdir(path):
                _git_try(repo, "branch", "-D", br)
                n += 1
        # ORPHANS the git-driven pass can never see: trees whose link to the
        # repo is severed (admin dir pruned, half-removed, repo moved), so
        # `worktree list` no longer reports them and `worktree remove` fails.
        # Ownership by path shape + a provably broken .git is the reclaim
        # ticket; a tree ANY card still references is kept (nothing-lost).
        known = {os.path.realpath(p) for _, p in pairs if p}
        hashdir = os.path.join(os.path.abspath(os.path.join(repo, "..", WORKTREE_DIRNAME)),
                               _repo_hash(repo))
        if os.path.isdir(hashdir):
            for name in os.listdir(hashdir):
                path = os.path.join(hashdir, name)
                if (not os.path.isdir(path)
                        or os.path.realpath(path) in known
                        or os.path.realpath(path) in referenced
                        or not _owned_worktree(path)
                        or not _git_state_broken(path)):
                    continue
                shutil.rmtree(path, ignore_errors=True)
                if not os.path.isdir(path):
                    n += 1
        _git_try(repo, "worktree", "prune")
    return n


def _autocommit(t):
    """Clean up + commit uncommitted worktree work on the card's OWN branch (also
    COMPLETES a conflict merge the harness set up), so finishing never dead-ends on
    'uncommitted changes'. `git add -A` respects .gitignore. Returns:
      True     - committed
      False    - nothing to commit
      "markers"- unresolved conflict markers remain; caller must bounce."""
    wt = t.get("worktree")
    if not wt or not os.path.isdir(wt):
        return False
    merging = _git_try(wt, "rev-parse", "-q", "--verify", "MERGE_HEAD")[0] == 0
    rc, dirty, _ = _git_try(wt, "status", "--porcelain")
    if rc != 0 or (not dirty and not merging):
        return False
    if _git_try(wt, "add", "-A")[0] != 0:
        return False
    # refuse to commit if conflict markers are still in the staged content
    chk = subprocess.run(["git", "-C", wt, "diff", "--cached", "--check"],
                         capture_output=True, text=True)
    if "conflict marker" in (chk.stdout or "").lower():
        return "markers"
    if _git_try(wt, "commit", "-m", "HelmDeck: finalize %s" % t.get("id", ""))[0] != 0:
        return False
    return True


def _pull_main_into_branch(t):
    """Harness-side conflict resolution: merge main INTO the card's branch, in the
    card's worktree (the daemon has full git access; the agent never runs a merge).
    Either git auto-resolves it, or it leaves standard conflict MARKERS in the
    worktree files - which the agent/owner then resolves by plain EDITING (allowed
    in acceptEdits), never a git-merge. Returns "resolved" | "markers:<files>" |
    "error:<msg>"."""
    wt = t.get("worktree"); repo = t.get("repo")
    if not wt or not os.path.isdir(wt) or not repo:
        return "error:no worktree"
    rc, mainbranch, err = _git_try(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0:
        return "error:%s" % err
    rc, _out, _err = _git_try(wt, "merge", mainbranch, "--no-edit")
    if rc == 0:
        return "resolved"
    files = _git_try(wt, "diff", "--name-only", "--diff-filter=U")[1]
    return "markers:" + (files or _err[:150])


def dispatch_conflict_resolution(card_id, actor="board copilot", background=True):
    """Hand a REAL <<<<<<< merge conflict to the card's OWN worker as an edit-only
    task - the chat itself never edits code, but it can dispatch the card's agent.
    Sets up (or reuses) conflict markers in the worker's worktree via
    _pull_main_into_branch, then steers the worker to merge the markers by plain
    EDITING (never a git merge). On the next move to done, _autocommit completes
    the merge and the gate runs. Returns a human-readable status string.

    background=False runs the steer synchronously (the PM coordinator uses this
    to chain delegate -> re-submit on its own thread; the chat keeps True)."""
    t = _find(_load(), card_id)
    if not t:
        return "no card '%s'" % card_id
    if t.get("machine"):
        return ("'%s' ist eine Maschinen-Aufgabe (Ordner %s) ohne Branch - es gibt keinen "
                "Merge-Konflikt. Steuere sie einfach weiter."
                % (card_id, t.get("worktree") or "?"))
    wt = t.get("worktree")
    if not wt or not os.path.isdir(wt):
        return "%s has no worktree - dispatch/start the card first" % t.get("branch", card_id)
    # already mid-merge with markers (from a prior Done attempt)? reuse it - a
    # second `git merge` would abort with "already merging". Otherwise set one up.
    merging = _git_try(wt, "rev-parse", "-q", "--verify", "MERGE_HEAD")[0] == 0
    if not merging:
        res = _pull_main_into_branch(t)
        if res == "resolved":
            return ("%s: main merged cleanly into the branch - no markers, nothing to "
                    "resolve. Move it to done to land it." % t.get("branch", card_id))
        if res.startswith("error"):
            return "%s: could not set up resolution (%s)" % (t.get("branch", card_id), res[6:])
    files = (_git_try(wt, "diff", "--name-only", "--diff-filter=U")[1] or "").strip()
    if not files:
        if merging:
            # mid-merge but nothing unmerged -> the markers are already resolved and
            # staged; the harness finalizes on the next move to done.
            return ("%s: Konflikte sind bereits aufgeloest (keine Markierungen mehr offen). "
                    "Schieb die Karte auf Done - der Harness committet + merged dann selbst."
                    % t.get("branch", card_id))
        return ("%s: no conflict markers in the worktree - if it still won't merge it is "
                "likely a dirty shared checkout (use resolve_blocker)." % t.get("branch", card_id))
    flist = ", ".join(files.split("\n"))
    instr = ("Es stehen Git-Konfliktmarkierungen (<<<<<<< / ======= / >>>>>>>) in diesen "
             "Dateien: %s. Oeffne jede Datei, fuehre beide Seiten inhaltlich sinnvoll "
             "zusammen und ENTFERNE alle Markierungen restlos. Nur editieren - kein git, "
             "kein merge oder commit. Wenn keine Markierung mehr uebrig ist, bist du fertig; "
             "der Harness committet und merged dann selbst." % flist)
    if not background:
        steer(t["id"], instr, actor=actor, source="conflict-resolution")
        return ("Konfliktaufloesung durch den Worker von %s gelaufen (Dateien: %s) - "
                "jetzt neu einreichen, dann committet+merged der Harness." % (t.get("branch", card_id), flist))
    import threading
    threading.Thread(target=steer, args=(t["id"], instr),
                     kwargs={"actor": actor, "source": "conflict-resolution"}, daemon=True).start()
    return ("Konfliktaufloesung an %s geschickt (Dateien: %s). Der Worker merged die "
            "Markierungen im Hintergrund - danach die Karte auf Done schieben, dann "
            "committet+merged der Harness." % (t.get("branch", card_id), flist))


def _classify_merge(t):
    """DRY-RUN of the merge - what a Done WOULD do, without landing anything. Used
    by Review to rest the card on the board with a verdict. Returns (kind, message):
      already_merged / redundant_uncommitted - nothing to land (redundant)
      mergeable  - N commits merge cleanly
      conflict   - would conflict with main (names the files)
      blocked    - detached / on the card branch / no repo
    Leaves the main checkout exactly as found."""
    repo = t.get("repo"); branch = t.get("branch"); wt = t.get("worktree")
    if not repo or not os.path.isdir(repo):
        return "blocked", "kein Repo-Checkout zum Mergen"
    if not branch:
        return "blocked", "keine Branch"
    rc, cur, err = _git_try(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0:
        return "blocked", "kein git-Checkout: %s" % err
    if cur == "HEAD":
        return "blocked", "main-Checkout ist detached"
    if cur == branch:
        return "blocked", "main-Checkout steht auf dem Karten-Branch (%s)" % branch
    rc, ahead, _ = _git_try(repo, "rev-list", "--count", "HEAD..%s" % branch)
    ahead = int(ahead or "0") if rc == 0 else 0
    if ahead == 0:
        dirty = _git_try(wt, "status", "--porcelain")[1] if wt and os.path.isdir(wt) else ""
        if dirty:
            return "redundant_uncommitted", ("Redundant: committet nichts Neues (schon in main); "
                                             "%d uncommittete Aenderung(en) wuerden beim Abschluss committet." % len(dirty.splitlines()))
        return "already_merged", "Redundant: die Arbeit ist bereits vollstaendig in main."
    # dry-run the merge, then undo it (main left exactly as found)
    rc, _o, _e = _git_try(repo, "merge", "--no-commit", "--no-ff", branch)
    conflicts = _git_try(repo, "diff", "--name-only", "--diff-filter=U")[1]
    _git_try(repo, "merge", "--abort")
    if rc == 0:
        return "mergeable", "Bereit: %d Commit(s) mergen sauber nach main." % ahead
    return "conflict", ("Konflikt mit main - dieselben Stellen geaendert. Dateien:\n%s\n"
                        "Beim Abschluss holt der Harness main in den Branch; loese die "
                        "Markierungen (editieren)." % (conflicts or _e[:150]))


def _hook_kill_tree(proc):
    """Force the hook's whole process tree down. The hook is a SHELL, so
    terminating it alone orphans the real workers (gradle/java/node keep the
    build running and holding file locks). taskkill /T walks the tree at kill
    time, so kill the parent forcefully in ONE call rather than politely first
    (which would blind /T to the children)."""
    import subprocess
    if proc is None or proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=15)
        else:
            proc.kill()
        proc.wait(timeout=10)
    except Exception:
        pass


def _repo_hook(t, kind):
    """Owner-defined per-repo hook, policy in settings:
      "repo_hooks": {"<repo path>": {"preview": "<cmd>", "deploy": "<cmd>"}}
    preview runs in the WORKTREE when a card reaches Review (try it before
    merging); deploy runs in the MAIN REPO after accept - by the daemon, which
    is the only party holding secrets. Output lands on the card (last_reply
    stays the agent's - hooks log to the actionlog + a hook field).

    Bounded by SILENCE, not by wall-clock. A fixed 1800s cap killed the deploy
    hook mid-build: the NATIVE ship path (npm ci -> gradle assembleRelease ->
    emulator smoke -> scp the APK -> two expo exports -> two more uploads)
    legitimately runs past 30 minutes, so the ceiling fired on a HEALTHY build
    and left main merged with nothing shipped. Same defect the turn watchdog
    already fixed (drivers.run_turn): a build that is still printing is
    working. The window has to be generous because scp of a ~100MB APK over a
    pipe prints NOTHING while it uploads - silence, not duration, is what
    separates wedged from busy. `hook_max_s` is an optional absolute ceiling
    (0/unset = none) for a hook that dribbles output forever.

    STREAMS live: any output line prefixed `HOOK-NOTE:` is logged to the
    actionlog THE MOMENT it's read (ship.sh/build_apk.sh narrate their own
    long phases through it - "npm ci starting", "gradle running, ~10-15
    min", "APK built") - without this a healthy 15-20 min build looked from
    the owner's phone identical to a genuinely stuck card."""
    import collections, events, subprocess, threading
    import time as _t
    st = events.settings()
    hooks = (st.get("repo_hooks") or {}).get(t.get("repo") or "", {})
    cmd = (hooks or {}).get(kind, "").strip()
    if not cmd:
        return None
    def _num(key, default):
        try:
            return float(st.get(key) or 0) or default
        except Exception:
            return default
    idle = _num("hook_idle_s", 900.0)       # 15 min of TOTAL silence = wedged
    hard = _num("hook_max_s", 0.0)          # optional absolute cap; default none
    cwd = t.get("worktree") if kind == "preview" else t.get("repo")
    from actionlog import ActionLog
    log = ActionLog(t["run_dir"])
    log.log("note", "%s HOOK: %s" % (kind.upper(), cmd))
    proc, why = None, ""
    # bounded tail: a chatty gradle build must not accumulate in memory (the old
    # capture_output buffered the ENTIRE build log just to slice 1500 chars off it)
    lines = collections.deque(maxlen=400)
    last = [_t.time()]
    try:
        proc = subprocess.Popen(cmd, cwd=cwd or ".", shell=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", bufsize=1)

        def _pump():
            try:
                for line in proc.stdout:
                    stripped = line.rstrip("\n")
                    lines.append(stripped)
                    last[0] = _t.time()      # ANY output = still alive
                    # live progress narration: a hook script can announce its own
                    # long phases instead of the owner watching dead silence
                    if stripped.strip().startswith("HOOK-NOTE:"):
                        log.log("note", stripped.strip()[len("HOOK-NOTE:"):].strip())
            except Exception:
                pass
        pump = threading.Thread(target=_pump, daemon=True)
        pump.start()
        start = _t.time()
        poll = min(5.0, max(0.5, idle / 4.0))
        while True:
            try:
                proc.wait(timeout=poll)
                break                        # exited on its own
            except subprocess.TimeoutExpired:
                pass
            now = _t.time()
            if now - last[0] > idle:
                why = "no output for %ds" % int(idle)
                break
            if hard and now - start > hard:
                why = "exceeded hard cap %ss" % int(hard)
                break
        if why:
            _hook_kill_tree(proc)
            lines.append("[hook killed: %s]" % why)
            ok = False
        else:
            pump.join(timeout=5)
            ok = proc.returncode == 0
        out = "\n".join(lines).strip()
    except Exception as e:
        _hook_kill_tree(proc)               # never leak the tree on an error path
        out, ok = str(e), False
    log.log("note", "%s HOOK %s: %s" % (kind.upper(), "OK" if ok else "FAILED", out[-800:]))
    t[kind + "_hook"] = {"ok": ok, "tail": out[-1500:]}
    return ok


import i18n as _i18n          # owner-facing prose only; the audit trail stays English


def _say_card(t, text):
    """Report a lane OUTCOME in the owner's board chat, in plain language.

    The lane pipeline is otherwise mute toward the chat: it writes the flight
    recorder, the event log and a push, none of which is the surface the owner
    actually reads. A drag to Done could run the gate, hit a conflict and
    bounce with nothing to show for it. Best-effort by design - reporting an
    outcome must never break the work that produced it."""
    try:
        import copilot
        title = (t.get("task") or "").replace("\n", " ")[:60]
        copilot.say("'%s': %s" % (title, text), cls="pm")
    except Exception:
        pass


def move_lane(tid, lane, actor="owner", _autopark=True):
    """The board move is the workflow verb: ->working dispatches, ->review submits
    (GATED: the card bounces back with a punch list unless its work is green),
    ->done accepts (records the acceptance economics)."""
    import events
    if lane not in LANES:
        raise RuntimeError("bad lane: " + lane)
    tracks = _load()
    t = _find(tracks, tid)
    if not t:
        raise RuntimeError("no such track: " + tid)
    prev = t.get("lane")
    # record the human's board move in the card's own feed (chat), so a drag to
    # Review/Done/Working/Backlog reads alongside the agent's work, not just in the
    # global event log. The lane-specific handlers below add the outcome detail.
    if t.get("run_dir") and prev != lane:
        from actionlog import ActionLog as _AL
        _lane_label = {"backlog": "Backlog", "working": "In Arbeit", "review": "Review", "done": "Done"}
        _AL(t["run_dir"]).log("note", "→ verschoben nach %s von %s"
                              % (_lane_label.get(lane, lane), actor))
    if lane == "working":
        # pulling a card back OUT of review is a human bounce - the reject touch
        if prev == "review":
            events.emit("touch", tid, touch="bounce", actor=actor)
            from actionlog import ActionLog
            ActionLog(t["run_dir"]).log("note", "BOUNCED by owner - back to Working")

            def _bounce(tt):
                tt["status"] = "bounced"; tt["lane"] = "working"
            t = _mutate(tid, _bounce) or t
            _say_card(t, _i18n.t("say.bouncedToWorking"))
            return t
        return _start(tid)   # idempotent: resumes position if already started
    from actionlog import ActionLog
    log = ActionLog(t["run_dir"])
    # ALREADY LANDED - an accept is IDEMPOTENT. status='accepted' is only ever
    # set after a successful merge, so a repeat move to Review/Done has nothing
    # left to gate or land. Re-running the cycle is not merely wasteful, it is
    # destructive: the first accept's reclaim_worktree has (correctly) emptied
    # the worktree, so the second run's gate finds no test files and BOUNCES a
    # card that already shipped.
    #
    # Observed live on card 20260812-164257: Done at 17:32:45 gated green,
    # merged 2 commits and ran the deploy hook; because lane='done' is written
    # only AFTER that ~22s hook, the card still read lane=review, so a second
    # Done at 17:34:32 started a concurrent cycle whose gate (17:34:53) hit the
    # just-reclaimed tree and bounced the card with a bogus "No such file or
    # directory" punch list. Accepting twice must never un-land a card.
    if t.get("status") == "accepted" and lane in ("review", "done"):
        log.log("note", "ALREADY LANDED - accept is a no-op (no re-gate, no re-merge)")

        def _settle(tt):
            tt["lane"] = "done"
            tt.pop("gate_report", None); tt.pop("merge_report", None)
        return _mutate(tid, _settle) or t
    if t.get("machine") and lane in ("review", "done"):
        # no branch, no merge - the owner's accept IS the gate (see _accept_machine)
        return _accept_machine(t, lane, actor, log)
    if lane in ("review", "done"):
        # Two verbs sharing one prep: clean up + commit, then the gate. REVIEW then
        # CLASSIFIES the merge (dry-run) and RESTS on Review showing the verdict -
        # a deliberate drag to DONE actually merges + deploys. gate-before-merge LAW
        # kept. Any problem keeps the card on Review with a clear reason.
        #
        # Publish "gating" FIRST: the gate is a real subprocess (up to 600s) and
        # the merge + deploy hook follow it, so without this the card looked
        # untouched for minutes while the work ran. Every poller now sees the
        # card is busy; each terminal branch below overwrites this status.
        # No chat line here on purpose - the card's own status covers "started",
        # and chains/policy auto-accept through this path too. The chat carries
        # OUTCOMES (what was missing), not progress chatter.
        def _gating(tt):
            tt["status"] = "gating"
        t = _mutate(tid, _gating) or t
        ac = _autocommit(t)
        if ac == "markers":
            msg = ("Konfliktmarkierungen sind noch im Worktree offen. Steuere den Agenten: "
                   "'loese die Konfliktmarkierungen (<<<<<<< / >>>>>>>) in den Dateien' - "
                   "nur editieren - und reiche dann neu ein.")
            log.log("note", "CONFLICT MARKERS OPEN - stays on Review to resolve: " + msg[:200])

            def _markers(tt):
                tt["status"] = "bounced"; tt["lane"] = "review"   # stay on Review, not back to Working
                tt.pop("gate_report", None)                       # the CURRENT blocker is the conflict
                tt["merge_report"] = msg; tt["merge_kind"] = "conflict"
            t = _mutate(tid, _markers) or t
            import notify; notify.card_event(t, "bounced")
            _say_card(t, _i18n.t("say.conflictMarkers", detail=msg))
            t = dict(t); t["merge_failed"] = True; t["merge_kind"] = "conflict"
            return t
        if ac is True:
            log.log("note", "COMMITTED worktree changes on the branch before merge")
        # the repo's own quality gate (helmdeck.gate command). The committed
        # check now trivially passes because we just committed. Say it in the CARD
        # chat first: the gate runs daemon-side (outside the agent session), so
        # without this the card just spins "In Arbeit"/"Gate laeuft" with nothing in
        # the chat and the owner cannot see WHAT is happening. NB: use the actionlog
        # (log.log note), NOT _say_card - _say_card -> copilot.say lands in the BOARD-
        # Agent chat, but the owner reads the card's WORKER chat, which weaves in
        # these notes (that is why the other lane notes show but _say_card did not).
        log.log("note", _i18n.t("say.gateRunning"))
        ok, problems = _gate(t)
        events.emit("gate", tid, ok=ok, problems=problems)
        if not ok:
            punch = " | ".join(p.split("\n")[0] for p in problems)
            log.log("note", "GATE FAILED - stays on Review to fix: " + punch[:400])

            def _gatefail(tt):
                tt["status"] = "bounced"; tt["lane"] = "review"; tt["gate_report"] = problems   # stay on Review
                tt.pop("merge_report", None); tt.pop("merge_kind", None)   # the CURRENT blocker is the gate
            t = _mutate(tid, _gatefail) or t
            import notify; notify.card_event(t, "bounced")
            # The chat gets the FULL problem text, not the one-line `punch`:
            # a gate failure's actual output (which test, which assertion) lives
            # on the lines after the header, and the chat is where the owner
            # reads the reason. `punch` stays for the card's compact report.
            _say_card(t, _i18n.t("say.gateRed", detail="\n".join(problems)[:800]))
            t = dict(t); t["gate_failed"] = True
            return t
        t.pop("gate_report", None)
        log.log("note", _i18n.t("say.gateGreen"))
        if lane == "review":
            # PREVIEW ONLY: say what a Done would do; the card RESTS on Review.
            kind, msg = _classify_merge(t)
            # AUTO-DELEGATION: a "conflict" that is really an uncommitted (dirty)
            # shared checkout, not <<<<<< markers, is an out-of-worktree blocker
            # the sandboxed worker can't fix. Hand it to the board-Agent capability
            # automatically - park the dirty tree on a wip-* branch (nothing lost)
            # and retry, ONCE (_autopark guards recursion).
            if _autopark and kind == "conflict" and _is_dirty_block(msg):
                # actionlog note (shows in the WORKER chat), not _say_card
                log.log("note", _i18n.t("say.mergeBlockedDirty"))
                summary = park_and_retry_merge(tid, actor="board-Agent (auto)")
                log.log("note", _i18n.t("say.mergeUnblocked", detail=summary[:300]))
                return _find(_load(), tid) or dict(t)
            events.emit("merge", tid, ok=(kind not in ("conflict", "blocked")),
                        outcome=kind, detail="preview: " + msg[:200])
            # FAST-TRACK (per-card, SCOPED): a card flagged `fast_track` with a
            # GREEN gate (already checked above) and a clean merge LANDS
            # immediately - no human accept. Only for flagged cards; every other
            # card rests on Review for your accept. The gate still guards (a red
            # gate already bounced above), so this is auto-accept, not skip-gate.
            _clean = kind in ("mergeable", "already_merged", "redundant_uncommitted")
            if not (t.get("fast_track") and _clean):
                log.log("note", "REVIEW-Vorschau (%s): %s" % (kind, msg[:200]))

                def _submit(tt):
                    tt.pop("merge_report", None)
                    tt.pop("gate_report", None)          # gate just ran green
                    tt["merge_kind"] = kind; tt["review_report"] = msg
                    tt["status"] = "submitted"; tt["lane"] = "review"
                t = _mutate(tid, _submit) or t
                _VERDICT = {"mergeable": "verdict.mergeable",
                            "already_merged": "verdict.alreadyMerged",
                            "redundant_uncommitted": "verdict.alreadyMerged",
                            "conflict": "verdict.conflict"}
                _verdict = (_i18n.t(_VERDICT[kind]) if kind in _VERDICT
                            else _i18n.t("verdict.other", detail=msg[:200]))
                _say_card(t, _i18n.t("say.reviewChecked", verdict=_verdict))
                return dict(t, review_preview=True, merge_kind=kind)
            log.log("note", "FAST-TRACK %s: gruenes Gate + sauberer Merge -> lande + deploye ohne Abnahme"
                    % t.get("branch", ""))
        # lane == "done" (or a fast-tracked review): LAND it
        _repo_hook(t, "preview")   # best-effort try-it surface before it lands
        # classify + merge to main - conflict/blocked bounces with the resolve path
        accept_ok, kind, mergemsg = _merge_to_main(t)
        if not accept_ok and kind == "conflict":
            # HARNESS-side resolve: pull main INTO the card's branch so resolving is
            # an EDIT task, not an (impossible) agent merge. Auto-resolved -> retry
            # the landing; otherwise leave editable markers + a clear instruction.
            res = _pull_main_into_branch(t)
            if res == "resolved":
                log.log("note", "AUTO-RESOLVED: merged main into the branch, retrying")
                accept_ok, kind, mergemsg = _merge_to_main(t)
            elif res.startswith("markers"):
                files = res.split(":", 1)[1]
                mergemsg = ("Der Harness hat main in deinen Branch geholt - die Konflikte "
                            "stehen jetzt als Markierungen im Worktree (%s). Steuere den Agenten: "
                            "'loese die Konfliktmarkierungen in diesen Dateien' (nur editieren). "
                            "Danach neu auf Review - der Harness committet und mergt dann selbst." % files)
        events.emit("merge", tid, ok=accept_ok, outcome=kind, detail=mergemsg[:300])
        if not accept_ok:
            log.log("note", "MERGE %s - stays on Review to resolve: %s" % (kind.upper(), mergemsg[:400]))

            def _mergefail(tt):
                tt["status"] = "bounced"; tt["lane"] = "review"   # stay on Review, not back to Working
                tt["merge_report"] = mergemsg; tt["merge_kind"] = kind
                tt.pop("gate_report", None)          # gate ran green before the merge
            t = _mutate(tid, _mergefail) or t
            import notify; notify.card_event(t, "bounced")
            _say_card(t, _i18n.t("say.cannotLand", kind=kind, detail=mergemsg[:400]))
            t = dict(t); t["merge_failed"] = True; t["merge_kind"] = kind
            return t
        _NOTE = {"merged": "MERGED -> main", "already_merged": "REDUNDANT (bereits in main) - geschlossen",
                 "redundant_uncommitted": "REDUNDANT (bereits in main; uncommittete Aenderungen ignoriert) - geschlossen"}
        log.log("note", "%s: %s" % (_NOTE.get(kind, "ACCEPTED"), mergemsg[:280]))
        events.emit("touch", tid, touch="review", actor=actor)
        te = [e for e in events.read_events() if e.get("track") == tid]
        mode = events._completion_mode(te, t.get("turns"))
        events.emit("done", tid, mode=mode, ai_cost=t.get("ai_cost", 0.0),
                    value=t.get("value"), models=t.get("models", []),
                    tokens_in=t.get("tokens_in", 0), tokens_out=t.get("tokens_out", 0))
        log.log("note", "ACCEPTED (%s) - AI $%.4f, value %s" %
                (mode, t.get("ai_cost", 0.0), t.get("value")))

        def _accepted(tt):
            tt.pop("merge_report", None); tt.pop("gate_report", None)
            tt["merge_kind"] = kind
            tt["status"] = "accepted"; tt["mode"] = mode
            _record_outcome(tt)
        t = _mutate(tid, _accepted) or t
        _repo_hook(t, "deploy")    # daemon-side (post-merge), with the secrets agents never see
        # A landing was the QUIETEST outcome of all: no push (card_event was only
        # ever called for bounces) and no chat line. Report it like any other.
        _LANDED = {"merged": "say.landed.merged",
                   "already_merged": "say.landed.redundant",
                   "redundant_uncommitted": "say.landed.redundant"}
        _dh = t.get("deploy_hook") or {}
        _say_card(t, _i18n.t(_LANDED.get(kind, "say.landed.plain")) + (
            "" if not _dh else _i18n.t("say.deployOk" if _dh.get("ok") else "say.deployFailed")))
        import notify; notify.card_event(t, "done")
        try:
            import pm; pm.on_card_done(tid)   # re-judge the golden triangle at event time
        except Exception:
            pass
        if t.get("connector"):
            import connectors, checkpoints
            checkpoints.create(actor=actor, reason="connector install: " + t.get("connector", ""))
            try:
                inst = connectors.install_from_worktree(t)
                if inst:
                    log.log("note", "CONNECTOR INSTALLED: " + ", ".join(inst))
                    events.emit("connector", tid, action="installed", files=inst)
            except RuntimeError as e:
                log.log("note", str(e)[:400])
                events.emit("connector", tid, action="charter_blocked", detail=str(e)[:300])
        reclaim_worktree(t, log)   # isolation reclaimed: the work is in main now
        lane = "done"   # Review == Abnahme: a finished card lands in Done
    elif lane == "backlog":
        # Re-queueing a card IS the "run it again" instruction, so the
        # auto-dispatchers' one-shot stamps must not survive it (a re-queued
        # autopilot card otherwise keeps autopilot=true but never dispatches
        # again). status=queued + the stamp clearing happen in the _land
        # mutate below - one writer, no local-copy drift.
        # the chain keeps its OWN stamps on the step (processes.json), which the
        # loop above cannot reach - without this the card came back clean but
        # its step stayed "already dispatched" and never ran again.
        try:
            import processes
            processes.clear_step_stamps(tid)
        except Exception as e:      # a board move must not fail on the chain store
            print("clear_step_stamps failed for %s: %s" % (tid, e))
    events.emit("lane", tid, frm=prev, to=lane)
    _hooks = {k: t[k] for k in ("preview_hook", "deploy_hook") if k in t}

    def _land(tt):
        tt["lane"] = lane
        if lane == "backlog":
            tt["status"] = "queued"
            for k in ("autopilot_dispatched", "autopilot_accepted",
                      "autopilot_alerted", "autopilot_ts", "priority_dispatched"):
                tt.pop(k, None)
        # the repo hooks ran on the local copy (they are subprocesses and must
        # stay outside the mutation lock) - persist their outcome here.
        tt.update(_hooks)
    t = _mutate(tid, _land) or t
    return t

MODES = ("plan", "acceptEdits", "default", "bypassPermissions")


def _is_dirty_block(msg):
    """True when a 'conflict' is really git refusing to merge over an uncommitted
    (dirty) checkout - NOT real <<<<<< markers. That's an out-of-worktree blocker
    the sandboxed worker can't fix, so the board-Agent parks + retries."""
    m = (msg or "").lower()
    return "<<<<<<<" not in (msg or "") and (
        "would be overwritten by merge" in m
        or "local changes to the following" in m
        or "commit your changes or stash" in m)


def park_and_retry_merge(tid, actor="owner"):
    """Unblock a card whose review/merge is blocked by an uncommitted (dirty)
    working tree in its repo - NOT a real <<<<<< conflict, but git refusing to
    merge over local changes ("your local changes ... would be overwritten").

    Park ALL uncommitted work (tracked + untracked) onto a wip-<branch>-<ts>
    branch - nothing lost, the checkout goes clean - then re-run the review
    check. NON-DESTRUCTIVE (only ever adds a branch/commit; never discards).

    This is the board-Agent's job, not the sandboxed card worker's: the worker
    is confined to its worktree and cannot reach the shared main checkout by
    design, so this cross-cutting unblock belongs to the board-wide agent, gated
    by the owner's explicit instruction. Returns a human summary."""
    tracks = _load()
    t = _find(tracks, tid)
    if not t:
        raise RuntimeError("no such track: " + tid)
    if t.get("machine"):
        # its "repo" is a folder on the owner's PC - never run branch surgery there
        return ("'%s' ist eine Maschinen-Aufgabe (Ordner %s), kein Branch - da gibt es "
                "nichts zu parken. Steuere sie einfach weiter."
                % (tid, t.get("worktree") or "?"))
    repo = t.get("repo")
    if not repo or not is_git_repo(repo):
        return "cannot park: card '%s' has no git repo" % tid
    status = subprocess.run(["git", "-C", repo, "status", "--porcelain"],
                            capture_output=True, text=True).stdout.strip()
    parked = ""
    if status.strip():
        cur = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        wip = "wip-%s-%s" % (_slug(cur), time.strftime("%Y%m%d-%H%M%S"))
        _git(repo, "checkout", "-b", wip)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m",
             "wip: park uncommitted %s work so card %s could merge (by %s)" % (cur, t["branch"], actor))
        _git(repo, "checkout", cur)     # back on the original branch, now clean
        parked = wip
        import events
        events.log("merge", "parked dirty tree of %s onto %s to unblock %s (%s)"
                   % (cur, wip, t["branch"], actor))
    # tree is clean now -> re-run the review/merge check (no auto-park recursion)
    r = move_lane(tid, "review", actor=actor, _autopark=False)
    if r.get("gate_failed"):
        return "parked onto '%s', but the gate is red: %s" % (parked or "-", " | ".join(r.get("gate_report") or [])[:200])
    if r.get("merge_failed"):
        return "parked onto '%s', but the card still can't merge: %s" % (parked or "-", (r.get("merge_report") or "")[:200])
    head = ("Parked the uncommitted work onto branch '%s' (nothing lost) - " % parked) if parked else "The tree was already clean - "
    return head + "the review check now passes. Move the card to Done to land it."


def _pending_context(t):
    """Review/merge/gate checks run OUTSIDE the agent session (daemon-side, only
    in the actionlog), so the worker never sees a merge conflict or a failed
    gate - it's in the woven chat view but not the session. When the owner steers
    to fix one ("resolve the conflict"), prepend the actual report so the worker
    isn't blind. Empty string when nothing is pending."""
    parts = []
    # Repo hooks (preview/deploy) ALSO run daemon-side, outside the session -
    # same blind spot as gate/merge below. Incident (2026-08-15): a fast-track
    # deploy hook actually SUCCEEDED ("DEPLOY HOOK OK"), but its output tail
    # happened to contain a harmless "(23) Failed writing body" curl artifact;
    # the owner read that as a failure and told the worker "Deploy hook
    # failed", and the worker - with no way to check `t["deploy_hook"]` itself
    # (that field existed on the track the whole time, just never surfaced
    # here) - had to trust the owner's framing and chased a phantom infra bug.
    # steer() clears these after this call, so each hook result is told to the
    # worker exactly once (on the next steer), never repeated on later ones.
    for hook_kind in ("deploy_hook", "preview_hook"):
        dh = t.get(hook_kind)
        if dh:
            parts.append("%s HOOK %s (ran outside this session, daemon-side):\n%s" % (
                hook_kind.split("_")[0].upper(), "OK" if dh.get("ok") else "FAILED",
                str(dh.get("tail") or "")[:800]))
    gr = t.get("gate_report")
    if t.get("gate_failed") and gr:
        parts.append("Quality gate FAILED:\n" + ("\n".join(gr) if isinstance(gr, list) else str(gr)))
    elif isinstance(gr, list) and any(RESUME_NOTE in x or ZOMBIE_NOTE in x for x in gr):
        # A zombie-sweep/Stop interrupt (no gate involved) also stashes its note
        # in gate_report - the only channel _pending_context reads. Without this
        # branch a bare "continue" after an interrupt resumes BLIND: the worker
        # never learns its turn was cut, only that a new instruction arrived.
        parts.append("Note from the desktop since your last turn:\n" + "\n".join(gr))
    # Thrash guard: if this card has failed its gate several times in a row, a
    # naive rewrite-and-retry keeps burning the budget (SageRoute's rewrite/retest
    # trap). Tell the worker to stop rewriting and change approach - break the loop.
    import events, turnopts
    fails = events.consecutive_gate_fails(t["id"])
    if fails >= turnopts.ESCALATE_TURNS:
        parts.append("This card has FAILED its quality gate %d times in a row. Do "
                     "NOT just rewrite and resubmit - that pattern has not worked. "
                     "Step back: re-examine the assumption behind the fix, or say "
                     "plainly what is blocking you and stop." % fails)
    rep = t.get("review_report") or t.get("merge_report")
    if rep and (t.get("merge_kind") == "conflict" or t.get("merge_failed") or t.get("gate_failed")):
        parts.append("Review/merge check reported:\n" + str(rep))
    if not parts:
        return ""
    return ("[Desktop context since your last turn - the review/merge/gate ran "
            "outside this session, so you did not see this. Use it if the "
            "instruction refers to it:]\n\n" + "\n\n".join(parts) + "\n\n---\n\n")


# -- AUTO-COMPACT-AND-CONTINUE (Paseo parity: auto compaction at the brim) ----
# A persistent claude -p session fills over turns. Left alone it dead-ends the
# worker ("mein Kontext ist am Ende") and, worse, the NEXT resume of a full
# session rotates to a FRESH .jsonl carrying none of the prior conversation -
# the whole chat "disappears" from the card. So when a turn leaves the context
# near the brim we run ONE bounded /compact on the same session: it summarises
# itself in place, the next steer keeps headroom, the thread stays continuous.
_COMPACT_AT_TOKENS = 160_000     # ~80% of a 200k window - the high-water mark
_CTX_WINDOW = 200_000

# RE-ENABLED 2026-08-14 (was disabled 2026-08-10 as a0853d4; see debt.py
# [auto-compaction-disabled] history). BOTH things blamed for the "/compact
# corruption" were already root-caused and fixed by OTHER commits before this
# one was reinstated - the corruption was never actually /compact:
#   1. "shrink check read summed usage, not compacted context" - true of this
#      function's original Aug 7 form, but ctx_tokens has read the last-call-
#      only usage (meta.ctx_usage, Paseo-style, see _record_econ above) since
#      66930bb (2026-08-08 - TWO DAYS before the disable commit). The shrink
#      check below was already comparing against the right number.
#   2. "a later --resume silently started a FRESH session" - the actual cause
#      was the claude.cmd shim eating the trailing `--resume <sid>` arg when
#      exec'd via `cmd /s /c` (ANY --resume could silently miss, compaction or
#      not). Fixed by ea09780 (2026-08-10, the SAME DAY, 5h after the disable
#      commit): drivers now spawn the real exe as an argv list, never the
#      shim. The incident that got compaction blamed (Fix AI-Kosten-Tracking,
#      2026-08-10) is fully explained by the shim bug alone.
# accept-and-rebind (_finish_turn, Weg B) stays as the safety net for ANY
# unresumable session (idle eviction, a killed process, a genuinely corrupt
# tip) - compaction was never the only way to hit that path. This function
# stays self-verifying (probes once, learns True/False) so a CLI that doesn't
# honor /compact costs nothing per turn.
_autocompact_supported = None    # None=unprobed, True/False learned from first /compact


def _maybe_compact(t, log):
    """Compact the session in place if the live context crossed the high-water
    mark. Self-verifying: /compact must actually SHRINK the context (ctx_tokens
    is the last-call-only reading, not summed - a real compaction is visible
    there). If it does not (an older CLI that treats the slash line as literal
    input), we learn that once and stop - no no-op cost, no polluting the
    conversation every turn. Returns the fresh track (or None if nothing was
    done)."""
    global _autocompact_supported
    if _autocompact_supported is False:
        return None
    ctx = t.get("ctx_tokens", 0)
    # high-water mark scales with the session's DERIVED window (ctx_window is
    # runtime evidence, incl. the proof-beyond-200k 1M inference above) - the
    # fixed 160k mark made a 1M-tier session "compact" at a real ~16% fill,
    # burning a full-context /compact turn while the CLI (which knows its real
    # window) rightly saw no reason to shrink anything.
    window = max(t.get("ctx_window") or 0, _CTX_WINDOW)
    if ctx < 0.8 * window or not t.get("session_id"):
        return None
    pct = min(100, round(ctx / window * 100))
    log.log("note", "AUTO-COMPACT: Kontext bei %d%% (~%dk) - ich verdichte die Session, "
            "damit der Verlauf erhalten bleibt und es weitergeht." % (pct, round(ctx / 1000)))
    # SHORT watchdog, not the driver's default 900s: incident (2026-08-15) - a
    # /compact turn finished writing its own transcript (the session showed
    # "Compacted") but the underlying CLI process never exited, so this call
    # sat blocked for the full 15 minutes before the default idle-timeout
    # finally killed it - and every OTHER post-turn step (fast-track ship
    # included) waits on this call returning. Compact is a small, bounded
    # operation; 3 minutes of total silence is already generous slack above
    # every observed real compaction, and failing fast here just falls
    # through to the existing self-verifying "CLI doesn't honor /compact"
    # path below - never a hard failure, just a faster one.
    sid, _out, meta = _turn(t, "/compact", idle_timeout=180)

    def _apply(tt):
        if sid and tt.get("session_id") and sid != tt["session_id"]:
            chain = [s for s in (tt.get("session_chain") or []) if s != tt["session_id"]]
            chain.append(tt["session_id"])
            tt["session_chain"] = chain[-6:]
            tt["session_id"] = sid
        _record_econ(tt, meta)            # measured economics: the compact turn is billed too
    t = _mutate(t["id"], _apply) or t
    before = ctx
    after = t.get("ctx_tokens", before)
    if after <= before * 0.75:            # a real compaction frees a big chunk
        _autocompact_supported = True
        log.log("note", "AUTO-COMPACT ok: Kontext jetzt ~%dk - Verlauf verdichtet, es geht "
                "ohne Unterbrechung weiter." % round(after / 1000))
    else:
        _autocompact_supported = False
        log.log("note", "AUTO-COMPACT: diese CLI honoriert /compact nicht - fuer diese "
                "Session abgeschaltet. Kontext-Meter + Nudge bleiben aktiv.")
    return t


def steer(tid, text, perm=None, actor="owner", source="you",
          model="", thinking="", attachments=None, mode=None):
    """Continue the track's session (resume - context preserved, NO history rebuild).
    model/thinking/attachments come from the chat composer: model is resolved
    through the whitelist (incl. Auto), attachments are saved into the worktree
    for the agent to read, and the augmented prompt (thinking directive +
    attachment refs) is what the driver sees - but the AUDIT logs the human's
    original text, not the augmentation."""
    tracks = _load()
    t = _find(tracks, tid)
    if not t:
        raise RuntimeError("no such track: " + tid)
    if not t.get("session_id"):
        _start(tid)                      # steering a backlog card dispatches it first
        tracks = _load(); t = _find(tracks, tid)
    import events, turnopts, drivers
    events.emit("touch", tid, touch="steer", actor=actor)
    was_bounced = t.get("status") == "bounced"   # routing signal, read BEFORE 'running'
    from actionlog import ActionLog
    log = ActionLog(t["run_dir"])
    # INTERRUPT-AND-REPLACE: if a turn is live, soft-interrupt it and start THIS
    # instruction now (Paseo's replaceAgentRun), instead of queuing behind it on
    # the per-card lock. drivers.cancel is the cooperative interrupt (~2s ack,
    # the process stays alive, the session resumes), so the interrupted turn
    # releases the lock and this steer runs immediately after. A burst collapses
    # to last-wins via the epoch: only the newest steer survives the bail below.
    my_epoch = _bump_steer_epoch(tid, text)
    if drivers.turn_active(tid):
        log.log("note", "⏹ neue Anweisung ersetzt den laufenden Turn (Interrupt).")
        try:
            drivers.cancel(tid)
        except Exception as _ie:
            log.log("note", "Interrupt fehlgeschlagen: %s" % str(_ie)[:150])
    if _steer_epoch_current(tid) != my_epoch:
        # a newer steer superseded this one. AUDIT the command anyway and hand it
        # to the winner via the pending list - bundled, never silently dropped.
        log.log("steer", text)
        log.log("note", "⏫ mit der nächsten Anweisung gebündelt (ein Turn).")
        return t
    _burst = _drain_steer_texts(tid)
    if len(_burst) > 1:
        text = "\n\n".join(_burst)        # the winner carries the WHOLE burst
        log.log("note", "%d schnelle Anweisungen zu einem Turn gebündelt." % len(_burst))
    if source and source != "you":
        log.log("note", "DELEGATED by %s -> this card's worker" % source)
    log.log("steer", text)               # audit the human's words, not the augmented prompt
    log.log("turn", "Turn gestartet", event="started")
    # the card is moving again, so whatever we last pushed about it is stale -
    # the next notification is news and must not be swallowed by the dedup
    import notify
    notify.clear_dedup(tid)

    def _begin(tt):
        # A card on Review that's being resolved (e.g. steering the agent to fix
        # a conflict) STAYS on Review - steering no longer demotes it to Working.
        # Any other lane (backlog/done) still means "back to active work".
        if tt["lane"] not in ("working", "review"):
            events.emit("lane", tid, frm=tt["lane"], to="working")
            tt["lane"] = "working"
        # Any steer supersedes a pending question - the owner either answered it
        # through the buttons (this IS that steer) or decided something else
        # instead. Clearing here, not at turn end, means the panel disappears
        # the moment the turn starts rather than lingering for the whole turn.
        tt.pop("question", None)
        tt["status"] = "running"
    t = _mutate(tid, _begin) or t
    paths = turnopts.save_attachments(t.get("worktree") or t["run_dir"], attachments)
    # Auto routing sees the card's facts INCLUDING turn count - a card that's
    # already dragged on escalates to the strong model (cheap "escalate on
    # evidence"). An explicit model from the composer still wins.
    cli_model, _ = turnopts.resolve_model(model, text, bool(paths),
        signals={"value": t.get("value"), "priority": t.get("priority"), "turns": t.get("turns"),
                 "failed": was_bounced or bool(t.get("gate_failed")),
                 "fails": events.consecutive_gate_fails(t["id"])})
    # Hand the worker the daemon-side context it never saw (a merge conflict, a
    # failed gate) so a steer like "resolve the conflict" isn't blind. The AUDIT
    # above still logs the human's original text, not this augmentation.
    prompt = _pending_context(t) + turnopts.augment_prompt(text, thinking, paths)
    # Consumed: pop the hook results now so they're told to the worker exactly
    # ONCE (this steer), not repeated on every later unrelated one.
    if t.get("deploy_hook") or t.get("preview_hook"):
        _mutate(tid, lambda tt: (tt.pop("deploy_hook", None), tt.pop("preview_hook", None)))
    perm_override = mode if mode in MODES else None   # whitelist - no arbitrary mode
    # SELF-HEAL a missing OR broken worktree before spawning into it. The tree
    # is regenerable from the branch; without the isdir half, a reclaimed/
    # hand-deleted/never-created tree made EVERY steer die with WinError 267
    # (spawn cwd invalid) - a dead-end the owner cannot steer out of, on a
    # card that is otherwise fine. isdir alone is not enough, though: an
    # existing-but-never-`git worktree add`'d directory (interrupted add,
    # stray mkdir) also passes isdir, so a steer reused it as-is and dispatched
    # into a folder with no .git - the same class _ensure_worktree now guards
    # against internally, checked again here so the CALLER's decision whether
    # to even invoke it doesn't reintroduce the bug one level up.
    if (not t.get("machine") and t.get("branch")
            and (not os.path.isdir(t.get("worktree") or "")
                 or _git_state_broken(t["worktree"]))):
        try:
            wt_new = _ensure_worktree(t)
            t["worktree"] = wt_new
            _mutate(tid, lambda tt: tt.__setitem__("worktree", wt_new))
            log.log("note", "WORKTREE neu erzeugt (%s) - fehlte oder war nie initialisiert, Branch haelt den Stand." % wt_new)
        except Exception as _we:
            log.log("note", "WORKTREE fehlt und Neuaufbau schlug fehl: %s" % str(_we)[:200])
    try:
        sid, result, meta = _turn(t, prompt, model=cli_model, perm=perm_override)
    except BaseException as e:
        # The steer thread must NEVER die leaving 'running' behind - that flag
        # is a stored promise only this thread would clear, and a card frozen
        # on it shows an eternal spinner (Paseo avoids the whole class by
        # deriving lifecycle from the live run; the reconciler is our derive
        # loop, this is the fast path). _mutate loads fresh under the card's
        # mutation lock, so a concurrent cancel's write can't be resurrected.
        rel = {}

        def _release(tt):
            if tt.get("status") != "running":
                return False             # a concurrent cancel already settled it
            tt["status"] = "needs_you"
            rel["did"] = True
        _mutate(tid, _release)
        if rel.get("did"):
            log.log("note", "turn ABGEBROCHEN (%s) - Karte freigegeben, steuern setzt fort."
                    % str(e)[:160])
        log.log("turn", "Turn fehlgeschlagen", event="failed", error=str(e)[:500])
        raise
    # REPLACE HANDOFF: this turn was soft-interrupted to make room for a NEWER
    # steer (the epoch moved and the driver returned the cancelled sentinel).
    # Don't settle - the newer steer owns the card and will finish it. Settling
    # here would flap the status mid-replace.
    if _steer_epoch_current(tid) != my_epoch and "cancelled" in (result or "").lower():
        log.log("turn", "Turn ersetzt", event="canceled")
        return t
    # ONE atomic end-of-turn commit: session rotation, turn count, reply/
    # question/waiting_on, status, economics - all under the mutation lock.
    t, reason = _finish_turn(tid, sid, result, meta, log)
    # Auto-compact-and-continue: if this turn left the context near the brim,
    # verdict the session NOW (one bounded /compact on the same session) so the
    # next steer keeps headroom and the thread stays continuous - never a
    # dead-end or a fresh-session overflow. Best-effort, self-verifying.
    try:
        t = _maybe_compact(t, log) or t
    except Exception as _e:
        log.log("note", "auto-compact skipped: %s" % str(_e)[:200])
    import notify
    notify.card_event(t, reason)
    # FAST-TRACK = ship EVERY finished turn, hands-free. The flag used to fire
    # only when the OWNER dragged the card to Review - which is exactly the
    # manual push fast-track exists to remove ("man muss immer noch schieben,
    # also kein Vorteil"). Now a fast_track card SUBMITS ITSELF when its turn
    # ends: gate -> merge -> deploy hook run in the background, and the change
    # is testable without touching the board. The gate still guards (red gate
    # bounces back with the report), a pending question still parks the card
    # (the owner's decision comes first), and a turn that produced NOTHING new
    # to ship is skipped so a chat-only turn can't close the card.
    _maybe_fast_track_ship(t, log)
    return t


def _maybe_fast_track_ship(t, log):
    """Fast-track = every finished turn is DEPLOYED for testing while the card
    STAYS exactly where it is (owner: "keep the card in the same state but
    still deploy everything so I can test - not automatically review/done").
    So: background gate -> merge -> deploy, NO lane change, NO status change,
    the card never closes and the owner keeps steering the same session. The
    gate still guards main (red = no deploy, reasons in the chat); the accept
    flow on Review stays the human judgement it always was."""
    if not (t.get("fast_track") and not t.get("machine")
            and t.get("status") == "needs_you" and not t.get("question")):
        return
    wt = t.get("worktree") or ""
    if not os.path.isdir(wt):
        return
    # anything to ship? dirty tree OR branch commits not yet in the integration
    rc, dirty, _ = _git_try(wt, "status", "--porcelain")
    ahead = False
    integ = _current_branch(t.get("repo") or "")
    if integ and t.get("branch"):
        ahead = _git_try(t["repo"], "merge-base", "--is-ancestor",
                         t["branch"], integ)[0] != 0
    if not ((rc == 0 and dirty) or ahead):
        return                          # chat-only turn - nothing to deploy
    tid = t["id"]
    log.log("note", "FAST-TRACK: Turn fertig -> Gate + Merge + Deploy im Hintergrund. "
            "Die Karte bleibt in Arbeit.")

    def _ship():
        from actionlog import ActionLog
        import events
        lg = ActionLog(t["run_dir"])
        try:
            if _autocommit(t) == "markers":
                lg.log("note", "FAST-TRACK: offene Konfliktmarkierungen - nicht deployed.")
                return
            ok, problems = _gate(t)
            events.emit("gate", tid, ok=ok, source="fast-track")
            if not ok:
                lg.log("note", "FAST-TRACK: Gate rot - NICHT deployed, Karte bleibt "
                       "in Arbeit. Grund:\n%s" % "\n".join(problems)[:500])
                return
            accept_ok, kind, msg = _merge_to_main(t)
            events.emit("merge", tid, ok=bool(accept_ok), outcome=kind,
                        detail="fast-track: " + (msg or "")[:200])
            if not accept_ok:
                lg.log("note", "FAST-TRACK: Merge nicht moeglich (%s) - nicht deployed. %s"
                       % (kind, (msg or "")[:300]))
                return
            hk = _repo_hook(t, "deploy")   # None = no hook configured
            # PERSIST the hook outcome - _repo_hook ran on THIS thread's local
            # `t` copy (a subprocess call, kept outside the mutation lock), the
            # same reason move_lane's _land() persists it post-hook. Without
            # this the field only ever lived in this thread's dict and never
            # reached the DB, so _pending_context's next-steer surfacing of
            # deploy_hook (added for exactly this failure mode) was silently a
            # no-op for every fast-track ship - the worker still never saw it.
            _hooks = {k: t[k] for k in ("preview_hook", "deploy_hook") if k in t}
            if _hooks:
                _mutate(tid, lambda tt: tt.update(_hooks))
            lg.log("note", "FAST-TRACK deployed (%s)%s - teste auf dem Handy; die Karte "
                   "bleibt in Arbeit, steuern geht einfach weiter."
                   % (kind, " · ACHTUNG: Deploy-Hook rot" if hk is False else ""))
            if hk is False:
                _try_auto_fix_deploy(t, lg)
            elif hk is True:
                _mutate(tid, lambda tt: tt.pop("deploy_fail_streak", None))
        except Exception as e:
            try:
                lg.log("note", "FAST-TRACK fehlgeschlagen: %s" % str(e)[:250])
            except Exception:
                pass
    _threading.Thread(target=_ship, daemon=True).start()


_DEPLOY_FIX_CAP = 3   # matches turnopts.ESCALATE_TURNS - the gate thrash-guard's cap


def _try_auto_fix_deploy(t, lg):
    """A fast-track deploy hook failure (in practice: a native build broke,
    like a Gradle task blowing up) already landed on main by the time we see
    it - the merge already happened, only the build/distribute step failed.
    Left alone, that just sits as a red note until the owner happens to
    notice - unattended is the whole point of fast-track, so make the repair
    unattended too: feed the worker the actual error and let it try to fix it,
    same as it already would for a red gate. Bounded (never more than
    _DEPLOY_FIX_CAP attempts in a row) so a genuinely, persistently broken
    build doesn't burn turns forever without the owner ever finding out -
    mirrors the existing gate thrash-guard in _pending_context."""
    tid = t["id"]
    streak = (t.get("deploy_fail_streak") or 0) + 1
    _mutate(tid, lambda tt: tt.__setitem__("deploy_fail_streak", streak))
    if streak > _DEPLOY_FIX_CAP:
        lg.log("note", "FAST-TRACK: Deploy-Hook %dx in Folge rot - kein automatischer "
               "Reparaturversuch mehr, wartet auf dich." % (streak - 1))
        return
    tail = ((t.get("deploy_hook") or {}).get("tail") or "")[:1200]
    instr = ("FAST-TRACK deploy hook FAILED after your last change was already merged "
             "to main (repair attempt %d/%d - stops auto-retrying past this). This "
             "usually means a native build broke. Actual error:\n\n%s\n\nInvestigate and "
             "fix it. Your next turn's fast-track ship retries the deploy automatically "
             "once you've committed a fix." % (streak, _DEPLOY_FIX_CAP, tail))
    lg.log("note", "FAST-TRACK: Deploy-Hook rot - Worker bekommt den Fehler automatisch "
           "zur Reparatur (Versuch %d/%d)." % (streak, _DEPLOY_FIX_CAP))
    steer(tid, instr, actor="fast-track", source="fast-track-deploy-fix")


def answer_question(tid, answers, request_id="", actor="owner"):
    """Answer the worker's pending multiple-choice question (Phase 2.4).

    The owner's pick becomes the next steer, so the SAME session continues via
    `--resume` with the decision in hand - the turn is resumed, not restarted,
    and the card never parks on a question nobody could answer.

    `request_id` is the optimistic-concurrency guard: the app sends back the id
    it rendered, so a stale panel (the worker asked again, or another device
    already answered) is rejected instead of steering the worker with an answer
    to a question it has moved past.

    The answer is either one of the worker's offered labels or the owner's own
    free text (the Paseo 'Other' escape hatch) - see ask.validate_answers. Free
    text is no injection risk: the owner is authenticated and could type the
    same thing through /steer anyway."""
    import ask
    # CLAIM the question atomically via _mutate (the per-card MUTATION lock,
    # deliberately NOT the turn lock - answering ends in a steer, whose turn
    # holds that one). Answering is backgrounded by the server, so two quick
    # taps are two threads: without this both could read the same pending
    # question and steer the worker twice with contradictory decisions.
    # Clearing it here - not leaving it to steer() - makes the second caller
    # lose deterministically. A raise inside fn aborts before the save, so an
    # invalid answer leaves the panel standing.
    box = {}

    def _claim(t):
        q = t.get("question")
        if not q:
            raise RuntimeError("no pending question on this card")
        if request_id and request_id != q.get("id"):
            raise RuntimeError("this question was already answered or replaced")
        picks, err = ask.validate_answers(q, answers)
        if err:
            raise ValueError(err)          # invalid: leave the panel standing
        box["q"], box["picks"] = q, picks
        t.pop("question", None)
    t = _mutate(tid, _claim)
    if t is None:
        raise RuntimeError("no such track: " + tid)
    q, picks = box["q"], box["picks"]
    from actionlog import ActionLog
    ActionLog(t["run_dir"]).log("note", ask.answer_note(picks))
    import events
    events.emit("answer", tid, actor=actor, qkind=q.get("kind"),
                picks=[ask._pick_parts(p) for p in picks])
    # steer() clears the pending question itself and runs the turn under the
    # per-card lock, so the worker continues with the decision.
    return steer(tid, ask.answer_prompt(picks), actor=actor, source="answer")


# -- AUTO-CONTINUE on background completion (Paseo adoption, Phase 2.5) -------
# A turn that ends while a worker-launched background task is still running used
# to park the card in needs_you limbo: the owner had nothing to do, and nothing
# would ever wake the card again - the finished build just sat there. Now the
# harness watches for the task to finish and continues the card ITSELF.
#
# The completion signal is the runtime's own: Claude Code injects a
# <task-notification> carrying the originating tool-use-id when a background
# task ends, and claude_sessions.background_wait() reads exactly that. So this
# fires on positive evidence of completion, never on a timer - and when the
# evidence never arrives the card simply keeps its honest "waiting on a
# background task" cue instead of being auto-steered on a guess.

_BG_POLL_S = 20.0            # how often the watcher re-reads the transcripts
_BG_MAX_WAIT_S = 6 * 3600    # stop watching a task that never reports (6h)
_bg_watcher_started = False


def _bg_continue_on(t):
    """policy.auto_continue (default on). Off => the card keeps the cue but is
    never steered automatically."""
    import events
    pol = events.settings().get("policy") or {}
    return bool(pol.get("auto_continue", True))


def _continue_prompt():
    """Tagged as harness-injected so the card feed renders it as a system note
    instead of a message the owner appears to have typed (ask.harness_msg)."""
    import ask
    return ask.harness_msg(
        "background-done",
        "Dein Hintergrund-Task ist fertig - das hier ist ein automatischer "
        "Hinweis des Harness, keine Nachricht vom Owner.\n"
        "Hol dir seine Ausgabe (BashOutput bzw. das Task-Ergebnis) und arbeite "
        "genau dort weiter, wo du auf ihn gewartet hast. Wenn die Ausgabe zeigt, "
        "dass etwas fehlgeschlagen ist, behebe es oder sag klar, was der Owner "
        "entscheiden muss.")


def _sweep_background():
    """One pass: continue every card whose background task has finished.

    Two jobs with DIFFERENT gates, and they must not share one. Keeping
    waiting_on honest - orphan reconciliation, the give-up window, clearing the
    cue once nothing is outstanding - runs for EVERY waiting card. Only the
    auto-steer is gated on lane + policy.auto_continue. They used to be gated
    together, so a card with auto_continue off (or parked outside
    working/review) kept its "wartet auf Hintergrund-Task" cue forever after
    the tasks were long done - and with it the idle-eviction protection
    (drivers._running_cards), leaking the very session it no longer needed."""
    for t in _load():
        if t.get("waiting_on") != "background" or t.get("status") == "running":
            continue
        # ORPHAN reconciliation (finishAll): a background task is a child of the
        # worker process. If this daemon holds NO live session for the card (a
        # restart wiped the registry, or the worker crashed) and no turn is in
        # flight, the tasks died with their parent - flip the still-running ones
        # to 'canceled' NOW instead of parking the card for the full 6h. The
        # continue-on-clear path below then resumes the worker to pick up.
        import drivers
        if not drivers.has_session(t["id"]) and not drivers.turn_active(t["id"]):
            if reconcile_bg(t["id"]):
                t = _find(_load(), t["id"]) or t
        since = ((t.get("background") or {}).get("since")
                 or _epoch_of(t.get("updated")) or time.time())
        if time.time() - since > _BG_MAX_WAIT_S:
            def _giveup(tt):
                if tt.get("waiting_on") != "background":
                    return False
                tt["waiting_on"] = "you"     # give up watching, hand it back
                tt.pop("background", None)
            _mutate(t["id"], _giveup)
            continue
        import claude_sessions
        try:
            state, _payload = claude_sessions.background_state(t)
        except Exception:
            continue                          # try again next pass
        # Continue ONLY on positive evidence that the transcript was read and
        # nothing is outstanding. "unknown" (missing/rotated transcript) must
        # never be mistaken for "the build finished" - that would spend a real
        # turn of the owner's money on a guess.
        if state != "clear":
            continue
        # Clear the claim BEFORE steering: that is what stops the next pass from
        # firing this card a second time, and it is why the steer can safely be
        # detached below. The in-lock recheck makes a racing second watcher pass
        # lose deterministically.
        claim = {}

        def _claim(tt):
            if tt.get("waiting_on") != "background":
                return False
            tt["waiting_on"] = "you"
            tt.pop("background", None)
            claim["ok"] = True
        _mutate(t["id"], _claim)
        if not claim.get("ok"):
            continue
        from actionlog import ActionLog
        # steer only ACTIVE work, and only if the owner allows auto-continue;
        # otherwise the cue is cleared (above) and the card honestly waits on
        # the owner instead of on a task that has already reported.
        if t.get("lane") not in ("working", "review") or not _bg_continue_on(t):
            ActionLog(t["run_dir"]).log(
                "note", "Hintergrund-Task fertig - Karte wartet auf dich "
                "(kein Auto-Continue)")
            continue
        ActionLog(t["run_dir"]).log(
            "note", "Hintergrund-Task fertig - Karte laeuft automatisch weiter")
        import events
        events.emit("autocontinue", t["id"], actor="daemon")

        # A continuation is a full turn (up to 1800s). Run it OFF the watcher
        # thread - held inline, one long build's follow-up would stall the whole
        # loop, so a second card finishing behind it would wait out that entire
        # turn before anyone noticed. Per-card serialisation still holds: _turn
        # takes the card's own lock.
        def _go(tid=t["id"]):
            try:
                steer(tid, _continue_prompt(), actor="daemon", source="background-task")
            except Exception as e:
                print("auto-continue failed for %s: %s" % (tid, e))

        _threading.Thread(target=_go, daemon=True).start()


def _epoch_of(stamp):
    try:
        return time.mktime(time.strptime(stamp, "%Y-%m-%d %H:%M:%S"))
    except (TypeError, ValueError):
        return None


def start_background_watcher(interval=None):
    """Start the auto-continue loop (idempotent). Called from server.serve."""
    global _bg_watcher_started
    if _bg_watcher_started:
        return
    _bg_watcher_started = True
    iv = _BG_POLL_S if interval is None else interval
    import threading

    def loop():
        while True:
            time.sleep(iv)
            try:
                _sweep_background()
            except Exception as e:
                print("background watcher error:", e)

    threading.Thread(target=loop, daemon=True).start()


def adopt_session(session_id, cwd, mode="continue", first="", actor="owner"):
    """Bring an existing Claude Code session (from ~/.claude) onto the board.
      mode="continue": wrap it IN PLACE as a card - no new branch/worktree; the
        card's steer resumes the exact session (`claude --resume`) in its own cwd.
      mode="fork": open a NEW branch + worktree from that repo with a fresh
        session, seeded with the original's starting request (source untouched).
    No git commit is made either way - tracking is the card's audit trail; a fork
    creates a branch pointer, real commits come only when the agent commits code."""
    import events
    cwd = os.path.abspath(cwd)
    if not os.path.isdir(cwd):
        raise RuntimeError("session working dir not found: " + cwd)
    # one session = one card (the Paseo invariant). Two cards sharing a
    # session id would both mirror the same ever-growing conversation. The
    # CHAIN counts too: a rotated-away session is that card's own history
    # (read_transcript_live renders it); adopting it would spawn a second card
    # writing into the middle of another card's conversation. lane=done stays
    # exempt (deliberate: finished work releases its session for re-adoption) -
    # the UI still LINKS those to the owning card instead, which is the better
    # flow (open the card, steer it), but the API keeps the escape hatch.
    for ex in _load():
        if ex.get("lane") == "done":
            continue
        if session_id == ex.get("session_id") \
                or session_id in (ex.get("session_chain") or []):
            raise RuntimeError("session already on the board as card " + ex["id"])
    short = (session_id or "sess")[:8]

    if mode == "fork":
        task = ("Fork of a prior Claude Code session in this repo. Original "
                "starting request:\n\n" + (first or "(unknown)")
                + "\n\nContinue that line of work here.")
        t = new_track(cwd, "fork-" + short, task, lane="backlog", actor=actor)
        def _stamp(tt):
            tt["forked_from"] = session_id
        return _mutate(t["id"], _stamp) or t

    # continue: a card that IS the existing session, running in its own cwd
    tid = _unique_id("adopt-" + short)
    run_dir = os.path.join(REC, tid); os.makedirs(run_dir, exist_ok=True)
    branch = _current_branch(cwd) or "(no git)"
    t = {"id": tid, "repo": cwd, "branch": branch, "worktree": cwd,
         "task": (first or "Continued Claude Code session")[:400],
         "client": "", "session_id": session_id, "perm": DEFAULT_PERM,
         "lane": "working", "status": "needs_you", "turns": 0, "run_dir": run_dir,
         "last_reply": "", "value": events.settings()["value_per_card"],
         "driver": "claude", "priority": "medium", "due": "", "rank": None,
         "model": "", "attachments": [], "adopted": True,
         # remembered so the first steer forks AWAY from the source session
         # instead of writing into the desktop's live conversation
         "adopted_source": session_id,
         "ai_cost": 0.0, "tokens_in": 0, "tokens_out": 0, "models": [],
         "created": time.strftime("%Y-%m-%d %H:%M:%S"),
         "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
    from actionlog import ActionLog
    ActionLog(run_dir).log("note", "ADOPTED Claude session %s (cwd %s)" % (session_id, cwd))
    events.emit("filed", tid, branch=branch, value=t["value"], actor=actor, driver="claude")
    _save_track(t)
    return t


def reorder(ids, actor="owner"):
    """Persist manual card order. rank = position in the given (single-lane)
    ordered id list; the board sorts by rank first, so this overrides the
    computed priority/due order - 'policy is data', order is now data too."""
    changed = 0
    for i, tid in enumerate(ids):
        def _rank(tt, i=i):
            if tt.get("rank") == i:
                return False
            tt["rank"] = i
        t = _mutate(tid, _rank)
        if t and t.get("rank") == i:
            changed += 1
    return {"reordered": changed}


def cancel_turn(tid, actor="owner"):
    """Stop a running turn (the composer's Stop button). Kills the driver
    subprocess; the turn returns as '(cancelled)'. Audit records it.

    If there is NO live session but the card is still flagged running, it is a
    ZOMBIE: a turn that died between daemon restarts (a 1800s kill, a driver
    crash) leaves status=running with no owning worker, and the old behaviour -
    cancel returns false, do nothing - left the phone watching a frozen card with
    a spinner that Stop could never clear. Now Stop unfreezes it exactly like the
    startup sweep does (bounce + resend note), so the button always does
    something instead of no-oping on a dead session."""
    import drivers, events
    killed = drivers.cancel(tid)
    if killed:
        events.emit("touch", tid, touch="cancel", actor=actor)
        t = get_track(tid)
        if t:
            from actionlog import ActionLog
            ActionLog(t["run_dir"]).log("note", "turn CANCELLED by %s" % actor)

            # Reset the card OFF "running" here. Normally the steer thread does
            # this when _turn returns after the kill, but a racing/dead steer
            # thread (a daemon restart, overlapping cancels) can leave it stuck
            # at running with no session - a frozen spinner. The turn is
            # cancelled; it's the owner's move now. Through _mutate, so this
            # write and the steer thread's settle can interleave in any order
            # and the end state is still needs_you (invariant I3).
            def _settle(tt):
                if tt.get("status") != "running":
                    return False
                tt["status"] = "needs_you"
            _mutate(tid, _settle)
        return {"cancelled": True}
    # no live session - clear a stuck/zombie card so Stop is never a no-op, and
    # promote the interrupted session so re-steering RESUMES it losslessly.
    t = get_track(tid)
    if t and t.get("status") == "running" and not drivers.has_session(tid):
        box = {}

        def _unfreeze(tt):
            if tt.get("status") != "running" or drivers.has_session(tid):
                return False             # settled (or respawned) since the check
            box["resumable"] = _promote_live_session(tt)
            box["note"] = RESUME_NOTE if box["resumable"] else ZOMBIE_NOTE
            tt["status"] = "bounced"
            tt["gate_report"] = _interrupt_note_report(tt, box["note"])
        _mutate(tid, _unfreeze)
        if "note" in box:
            try:
                from actionlog import ActionLog
                ActionLog(t["run_dir"]).log("note", "STOP on a dead session - " + box["note"])
            except Exception:
                pass
            events.emit("bounce", tid, reason="stopped_zombie", actor=actor)
            return {"cancelled": True, "unfroze": True, "resumable": box["resumable"]}
    return {"cancelled": killed}


ZOMBIE_NOTE = "daemon restarted mid-turn - resend the last instruction"
RESUME_NOTE = "Turn unterbrochen - erneut steuern setzt den Kontext fort"
_BOUNCE_ESCALATE_AT = 3   # consecutive daemon-restart bounces before the note stops
                          # inviting a doomed retry and says so plainly instead


def _interrupt_note_report(t, note):
    """gate_report is the channel the worker is fed on the next steer
    (_pending_context). An interrupt (zombie sweep / Stop on a dead session) must
    NOT clobber a REAL gate/merge failure that was already there - overwriting it
    with 'daemon restarted mid-turn' leaves the worker blind, chasing a phantom
    cause across 2-3 dead-end steers. Prepend the interrupt note but PRESERVE any
    substantive prior failure lines (dropping only stacked interrupt notes)."""
    prior = [l for l in (t.get("gate_report") or [])
             if RESUME_NOTE not in l and ZOMBIE_NOTE not in l]
    return [note] + prior


def _promote_live_session(t):
    """Paseo-style LOSSLESS resume. A turn that died WITH the daemon (a restart, a
    crash) emitted a rotated `claude --resume` session id to run_dir/
    live_session.txt, but the track's session_id is only written back AFTER a turn
    returns - so a killed turn leaves the card pointing at the PRE-steer session.
    The next steer would then --resume the old conversation and lose the
    interrupted turn's context. Promoting the live session id fixes that: the next
    steer resumes the actual interrupted conversation. This is why Paseo can idle
    a session and silently continue it; we now keep the same context, just surfaced
    (the owner re-steers to continue). Returns True if a newer session was promoted."""
    rd = t.get("run_dir") or ""
    if not rd:
        return False
    try:
        with open(os.path.join(rd, "live_session.txt"), encoding="utf-8") as f:
            live = f.read().strip()
    except OSError:
        return False
    if live and live != t.get("session_id"):
        t["session_id"] = live
        return True
    return False

def _track_idle_s(t):
    """Seconds since the card last showed ANY activity (its flight-recorder /
    live-session files). Distinguishes a true zombie from the brief steer-START
    window where status is already 'running' but the session is still spawning
    (has_session False for ~1s). Unknown -> treated as very idle."""
    rd = t.get("run_dir") or ""
    newest = 0.0
    for f in ("actions.jsonl", "live_session.txt", "live_partial.txt"):
        try:
            newest = max(newest, os.path.getmtime(os.path.join(rd, f)))
        except OSError:
            pass
    return (time.time() - newest) if newest else 1e9


PRESENT_IDLE_S = 45      # spawn window: a just-started steer may briefly show
                         # running before its turn registers - don't coerce it


def present(t):
    """READ-side lifecycle derivation for the API (Paseo's normalizeArchivedStatus,
    server-side): a stored 'running' is only ever DELIVERED as running while a
    turn is actually in flight (drivers.turn_active). Otherwise - once past the
    spawn window - the client gets 'needs_you', WITHOUT touching the stored
    value. A phantom spinner is thereby impossible no matter what any write race
    puts in the DB (invariant I2); the reconciler remains the healer of the
    stored value. Returns a copy when coercing, the original otherwise."""
    if (t or {}).get("status") != "running":
        return t
    import drivers
    if drivers.turn_active(t["id"]):
        return t
    if _track_idle_s(t) <= PRESENT_IDLE_S:
        return t                       # spawn window - let it settle
    out = dict(t)
    out["status"] = "needs_you"
    out["status_derived"] = True       # marker: coerced at read, not stored
    return out


def sweep_zombies(min_idle_s=0):
    """Reconcile status vs the live session: a card flagged status=running with no
    owning worker is a ZOMBIE (its turn died with a prior daemon, or a dead/racing
    steer thread left it stuck). Flip every such track to bounced with a visible
    note (gate_report is the bounce-reason channel both UIs already render), audit
    it, and push - so the owner learns the instruction was lost instead of staring
    at a frozen card.

    min_idle_s=0 at startup (every running-without-session card died with the old
    daemon - reap all). The PERIODIC reconciler passes min_idle_s>0 so it skips the
    steer-start race window and only reaps cards genuinely idle that long.

    Paseo-parity (the loss is now RECOVERABLE): before surfacing, promote the
    interrupted session id (run_dir/live_session.txt) onto the track, so
    re-steering RESUMES the interrupted conversation instead of the pre-steer
    one. We still surface it (bounce is re-steerable, and async push-driven
    ownership wants the owner to know a turn was cut) - but the context is no
    longer thrown away, which is what made Paseo's silent idle-resume feel
    seamless. Cards with a promotable session get the resume note."""
    import drivers, events, notify
    from actionlog import ActionLog
    swept = []
    for t in _load():
        # STARTUP (min_idle_s==0): every worker tree died with the old daemon -
        # so did every background agent inside it. A registry entry surviving
        # here is a zombie by construction: clear it (with a visible note) so
        # the card doesn't wait on a task that can never report.
        if not min_idle_s and isinstance(t.get("bg_tasks"), dict) \
                and not drivers.has_session(t["id"]):
            names = ", ".join((v.get("title") or v.get("desc") or "task")
                              for v in t["bg_tasks"].values() if v.get("status", "running") == "running")[:120]
            # reconcile (finishAll), don't DELETE: the descriptors survive as
            # 'canceled' so the owner can still see what the worker was running
            # and that the restart ended it (Paseo clickable history). Only the
            # waiting_on gate is cleared so the card is handed back.
            n = reconcile_bg(t["id"], why="Mit dem Daemon-Neustart abgebrochen")
            _mutate(t["id"], lambda tt: tt.__setitem__("waiting_on", "you")
                    if tt.get("waiting_on") == "background" else None)
            if n:
                try:
                    ActionLog(t["run_dir"]).log(
                        "note", "Hintergrund-Task(s) mit dem Daemon-Neustart abgebrochen: %s "
                        "- steuern startet sie neu." % names)
                except Exception:
                    pass
        st = t.get("status")
        if st == "running":
            # genuinely working = a TURN is in flight (Paseo: "running" is a
            # derived observation, not a stored flag). has_session() was the
            # old test and it lied by design: a soft cancel keeps the worker
            # process alive for --resume, so an idle-after-cancel worker looked
            # busy forever and the frozen card was never swept ("stuck again").
            if drivers.turn_active(t["id"]) or (min_idle_s and _track_idle_s(t) < min_idle_s):
                continue
            if drivers.has_session(t["id"]):
                # Worker alive, NO turn in flight: the turn already ended (or
                # was cancelled) and a racing status write resurrected
                # 'running'. Nothing died and nothing was lost - settle QUIETLY
                # to needs_you (Paseo's running->idle on turn end), no bounce,
                # no zombie note. Re-steering resumes the live session as-is.
                did = {}

                def _settle(tt):
                    # in-lock recheck: a turn may have started (or the steer
                    # thread settled it) since the snapshot above
                    if tt.get("status") != "running" or drivers.turn_active(tt["id"]):
                        return False
                    tt["status"] = "needs_you"
                    did["ok"] = True
                t2 = _mutate(t["id"], _settle)
                if not did.get("ok"):
                    continue
                t = t2
                try:
                    ActionLog(t["run_dir"]).log(
                        "note", "SETTLED - Turn war schon beendet, Status hing auf "
                        "'running' (Schreib-Rennen). Session lebt - einfach weiter steuern.")
                except Exception:
                    pass
                events.emit("settle", t["id"], reason="stale_running", actor="daemon")
                try:
                    notify.card_event(t, "needs_you")
                except Exception:
                    pass
                swept.append(t["id"])
                continue
        elif st == "gating":
            # the gate runs SYNCHRONOUSLY in a request thread (no session to check),
            # so a restart mid-gate freezes the card at 'gating' forever. Reap it -
            # but only once idle past a real gate's runtime (~2min) so a legit slow
            # gate is never cut. 0 at startup (a gating card then died with the daemon).
            if _track_idle_s(t) < (120 if min_idle_s else 0):
                continue
        else:
            continue
        box = {}
        # Repeated-bounce evidence BEFORE this one is recorded, so a card that
        # keeps taking the daemon down with it (not just failing its own turn)
        # gets told apart from an ordinary one-off restart. Derived from the
        # event trail (consecutive_gate_fails' pattern), never a stored flag.
        prior_bounces = events.consecutive_bounces(t["id"])

        def _bounce(tt, st=st):
            if tt.get("status") != st:
                return False             # settled by another writer meanwhile
            note = RESUME_NOTE if _promote_live_session(tt) else ZOMBIE_NOTE
            if prior_bounces + 1 >= _BOUNCE_ESCALATE_AT:
                note = ("daemon restarted mid-turn %dx IN A ROW on this card - "
                         "resending the same instruction has failed repeatedly and "
                         "is likely to fail again (the session itself may be too "
                         "large/expensive to resume, or stuck in a loop). Do not "
                         "just retry - fork this card into a fresh session, or ask "
                         "the owner what to do." % (prior_bounces + 1))
            box["note"] = note
            tt["status"] = "bounced"
            tt["gate_report"] = _interrupt_note_report(tt, box["note"])
        t = _mutate(t["id"], _bounce) or t
        if "note" not in box:
            continue
        try:
            ActionLog(t["run_dir"]).log("note", "ZOMBIE SWEEP - " + box["note"])
        except Exception:
            pass
        events.emit("bounce", t["id"], reason="daemon_restart", actor="daemon")
        try:
            notify.card_event(t, "bounced")
        except Exception as e:
            print("sweep_zombies: push failed for %s: %s" % (t["id"], e))
        swept.append(t["id"])
    return swept


def start_zombie_reconciler(interval=20, min_idle_s=45):
    """Reconcile status vs the live session CONTINUOUSLY (Paseo-parity), not just at
    boot. HelmDeck's `status` is a STORED field a thread must remember to clear; if
    that thread dies or races (a daemon restart mid-turn, overlapping Stop presses
    whose cancel didn't reset status), the card sits frozen at 'running' with no
    session and, because sweep_zombies only ran at startup, NOTHING noticed until the
    next restart. Paseo derives lifecycle from the live run and sweeps every 15s, so
    it self-heals; this background pass gives HelmDeck the same - a stuck card is
    caught within ~`interval`s. The idle guard skips the steer-start window so a
    legitimately-spawning turn is never falsely reaped. Idempotent."""
    import threading
    def _loop():
        while True:
            time.sleep(interval)
            try:
                swept = sweep_zombies(min_idle_s=min_idle_s)
                if swept:
                    print("RECONCILER: bounced %d stuck running card(s): %s"
                          % (len(swept), ", ".join(swept)), flush=True)
            except Exception as e:
                print("zombie reconciler error: %s" % e, flush=True)
    threading.Thread(target=_loop, daemon=True).start()


EDITABLE = ("task", "description", "priority", "due", "value", "client", "driver",
            "project_id", "billing", "rate", "autopilot", "fast_track")
# project_id may be explicitly cleared (unassign from a project) - unlike the
# other fields, "" / null is a meaningful value here, not "leave unset".
CLEARABLE = ("project_id",)
# "autopilot" is a card's own flag, NOT a mode: `mode` is already overloaded
# (execution mode for process steps, then the completion statistic auto/assisted
# written on accept by events._completion_mode), so the opt-in gets its own key
# and can never be set as a side effect of a touch-free acceptance.
# For the same reason a CARD's mode is never compared against
# policy.auto_dispatch_modes (that gates process STEPS in processes.sync):
# card dispatch only excludes the needs-a-person modes human/teach/cowork,
# so the 'auto' stat on an accepted card can never block a (re)dispatch
# (test_mode_dispatch.py pins this).
BOOLFIELDS = ("autopilot", "fast_track")

def archive_track(tid, on=True, actor="owner"):
    """Reversible: hides the card from work views; economics and audit stay."""
    import events

    def _flag(tt):
        tt["archived"] = bool(on)
    t = _mutate(tid, _flag)
    if not t:
        raise RuntimeError("no such track: " + tid)
    events.emit("archive", tid, on=bool(on), actor=actor)
    from actionlog import ActionLog
    log = ActionLog(t["run_dir"])
    log.log("note", ("ARCHIVED" if on else "UNARCHIVED") + " by " + actor)
    if on:
        # Archiving is terminal for work views - reclaim the isolation. Safe by
        # construction: a dirty tree is kept, an unmerged branch is kept (only
        # the regenerable worktree of a landed/clean card goes).
        reclaim_worktree(t, log)
    return t

def delete_track(tid, actor="owner"):
    """Destructive but bounded: removes the card, its worktree and branch.
    The audit trail is NOT deletable - events and the recording stay."""
    import events
    tracks = _load()
    t = _find(tracks, tid)
    if not t:
        raise RuntimeError("no such track: " + tid)
    if t.get("worktree") and os.path.exists(t["worktree"]):
        subprocess.run(["git", "-C", t["repo"], "worktree", "remove", "--force",
                        t["worktree"]], capture_output=True, text=True)
    if _branch_exists(t["repo"], t["branch"]):
        subprocess.run(["git", "-C", t["repo"], "branch", "-D", t["branch"]],
                       capture_output=True, text=True)
    _db.track_delete(tid)
    events.emit("delete", tid, branch=t["branch"], task=t["task"][:80], actor=actor)
    return {"deleted": tid}

def update_track(tid, patch, actor="owner"):
    """Edit a card's request fields after creation. Only benign fields -
    lane/status/economics move through their own verbs.

    "driver" is technically in EDITABLE (a card can switch execution engine
    after filing - e.g. claude -> claude-desktop to grant windows-mcp/GUI
    control) but it is NOT benign like the others: it's a capability grant,
    not a request-detail edit. This function is the ONE place that field is
    ever written (server.py's /tracks/<id>/update and copilot.py's
    set_driver action both route through here), so its guards apply
    regardless of caller - role-gating still belongs to the caller (mirrors
    fast_track/resolve_conflict: policy.chat_admin_roles checked BEFORE
    calling this), but "is this even a real driver" and "not mid-turn" are
    invariants no caller should be able to skip."""
    import events
    if "driver" in patch and patch["driver"] is not None:
        valid = set((events.settings().get("drivers") or {}).keys())
        if patch["driver"] not in valid:
            raise ValueError("unknown driver '%s' - choices: %s"
                              % (patch["driver"], ", ".join(sorted(valid)) or "(none configured)"))
        import drivers
        if drivers.turn_active(tid):
            raise RuntimeError("cannot change driver while a turn is running - wait for it to finish")
    changed = {}

    def _edit(t):
        for k in EDITABLE:
            if k not in patch:
                continue
            v = patch[k] or None if k in CLEARABLE else patch[k]
            if k not in CLEARABLE and v is None:
                continue
            if k in BOOLFIELDS:
                v = bool(v)      # "off" arrives as false/0/"" - never as a string
            if v == t.get(k):
                continue
            t[k] = float(v) if k in ("value", "rate") and v is not None else v
            changed[k] = t[k]
        if not changed:
            return False
    t = _mutate(tid, _edit)
    if not t:
        raise RuntimeError("no such track: " + tid)
    if changed:
        events.emit("edit", tid, actor=actor, fields=changed)
        from actionlog import ActionLog
        log = ActionLog(t["run_dir"])
        log.log("note", "EDITED by %s: %s" % (actor, ", ".join(changed)))
        # Visible capability-grant note (never a silent change) whenever the
        # NEW driver carries windows-mcp - the card's agent gains real
        # desktop/GUI control from here on, and every future turn on this
        # driver is screen-recorded (see events.py DEFAULTS["drivers"]).
        if "driver" in changed:
            dcfg = (events.settings().get("drivers") or {}).get(changed["driver"]) or {}
            if "mcp__windows-mcp__*" in (dcfg.get("allowed_tools") or []):
                log.log("note", "⚠ Desktop-Zugriff aktiviert (%s) von %s - "
                        "der Agent kann jetzt Maus/Tastatur/Bildschirm steuern, "
                        "Turns werden aufgezeichnet." % (changed["driver"], actor))
            # A driver's tool grant is baked into the argv at spawn and can't be
            # hot-swapped on a live process (drivers.apply_opts refuses it). The
            # guard above already blocked the change if a turn was in flight, so
            # any surviving session is IDLE - drop it now instead of leaving the
            # stale old-grant process to linger until the next turn notices. The
            # flip then takes hold on the very next message with no ghost process.
            import drivers as _drivers
            _drivers.drop_session(tid)
        # Flipping fast_track ON is itself a ship trigger, not just future turns:
        # a card can already be sitting on a finished-but-undeployed turn (owner
        # enables fast-track AFTER the turn ended), and the hook in _run_turn
        # only fires at turn-end - without this the flag does nothing until the
        # NEXT turn completes, and the owner asks "why didn't it deploy" while
        # the worker (unaware fast-track exists) wrongly says to use Review.
        if changed.get("fast_track") is True:
            _maybe_fast_track_ship(t, log)
    return t

DIRECTIVES = os.path.join(ROOT, "board_directives.json")

def apply_board_directives():
    """One-shot board-data patches shipped as repo DATA (policy is data). A
    card worker is worktree-isolated and never touches the live DB, so a card
    whose deliverable is a board change ships it here; the DAEMON applies it at
    startup through update_track (audit event + actionlog note included).
    Each entry {"id", "card", "set": {...}} is applied ONCE - the entry id is
    recorded on the card - so a later owner edit is never overwritten on
    restart. Done cards are left alone (their fields are accounting by then)."""
    if not os.path.exists(DIRECTIVES):
        return 0
    try:
        with open(DIRECTIVES, encoding="utf-8") as f:
            entries = json.load(f)
    except ValueError as e:
        print("directives: unreadable board_directives.json:", e)
        return 0
    applied = 0
    for entry in entries:
        did, tid = entry.get("id"), entry.get("card")
        if not did or not tid:
            continue
        t = get_track(tid)
        if not t or did in (t.get("directives_applied") or []) or t.get("lane") == "done":
            continue
        try:
            update_track(tid, entry.get("set") or {}, actor="directive:" + did)
        except (RuntimeError, ValueError) as e:
            print("directives: %s failed: %s" % (did, e))
            continue
        _mutate(tid, lambda tt: tt.setdefault("directives_applied", []).append(did) or None)
        applied += 1
    if applied:
        print("directives: applied %d board directive(s)" % applied)
    return applied

def add_attachments(tid, attachments, actor="owner"):
    """Attach files (PDF etc.) to an existing card, Jira/Plane-style. Saved into
    the card's run_dir/.attachments and appended to the card's file list; the
    worker sees them on its next turn (prompt lists attached files)."""
    import turnopts, events
    t = _find(_load(), tid)
    if not t:
        raise RuntimeError("no such track: " + tid)
    new_paths = turnopts.save_attachments(t["run_dir"], attachments)
    if new_paths:
        def _attach(tt):
            tt["attachments"] = (tt.get("attachments") or []) + new_paths
        t = _mutate(tid, _attach) or t
        events.emit("edit", tid, actor=actor, fields={"attachments": len(new_paths)})
        from actionlog import ActionLog
        ActionLog(t["run_dir"]).log("note", "%s attached %d file(s)" % (actor, len(new_paths)))
    return t

def remove_attachment(tid, name, actor="owner"):
    """Detach a file from the card by its basename (leaves the file on disk -
    append-only audit; the card just stops referencing it)."""
    def _detach(t):
        before = t.get("attachments") or []
        t["attachments"] = [p for p in before if os.path.basename(p) != name]
        if len(t["attachments"]) == len(before):
            return False
    t = _mutate(tid, _detach)
    if not t:
        raise RuntimeError("no such track: " + tid)
    return t

def list_checkpoints(tid):
    """The per-turn rewind anchors recorded for this card (newest last)."""
    t = _find(_load(), tid)
    return (t or {}).get("checkpoints") or []

def rewind_files(tid, commit, actor="owner"):
    """Restore the worktree's FILES to a recorded checkpoint (reversible: the
    current state is snapshotted first, and git keeps the objects). Only a
    checkpoint this card recorded is accepted - never an arbitrary ref. The
    session/conversation is NOT touched; use fork for a fresh line from here."""
    t = _find(_load(), tid)
    if not t:
        raise RuntimeError("no such track: " + tid)
    wt = t.get("worktree")
    if not wt or not os.path.isdir(wt):
        raise RuntimeError("no worktree for this card")
    valid = {c.get("commit") for c in (t.get("checkpoints") or [])}
    if commit not in valid:
        raise RuntimeError("unknown checkpoint for this card")
    undo = _checkpoint(wt)                 # safety anchor of the current state
    _git(wt, "checkout", commit, "--", ".")
    if undo:
        def _anchor(tt):
            tt.setdefault("checkpoints", []).append(
                {"turn": tt.get("turns"), "commit": undo,
                 "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "reply": "(pre-rewind snapshot)"})
        _mutate(tid, _anchor)
    import events
    events.emit("rewind", tid, commit=commit[:12], undo=(undo or "")[:12], actor=actor)
    from actionlog import ActionLog
    ActionLog(t["run_dir"]).log("note", "REWOUND files to %s (undo %s) by %s"
                                % (commit[:8], (undo or "?")[:8], actor))
    return {"ok": True, "undo": undo}

def fork_conversation(tid, first="", actor="owner"):
    """Fork this card's LIVE CONVERSATION into a new sibling card: same context
    up to now, growing independently from here - so a crowded card (many
    unrelated threads steered into one) can be split without losing what it
    already knows. Different from fork_track (which forks the CODE at a ref
    with a FRESH session - no context carried).

    Mechanism: reuses the adopted_source pattern already proven for adopting an
    external Claude Code session (adopt_session, drivers.py:765) - the new card
    is seeded with the source's CURRENT session id, but adopted_source is set to
    that same id, so the driver's first spawn adds --fork-session. The CLI then
    clones the conversation into a FRESH session id on that first turn; the
    source card's own session is never touched or resumed-into. After that
    first turn, session_chain carries the pre-fork id, so the split-off card's
    transcript still SHOWS the shared history (read_transcript_live renders
    session_chain), then continues on its own below it - the owner sees exactly
    where the fork happened, not a history-less blank card.

    Isolation: a MACHINE card has no code-isolation model (its "worktree" is a
    real folder) - the new card shares the same cwd, same as filing two machine
    cards there today. A git card gets its OWN worktree (checked out at the
    source's CURRENT branch tip) so two cards never write into the same
    checkout at once - a chat split is not a licence for concurrent edits."""
    import events
    src = get_track(tid)
    if not src:
        raise RuntimeError("no such card: " + tid)
    sid = src.get("session_id")
    if not sid:
        raise RuntimeError("this card has no conversation yet to fork - steer it at least once first")
    new_id = _unique_id("chatfork")
    run_dir = os.path.join(REC, new_id)
    os.makedirs(run_dir, exist_ok=True)
    machine = bool(src.get("machine"))
    if machine:
        worktree = src.get("worktree", "")
        branch = src.get("branch", "(no git)")
    else:
        branch = "chatfork-" + _slug(src.get("branch", ""))[:20] + "-" + new_id.split("-")[-1][-4:]
        worktree = _worktree_for(src["repo"], branch)
        if os.path.exists(worktree):
            raise RuntimeError("fork worktree already exists")
        _git(src["repo"], "worktree", "add", worktree, "-b", branch, src.get("branch", "HEAD"))
    t = {"id": new_id, "repo": src["repo"], "branch": branch, "worktree": worktree,
         "machine": machine,
         "task": (first or ("Fork of the conversation from card %s" % tid))[:400],
         "client": src.get("client", ""), "session_id": sid,
         "perm": src.get("perm", DEFAULT_PERM), "lane": "working",
         "status": "needs_you", "turns": 0, "run_dir": run_dir, "last_reply": "",
         "value": src.get("value", 0), "driver": src.get("driver", "claude"),
         "priority": src.get("priority", "medium"), "due": src.get("due", ""),
         "model": "", "attachments": [],
         # remembered so the FIRST steer forks AWAY from the source session
         # instead of resuming into it (same guard adopt_session relies on)
         "adopted_source": sid,
         "forked_from": tid, "forked_from_session": sid,
         "ai_cost": 0.0, "tokens_in": 0, "tokens_out": 0, "models": [],
         "created": time.strftime("%Y-%m-%d %H:%M:%S"),
         "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
    from actionlog import ActionLog
    ActionLog(run_dir).log("note", "KONVERSATION FORKED von Karte %s (Session %s...)"
                           % (tid, sid[:8]))
    events.emit("chatfork", new_id, source_card=tid, session=sid, actor=actor)
    _save_track(t)
    return t


def fork_track(tid, from_ref="", actor="owner"):
    """Fork a NEW card from this card's state (its branch tip, or a specific
    commit hash). Append-only: creates a new branch/worktree/session off the
    ref; the source card is never modified. The forked worktree carries the
    code exactly as of `ref`."""
    import events
    src = get_track(tid)
    if not src:
        raise RuntimeError("no such card: " + tid)
    repo = src["repo"]
    ref = (from_ref or "").strip() or src["branch"]
    new_id = _unique_id("fork")
    branch = "fork-" + _slug(src["branch"])[:20] + "-" + new_id.split("-")[0][-4:]
    wt = _worktree_for(repo, branch)
    if os.path.exists(wt):
        raise RuntimeError("fork worktree already exists")
    _git(repo, "worktree", "add", wt, "-b", branch, ref)
    run_dir = os.path.join(REC, new_id)
    os.makedirs(run_dir, exist_ok=True)
    short = (from_ref[:8] + " of ") if from_ref else ""
    t = {"id": new_id, "repo": repo, "branch": branch, "worktree": wt,
         "task": "Forked from %s%s:\n\n%s" % (short, src["branch"], src["task"]),
         "client": src.get("client", ""), "session_id": None,
         "perm": src.get("perm", DEFAULT_PERM), "lane": "backlog",
         "status": "queued", "turns": 0, "run_dir": run_dir, "last_reply": "",
         "value": src.get("value", 0), "driver": src.get("driver", "claude"),
         "priority": src.get("priority", "medium"), "due": src.get("due", ""),
         "ai_cost": 0.0, "tokens_in": 0, "tokens_out": 0, "models": [],
         "forked_from": tid, "forked_ref": from_ref or "tip",
         "created": time.strftime("%Y-%m-%d %H:%M:%S"),
         "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
    from actionlog import ActionLog
    ActionLog(run_dir).log("note", "FORKED from card %s (%s%s) by %s" % (
        tid, short or "tip of ", src["branch"], actor))
    _save_track(t)
    events.emit("fork", new_id, source_card=tid, ref=from_ref or "tip", actor=actor)
    return t

def history(tid):
    """The track's conversation as recorded steers/replies (the reviewable timeline)."""
    from actionlog import read_timeline
    t = get_track(tid)
    if not t:
        return []
    return [r for r in read_timeline(t["run_dir"])
            if r.get("kind") in ("steer", "reply", "note", "turn")]
