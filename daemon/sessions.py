# -*- coding: utf-8 -*-
"""The orchestrator — SwarmDeck's Paseo half. A TRACK is a git branch, isolated in its own
worktree, bound to a RESUMABLE coding session (Claude Code --resume <session_id>). You select
a track and continue its context; history is never rebuilt. Each steer is recorded into the
flight recorder (actionlog) so what the session did stays reviewable.

Store: tracks.json (one list). Worktrees: <repo>/../swarmdeck-worktrees/<branch>.
Permission mode is per-track and defaults to acceptEdits — the worktree is the blast-radius
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

def _turn(t, prompt):
    """One turn through the track's DRIVER (drivers.py) - Claude Code by default,
    but any agent runtime configured in settings. Handles the flight-recorder
    hook: a driver with record:true gets its whole turn screen-captured into the
    track's run_dir (screen.mp4 + live.jpg glance feed)."""
    import drivers, events
    name = t.get("driver") or "claude"
    cfg = events.settings().get("drivers", {}).get(name) or {"type": "claude"}
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
              value=None, driver="claude", actor="owner", priority="medium", due=""):
    """File a request. lane=backlog stores it un-started (no worktree, no session);
    lane=working starts the branch session immediately. value = what the
    deliverable is worth (settings default when omitted) - set at intake so
    margin is computable at acceptance."""
    import events
    repo = os.path.abspath(repo)
    tracks = _load()
    tid = time.strftime("%Y%m%d-%H%M%S") + "-" + _slug(branch)
    run_dir = os.path.join(REC, tid)
    os.makedirs(run_dir, exist_ok=True)
    t = {"id": tid, "repo": repo, "branch": branch, "worktree": "", "task": task,
         "client": client, "session_id": None, "perm": perm, "lane": "backlog",
         "status": "queued", "turns": 0, "run_dir": run_dir, "last_reply": "",
         "value": float(value) if value else events.settings()["value_per_card"],
         "driver": driver or "claude", "priority": priority or "medium", "due": due or "",
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
    from actionlog import ActionLog
    log = ActionLog(t["run_dir"])
    log.log("note", "DISPATCHED -> branch %s" % t["branch"])
    log.log("steer", t["task"])
    import events
    events.emit("lane", tid, frm=t.get("lane"), to="working")
    t["worktree"] = wt; t["lane"] = "working"; t["status"] = "running"
    _save_track(t)
    sid, result, meta = _turn(t, t["task"])
    log.log("reply", result[:2000])
    t = _db.track_get(tid) or t
    t["session_id"] = sid; t["turns"] = 1
    t["last_reply"] = result[:2000]; t["status"] = "needs_you"
    _record_turn(t, meta)
    t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_track(t)
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
            t = dict(t); t["gate_failed"] = True
            return t
        t.pop("gate_report", None)
        try:
            stat = _git(t["worktree"], "diff", "--stat", "HEAD") or "(all committed)"
        except Exception:
            stat = "?"
        log.log("note", "GATE PASSED - SUBMITTED for review — diff: " + stat[:400])
        t["status"] = "submitted"
    elif lane == "done":
        events.emit("touch", tid, touch="review", actor=actor)
        te = [e for e in events.read_events() if e.get("track") == tid]
        mode = events._completion_mode(te, t.get("turns"))
        events.emit("done", tid, mode=mode, ai_cost=t.get("ai_cost", 0.0),
                    value=t.get("value"), models=t.get("models", []),
                    tokens_in=t.get("tokens_in", 0), tokens_out=t.get("tokens_out", 0))
        log.log("note", "ACCEPTED (%s) - AI $%.4f, value %s" %
                (mode, t.get("ai_cost", 0.0), t.get("value")))
        t["status"] = "accepted"; t["mode"] = mode
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

def steer(tid, text, perm=None, actor="owner", source="you"):
    """Continue the track's session (resume — context preserved, NO history rebuild)."""
    tracks = _load()
    t = _find(tracks, tid)
    if not t:
        raise RuntimeError("no such track: " + tid)
    if not t.get("session_id"):
        _start(tid)                      # steering a backlog card dispatches it first
        tracks = _load(); t = _find(tracks, tid)
    import events
    events.emit("touch", tid, touch="steer", actor=actor)
    if t["lane"] != "working":
        events.emit("lane", tid, frm=t["lane"], to="working")
    t["lane"] = "working"
    from actionlog import ActionLog
    log = ActionLog(t["run_dir"])
    if source and source != "you":
        log.log("note", "DELEGATED by %s -> this card's worker" % source)
    log.log("steer", text)
    t["status"] = "running"; _save_track(t)
    sid, result, meta = _turn(t, text)
    log.log("reply", result[:2000])
    # session_id can rotate on resume; keep the latest so the next steer continues.
    t["session_id"] = sid or t["session_id"]
    t["turns"] = t.get("turns", 0) + 1
    t["last_reply"] = result[:2000]
    t["status"] = "needs_you"
    _record_turn(t, meta)
    t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_track(t)
    return t

EDITABLE = ("task", "priority", "due", "value", "client", "driver")

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
        if k in patch and patch[k] is not None and patch[k] != t.get(k):
            t[k] = float(patch[k]) if k == "value" else patch[k]
            changed[k] = t[k]
    if changed:
        t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save_track(t)
        events.emit("edit", tid, actor=actor, fields=changed)
        from actionlog import ActionLog
        ActionLog(t["run_dir"]).log("note", "EDITED by %s: %s" % (actor, ", ".join(changed)))
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
