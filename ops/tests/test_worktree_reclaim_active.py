# -*- coding: utf-8 -*-
"""sessions.sweep_worktrees must never reclaim a NON-TERMINAL card's tree,
regardless of what git's merge check says. Real incident (2026-08-14): a
COWORK card's branch was already merged (an earlier commit landed) while the
card was still open on the board, actively being steered - the boot-time
backstop sweep saw "merged + git-status-clean" and tore the live worktree
out from under it (deregistered .git, deleted most files, orphaned an
in-use process's locked files as an empty app/ husk). "Is anyone still
using this" is the daemon's own fact and must win over git's verdict alone.
Self-sandboxing: throwaway git repos + throwaway sqlite/events (no daemon)."""
import os, sys, subprocess, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, DAEMON)

SANDBOX = tempfile.mkdtemp()
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from cells.engineer import sessions

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def git(repo, *args, check_ok=True):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if check_ok and r.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), r.stderr.strip()))
    return r.stdout.strip()


def new_repo():
    d = tempfile.mkdtemp()
    git(d, "init")
    git(d, "symbolic-ref", "HEAD", "refs/heads/main")
    git(d, "config", "user.email", "t@t.t")
    git(d, "config", "user.name", "t")
    with open(os.path.join(d, "base.txt"), "w") as f:
        f.write("base\n")
    git(d, "add", "-A"); git(d, "commit", "-m", "init")
    return d


def merged_worktree(repo, branch):
    """A branch whose commit is ALREADY merged into main, checked out as its
    own worktree - exactly the state that fooled the old sweep."""
    git(repo, "checkout", "-b", branch)
    with open(os.path.join(repo, branch + ".txt"), "w") as f:
        f.write("work\n")
    git(repo, "add", "-A"); git(repo, "commit", "-m", "work on " + branch)
    git(repo, "checkout", "main")
    git(repo, "merge", "--no-ff", branch, "-m", "merge " + branch)
    git(repo, "checkout", "-b", branch + "-dead")   # placeholder so branch delete below is safe
    git(repo, "checkout", "main")
    git(repo, "branch", "-D", branch + "-dead")
    wt = tempfile.mkdtemp()
    os.rmdir(wt)   # worktree add needs the target to NOT exist
    git(repo, "worktree", "add", wt, branch)
    return wt


def _track(tid, repo, worktree, branch, **kw):
    t = {"id": tid, "repo": repo, "worktree": worktree, "branch": branch,
         "task": "t", "lane": "working", "status": "needs_you"}
    t.update(kw)
    db.track_put(t)
    return t


def test_active_card_tree_survives_the_sweep():
    repo = new_repo()
    wt = merged_worktree(repo, "active-branch")
    _track("t-active", repo, wt, "active-branch", lane="working")   # NOT terminal

    n = sessions.sweep_worktrees()
    check(n == 0, "nothing reclaimed while the card is still open (got %d)" % n)
    check(os.path.isdir(wt), "the worktree directory still exists")
    check(os.path.isdir(os.path.join(wt, ".git")) or os.path.isfile(os.path.join(wt, ".git")),
          ".git link is intact - not deregistered")
    check(os.path.isfile(os.path.join(wt, "active-branch.txt")), "tracked file survives")


def test_terminal_card_tree_still_reclaimed():
    """The fix must not become a permanent leak - a DONE card's merged,
    clean tree is still reclaimed exactly as before."""
    repo = new_repo()
    wt = merged_worktree(repo, "done-branch")
    _track("t-done", repo, wt, "done-branch", lane="done")   # terminal

    n = sessions.sweep_worktrees()
    check(n == 1, "a terminal card's merged tree is still reclaimed (got %d)" % n)
    check(not os.path.isdir(wt), "the worktree directory is gone")


def test_archived_flag_also_counts_as_terminal():
    repo = new_repo()
    wt = merged_worktree(repo, "archived-branch")
    _track("t-archived", repo, wt, "archived-branch", lane="working", archived=True)

    n = sessions.sweep_worktrees()
    check(n == 1, "archived=True is terminal even if lane never moved (got %d)" % n)
    check(not os.path.isdir(wt), "the worktree directory is gone")


if __name__ == "__main__":
    test_active_card_tree_survives_the_sweep()
    test_terminal_card_tree_still_reclaimed()
    test_archived_flag_also_counts_as_terminal()
    print()
    if _fails:
        print("FAILED: %d check(s)" % len(_fails))
        sys.exit(1)
    print("ALL GREEN - sweep_worktrees never reclaims a non-terminal card's tree")
