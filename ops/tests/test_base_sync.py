# -*- coding: utf-8 -*-
"""Headless tests for BASE-SYNC before the gate (lanemachine._sync_base,
debt gate-base-lag / accept-merge-base-branch half A).

A worktree card is isolated from base drift for its whole open lifetime, and
move_lane never merged the base back in - so the gate answered "was this green
against the code we forked from?" instead of "is it green against the code it
will land beside?". Live on 2026-08-20 a 56-file base-only test-wiring fix
reddened card proc-20260816-s2 for code it never touched. move_lane now merges
the card's recorded base in between _autocommit and _gate.

Pinned here:
  1. the live failure shape: base changes a behaviour AND its test, the card
     touched neither -> gating as-is is RED, after _sync_base it is GREEN
  2. an up-to-date branch reports "uptodate" and makes no commit
  3. a real collision leaves editable MARKERS (never a mystery-red gate) and is
     completed by the existing edit -> _autocommit loop
  4. the live-tree cards (fast-track/direct, worktree == repo) are SKIPPED
  5. _base_branch DERIVES + VERIFIES: recorded base wins, origin/X prefers the
     local X, a stale record falls back to the repo checkout, never a guess
  6. dispatch records base_branch at branch CREATION - the one event where the
     fork point is a fact - and never rewrites it afterwards

Self-sandboxing: throwaway git repos + real worktrees + a throwaway DB, no
daemon, no network."""
import os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, DAEMON)

SANDBOX = tempfile.mkdtemp()
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")      # never touch the real board
from spine.storage import events
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from cells.engineer import sessions
from spine.storage.trackstore import _save_track, _load, _find

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


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def new_repo():
    d = tempfile.mkdtemp()
    git(d, "init")
    git(d, "symbolic-ref", "HEAD", "refs/heads/main")   # old git has no `init -b`
    git(d, "config", "user.email", "t@t.t")
    git(d, "config", "user.name", "t")
    write(os.path.join(d, "base.txt"), "base\n")
    # the gate refuses ANY dirty worktree; a checker that imports leaves
    # __pycache__ behind, exactly as the real repo's .gitignore covers.
    write(os.path.join(d, ".gitignore"), "__pycache__/\n")
    git(d, "add", "-A"); git(d, "commit", "-m", "init")
    return d


def card(repo, branch="card-x", base="main"):
    """A dispatched worktree card: its own branch + worktree, base recorded at
    creation exactly like dispatch._record_base_branch does."""
    wt = tempfile.mkdtemp(); os.rmdir(wt)
    git(repo, "worktree", "add", wt, "-b", branch, "--no-track", base)
    return {"repo": repo, "branch": branch, "worktree": wt, "base_branch": base,
            "id": "t-" + branch}


def test_base_drift_reds_the_gate_until_synced():
    """THE bug, end to end. _gate deliberately runs the REPO's gate - "main is
    authoritative, so EVERY card is verified with the current gate even on an
    old branch" - against the CARD's code. That is precisely what makes base
    drift lethal: base ships a behaviour and its check together, the card
    touched neither, and the card is judged by the NEW check while carrying the
    OLD behaviour."""
    repo = new_repo()
    write(os.path.join(repo, "lib.py"), "def f():\n    return 1\n")
    # the checker lives with the gate (in the repo) and imports the code under
    # test from the CARD's tree (cwd), same split as ops/tools/run_gate.py.
    write(os.path.join(repo, "check.py"),
          "import os, sys\nsys.path.insert(0, os.getcwd())\n"
          "import lib\nsys.exit(0 if lib.f() == 1 else 1)\n")
    write(os.path.join(repo, "helmdeck.gate"),
          '"%s" "%s"' % (sys.executable.replace("\\", "\\\\"),
                         os.path.join(repo, "check.py").replace("\\", "\\\\")))
    git(repo, "add", "-A"); git(repo, "commit", "-m", "lib + its check")

    t = card(repo, "card-drift")
    write(os.path.join(t["worktree"], "mine.txt"), "work this card DID do\n")
    git(t["worktree"], "add", "-A"); git(t["worktree"], "commit", "-m", "card work")
    ok0, _p = sessions._gate(t)
    check(ok0, "card is green when it is dispatched")

    # base moves the behaviour AND its check in ONE commit (the correct
    # discipline - and it still bites, because the card has neither half)
    write(os.path.join(repo, "lib.py"), "def f():\n    return 2\n")
    write(os.path.join(repo, "check.py"),
          "import os, sys\nsys.path.insert(0, os.getcwd())\n"
          "import lib\nsys.exit(0 if lib.f() == 2 else 1)\n")
    git(repo, "add", "-A"); git(repo, "commit", "-m", "base: new behaviour + its check")

    ok, problems = sessions._gate(t)
    check(not ok, "before sync: card reds on BASE code it never touched (%s)"
          % ("red" if not ok else "green"))

    res = sessions._sync_base(t)
    check(res.startswith("synced"), "sync merges the base into the card (%s)" % res)
    check("return 2" in open(os.path.join(t["worktree"], "lib.py")).read(),
          "the base's new behaviour is now in the worktree")
    check("work this card DID do" in
          open(os.path.join(t["worktree"], "mine.txt")).read(),
          "the card's own work survived the sync")
    ok2, problems2 = sessions._gate(t)
    check(ok2, "after sync: gate is GREEN against the current base (%s)"
          % (problems2[0][:80] if problems2 else "green"))


