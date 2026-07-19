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

def _load():
    if not os.path.exists(STORE):
        return []
    try:
        with open(STORE, encoding="utf-8") as f:
            return json.load(f)
    except ValueError:
        return []

def _save(tracks):
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(tracks, f, indent=2)
    os.replace(tmp, STORE)

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

def _claude(cwd, prompt, session_id=None, perm=DEFAULT_PERM, timeout=600):
    """One turn. Returns (session_id, result_text). Resumes if session_id given.
    Prompt goes over stdin (no arg-quoting); .cmd shim run via `cmd /c`."""
    cmd = ["cmd", "/c", CLAUDE, "-p", "--output-format", "json", "--permission-mode", perm]
    if session_id:
        cmd += ["--resume", session_id]
    r = subprocess.run(cmd, cwd=cwd, input=prompt, capture_output=True, text=True, timeout=timeout)
    if not r.stdout.strip():
        raise RuntimeError("claude no output: " + r.stderr.strip()[:300])
    d = json.loads(r.stdout)
    return d.get("session_id"), d.get("result", "")

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

def new_track(repo, branch, task, perm=DEFAULT_PERM, lane="working", client=""):
    """File a request. lane=backlog stores it un-started (no worktree, no session);
    lane=working starts the branch session immediately."""
    repo = os.path.abspath(repo)
    tracks = _load()
    tid = time.strftime("%Y%m%d-%H%M%S") + "-" + _slug(branch)
    run_dir = os.path.join(REC, tid)
    os.makedirs(run_dir, exist_ok=True)
    t = {"id": tid, "repo": repo, "branch": branch, "worktree": "", "task": task,
         "client": client, "session_id": None, "perm": perm, "lane": "backlog",
         "status": "queued", "turns": 0, "run_dir": run_dir, "last_reply": "",
         "created": time.strftime("%Y-%m-%d %H:%M:%S"),
         "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
    from actionlog import ActionLog
    ActionLog(run_dir).log("note", "REQUEST filed: %s (branch %s)" % (task, branch))
    tracks.insert(0, t)
    _save(tracks)
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
    t["worktree"] = wt; t["lane"] = "working"; t["status"] = "running"
    _save(tracks)
    sid, result = _claude(wt, t["task"], perm=t["perm"])
    log.log("reply", result[:2000])
    tracks = _load(); t = _find(tracks, tid)
    t["session_id"] = sid; t["turns"] = 1
    t["last_reply"] = result[:2000]; t["status"] = "needs_you"
    t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save(tracks)
    return t

def move_lane(tid, lane):
    """The board move is the workflow verb: ->working dispatches, ->review submits
    (records a submission note + branch diffstat), ->done accepts."""
    if lane not in LANES:
        raise RuntimeError("bad lane: " + lane)
    if lane == "working":
        return _start(tid)   # idempotent: resumes position if already started
    tracks = _load()
    t = _find(tracks, tid)
    if not t:
        raise RuntimeError("no such track: " + tid)
    from actionlog import ActionLog
    log = ActionLog(t["run_dir"])
    if lane == "review" and t.get("worktree"):
        try:
            stat = _git(t["worktree"], "diff", "--stat", "HEAD") or "(all committed)"
        except Exception:
            stat = "?"
        log.log("note", "SUBMITTED for review — diff: " + stat[:400])
        t["status"] = "submitted"
    elif lane == "done":
        log.log("note", "ACCEPTED")
        t["status"] = "accepted"
    elif lane == "backlog":
        t["status"] = "queued"
    t["lane"] = lane
    t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save(tracks)
    return t

def steer(tid, text, perm=None):
    """Continue the track's session (resume — context preserved, NO history rebuild)."""
    tracks = _load()
    t = _find(tracks, tid)
    if not t:
        raise RuntimeError("no such track: " + tid)
    if not t.get("session_id"):
        _start(tid)                      # steering a backlog card dispatches it first
        tracks = _load(); t = _find(tracks, tid)
    t["lane"] = "working"
    from actionlog import ActionLog
    log = ActionLog(t["run_dir"])
    log.log("steer", text)
    t["status"] = "running"; _save(tracks)
    sid, result = _claude(t["worktree"], text, session_id=t["session_id"],
                          perm=perm or t.get("perm", DEFAULT_PERM))
    log.log("reply", result[:2000])
    # session_id can rotate on resume; keep the latest so the next steer continues.
    t["session_id"] = sid or t["session_id"]
    t["turns"] = t.get("turns", 0) + 1
    t["last_reply"] = result[:2000]
    t["status"] = "needs_you"
    t["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save(tracks)
    return t

def history(tid):
    """The track's conversation as recorded steers/replies (the reviewable timeline)."""
    from actionlog import read_timeline
    t = get_track(tid)
    if not t:
        return []
    return [r for r in read_timeline(t["run_dir"]) if r.get("kind") in ("steer", "reply", "note")]
