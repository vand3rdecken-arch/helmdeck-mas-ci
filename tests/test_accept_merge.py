# -*- coding: utf-8 -*-
"""Headless tests for accept-classify-and-merge (sessions._merge_to_main).

Accepting a card must CLASSIFY it and say why: redundant (already in main) ->
close it; real work -> merge; conflict -> bounce with the conflicting files and a
resolve path, leaving main exactly as found. Self-sandboxing: throwaway git repos."""
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
    ok, kind, msg = sessions._merge_to_main({"repo": repo, "branch": "card-a", "id": "t1"})
    check(ok and kind == "merged", "real work -> kind=merged, accept ok (%s)" % kind)
    check(os.path.exists(os.path.join(repo, "feature.txt")), "branch's file now on main")
    check(git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main", "still on main after merge")


def test_redundant_already_merged():
    repo = new_repo()
    branch_with_commit(repo, "card-b", "f.txt", "x\n")
    sessions._merge_to_main({"repo": repo, "branch": "card-b", "id": "t2"})
    ok, kind, msg = sessions._merge_to_main({"repo": repo, "branch": "card-b", "id": "t2"})
    check(ok and kind == "already_merged", "already-in-main -> redundant, close (kind=%s)" % kind)
    check("edundant" in msg or "bereits" in msg, "message says it was redundant")


def test_redundant_uncommitted_warns():
    # branch already in main (nothing to land) BUT the worktree still has
    # uncommitted changes -> accept/close, and WARN they were not included.
    repo = new_repo()
    branch_with_commit(repo, "card-r", "f.txt", "x\n")
    sessions._merge_to_main({"repo": repo, "branch": "card-r", "id": "t2b"})
    with open(os.path.join(repo, "base.txt"), "w") as f:
        f.write("uncommitted redundant edit\n")
    ok, kind, msg = sessions._merge_to_main(
        {"repo": repo, "branch": "card-r", "worktree": repo, "id": "t2b"})
    check(ok and kind == "redundant_uncommitted", "redundant + dirty worktree -> close with warning (kind=%s)" % kind)
    check("uncommittet" in msg.lower() or "NICHT" in msg, "message warns uncommitted changes were dropped")


def test_dirty_unrelated_file_still_merges():
    repo = new_repo()
    branch_with_commit(repo, "card-c", "feature.txt", "x\n")   # branch touches feature.txt only
    with open(os.path.join(repo, "base.txt"), "w") as f:
        f.write("runtime output, uncommitted\n")               # dirty an UNRELATED file
    ok, kind, msg = sessions._merge_to_main({"repo": repo, "branch": "card-c", "id": "t3"})
    check(ok and kind == "merged", "merge lands despite unrelated dirty tree (kind=%s)" % kind)
    check("runtime output" in open(os.path.join(repo, "base.txt")).read(),
          "the pre-existing dirty change is preserved (not clobbered)")


def test_dirty_conflicting_file_bounces():
    repo = new_repo()
    git(repo, "checkout", "-b", "card-c2")
    with open(os.path.join(repo, "base.txt"), "w") as f:
        f.write("branch change to base\n")
    git(repo, "add", "-A"); git(repo, "commit", "-m", "edit base")
    git(repo, "checkout", "main")
    with open(os.path.join(repo, "base.txt"), "w") as f:
        f.write("uncommitted local edit to base\n")
    ok, kind, msg = sessions._merge_to_main({"repo": repo, "branch": "card-c2", "id": "t3b"})
    check(not ok and kind == "conflict", "merge that would clobber a dirty file -> conflict (kind=%s)" % kind)
    check("uncommitted local edit" in open(os.path.join(repo, "base.txt")).read(),
          "dirty file content preserved after the refused merge")


def test_conflict_reports_files_and_aborts():
    repo = new_repo()
    git(repo, "checkout", "-b", "card-d")
    with open(os.path.join(repo, "base.txt"), "w") as f:
        f.write("branch version\n")
    git(repo, "add", "-A"); git(repo, "commit", "-m", "branch edit")
    git(repo, "checkout", "main")
    with open(os.path.join(repo, "base.txt"), "w") as f:
        f.write("main version\n")
    git(repo, "add", "-A"); git(repo, "commit", "-m", "main edit")
    head_before = git(repo, "rev-parse", "HEAD")
    ok, kind, msg = sessions._merge_to_main({"repo": repo, "branch": "card-d", "id": "t4"})
    check(not ok and kind == "conflict", "diverged edits -> conflict (kind=%s)" % kind)
    check("base.txt" in msg, "conflict message names the conflicting file")
    check("merge main" in msg.lower() or "loese" in msg.lower(), "message gives a resolve path")
    check(git(repo, "rev-parse", "HEAD") == head_before, "main HEAD unchanged (merge aborted)")
    check(git(repo, "status", "--porcelain") == "", "main tree clean after abort")


def test_on_card_branch_guard():
    repo = new_repo()
    git(repo, "checkout", "-b", "card-e")   # checkout left ON the card branch
    ok, kind, msg = sessions._merge_to_main({"repo": repo, "branch": "card-e", "id": "t5"})
    check(not ok and kind == "blocked", "checkout ON the card branch -> blocked (kind=%s)" % kind)


def test_autocommit_commits_dirty_worktree():
    # Review==Abnahme: finishing a card commits its uncommitted worktree work on
    # the branch (so it never dead-ends on 'uncommitted changes').
    repo = new_repo()                                    # doubles as the worktree
    with open(os.path.join(repo, "new.txt"), "w") as f:
        f.write("agent's uncommitted work\n")
    committed = sessions._autocommit({"worktree": repo, "id": "tac"})
    check(committed, "dirty worktree -> autocommit makes a commit")
    check(git(repo, "status", "--porcelain") == "", "worktree clean after autocommit")
    check("finalize" in git(repo, "log", "-1", "--format=%s"), "commit message marks the finalize")
    check(not sessions._autocommit({"worktree": repo, "id": "tac"}), "clean worktree -> nothing to commit")


def test_harness_side_conflict_resolution():
    # The paradox fix: the HARNESS merges main into the card's branch (in the
    # worktree), turning the conflict into editable MARKERS - the agent never runs
    # a git-merge. Resolve by editing -> autocommit completes it -> lands clean.
    repo = new_repo()
    wt = tempfile.mkdtemp(); os.rmdir(wt)
    git(repo, "branch", "feat")
    git(repo, "worktree", "add", wt, "feat")
    with open(os.path.join(wt, "base.txt"), "w") as f:
        f.write("branch's take\n")
    git(wt, "add", "-A"); git(wt, "commit", "-m", "branch edit")
    with open(os.path.join(repo, "base.txt"), "w") as f:      # main diverges on same file
        f.write("main's take\n")
    git(repo, "add", "-A"); git(repo, "commit", "-m", "main edit")
    t = {"repo": repo, "branch": "feat", "worktree": wt, "id": "tcr"}

    ok, kind, _ = sessions._merge_to_main(t)
    check(not ok and kind == "conflict", "diverged edits -> conflict first (kind=%s)" % kind)
    res = sessions._pull_main_into_branch(t)
    check(res.startswith("markers"), "harness pulls main into the branch -> editable markers (%s)" % res[:30])
    check("<<<<<<<" in open(os.path.join(wt, "base.txt")).read(), "conflict markers now in the WORKTREE file (editable)")
    # agent 'resolves' by plain editing (no git-merge)
    with open(os.path.join(wt, "base.txt"), "w") as f:
        f.write("merged: main's take + branch's take\n")
    ac = sessions._autocommit(t)
    check(ac is True, "editing + autocommit completes the merge (ac=%s)" % ac)
    ok2, kind2, _ = sessions._merge_to_main(t)
    check(ok2 and kind2 == "merged", "now lands clean on main (kind=%s)" % kind2)
    check("merged: main" in open(os.path.join(repo, "base.txt")).read(), "resolved content on main")


def test_autocommit_refuses_unresolved_markers():
    repo = new_repo()
    wt = tempfile.mkdtemp(); os.rmdir(wt)
    git(repo, "branch", "feat2")
    git(repo, "worktree", "add", wt, "feat2")
    with open(os.path.join(wt, "base.txt"), "w") as f:
        f.write("branch\n")
    git(wt, "add", "-A"); git(wt, "commit", "-m", "b")
    with open(os.path.join(repo, "base.txt"), "w") as f:
        f.write("main\n")
    git(repo, "add", "-A"); git(repo, "commit", "-m", "m")
    t = {"repo": repo, "branch": "feat2", "worktree": wt, "id": "tmk"}
    sessions._pull_main_into_branch(t)                        # leaves markers, unresolved
    check(sessions._autocommit(t) == "markers", "autocommit refuses to commit unresolved markers")


def test_merge_event_signature_no_collision():
    # Regression: move_lane('done') does events.emit("merge", tid, ok=, outcome=,
    # detail=). A field named 'kind' here collides with emit's positional `kind`
    # param and crashed EVERY accept (TypeError). Guard the exact call shape.
    import events
    events.EV = os.path.join(tempfile.mkdtemp(), "events.jsonl")   # isolate the append
    row = events.emit("merge", "t-sig", ok=True, outcome="merged", detail="x")
    check(row.get("kind") == "merge" and row.get("outcome") == "merged",
          "merge event emits with ok/outcome/detail - no kind= collision")


if __name__ == "__main__":
    test_happy_merge_lands()
    test_redundant_already_merged()
    test_redundant_uncommitted_warns()
    test_dirty_unrelated_file_still_merges()
    test_dirty_conflicting_file_bounces()
    test_conflict_reports_files_and_aborts()
    test_on_card_branch_guard()
    test_autocommit_commits_dirty_worktree()
    test_harness_side_conflict_resolution()
    test_autocommit_refuses_unresolved_markers()
    test_merge_event_signature_no_collision()
    print("OK" if not _fails else "FAILED: %d" % len(_fails))
    sys.exit(1 if _fails else 0)