def test_uptodate_makes_no_commit():
    repo = new_repo()
    t = card(repo, "card-fresh")
    head = git(t["worktree"], "rev-parse", "HEAD")
    res = sessions._sync_base(t)
    check(res == "uptodate", "branch already contains the base -> uptodate (%s)" % res)
    check(git(t["worktree"], "rev-parse", "HEAD") == head,
          "no commit invented when there is nothing to sync")
    check(git(t["worktree"], "status", "--porcelain") == "",
          "worktree left clean")


def test_collision_leaves_editable_markers():
    """A real collision must NOT surface as a red gate on foreign code - it
    surfaces as markers the agent resolves by plain editing, then the existing
    _autocommit loop completes the merge."""
    repo = new_repo()
    t = card(repo, "card-clash")
    write(os.path.join(t["worktree"], "base.txt"), "the card's take\n")
    git(t["worktree"], "add", "-A"); git(t["worktree"], "commit", "-m", "card edit")
    write(os.path.join(repo, "base.txt"), "the base's take\n")
    git(repo, "add", "-A"); git(repo, "commit", "-m", "base edit")

    res = sessions._sync_base(t)
    check(res.startswith("conflict:"), "collision -> conflict (%s)" % res[:40])
    check("base.txt" in res, "conflict names the colliding file")
    check("<<<<<<<" in open(os.path.join(t["worktree"], "base.txt")).read(),
          "markers left IN THE WORKTREE, editable (never a git-merge for the agent)")

    # a second pass must report the same thing, not crash on "already merging"
    check(sessions._sync_base(t).startswith("conflict:"),
          "re-running while mid-merge reports the conflict, not a git error")

    # the agent resolves by editing; the existing loop finishes the job
    write(os.path.join(t["worktree"], "base.txt"), "both takes, merged\n")
    check(sessions._autocommit(t) is True, "editing + _autocommit completes the merge")
    check(sessions._sync_base(t) == "uptodate", "after resolving, the card is in sync")


def test_live_tree_cards_are_skipped():
    """Fast-track/direct cards edit the repo root itself (debt
    fast-track-no-gate) - there is no copy to drift and no base to merge in."""
    repo = new_repo()
    live = {"repo": repo, "worktree": repo, "branch": "main", "id": "t-live"}
    check(sessions._sync_base(live).startswith("skip:"),
          "worktree == repo -> skipped, never a surprise commit in the live tree")
    machine = {"repo": repo, "worktree": tempfile.mkdtemp(), "id": "t-mach",
               "machine": True}
    check(sessions._sync_base(machine).startswith("skip:"),
          "machine card (no branch) -> skipped")


def test_base_branch_is_derived_and_verified():
    repo = new_repo()
    t = card(repo, "card-base")
    check(sessions._base_branch(t) == "main", "recorded base is used")

    # a record naming a REMOTE ref prefers the LOCAL twin: the accept merges
    # into the local checkout, so that is the code the card lands beside.
    git(repo, "update-ref", "refs/remotes/origin/main", git(repo, "rev-parse", "main"))
    t_origin = dict(t, base_branch="origin/main")
    check(sessions._base_branch(t_origin) == "main",
          "origin/<base> resolves to the local base branch")

    # a stale/renamed record is NOT trusted - fall back to the repo's checkout
    t_stale = dict(t, base_branch="branch-that-was-deleted")
    check(sessions._base_branch(t_stale) == "main",
          "unresolvable record falls back to the repo checkout, never merged blindly")

    # a legacy card (dispatched before base_branch existed) still syncs
    t_legacy = dict(t); t_legacy.pop("base_branch")
    check(sessions._base_branch(t_legacy) == "main",
          "card with no recorded base falls back to the repo checkout")

    # nothing verifiable -> None, and _sync_base degrades instead of blocking
    git(repo, "checkout", "-q", "--detach", "HEAD")
    t_det = dict(t); t_det.pop("base_branch")
    check(sessions._base_branch(t_det) is None, "detached repo checkout -> no base")
    check(sessions._sync_base(t_det).startswith("error:"),
          "no base -> error (caller gates as-is), never a bounce")


