# -*- coding: utf-8 -*-
"""fork_conversation: split a crowded card's CONVERSATION into a new sibling
card that keeps context (unlike fork_track, which forks CODE at a ref with a
fresh session). Reuses the adopted_source/--fork-session mechanism already
proven for adopting an external Claude session - just with the SOURCE being
one of our own cards. Pins: machine cards share cwd (no isolation model);
git cards get their OWN worktree (never share a live checkout between two
cards); no-session and missing-card raise clear errors."""
import os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, DAEMON)

SANDBOX = tempfile.mkdtemp(prefix="hd-forkchat-")
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()
from spine.ops import runs
runs.REC = os.path.join(SANDBOX, "runs"); os.makedirs(runs.REC, exist_ok=True)
from cells.engineer import sessions
sessions.REC = runs.REC

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _git(*args, cwd):
    r = subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


# --- 1) machine card: new card shares the same cwd, no git touched ----------
mdir = os.path.join(SANDBOX, "machine-home"); os.makedirs(mdir, exist_ok=True)
src_m = {"id": "m1", "repo": mdir, "branch": "(no git)", "worktree": mdir,
         "machine": True, "task": "crowded machine card", "session_id": "sess-m",
         "session_chain": [], "status": "needs_you", "lane": "working",
         "run_dir": os.path.join(runs.REC, "m1")}
sessions._save([src_m])
fork = sessions.fork_conversation("m1", first="just the fiverr thing")
check(fork["machine"] is True, "forked machine card stays machine=True")
check(fork["worktree"] == mdir, "machine fork shares the SAME cwd (no isolation model)")
check(fork["session_id"] == "sess-m", "new card seeded with the source's session id")
check(fork["adopted_source"] == "sess-m", "adopted_source set -> first spawn will --fork-session")
check(fork["forked_from"] == "m1" and fork["forked_from_session"] == "sess-m",
      "provenance recorded (forked_from + forked_from_session)")
check(fork["task"] == "just the fiverr thing", "owner's own first text used as the new task")
check(sessions._find(sessions._load(), "m1")["session_id"] == "sess-m",
      "the SOURCE card's session is untouched")

# --- 2) git card: new card gets its OWN worktree, branched off the source ---
repo = os.path.join(SANDBOX, "repo"); os.makedirs(repo)
_git("init", "-q", cwd=repo)
_git("config", "user.email", "t@t", cwd=repo)
_git("config", "user.name", "t", cwd=repo)
open(os.path.join(repo, "f.txt"), "w").write("x")
_git("add", ".", cwd=repo)
_git("commit", "-q", "-m", "init", cwd=repo)
_git("checkout", "-q", "-b", "feature-x", cwd=repo)
src_g = {"id": "g1", "repo": repo, "branch": "feature-x", "worktree": repo,
         "machine": False, "task": "crowded code card", "session_id": "sess-g",
         "session_chain": [], "status": "needs_you", "lane": "working",
         "run_dir": os.path.join(runs.REC, "g1")}
sessions._save(sessions._load() + [src_g])
fork_g = sessions.fork_conversation("g1")
check(fork_g["worktree"] != repo, "git fork gets its OWN worktree, not the source's")
check(os.path.isdir(fork_g["worktree"]), "the new worktree really exists on disk")
check(fork_g["branch"] != "feature-x", "the new worktree is on its own branch")
check(fork_g["session_id"] == "sess-g", "git fork also seeds the source's session id")

# --- 3) no session yet -> clear error, nothing created -----------------------
src_n = {"id": "n1", "repo": mdir, "worktree": mdir, "machine": True,
         "task": "no session", "session_id": None, "status": "needs_you",
         "lane": "working", "run_dir": os.path.join(runs.REC, "n1")}
sessions._save(sessions._load() + [src_n])
try:
    sessions.fork_conversation("n1")
    check(False, "no-session card raises")
except RuntimeError as e:
    check("no conversation yet" in str(e), "no-session card raises clearly (%s)" % str(e)[:50])

# --- 4) missing card -> clear error ------------------------------------------
try:
    sessions.fork_conversation("does-not-exist")
    check(False, "missing card raises")
except RuntimeError as e:
    check("no such card" in str(e), "missing card raises clearly")

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails)); sys.exit(1)
print("fork-chat: all pinned - PASS")
