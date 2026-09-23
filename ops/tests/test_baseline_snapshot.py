# -*- coding: utf-8 -*-
"""Henry's rollback point must not eat anyone else's work.

2026-09-23, three times in one day: `_baseline_commit` did `git add -A` +
`git commit` on the live tree, so every in-flight change went into a commit
titled "Henry baseline - snapshot before hands-on judgement turn" - an
unapproved Wear edit set, then two finished changes of the owner's own, with
their real messages and authorship gone. It is a dangling `commit-tree`
object now: the rollback point exists, HEAD / index / working tree do not
move.

Self-sandboxing: a throwaway git repo in a temp dir. No daemon, no network,
no LLM, never the real checkout."""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from spine.git import gitutil

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return r.stdout.strip()


def main():
    tmp = tempfile.mkdtemp(prefix="hd-baseline-")
    try:
        git(tmp, "init", "-q")
        git(tmp, "config", "user.email", "t@t")
        git(tmp, "config", "user.name", "T")
        with open(os.path.join(tmp, "kept.txt"), "w") as f:
            f.write("committed\n")
        with open(os.path.join(tmp, ".gitignore"), "w") as f:
            f.write("secret.json\n")
        git(tmp, "add", "-A")
        git(tmp, "commit", "-qm", "base")
        head0 = git(tmp, "rev-parse", "HEAD")

        # 1) clean tree -> nothing to snapshot
        check(gitutil.snapshot_object(tmp, "x") == "", "clean tree -> no snapshot object")

        # someone else's work in flight: an edit, a new file, and a secret
        with open(os.path.join(tmp, "kept.txt"), "a") as f:
            f.write("owner's uncommitted edit\n")
        with open(os.path.join(tmp, "new.txt"), "w") as f:
            f.write("owner's new file\n")
        with open(os.path.join(tmp, "secret.json"), "w") as f:
            f.write("token\n")
        git(tmp, "add", "new.txt")            # partially staged, on purpose
        status_before = git(tmp, "status", "--porcelain")

        snap = gitutil.snapshot_object(tmp, "Henry baseline - rollback point")
        check(len(snap) == 40, "dirty tree -> a 40-char object sha (%s)" % snap[:12])

        # 2) THE POINT: nothing moved
        check(git(tmp, "rev-parse", "HEAD") == head0, "HEAD did not move")
        check(git(tmp, "status", "--porcelain") == status_before,
              "working tree + index untouched (staged stays staged)")
        check(git(tmp, "log", "--oneline").count("\n") == 0, "no new commit in the log")
        check("Henry baseline" not in git(tmp, "log", "--all", "--oneline"),
              "the snapshot is NOT reachable from any branch")

        # 3) but it captured everything - that is what makes it a rollback point
        files = git(tmp, "ls-tree", "-r", "--name-only", snap).split("\n")
        check("kept.txt" in files, "snapshot has the tracked file")
        check("new.txt" in files, "snapshot has the untracked-but-added file")
        body = git(tmp, "show", "%s:kept.txt" % snap)
        check("owner's uncommitted edit" in body, "snapshot has the UNCOMMITTED edit")
        check("secret.json" not in files, "gitignored secret stays OUT of the snapshot")

        # 4) and it is restorable
        with open(os.path.join(tmp, "kept.txt"), "w") as f:
            f.write("henry broke it\n")
        subprocess.run(["git", "-C", tmp, "checkout", snap, "--", "kept.txt"],
                       capture_output=True, text=True)
        with open(os.path.join(tmp, "kept.txt")) as f:
            back = f.read()
        check("owner's uncommitted edit" in back, "restorable: git checkout <snap> -- <file>")

        # 5) an untracked file the snapshot captured is also a real parent-linked
        #    object, so `git show` works on it without a branch
        check(head0[:8] in git(tmp, "cat-file", "-p", snap), "snapshot's parent is HEAD")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 6) the broker uses it and no longer commits
    src = open(os.path.join(ROOT, "cells", "copilot", "broker", "henry_broker.py"),
               encoding="utf-8").read()
    at = src.find("def _baseline_commit")
    body = src[at:at + 1600]
    check("snapshot_object" in body, "_baseline_commit uses snapshot_object")
    check('"commit"' not in body and "'commit'" not in body,
          "_baseline_commit no longer runs git commit")
    check('"add", "-A"' not in body, "_baseline_commit no longer runs git add -A")

    print("\n%d FAIL" % len(_fails) if _fails else "\nall ok")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