def test_autoaccept_probe_syncs_before_gating():
    """The chain poller / autopilot pre-gate a delivered card before spawning
    the real accept (processes._probe_gate). Probing the STALE tree re-opened
    gate-base-lag for exactly the autonomous paths: a drifted card probed red
    on foreign code forever and never auto-accepted, even though move_lane
    would sync and gate it green. The probe must sync first - and a sync
    CONFLICT must read as red (an auto-accept never lands a half-merge)."""
    from cells.process import processes
    repo = new_repo()
    write(os.path.join(repo, "lib.py"), "def f():\n    return 1\n")
    write(os.path.join(repo, "check.py"),
          "import os, sys\nsys.path.insert(0, os.getcwd())\n"
          "import lib\nsys.exit(0 if lib.f() == 1 else 1)\n")
    write(os.path.join(repo, "helmdeck.gate"),
          '"%s" "%s"' % (sys.executable.replace("\\", "\\\\"),
                         os.path.join(repo, "check.py").replace("\\", "\\\\")))
    git(repo, "add", "-A"); git(repo, "commit", "-m", "lib + its check")
    t = card(repo, "card-probe")
    # base drifts behaviour + check together; the card touched neither
    write(os.path.join(repo, "lib.py"), "def f():\n    return 2\n")
    write(os.path.join(repo, "check.py"),
          "import os, sys\nsys.path.insert(0, os.getcwd())\n"
          "import lib\nsys.exit(0 if lib.f() == 2 else 1)\n")
    git(repo, "add", "-A"); git(repo, "commit", "-m", "base drift")

    check(not sessions._gate(t)[0], "stale probe would be red (the starvation)")
    ok, _p = processes._probe_gate(t)
    check(ok, "probe syncs first -> green, the card can auto-accept")

    # a colliding card must probe RED, with the markers left as the medium
    t2 = card(repo, "card-probe-clash")
    write(os.path.join(t2["worktree"], "base.txt"), "card take\n")
    git(t2["worktree"], "add", "-A"); git(t2["worktree"], "commit", "-m", "card")
    write(os.path.join(repo, "base.txt"), "base take\n")
    git(repo, "add", "-A"); git(repo, "commit", "-m", "base")
    ok2, problems2 = processes._probe_gate(t2)
    check(not ok2 and "base-sync conflict" in problems2[0],
          "sync conflict probes red - an auto-accept never lands a half-merge")


def test_dispatch_records_the_base_at_branch_creation():
    """The fork point is only a fact at the fork. dispatch._ensure_worktree
    records it there, into the STORE (not just the caller's snapshot), and the
    record is never rewritten on a later dispatch - by then the repo checkout
    may sit on a different branch and HEAD would answer a different question."""
    repo = new_repo()
    git(repo, "checkout", "-q", "-b", "release-2")     # a NON-default base
    t = {"id": "t-dispatch-base", "repo": repo, "branch": "card-dispatch",
         "task": "x", "lane": "working"}
    _save_track(t)

    wt = sessions._ensure_worktree(t)
    stored = _find(_load(), "t-dispatch-base")
    check(stored.get("base_branch") == "release-2",
          "base recorded ON THE CARD at branch creation (%s)" % stored.get("base_branch"))
    check(t.get("base_branch") == "release-2", "the caller's snapshot sees it too")
    check(git(wt, "rev-parse", "--abbrev-ref", "HEAD") == "card-dispatch",
          "the worktree really is the card's branch")

    # the owner moves the main checkout elsewhere and the card is re-dispatched
    # (its worktree reclaimed): the ORIGINAL base must survive.
    git(repo, "checkout", "-q", "main")
    subprocess.run(["git", "-C", repo, "worktree", "remove", "--force", wt],
                   capture_output=True, text=True)
    sessions._ensure_worktree(_find(_load(), "t-dispatch-base"))
    again = _find(_load(), "t-dispatch-base")
    check(again.get("base_branch") == "release-2",
          "re-dispatch does NOT rewrite the base to the current checkout (%s)"
          % again.get("base_branch"))


if __name__ == "__main__":
    test_base_drift_reds_the_gate_until_synced()
    test_uptodate_makes_no_commit()
    test_collision_leaves_editable_markers()
    test_live_tree_cards_are_skipped()
    test_base_branch_is_derived_and_verified()
    test_autoaccept_probe_syncs_before_gating()
    test_dispatch_records_the_base_at_branch_creation()
    print("OK" if not _fails else "FAILED: %d" % len(_fails))
    sys.exit(1 if _fails else 0)
