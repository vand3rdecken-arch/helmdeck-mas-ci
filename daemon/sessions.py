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

# -- public API ----------------------------------------------------------

def list_tracks():
    return _load()

def get_track(tid):
    return _find(_load(), tid)

def new_track(repo, branch, task, perm=DEFAULT_PERM):
    """Create branch (worktree) + open a coding session on it with the opening task."""
    repo = os.path.abspath(repo)
    tracks = _load()
    tid = time.strftime("%Y%m%d-%H%M%S") + "-" + _slug(branch)
    wt = _worktree_for(repo, branch)
    if not os.path.exists(wt):
        if _branch_exists(repo, branch):
            _git(repo, "worktree", "add", wt, branch)
        else:
            _git(repo, "worktree", "add", wt, "-b", branch)
    run_dir = os.path.join(REC, tid)
    os.makedirs(run_dir, exist_ok=True)
    from actionlog import ActionLog
    log = ActionLog(run_dir)
    log.log("note", "TRACK opened on branch %s (%s)" % (branch, repo))
    log.log("steer", task)
    sid, result = _claude(wt, task, perm=perm)
    log.log("reply", result[:2000])
    t = {"id": tid, "repo": repo, "branch": branch, "worktree": wt, "task": task,
         "session_id": sid, "perm": perm, "status": "needs_you", "turns": 1,
         "run_dir": run_dir, "last_reply": result[:2000],
         "created": time.strftime("%Y-%m-%d %H:%M:%S"),
         "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
    tracks.insert(0, t)
    _save(tracks)
    return t

def steer(tid, text, perm=None):
    """Continue the track's session (resume — context preserved, NO history rebuild)."""
    tracks = _load()
    t = _find(tracks, tid)
    if not t:
        raise RuntimeError("no such track: " + tid)
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
