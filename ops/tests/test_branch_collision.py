# -*- coding: utf-8 -*-
"""A card's branch (and therefore its WORKTREE) must be unique per CARD, never
per opening sentence.

Real incident, 2026-08-30 - a full card's work lost. Branch names were derived
from the first ~24 characters of the task text alone, and _worktree_for maps
branch -> directory. Two cards both opening with "NUR PRD SCHREIBEN, KEIN
CODE..." therefore addressed ONE directory. Card 20260830-065545 was accepted;
reclaim_worktree gave "its" tree back - which was the tree card 20260830-194212
was live inside. The worker found an empty directory with no .git.

Two locks are pinned here:
  1. naming   - trackstore._card_branch appends the card id and PROVES the
                result free (and _slug_tail keeps that tail alive through the
                branch -> directory slug, which used to cut it off at 32 chars).
  2. reclaim  - reclaim_worktree refuses to delete a tree another still-open
                card lives in, whatever the branch says. Cards filed before
                lock 1 are still on the board and still share trees.

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
from spine.ops import runs
runs.REC = os.path.join(SANDBOX, "runs")
os.makedirs(runs.REC, exist_ok=True)

from cells.engineer.cards import sessions, dispatch
from spine.storage.trackstore import _slug, _slug_tail, _card_branch
from spine.git.gitutil import _worktree_for

# the two real requests from the incident: same opening, different work
PRD_A = ("NUR PRD SCHREIBEN, KEIN CODE. Schreibe ein PRD fuer die "
         "Ship-Entscheidung als Agent statt als Hash-Vergleich.")
PRD_B = ("NUR PRD SCHREIBEN, KEIN CODE. Schreibe ein PRD fuer den "
         "Settings-Umbau zum Sechs-Tueren-Hub.")

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
    """A repo nested one level deep: _worktree_for puts trees in a SIBLING
    'helmdeck-worktrees' dir, so the repo must not sit at a filesystem root."""
    d = os.path.join(tempfile.mkdtemp(), "repo")
    os.makedirs(d)
    git(d, "init")
    git(d, "symbolic-ref", "HEAD", "refs/heads/main")
    git(d, "config", "user.email", "t@t.t")
    git(d, "config", "user.name", "t")
    with open(os.path.join(d, "base.txt"), "w") as f:
        f.write("base\n")
    git(d, "add", "-A"); git(d, "commit", "-m", "init")
    return d


class Log:
    def log(self, *a, **k):
        pass


# -- lock 1: naming ----------------------------------------------------------

def test_same_opening_sentence_gets_its_own_branch_and_tree():
    repo = new_repo()
    a = sessions.new_track(repo, "chat-" + PRD_A, PRD_A, lane="backlog")
    b = sessions.new_track(repo, "chat-" + PRD_B, PRD_B, lane="backlog")

    check(a["branch"] != b["branch"],
          "two cards with the same opening sentence get different branches "
          "(%s vs %s)" % (a["branch"], b["branch"]))
    check(a["id"][:15] in a["branch"] and b["id"][:15] in b["branch"],
          "each branch carries its own card id token")
    check(a["branch"].startswith("chat-nur-prd-schreiben"),
          "the human stem still leads the branch (%s)" % a["branch"])
    check(a["branch"].isascii() and b["branch"].isascii(),
          "branch stays ASCII (an umlaut in a git ref broke every steer)")

    wt_a, wt_b = _worktree_for(repo, a["branch"]), _worktree_for(repo, b["branch"])
    check(os.path.normcase(wt_a) != os.path.normcase(wt_b),
          "and therefore two DIFFERENT worktree directories:\n"
          "        %s\n        %s" % (wt_a, wt_b))

    # the real dispatch path, not just the formula: both trees must exist at once
    real_a = dispatch._ensure_worktree(sessions._find(sessions._load(), a["id"]))
    real_b = dispatch._ensure_worktree(sessions._find(sessions._load(), b["id"]))
    check(os.path.normcase(real_a) != os.path.normcase(real_b),
          "_ensure_worktree hands out two distinct live trees")
    check(os.path.isdir(real_a) and os.path.isdir(real_b),
          "both trees exist on disk simultaneously")
    check(os.path.exists(os.path.join(real_a, ".git"))
          and os.path.exists(os.path.join(real_b, ".git")),
          "both are real worktrees (.git link present)")


def test_a_third_card_in_the_same_second_still_differs():
    """Same sentence AND same second - the id's own collision counter, and the
    freeness loop behind it, must still separate them."""
    repo = new_repo()
    names = [sessions.new_track(repo, "chat-" + PRD_A, PRD_A, lane="backlog")["branch"]
             for _ in range(3)]
    check(len(set(names)) == 3, "three identical requests, three branches (%s)" % names)
    dirs = {os.path.normcase(_worktree_for(repo, n)) for n in names}
    check(len(dirs) == 3, "three identical requests, three worktree directories")


def test_slug_tail_keeps_the_unique_tail():
    """The directory half of the bug. _slug cuts head-first at 32 chars, which
    sheared the card-id token straight back off - two distinct branches, one
    directory. _slug_tail must keep the end."""
    a = "chat-nur-prd-schreiben-kein-code-20260830-065545"
    b = "chat-nur-prd-schreiben-kein-code-20260830-194212"
    check(_slug(a) == _slug(b),
          "precondition: plain _slug still collapses these two (%s)" % _slug(a))
    check(_slug_tail(a) != _slug_tail(b),
          "_slug_tail keeps them apart (%s vs %s)" % (_slug_tail(a), _slug_tail(b)))
    check(_slug_tail(a).endswith("20260830-065545"), "the card-id tail survives")
    check(_slug_tail("short-branch") == "short-branch", "short names are untouched")
    check(_slug_tail("") == "track", "empty stays addressable")


def test_card_branch_dodges_a_branch_the_store_forgot():
    """reclaim keeps UNMERGED branches after removing their tree, so a branch
    can outlive its card. Freeness is verified against git too, not just the
    track store."""
    repo = new_repo()
    t = sessions.new_track(repo, "chat-" + PRD_A, PRD_A, lane="backlog")
    git(repo, "branch", t["branch"])                  # the card's branch, now real
    git(repo, "branch", t["branch"] + "-2")           # squat on the next candidate too
    db.track_delete(t["id"])                          # ...and the store forgets the card
    again = _card_branch(repo, "chat-" + PRD_A, t["id"])
    check(again not in (t["branch"], t["branch"] + "-2"),
          "steps over the surviving branch AND the squatted next candidate (%s)" % again)
    check(subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "-q", again],
                         capture_output=True).returncode != 0,
          "the chosen branch really is free in git")


# -- lock 2: reclaim ---------------------------------------------------------

def test_reclaim_keeps_a_tree_another_open_card_lives_in():
    """The incident itself, replayed on cards that ALREADY share a tree (filed
    before the naming fix). Accepting the finished one must not evict the live
    one."""
    repo = new_repo()
    a = sessions.new_track(repo, "chat-" + PRD_A, PRD_A, lane="backlog")
    shared = dispatch._ensure_worktree(sessions._find(sessions._load(), a["id"]))
    sessions._mutate(a["id"], lambda tt: tt.__setitem__("worktree", shared))

    # card B: same tree, still working - the pre-fix collision, forced by hand
    b = dict(sessions._find(sessions._load(), a["id"]))
    b.update({"id": a["id"] + "-victim", "worktree": shared, "lane": "working",
              "status": "needs_you", "task": PRD_B})
    db.track_put(b)

    with open(os.path.join(shared, "work_in_progress.txt"), "w") as f:
        f.write("the live card's work\n")

    # card A is accepted: clean, merged, terminal - every old reclaim gate open
    git(shared, "add", "-A"); git(shared, "commit", "-m", "a's work")
    git(repo, "merge", "--no-ff", a["branch"], "-m", "accept a")
    sessions._mutate(a["id"], lambda tt: tt.update({"lane": "done"}))

    ok = sessions.reclaim_worktree(sessions._find(sessions._load(), a["id"]), Log())
    check(ok is False, "reclaim refuses while another open card lives there")
    check(os.path.isdir(shared), "the shared worktree still exists")
    check(os.path.exists(os.path.join(shared, ".git")), ".git link is intact")
    check(os.path.isfile(os.path.join(shared, "work_in_progress.txt")),
          "the live card's file survives (this is what was lost on 2026-08-30)")

    # and it is not a permanent leak: once the cohabitant is terminal too, the
    # tree comes back exactly as before.
    db.track_put(dict(b, lane="done"))
    ok2 = sessions.reclaim_worktree(sessions._find(sessions._load(), a["id"]), Log())
    check(ok2 is True, "reclaimed once nobody is working there any more")
    check(not os.path.isdir(shared), "the worktree directory is gone")


if __name__ == "__main__":
    test_same_opening_sentence_gets_its_own_branch_and_tree()
    test_a_third_card_in_the_same_second_still_differs()
    test_slug_tail_keeps_the_unique_tail()
    test_card_branch_dodges_a_branch_the_store_forgot()
    test_reclaim_keeps_a_tree_another_open_card_lives_in()
    print()
    if _fails:
        print("FAILED: %d check(s)" % len(_fails))
        sys.exit(1)
    print("ALL GREEN - one card, one branch, one worktree")
