# -*- coding: utf-8 -*-
"""The orchestrator - SwarmDeck's Paseo half. A TRACK is a git branch, isolated in its own
worktree, bound to a RESUMABLE coding session (Claude Code --resume <session_id>). You select
a track and continue its context; history is never rebuilt. Each steer is recorded into the
flight recorder (actionlog) so what the session did stays reviewable.

Store: tracks.json (one list). Worktrees: <repo>/../swarmdeck-worktrees/<branch>.
Permission mode is per-track and defaults to acceptEdits - the worktree is the blast-radius
control. Escalate a track to bypassPermissions only deliberately (owner decision)."""
import json, os, re, shutil, subprocess, time
from runs import REC

ROOT = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(ROOT, "tracks.json")
DEFAULT_PERM = os.environ.get("SWARMDECK_PERM", "acceptEdits")
CLAUDE = (os.environ.get("SWARMDECK_CLAUDE") or shutil.which("claude")
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
        commit = _git(worktree, "commit-tree", tree, "-p", head, "-m", "swarmdeck checkpoint")
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

def _worktree_for(repo, branch):
    base = os.path.abspath(os.path.join(repo, "..", "swarmdeck-worktrees"))
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, _slug(branch))

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

def _record_turn(t, meta):
    """Fold one turn's economics into the track and the event log."""
    import events
    # structured failure signal off the driver's result event (not the prose
    # reply) - the night shift reads this instead of grepping last_reply.
    t["last_subtype"] = meta.get("subtype")
    t["last_error"] = meta.get("error") or ""
    u = meta.get("usage") or {}
    cost = events.price_turn(meta.get("models"), u, meta.get("cost_usd"))
    t["ai_cost"] = round(t.get("ai_cost", 0.0) + cost, 6)
    t["tokens_in"] = t.get("tokens_in", 0) + u.get("input_tokens", 0) \
        + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)
    t["tokens_out"] = t.get("tokens_out", 0) + u.get("output_tokens", 0)
    for m in meta.get("models") or []:
        if m not in t.setdefault("models", []):
            t["models"].append(m)
    events.emit("turn", t["id"], cost=round(cost, 6), usage=u, models=meta.get("models") or [])
    # per-turn rewind anchor: snapshot the worktree so a message can be rewound
    # to (files restored to this point) later. Non-fatal if git isn't available.
    if t.get("worktree") and os.path.isdir(t["worktree"]):
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
    tid = time.strftime("%Y%m%d-%H%M%S") + "-" + _slug(branch)
    run_dir = os.path.join(REC, tid)
    os.makedirs(run_dir, exist_ok=True)
    # attachments filed with the request are saved now; the first run reads them.
    # model chosen in the composer becomes the card's execution model (Auto too).
    att_paths = turnopts.save_attachments(run_dir, attachments)
    cli_model, _ = turnopts.resolve_model(model, task, bool(att_paths))
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

def _start(tid):
    """Dispatch a backlog request: create the worktree + open its coding session."""
    tracks = _load()
    t = _find(tracks, tid)
    if not t:
        raise RuntimeError("no such track: " + tid)
    if t["session_id"]:
        return t
    wt = _worktree_for(t["repo"], t["branch"])
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
    log.log("reply", result[:2000])
    t = _db.track_get(tid) or t
    t["session_id"] = sid; t["turns"] = 1
    t["last_reply"] = result[:2000]; t["status"] = "needs_you"
    _record_turn(t, meta)
    t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_track(t)
    import notify
    notify.card_event(t, "needs_you")
    return t

# -- the review gate: work may only reach the client when it is green ----

