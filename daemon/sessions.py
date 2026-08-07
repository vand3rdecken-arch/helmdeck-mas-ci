# -*- coding: utf-8 -*-
"""The orchestrator - HelmDeck's Paseo half. A TRACK is a git branch, isolated in its own
worktree, bound to a RESUMABLE coding session (Claude Code --resume <session_id>). You select
a track and continue its context; history is never rebuilt. Each steer is recorded into the
flight recorder (actionlog) so what the session did stays reviewable.

Store: tracks.json (one list). Worktrees: <repo>/../helmdeck-worktrees/<branch>.
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

def _worktree_for(repo, branch):
    base = os.path.abspath(os.path.join(repo, "..", "helmdeck-worktrees"))
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, _slug(branch))

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

def _turn(t, prompt, model=None, perm=None):
    """One turn through the track's DRIVER (drivers.py) - Claude Code by default,
    but any agent runtime configured in settings. Handles the flight-recorder
    hook: a driver with record:true gets its whole turn screen-captured into the
    track's run_dir (screen.mp4 + live.jpg glance feed). Per-turn `model` and
    `perm` overrides (from the chat composer's model + mode controls) win over
    the driver's configured values."""
    import drivers, events
    name = t.get("driver") or "claude"
    cfg = events.settings().get("drivers", {}).get(name) or {"type": "claude"}
    model = model or t.get("model")      # card's chosen model (from New Request) unless overridden
    if model:
        cfg = {**cfg, "model": model}
    if perm:
        cfg = {**cfg, "perm": perm}
    rec = None
    if cfg.get("record"):
        try:
            import wincap
            rec = wincap.start(t["run_dir"])
        except Exception as e:
            print("recorder failed to start:", e)
    try:
        with _lock_for(t["id"]):   # one turn per card at a time - pays turn-locks debt
            return drivers.run(cfg, t, prompt)
    finally:
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
    _record_econ(t, meta)          # measured economics: this turn is billed too
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


def waits_for_owner(t):
    """True when the card wants something from the HUMAN right now - finished
    work to accept, or a question to answer. A background wait is excluded: it
    is the one parked state that is nobody's move but the machine's."""
    t = t or {}
    return (t.get("status") in ("needs_you", "bounced")
            and t.get("waiting_on") != "background")


def _settle_reply(t, result, log):
    """Fold a finished turn's REPLY into the card and say what it is waiting on.

    Returns the notify reason: "question" when the worker is waiting on a typed
    multiple-choice decision (Phase 2.4), else "needs_you".

    This is the one place a reply is interpreted, so the three turn sites
    (dispatch, machine dispatch, steer) cannot drift apart. The machine block is
    stripped from BOTH the audit line and last_reply: the owner reads those, and
    raw protocol JSON in them is noise - the parsed question carries the same
    information in typed form."""
    import ask, events
    question, cleaned = ask.parse(result or "")
    log.log("reply", cleaned[:2000])
    t["last_reply"] = cleaned[:2000]
    if not question and _ask_repair_on(t) and ask.looks_like_question(cleaned):
        question = _repair_question(t, log)
    if not question:
        # A turn that does not ask supersedes any older pending question -
        # leaving a stale one would show buttons for a decision the worker has
        # already moved past.
        t.pop("question", None)
        # ...but it may not be waiting on the OWNER either: a turn that ended
        # while a background task it launched is still running is waiting on
        # THAT (Phase 2.5). Saying "waiting for you" there is what parked such
        # cards in limbo - the owner had nothing to do and no way to know.
        import claude_sessions
        try:
            bg = claude_sessions.background_wait(t)
        except Exception:
            bg = None                    # a cue is never worth failing a turn
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
    # CUMULATIVE across turns - useless for "how full is the window". The actual
    # context size = THIS call's input side (the whole conversation is re-sent as
    # the prompt each turn), so store it separately for the card's meter. Lets the
    # owner SEE the context filling instead of a surprise "Kontext ist am Ende".
    ctx = (u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
           + u.get("cache_read_input_tokens", 0))
    if ctx:
        t["ctx_tokens"] = ctx
    for m in meta.get("models") or []:
        if m not in t.setdefault("models", []):
            t["models"].append(m)
    events.emit("turn", t["id"], cost=round(cost, 6), usage=u, models=meta.get("models") or [])
    return cost


def _record_turn(t, meta):
    """Fold one turn's economics into the track and the event log."""
    # structured failure signal off the driver's result event (not the prose
    # reply) - the night shift reads this instead of grepping last_reply.
    t["last_subtype"] = meta.get("subtype")
    t["last_error"] = meta.get("error") or ""
    _record_econ(t, meta)
    # per-turn rewind anchor: snapshot the worktree so a message can be rewound
    # to (files restored to this point) later. Non-fatal if git isn't available.
    # NOT for machine cards: their "worktree" is a real folder on the owner's PC
    # (often his home), and snapshotting every file in it each turn is both slow
    # and none of our business - rewind is a code-worktree feature.
    if t.get("worktree") and not t.get("machine") and os.path.isdir(t["worktree"]):
        cp = _checkpoint(t["worktree"])
        if cp:
            t.setdefault("checkpoints", []).append(
                {"turn": t.get("turns"), "commit": cp,
                 "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "reply": (t.get("last_reply") or "")[:80]})

# -- lanes: the kanban IS the company structure, just relabeled ----------
# backlog = request filed (client needs ABC; nothing started, no session yet)
# working = dispatched      (agent session live on its branch)
# review  = submitted       (work + recording handed back for acceptance)
# done    = accepted        (deliverable taken; branch ready to merge)
LANES = ("backlog", "working", "review", "done")

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
        ActionLog(t["run_dir"]).log("note", err[:2000])
    except Exception:
        pass
    events.emit("error", t["id"], where="dispatch", detail=str(e)[:600])
    cur = _db.track_get(t["id"]) or t
    cur["status"] = "bounced"
    cur["last_reply"] = err[:2000]
    cur["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_track(cur)

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

def _start_inner(t):
    if t.get("machine"):
        return _start_machine(t)
    tid = t["id"]
    wt = _worktree_for(t["repo"], t["branch"])
    existing = _worktree_of_branch(t["repo"], t["branch"])
    if existing and os.path.isdir(existing):
        wt = existing                       # reuse a prior checkout (e.g. legacy dir)
    if not os.path.exists(wt):
        if _branch_exists(t["repo"], t["branch"]):
            _git(t["repo"], "worktree", "add", wt, t["branch"])
        else:
            _git(t["repo"], "worktree", "add", wt, "-b", t["branch"])
        _seed_worktree(t["repo"], wt)
    from actionlog import ActionLog
    log = ActionLog(t["run_dir"])
    log.log("note", "DISPATCHED -> branch %s" % t["branch"])
    log.log("steer", t["task"])
    import events
    events.emit("lane", tid, frm=t.get("lane"), to="working")
    t["worktree"] = wt; t["lane"] = "working"; t["status"] = "running"
    _save_track(t)
    prompt = t["task"]
    if t.get("description"):              # the long-form body (Jira-style)
        prompt += "\n\n" + t["description"]
    if t.get("attachments"):             # files filed with the request
        prompt += "\n\nAttached files (read them as needed): " + ", ".join(t["attachments"])
    sid, result, meta = _turn(t, prompt)
    t = _db.track_get(tid) or t
    t["session_id"] = sid; t["turns"] = 1
    reason = _settle_reply(t, result, log)
    t["status"] = "needs_you"
    _record_turn(t, meta)
    t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_track(t)
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
    cur = _db.track_get(t["id"]) or t
    cur["machine"] = True
    cur["worktree"] = cwd            # the driver's cwd - a real folder, no worktree
    _save_track(cur)
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
    events.emit("lane", tid, frm=t.get("lane"), to="working")
    t["worktree"] = cwd; t["lane"] = "working"; t["status"] = "running"
    _save_track(t)
    prompt = t["task"]
    if t.get("description"):
        prompt += "\n\n" + t["description"]
    if t.get("attachments"):
        prompt += "\n\nAttached files (read them as needed): " + ", ".join(t["attachments"])
    sid, result, meta = _turn(t, prompt)
    t = _db.track_get(tid) or t
    t["session_id"] = sid; t["turns"] = 1
    reason = _settle_reply(t, result, log)
    t["status"] = "needs_you"
    _record_turn(t, meta)
    t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_track(t)
    import notify
    notify.card_event(t, reason)
    return t


def _accept_machine(t, lane, actor, log):
    """Review/Done for a machine card. There is no branch to gate or merge, so
    Review RESTS it for the owner to judge and Done records the acceptance
    economics. The repo deploy hook does NOT run (nothing landed in a repo)."""
    import events
    if lane == "review":
        log.log("note", "REVIEW (machine): erledigt auf dem Rechner - wartet auf deine Abnahme.")
        t["status"] = "submitted"; t["lane"] = "review"
        t["review_report"] = ("Maschinen-Aufgabe - kein Branch, kein Merge. Pruefe das "
                              "Ergebnis auf dem Rechner und nimm die Karte ab.")
        t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S"); _save_track(t)
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
    t["status"] = "accepted"; t["mode"] = mode; t["lane"] = "done"
    t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S"); _save_track(t)
    events.emit("lane", t["id"], frm="review", to="done")
    _say_card(t, _i18n.t("say.machineAccepted"))
    import notify; notify.card_event(t, "done")
    return t


# -- the review gate: work may only reach the client when it is green ----

def _gate(t):
    """Quality gate run when a card is submitted for review. Checks: (1) the
    worktree exists and its work is committed; (2) if the repo declares its own
    gate (a `helmdeck.gate` file holding a shell command - the harness's
    standard), it must exit 0. Returns (ok, problems)."""
    problems = []
    wt = t.get("worktree")
    if not wt or not os.path.exists(wt):
        return False, ["never dispatched - nothing to submit"]
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
            if r.returncode != 0:
                out = (r.stdout + "\n" + r.stderr).strip()
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
    rc, out, _ = _git_try(repo, "rev-parse", "--abbrev-ref", "HEAD")
    return out if rc == 0 else ""


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
    catching trees left by builds from before reclamation existed. Git-driven
    (merged into the integration branch AND clean), so it is independent of card
    status. Returns the number reclaimed."""
    repos = {t.get("repo") for t in _load() if t.get("repo")}
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
            if _git_try(repo, "merge-base", "--is-ancestor", br, integ)[0] != 0:
                continue                    # not merged - keep
            rc3, dirty, _ = _git_try(path, "status", "--porcelain", "--untracked-files=no")
            if rc3 == 0 and dirty:
                continue                    # dirty tracked - keep
            _git_try(repo, "worktree", "remove", "--force", path)
            if not os.path.isdir(path):
                _git_try(repo, "branch", "-D", br)
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


def _repo_hook(t, kind):
    """Owner-defined per-repo hook, policy in settings:
      "repo_hooks": {"<repo path>": {"preview": "<cmd>", "deploy": "<cmd>"}}
    preview runs in the WORKTREE when a card reaches Review (try it before
    merging); deploy runs in the MAIN REPO after accept - by the daemon, which
    is the only party holding secrets. Output lands on the card (last_reply
    stays the agent's - hooks log to the actionlog + a hook field)."""
    import events, subprocess
    hooks = (events.settings().get("repo_hooks") or {}).get(t.get("repo") or "", {})
    cmd = (hooks or {}).get(kind, "").strip()
    if not cmd:
        return None
    cwd = t.get("worktree") if kind == "preview" else t.get("repo")
    from actionlog import ActionLog
    log = ActionLog(t["run_dir"])
    log.log("note", "%s HOOK: %s" % (kind.upper(), cmd))
    try:
        r = subprocess.run(cmd, cwd=cwd or ".", shell=True, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=1800)
        out = ((r.stdout or "") + ("\n" + r.stderr if r.stderr else "")).strip()
        ok = r.returncode == 0
    except Exception as e:
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
            t["status"] = "bounced"; t["lane"] = "working"
            t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _save_track(t)
            _say_card(t, _i18n.t("say.bouncedToWorking"))
            return t
        return _start(tid)   # idempotent: resumes position if already started
    from actionlog import ActionLog
    log = ActionLog(t["run_dir"])
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
        t["status"] = "gating"
        t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S"); _save_track(t)
        ac = _autocommit(t)
        if ac == "markers":
            msg = ("Konfliktmarkierungen sind noch im Worktree offen. Steuere den Agenten: "
                   "'loese die Konfliktmarkierungen (<<<<<<< / >>>>>>>) in den Dateien' - "
                   "nur editieren - und reiche dann neu ein.")
            log.log("note", "CONFLICT MARKERS OPEN - stays on Review to resolve: " + msg[:200])
            t["status"] = "bounced"; t["lane"] = "review"   # stay on Review, not back to Working
            t.pop("gate_report", None)                      # the CURRENT blocker is the conflict
            t["merge_report"] = msg; t["merge_kind"] = "conflict"
            t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S"); _save_track(t)
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
            t["status"] = "bounced"; t["lane"] = "review"; t["gate_report"] = problems   # stay on Review
            t.pop("merge_report", None); t.pop("merge_kind", None)   # the CURRENT blocker is the gate
            t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S"); _save_track(t)
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
                t.pop("merge_report", None)
                t["merge_kind"] = kind; t["review_report"] = msg
                t["status"] = "submitted"; t["lane"] = "review"
                t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S"); _save_track(t)
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
            t["status"] = "bounced"; t["lane"] = "review"   # stay on Review, not back to Working
            t["merge_report"] = mergemsg; t["merge_kind"] = kind
            t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S"); _save_track(t)
            import notify; notify.card_event(t, "bounced")
            _say_card(t, _i18n.t("say.cannotLand", kind=kind, detail=mergemsg[:400]))
            t = dict(t); t["merge_failed"] = True; t["merge_kind"] = kind
            return t
        t.pop("merge_report", None); t["merge_kind"] = kind
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
        t["status"] = "accepted"; t["mode"] = mode
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
        t["status"] = "queued"
        # Re-queueing a card IS the "run it again" instruction, so the
        # auto-dispatchers' one-shot stamps must not survive it. They are
        # written once (processes._autopilot / _priority_dispatch /
        # _auto_resolve) and NOTHING else ever clears them, so a re-queued
        # autopilot card kept autopilot=true but never dispatched again - it
        # sat in Backlog looking like a normal queued card, which is exactly
        # the silent waiting the autopilot exists to remove. A fresh queue =
        # a fresh dispatch/escalation budget. This is also the ONLY retry
        # handle for a card whose automatic dispatch failed, so every
        # dispatcher stamp added here must be cleared here too.
        for k in ("autopilot_dispatched", "autopilot_accepted",
                  "autopilot_alerted", "autopilot_ts", "priority_dispatched"):
            t.pop(k, None)
        # the chain keeps its OWN stamps on the step (processes.json), which the
        # loop above cannot reach - without this the card came back clean but
        # its step stayed "already dispatched" and never ran again.
        try:
            import processes
            processes.clear_step_stamps(tid)
        except Exception as e:      # a board move must not fail on the chain store
            print("clear_step_stamps failed for %s: %s" % (tid, e))
    events.emit("lane", tid, frm=prev, to=lane)
    t["lane"] = lane
    t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_track(t)
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
    gr = t.get("gate_report")
    if t.get("gate_failed") and gr:
        parts.append("Quality gate FAILED:\n" + ("\n".join(gr) if isinstance(gr, list) else str(gr)))
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
_COMPACT_AT_TOKENS = 160_000     # ~80% of a 200k window - compact before the brim
_CTX_WINDOW = 200_000
_autocompact_supported = None    # None=unprobed, True/False learned from first /compact


def _maybe_compact(t, log):
    """Compact the session in place if the live context crossed the high-water
    mark. Self-verifying: /compact must actually SHRINK the context. If it does
    not (an older CLI that treats the slash line as literal input), we learn that
    once and stop - no no-op cost, no polluting the conversation every turn."""
    global _autocompact_supported
    if _autocompact_supported is False:
        return
    ctx = t.get("ctx_tokens", 0)
    if ctx < _COMPACT_AT_TOKENS or not t.get("session_id"):
        return
    pct = min(100, round(ctx / _CTX_WINDOW * 100))
    log.log("note", "AUTO-COMPACT: Kontext bei %d%% (~%dk) - ich verdichte die Session, "
            "damit der Verlauf erhalten bleibt und es weitergeht." % (pct, round(ctx / 1000)))
    sid, _out, meta = _turn(t, "/compact")
    if sid and t.get("session_id") and sid != t["session_id"]:
        _chain = [s for s in (t.get("session_chain") or []) if s != t["session_id"]]
        _chain.append(t["session_id"])
        t["session_chain"] = _chain[-6:]
        t["session_id"] = sid
    before = ctx
    _record_econ(t, meta)                 # measured economics: the compact turn is billed too
    after = t.get("ctx_tokens", before)
    if after <= before * 0.75:            # a real compaction frees a big chunk
        _autocompact_supported = True
        log.log("note", "AUTO-COMPACT ok: Kontext jetzt ~%dk - Verlauf verdichtet, es geht "
                "ohne Unterbrechung weiter." % round(after / 1000))
    else:
        _autocompact_supported = False
        log.log("note", "AUTO-COMPACT: diese CLI honoriert /compact nicht - fuer diese "
                "Session abgeschaltet. Kontext-Meter + Nudge bleiben aktiv.")


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
    import events, turnopts
    events.emit("touch", tid, touch="steer", actor=actor)
    # A card on Review that's being resolved (e.g. steering the agent to fix a
    # conflict) STAYS on Review - steering no longer demotes it to Working. Any
    # other lane (backlog/done) still means "back to active work".
    if t["lane"] not in ("working", "review"):
        events.emit("lane", tid, frm=t["lane"], to="working")
        t["lane"] = "working"
    from actionlog import ActionLog
    log = ActionLog(t["run_dir"])
    if source and source != "you":
        log.log("note", "DELEGATED by %s -> this card's worker" % source)
    log.log("steer", text)               # audit the human's words, not the augmented prompt
    # Any steer supersedes a pending question - the owner either answered it
    # through the buttons (this IS that steer) or decided something else
    # instead. Clearing here, not at turn end, means the panel disappears the
    # moment the turn starts rather than lingering for the whole turn.
    t.pop("question", None)
    # the card is moving again, so whatever we last pushed about it is stale -
    # the next notification is news and must not be swallowed by the dedup
    import notify
    notify.clear_dedup(tid)
    t["status"] = "running"; _save_track(t)
    paths = turnopts.save_attachments(t.get("worktree") or t["run_dir"], attachments)
    # Auto routing sees the card's facts INCLUDING turn count - a card that's
    # already dragged on escalates to the strong model (cheap "escalate on
    # evidence"). An explicit model from the composer still wins.
    cli_model, _ = turnopts.resolve_model(model, text, bool(paths),
        signals={"value": t.get("value"), "priority": t.get("priority"), "turns": t.get("turns"),
                 "failed": t.get("status") == "bounced" or bool(t.get("gate_failed")),
                 "fails": events.consecutive_gate_fails(t["id"])})
    # Hand the worker the daemon-side context it never saw (a merge conflict, a
    # failed gate) so a steer like "resolve the conflict" isn't blind. The AUDIT
    # above still logs the human's original text, not this augmentation.
    prompt = _pending_context(t) + turnopts.augment_prompt(text, thinking, paths)
    perm_override = mode if mode in MODES else None   # whitelist - no arbitrary mode
    try:
        sid, result, meta = _turn(t, prompt, model=cli_model, perm=perm_override)
    except BaseException as e:
        # The steer thread must NEVER die leaving 'running' behind - that flag
        # is a stored promise only this thread would clear, and a card frozen
        # on it shows an eternal spinner (Paseo avoids the whole class by
        # deriving lifecycle from the live run; the reconciler is our derive
        # loop, this is the fast path). Settle on a FRESH load so we can't
        # resurrect state a concurrent cancel already wrote.
        t2 = _find(_load(), tid)
        if t2 and t2.get("status") == "running":
            t2["status"] = "needs_you"
            t2["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _save_track(t2)
            log.log("note", "turn ABGEBROCHEN (%s) - Karte freigegeben, steuern setzt fort."
                    % str(e)[:160])
        raise
    # session_id can rotate on resume/compaction; keep the latest so the next
    # steer continues, and REMEMBER the one we're leaving. A compaction (or a
    # resume of a full session) rotates to a FRESH .jsonl that carries none of
    # the prior conversation - without this pointer the whole chat "disappears"
    # from the card view ("warum ist der ganze Chat verschwunden"). The card feed
    # uses the chain to lead with a "Kontext verdichtet" marker instead.
    if sid and t.get("session_id") and sid != t["session_id"]:
        _chain = [s for s in (t.get("session_chain") or []) if s != t["session_id"]]
        _chain.append(t["session_id"])
        t["session_chain"] = _chain[-6:]     # bounded - last 6 prior sessions
    t["session_id"] = sid or t["session_id"]
    t["turns"] = t.get("turns", 0) + 1
    reason = _settle_reply(t, result, log)
    t["status"] = "needs_you"
    # A successful turn makes any stale interrupt/zombie note obsolete. Clear it so a
    # normal turn-end stops showing "daemon restarted mid-turn" from a PAST bounce -
    # otherwise the card reads as 'the daemon killed my turn' when it just ended
    # cleanly ("stuck again, did you kill it?" when nothing did).
    _gr = t.get("gate_report")
    if isinstance(_gr, list) and any(ZOMBIE_NOTE in x or RESUME_NOTE in x for x in _gr):
        t.pop("gate_report", None)
    _record_turn(t, meta)
    # Auto-compact-and-continue: if this turn left the context near the brim,
    # verdict the session NOW (one bounded /compact on the same session) so the
    # next steer keeps headroom and the thread stays continuous - never a
    # dead-end or a fresh-session overflow. Best-effort, self-verifying.
    try:
        _maybe_compact(t, log)
    except Exception as _e:
        log.log("note", "auto-compact skipped: %s" % str(_e)[:200])
    t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_track(t)
    import notify
    notify.card_event(t, reason)
    return t

# Guards the read-verify-clear of a pending question. Deliberately NOT the
# per-card turn lock (_lock_for): that one is held for the whole turn by _turn,
# and answering ends in a steer - taking it here would deadlock.
_answer_guard = _threading.Lock()


def answer_question(tid, answers, request_id="", actor="owner"):
    """Answer the worker's pending multiple-choice question (Phase 2.4).

    The owner's pick becomes the next steer, so the SAME session continues via
    `--resume` with the decision in hand - the turn is resumed, not restarted,
    and the card never parks on a question nobody could answer.

    `request_id` is the optimistic-concurrency guard: the app sends back the id
    it rendered, so a stale panel (the worker asked again, or another device
    already answered) is rejected instead of steering the worker with an answer
    to a question it has moved past.

    Only labels the WORKER offered are accepted (ask.validate_answers), so this
    endpoint cannot be used to inject arbitrary text into a worker's prompt."""
    import ask
    # CLAIM the question atomically. Answering is backgrounded by the server
    # (it runs a turn), so two quick taps are two threads: without this both
    # could read the same pending question and steer the worker twice with
    # contradictory decisions. Clearing it here - not leaving it to steer() -
    # makes the second caller lose deterministically.
    with _answer_guard:
        t = _find(_load(), tid)
        if not t:
            raise RuntimeError("no such track: " + tid)
        q = t.get("question")
        if not q:
            raise RuntimeError("no pending question on this card")
        if request_id and request_id != q.get("id"):
            raise RuntimeError("this question was already answered or replaced")
        picks, err = ask.validate_answers(q, answers)
        if err:
            raise ValueError(err)          # invalid: leave the panel standing
        t.pop("question", None)
        _save_track(t)
    from actionlog import ActionLog
    ActionLog(t["run_dir"]).log("note", ask.answer_note(picks))
    import events
    events.emit("answer", tid, actor=actor, qkind=q.get("kind"),
                picks=[p["labels"] for p in picks])
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
    """One pass: continue every card whose background task has finished."""
    for t in _load():
        if t.get("waiting_on") != "background" or t.get("status") == "running":
            continue
        if t.get("lane") not in ("working", "review"):
            continue
        if not _bg_continue_on(t):
            continue
        since = ((t.get("background") or {}).get("since")
                 or _epoch_of(t.get("updated")) or time.time())
        if time.time() - since > _BG_MAX_WAIT_S:
            t["waiting_on"] = "you"          # give up watching, hand it back
            t.pop("background", None)
            _save_track(t)
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
        from actionlog import ActionLog
        ActionLog(t["run_dir"]).log(
            "note", "Hintergrund-Task fertig - Karte laeuft automatisch weiter")
        import events
        events.emit("autocontinue", t["id"], actor="daemon")
        # Clear the claim BEFORE steering: that is what stops the next pass from
        # firing this card a second time, and it is why the steer can safely be
        # detached below.
        t["waiting_on"] = "you"
        t.pop("background", None)
        _save_track(t)

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


def _current_branch(repo):
    r = subprocess.run(["git", "-C", repo, "rev-parse", "--abbrev-ref", "HEAD"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


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
    # session id would both mirror the same ever-growing conversation.
    for ex in _load():
        if ex.get("session_id") == session_id and ex.get("lane") != "done":
            raise RuntimeError("session already on the board as card " + ex["id"])
    short = (session_id or "sess")[:8]

    if mode == "fork":
        task = ("Fork of a prior Claude Code session in this repo. Original "
                "starting request:\n\n" + (first or "(unknown)")
                + "\n\nContinue that line of work here.")
        t = new_track(cwd, "fork-" + short, task, lane="backlog", actor=actor)
        tracks = _load(); tt = _find(tracks, t["id"])
        if tt:
            tt["forked_from"] = session_id; _save_track(tt); t = tt
        return t

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
    tracks = _load()
    changed = 0
    for i, tid in enumerate(ids):
        t = _find(tracks, tid)
        if t and t.get("rank") != i:
            t["rank"] = i
            _save_track(t)
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
            # Reset the card OFF "running" here. Normally the steer thread does this
            # when _turn returns after the kill, but a racing/dead steer thread (a
            # daemon restart, overlapping cancels) can leave it stuck at running with
            # no session - a frozen spinner. The turn is cancelled; it's the owner's
            # move now.
            if t.get("status") == "running":
                t["status"] = "needs_you"
                t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
                _save_track(t)
        return {"cancelled": True}
    # no live session - clear a stuck/zombie card so Stop is never a no-op, and
    # promote the interrupted session so re-steering RESUMES it losslessly.
    t = get_track(tid)
    if t and t.get("status") == "running" and not drivers.has_session(tid):
        resumable = _promote_live_session(t)
        note = RESUME_NOTE if resumable else ZOMBIE_NOTE
        t["status"] = "bounced"
        t["gate_report"] = _interrupt_note_report(t, note)
        t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save_track(t)
        try:
            from actionlog import ActionLog
            ActionLog(t["run_dir"]).log("note", "STOP on a dead session - " + note)
        except Exception:
            pass
        events.emit("bounce", tid, reason="stopped_zombie", actor=actor)
        return {"cancelled": True, "unfroze": True, "resumable": resumable}
    return {"cancelled": killed}


ZOMBIE_NOTE = "daemon restarted mid-turn - resend the last instruction"
RESUME_NOTE = "Turn unterbrochen - erneut steuern setzt den Kontext fort"


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
                t["status"] = "needs_you"
                t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
                _save_track(t)
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
        note = RESUME_NOTE if _promote_live_session(t) else ZOMBIE_NOTE
        t["status"] = "bounced"
        t["gate_report"] = _interrupt_note_report(t, note)
        t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save_track(t)
        try:
            ActionLog(t["run_dir"]).log("note", "ZOMBIE SWEEP - " + note)
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
    tracks = _load()
    t = _find(tracks, tid)
    if not t:
        raise RuntimeError("no such track: " + tid)
    t["archived"] = bool(on)
    t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_track(t)
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
    lane/status/economics move through their own verbs."""
    import events
    tracks = _load()
    t = _find(tracks, tid)
    if not t:
        raise RuntimeError("no such track: " + tid)
    changed = {}
    for k in EDITABLE:
        if k not in patch:
            continue
        v = patch[k] or None if k in CLEARABLE else patch[k]
        if k not in CLEARABLE and v is None:
            continue
        if k in BOOLFIELDS:
            v = bool(v)          # "off" arrives as false/0/"" - never as a string
        if v == t.get(k):
            continue
        t[k] = float(v) if k in ("value", "rate") and v is not None else v
        changed[k] = t[k]
    if changed:
        t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save_track(t)
        events.emit("edit", tid, actor=actor, fields=changed)
        from actionlog import ActionLog
        ActionLog(t["run_dir"]).log("note", "EDITED by %s: %s" % (actor, ", ".join(changed)))
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
        t = get_track(tid)
        t.setdefault("directives_applied", []).append(did)
        _save_track(t)
        applied += 1
    if applied:
        print("directives: applied %d board directive(s)" % applied)
    return applied

def add_attachments(tid, attachments, actor="owner"):
    """Attach files (PDF etc.) to an existing card, Jira/Plane-style. Saved into
    the card's run_dir/.attachments and appended to the card's file list; the
    worker sees them on its next turn (prompt lists attached files)."""
    import turnopts, events
    tracks = _load()
    t = _find(tracks, tid)
    if not t:
        raise RuntimeError("no such track: " + tid)
    new_paths = turnopts.save_attachments(t["run_dir"], attachments)
    if new_paths:
        t["attachments"] = (t.get("attachments") or []) + new_paths
        t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save_track(t)
        events.emit("edit", tid, actor=actor, fields={"attachments": len(new_paths)})
        from actionlog import ActionLog
        ActionLog(t["run_dir"]).log("note", "%s attached %d file(s)" % (actor, len(new_paths)))
    return t

def remove_attachment(tid, name, actor="owner"):
    """Detach a file from the card by its basename (leaves the file on disk -
    append-only audit; the card just stops referencing it)."""
    tracks = _load()
    t = _find(tracks, tid)
    if not t:
        raise RuntimeError("no such track: " + tid)
    before = t.get("attachments") or []
    t["attachments"] = [p for p in before if os.path.basename(p) != name]
    if len(t["attachments"]) != len(before):
        t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save_track(t)
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
        t.setdefault("checkpoints", []).append(
            {"turn": t.get("turns"), "commit": undo,
             "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "reply": "(pre-rewind snapshot)"})
        _save_track(t)
    import events
    events.emit("rewind", tid, commit=commit[:12], undo=(undo or "")[:12], actor=actor)
    from actionlog import ActionLog
    ActionLog(t["run_dir"]).log("note", "REWOUND files to %s (undo %s) by %s"
                                % (commit[:8], (undo or "?")[:8], actor))
    return {"ok": True, "undo": undo}

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
    return [r for r in read_timeline(t["run_dir"]) if r.get("kind") in ("steer", "reply", "note")]
