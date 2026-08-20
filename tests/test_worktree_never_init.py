# -*- coding: utf-8 -*-
"""A worktree PATH existing is not proof it is a working worktree (found via a
worker's incidental finding 2026-08-15, in a card unrelated to worktrees: a
plain directory sitting where `git worktree add` should have run made
_ensure_worktree hand it out as-is, so every git command the turn ran inside
it failed with 'not a git repository' - the failure surfaced deep in the
turn, not at dispatch).

Two call sites needed the same fix, found live only once the first one
shipped: `_ensure_worktree` itself trusted `os.path.exists`, and `steer`'s
self-heal guard trusted `os.path.isdir` before even calling it (real card
proc-20260814-s5, worktree existed as a completely empty directory - isdir
was True, so steer never invoked _ensure_worktree and would have kept
dispatching into the empty folder forever). Both now defer to
_git_state_broken - the same check reclaim already trusts to judge a
worktree's git link.

Self-sandboxing: throwaway git repos + throwaway sqlite/events (no daemon),
mirrors tests/test_worktree_reclaim_active.py."""
import os, sys, subprocess, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.dirname(HERE)
sys.path.insert(0, DAEMON)

SANDBOX = tempfile.mkdtemp()
from daemon.spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from daemon.spine.storage import events
events.EV = os.path.join(SANDBOX, "events.jsonl")
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from daemon.cells.engineer import sessions

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


def test_ensure_worktree_rebuilds_a_never_init_slot():
    repo = new_repo()
    t = {"repo": repo, "branch": "card-branch"}
    wt = sessions._worktree_for(repo, t["branch"])

    # simulate the failure mode: a plain dir sits at the worktree slot, never
    # created via `git worktree add` (interrupted add, stray mkdir, or a
    # hand-severed .git link)
    os.makedirs(wt)
    with open(os.path.join(wt, "stray.txt"), "w") as f:
        f.write("not a real worktree")
    check(sessions._git_state_broken(wt), "test setup: plain dir detected as broken")

    got = sessions._ensure_worktree(t)
    check(got == wt, "returned the expected slot")
    check(not sessions._git_state_broken(wt), "rebuilt slot is a real worktree now")
    r = subprocess.run(["git", "-C", wt, "rev-parse", "--is-inside-work-tree"],
                       capture_output=True, text=True)
    check(r.returncode == 0 and r.stdout.strip() == "true",
          "rebuilt slot passes basic git commands")
    check(not os.path.exists(os.path.join(wt, "stray.txt")),
          "stray content from the broken dir did not survive the rebuild")

    got2 = sessions._ensure_worktree(t)
    check(os.path.normcase(os.path.normpath(got2)) == os.path.normcase(os.path.normpath(wt)),
          "second call reuses the now-valid worktree instead of rebuilding again")


def test_steer_self_heal_guard_catches_existing_but_broken_worktree():
    """The regression this test pins: steer()'s guard used to be
    `not os.path.isdir(worktree)`, which is False for an EXISTING empty
    directory - so a card whose worktree was never `git worktree add`'d, but
    still isdir()==True, never got repaired and steer dispatched into the
    broken folder again. Stubs _turn (no real driver) to isolate the guard."""
    repo = new_repo()
    branch = "card-branch-2"
    git(repo, "checkout", "-b", branch)
    git(repo, "checkout", "main")

    wt = sessions._worktree_for(repo, branch)
    os.makedirs(wt)          # exists, isdir()==True, but never `worktree add`'d

    tid = "t-steer-repair"
    db.track_put({"id": tid, "repo": repo, "worktree": wt, "branch": branch,
                  "task": "t", "lane": "working", "status": "needs_you",
                  "session_id": "sess-0", "run_dir": tempfile.mkdtemp()})

    calls = []
    real_ensure = sessions._ensure_worktree
    def spy_ensure(t):
        calls.append(t.get("worktree"))
        return real_ensure(t)
    sessions._ensure_worktree = spy_ensure

    seen_cwd = {}
    def fake_turn(t, prompt, model=None, perm=None):
        seen_cwd["worktree"] = t.get("worktree")
        return "sess-1", "done", {"usage": {}, "models": []}
    sessions._turn = fake_turn

    from daemon.spine.ops import actionlog
    actionlog.ActionLog = lambda rd: type("L", (), {"log": lambda *a, **k: None})()
    from daemon.spine.comms import notify
    notify.clear_dedup = lambda *a, **k: None
    notify.card_event = lambda *a, **k: None
    from daemon.spine.agent import turnopts
    turnopts.save_attachments = lambda *a, **k: []
    turnopts.resolve_model = lambda *a, **k: ("model", None)
    turnopts.augment_prompt = lambda text, *a, **k: text
    from daemon.spine.agent import drivers
    drivers.turn_active = lambda tid: False

    try:
        sessions.steer(tid, "do the thing")
    finally:
        sessions._ensure_worktree = real_ensure

    check(len(calls) == 1, "steer's self-heal guard called _ensure_worktree "
          "for an existing-but-broken worktree (calls=%d)" % len(calls))
    check(not sessions._git_state_broken(seen_cwd.get("worktree") or ""),
          "the turn was dispatched into a REPAIRED worktree, not the broken one")


if __name__ == "__main__":
    test_ensure_worktree_rebuilds_a_never_init_slot()
    test_steer_self_heal_guard_catches_existing_but_broken_worktree()
    print()
    if _fails:
        print("FAILED: %d check(s)" % len(_fails))
        sys.exit(1)
    print("ALL GREEN - a never-git-init'd worktree slot is detected and rebuilt, "
          "both inside _ensure_worktree and by steer's self-heal guard")