def _gate(t):
    """Quality gate run when a card is submitted for review. Checks: (1) the
    worktree exists and its work is committed; (2) if the repo declares its own
    gate (a `swarmdeck.gate` file holding a shell command - the harness's
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
    gate_file = os.path.join(wt, "swarmdeck.gate")
    if os.path.exists(gate_file):
        with open(gate_file, encoding="utf-8") as f:
            cmd = f.read().strip()
        if cmd:
            r = subprocess.run(cmd, cwd=wt, shell=True, capture_output=True,
                               text=True, timeout=600)
            if r.returncode != 0:
                out = (r.stdout + "\n" + r.stderr).strip()
                problems.append("gate command failed (%s):\n%s" % (cmd[:80], out[-600:]))
    return (not problems), problems

def _merge_to_main(t):
    """Land an accepted card: merge its branch into the repo's MAIN checkout.
    This is the payoff of the charter walk - accept = the work reaches main. Runs
    in t['repo'] (the daemon's checkout, which holds the secrets the worktree
    never sees), NOT in the agent's worktree. Returns (ok, message).

    Guards so we never corrupt the main checkout: the checkout must be on a real
    branch (not detached, not the card branch itself) and CLEAN; a conflicting
    merge is aborted. A branch already contained in HEAD is treated as merged
    (idempotent - re-accepting is safe)."""
    repo = t.get("repo"); branch = t.get("branch")
    if not repo or not os.path.isdir(repo):
        return False, "card has no repo checkout to merge into"
    if not branch:
        return False, "card has no branch"
    try:
        cur = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    except Exception as e:
        return False, "repo is not a git checkout: %s" % e
    if cur == "HEAD":
        return False, "main checkout is in detached HEAD - checkout the base branch first"
    if cur == branch:
        return False, "main checkout is ON the card branch (%s) - switch it to the base branch" % branch
    # already merged? merge-base --is-ancestor exits 0 when branch is in HEAD.
    try:
        subprocess.run(["git", "-C", repo, "merge-base", "--is-ancestor", branch, "HEAD"],
                       capture_output=True, check=True)
        return True, "already merged into %s" % cur
    except Exception:
        pass
    dirty = ""
    try:
        dirty = _git(repo, "status", "--porcelain")
    except Exception as e:
        return False, "cannot read repo status: %s" % e
    if dirty:
        return False, ("main checkout '%s' has uncommitted changes - commit or stash "
                       "before accepting:\n%s" % (cur, dirty[:300]))
    try:
        out = _git(repo, "merge", "--no-ff", branch, "-m",
                   "SwarmDeck accept: %s (%s)" % (branch, t.get("id", "")))
        return True, out or ("merged %s into %s" % (branch, cur))
    except Exception as e:
        try:
            _git(repo, "merge", "--abort")
        except Exception:
            pass
        return False, "merge conflict - resolve on the branch, re-review, re-accept:\n%s" % str(e)[:400]


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


def move_lane(tid, lane, actor="owner"):
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
    if lane == "working":
        # pulling a card back OUT of review is a human bounce - the reject touch
        if prev == "review":
            events.emit("touch", tid, touch="bounce", actor=actor)
            from actionlog import ActionLog
            ActionLog(t["run_dir"]).log("note", "BOUNCED by owner - back to Working")
            t["status"] = "bounced"; t["lane"] = "working"
            t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _save_track(t)
            return t
        return _start(tid)   # idempotent: resumes position if already started
    from actionlog import ActionLog
    log = ActionLog(t["run_dir"])
    if lane == "review":
        ok, problems = _gate(t)
        events.emit("gate", tid, ok=ok, problems=problems)
        if not ok:
            punch = " | ".join(p.split("\n")[0] for p in problems)
            log.log("note", "GATE FAILED - bounced with punch list: " + punch[:400])
            t["status"] = "bounced"; t["lane"] = "working"
            t["gate_report"] = problems
            t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _save_track(t)
            import notify
            notify.card_event(t, "bounced")
            t = dict(t); t["gate_failed"] = True
            return t
        t.pop("gate_report", None)
        try:
            stat = _git(t["worktree"], "diff", "--stat", "HEAD") or "(all committed)"
        except Exception:
            stat = "?"
        log.log("note", "GATE PASSED - SUBMITTED for review - diff: " + stat[:400])
        t["status"] = "submitted"
        _repo_hook(t, "preview")   # spin up the try-it-before-merge surface
    elif lane == "done":
        # accept = LAND it: merge the card's branch into main, THEN deploy. A
        # merge that can't land cleanly bounces the card (like a failed gate) -
        # never a silent "accepted" that never reached main.
        merged, mergemsg = _merge_to_main(t)
        events.emit("merge", tid, ok=merged, detail=mergemsg[:300])
        if not merged:
            log.log("note", "MERGE FAILED - not accepted: " + mergemsg[:400])
            t["status"] = "bounced"; t["lane"] = "working"
            t["merge_report"] = mergemsg
            t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _save_track(t)
            import notify
            notify.card_event(t, "bounced")
            t = dict(t); t["merge_failed"] = True
            return t
        t.pop("merge_report", None)
        log.log("note", "MERGED -> " + mergemsg[:300])
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
    elif lane == "backlog":
        t["status"] = "queued"
    events.emit("lane", tid, frm=prev, to=lane)
    t["lane"] = lane
    t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_track(t)
    return t

MODES = ("plan", "acceptEdits", "default", "bypassPermissions")


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
    if t["lane"] != "working":
        events.emit("lane", tid, frm=t["lane"], to="working")
    t["lane"] = "working"
    from actionlog import ActionLog
    log = ActionLog(t["run_dir"])
    if source and source != "you":
        log.log("note", "DELEGATED by %s -> this card's worker" % source)
    log.log("steer", text)               # audit the human's words, not the augmented prompt
    t["status"] = "running"; _save_track(t)
    paths = turnopts.save_attachments(t.get("worktree") or t["run_dir"], attachments)
    cli_model, _ = turnopts.resolve_model(model, text, bool(paths))
    prompt = turnopts.augment_prompt(text, thinking, paths)
    perm_override = mode if mode in MODES else None   # whitelist - no arbitrary mode
    sid, result, meta = _turn(t, prompt, model=cli_model, perm=perm_override)
    log.log("reply", result[:2000])
    # session_id can rotate on resume; keep the latest so the next steer continues.
    t["session_id"] = sid or t["session_id"]
    t["turns"] = t.get("turns", 0) + 1
    t["last_reply"] = result[:2000]
    t["status"] = "needs_you"
    _record_turn(t, meta)
    t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_track(t)
    import notify
    notify.card_event(t, "needs_you")
    return t

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
    tid = time.strftime("%Y%m%d-%H%M%S") + "-adopt-" + short
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
    subprocess; the turn returns as '(cancelled)'. Audit records it."""
    import drivers, events
    killed = drivers.cancel(tid)
    if killed:
        events.emit("touch", tid, touch="cancel", actor=actor)
        t = get_track(tid)
        if t:
            from actionlog import ActionLog
            ActionLog(t["run_dir"]).log("note", "turn CANCELLED by %s" % actor)
    return {"cancelled": killed}


