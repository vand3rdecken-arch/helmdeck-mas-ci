# -*- coding: utf-8 -*-
"""A worktree PATH existing is not proof it is a working worktree (found via a
worker's incidental finding 2026-08-15, in a card unrelated to worktrees: a
plain directory sitting where `git worktree add` should have run made
_ensure_worktree hand it out as-is, so every git command the turn ran inside
it failed with 'not a git repository' - the failure surfaced deep in the
turn, not at dispatch). _ensure_worktree must detect that case via
_git_state_broken (the same check reclaim already trusts) and rebuild the
slot before returning it.

Self-sandboxing: builds a real temp git repo, no daemon/db involved.

Run: py -3.12 daemon/test_worktree_never_init.py
"""
import os, shutil, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sessions


def _git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    assert r.returncode == 0, "git %s failed: %s" % (" ".join(args), r.stderr)
    return r.stdout.strip()


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-test-")
    try:
        repo = os.path.join(tmp, "repo")
        os.makedirs(repo)
        _git(repo, "init")
        _git(repo, "config", "user.email", "test@example.com")
        _git(repo, "config", "user.name", "test")
        with open(os.path.join(repo, "f.txt"), "w") as f:
            f.write("x")
        _git(repo, "add", "f.txt")
        _git(repo, "commit", "-m", "init")
        _git(repo, "checkout", "-B", "main")

        t = {"repo": repo, "branch": "card-branch"}
        wt = sessions._worktree_for(repo, t["branch"])

        # -- simulate the failure mode: a plain dir sits at the worktree slot,
        # never created via `git worktree add` (interrupted add, stray mkdir,
        # or .git severed by hand) -------------------------------------------
        os.makedirs(wt)
        with open(os.path.join(wt, "stray.txt"), "w") as f:
            f.write("not a real worktree")
        assert sessions._git_state_broken(wt), \
            "test setup wrong: plain dir not detected as broken"

        got = sessions._ensure_worktree(t)

        assert got == wt, "returned a different path than expected: %r" % got
        assert not sessions._git_state_broken(wt), \
            "_ensure_worktree returned a slot that is still not a real worktree"
        r = subprocess.run(["git", "-C", wt, "rev-parse", "--is-inside-work-tree"],
                           capture_output=True, text=True)
        assert r.returncode == 0 and r.stdout.strip() == "true", \
            "rebuilt slot still fails basic git commands: %s" % r.stderr
        assert not os.path.exists(os.path.join(wt, "stray.txt")), \
            "stray content from the broken dir survived the rebuild"
        print("PASS _ensure_worktree: never-git-init'd slot detected and rebuilt")

        # -- calling it again on the now-valid worktree must be a no-op reuse --
        # (git worktree list --porcelain reports forward slashes regardless of
        # OS, so normalize before comparing paths)
        got2 = sessions._ensure_worktree(t)
        assert os.path.normcase(os.path.normpath(got2)) == \
               os.path.normcase(os.path.normpath(wt)), \
               "reuse returned a different worktree: %r" % got2
        print("PASS _ensure_worktree: valid worktree reused, not rebuilt again")
        print("ALL PASS")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
