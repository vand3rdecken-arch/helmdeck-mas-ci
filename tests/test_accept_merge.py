# -*- coding: utf-8 -*-
"""Headless tests for accept-merges-to-main (sessions._merge_to_main).

Accepting a card must LAND its branch in the repo, or bounce cleanly if it can't.
Self-sandboxing: throwaway git repos in temp dirs, no daemon, no board state."""
import os, sys, subprocess, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.join(os.path.dirname(HERE), "daemon")
sys.path.insert(0, DAEMON)
import sessions

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
    git(d, "symbolic-ref", "HEAD", "refs/heads/main")   # old git has no `init -b`
    git(d, "config", "user.email", "t@t.t")
    git(d, "config", "user.name", "t")
    with open(os.path.join(d, "base.txt"), "w") as f:
        f.write("base\n")
    git(d, "add", "-A"); git(d, "commit", "-m", "init")
    return d


def branch_with_commit(repo, branch, fname, content):
    git(repo, "checkout", "-b", branch)
    with open(os.path.join(repo, fname), "w") as f:
        f.write(content)
    git(repo, "add", "-A"); git(repo, "commit", "-m", "work on " + branch)
    git(repo, "checkout", "main")


def test_happy_merge_lands():
    repo = new_repo()
    branch_with_commit(repo, "card-a", "feature.txt", "hello\n")
    ok, msg = sessions._merge_to_main({"repo": repo, "branch": "card-a", "id": "t1"})
    check(ok, "clean merge reported ok (%r)" % msg[:50])
    check(os.path.exists(os.path.join(repo, "feature.txt")), "branch's file now on main")
    check("card-a" in git(repo, "log", "--oneline"), "merge commit references the card branch")
    check(git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main", "still on main after merge")


def test_idempotent_already_merged():
    repo = new_repo()
    branch_with_commit(repo, "card-b", "f.txt", "x\n")
    sessions._merge_to_main({"repo": repo, "branch": "card-b", "id": "t2"})
    ok, msg = sessions._merge_to_main({"repo": repo, "branch": "card-b", "id": "t2"})
    check(ok and "already merged" in msg, "re-accepting an already-merged branch is a no-op ok (%r)" % msg[:40])


def test_dirty_unrelated_file_still_merges():
    # a real project repo (scraper) keeps tracked runtime output perpetually
    # 'modified'. The merge doesn't touch those files, so it must STILL land.
    repo = new_repo()
    branch_with_commit(repo, "card-c", "feature.txt", "x\n")   # branch touches feature.txt only
    with open(os.path.join(repo, "base.txt"), "w") as f:
        f.write("runtime output, uncommitted\n")               # dirty an UNRELATED file
    ok, msg = sessions._merge_to_main({"repo": repo, "branch": "card-c", "id": "t3"})
    check(ok, "merge lands despite a dirty tree when the merge is unrelated (%r)" % msg[:50])
    check(os.path.exists(os.path.join(repo, "feature.txt")), "branch file merged in")
    check("runtime output" in open(os.path.join(repo, "base.txt")).read(),
          "the pre-existing dirty change is preserved (not clobbered)")


def test_dirty_conflicting_file_bounces():
    # if the merge WOULD touch a file that is dirty, git refuses - we must bounce
    # and leave the tree exactly as found.
    repo = new_repo()
    git(repo, "checkout", "-b", "card-c2")
    with open(os.path.join(repo, "base.txt"), "w") as f:
        f.write("branch change to base\n")            # branch edits base.txt
    git(repo, "add", "-A"); git(repo, "commit", "-m", "edit base")
    git(repo, "checkout", "main")
    with open(os.path.join(repo, "base.txt"), "w") as f:
        f.write("uncommitted local edit to base\n")    # SAME file dirty, uncommitted
    ok, msg = sessions._merge_to_main({"repo": repo, "branch": "card-c2", "id": "t3b"})
    check(not ok, "merge that would clobber an uncommitted file is refused")
    check(git(repo, "status", "--porcelain") != "", "the local edit is still there (not lost)")
    check("uncommitted local edit" in open(os.path.join(repo, "base.txt")).read(),
          "dirty file content preserved after the refused merge")


def test_conflict_bounces_and_aborts():
    repo = new_repo()
    # branch edits base.txt one way...
    git(repo, "checkout", "-b", "card-d")
    with open(os.path.join(repo, "base.txt"), "w") as f:
        f.write("branch version\n")
    git(repo, "add", "-A"); git(repo, "commit", "-m", "branch edit")
    git(repo, "checkout", "main")
    # ...main edits the SAME file the other way and commits (clean tree, real conflict)
    with open(os.path.join(repo, "base.txt"), "w") as f:
        f.write("main version\n")
    git(repo, "add", "-A"); git(repo, "commit", "-m", "main edit")
    head_before = git(repo, "rev-parse", "HEAD")
    ok, msg = sessions._merge_to_main({"repo": repo, "branch": "card-d", "id": "t4"})
    check(not ok, "conflicting merge is refused")
    check("conflict" in msg.lower(), "message says conflict (%r)" % msg[:50])
    check(git(repo, "rev-parse", "HEAD") == head_before, "main HEAD unchanged (merge aborted)")
    check(git(repo, "status", "--porcelain") == "", "main tree clean after abort - not left mid-merge")


def test_on_card_branch_guard():
    repo = new_repo()
    git(repo, "checkout", "-b", "card-e")   # leave the checkout ON the card branch
    ok, msg = sessions._merge_to_main({"repo": repo, "branch": "card-e", "id": "t5"})
    check(not ok and "card branch" in msg, "refuses to merge when checkout is ON the card branch")


if __name__ == "__main__":
    test_happy_merge_lands()
    test_idempotent_already_merged()
    test_dirty_unrelated_file_still_merges()
    test_dirty_conflicting_file_bounces()
    test_conflict_bounces_and_aborts()
    test_on_card_branch_guard()
    print("OK" if not _fails else "FAILED: %d" % len(_fails))
    sys.exit(1 if _fails else 0)