ZOMBIE_NOTE = "daemon restarted mid-turn - resend the last instruction"

def sweep_zombies():
    """Startup pass: a daemon that dies mid-turn leaves cards flagged
    status=running with no owning worker - cancel returns false, the phone
    watches a card that will never move again. Flip every such track to
    bounced with a visible note (gate_report is the bounce-reason channel
    both UIs already render), audit it, and push - so the owner learns the
    instruction was lost instead of staring at a frozen card."""
    import drivers, events, notify
    from actionlog import ActionLog
    swept = []
    for t in _load():
        if t.get("status") != "running" or drivers.has_session(t["id"]):
            continue
        t["status"] = "bounced"
        t["gate_report"] = [ZOMBIE_NOTE]
        t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save_track(t)
        try:
            ActionLog(t["run_dir"]).log("note", "ZOMBIE SWEEP - " + ZOMBIE_NOTE)
        except Exception:
            pass
        events.emit("bounce", t["id"], reason="daemon_restart", actor="daemon")
        try:
            notify.card_event(t, "bounced")
        except Exception as e:
            print("sweep_zombies: push failed for %s: %s" % (t["id"], e))
        swept.append(t["id"])
    return swept


EDITABLE = ("task", "description", "priority", "due", "value", "client", "driver",
            "project_id", "billing", "rate")
# project_id may be explicitly cleared (unassign from a project) - unlike the
# other fields, "" / null is a meaningful value here, not "leave unset".
CLEARABLE = ("project_id",)

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
    ActionLog(t["run_dir"]).log("note", ("ARCHIVED" if on else "UNARCHIVED") + " by " + actor)
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
    new_id = time.strftime("%Y%m%d-%H%M%S") + "-fork"
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
