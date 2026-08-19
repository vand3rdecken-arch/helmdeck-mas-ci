# -*- coding: utf-8 -*-
"""Worktree reclamation — the second half of the isolation law, extracted from
sessions.py. reclaim_worktree gives ONE finished card's tree+branch back on a
terminal transition; sweep_worktrees is the startup backstop that reclaims every
merged, clean, UNREFERENCED tree. Nothing-lost: a tree with uncommitted tracked
files, or one a non-terminal card still references, is always kept. Depends only
on gitutil (pure) + sessions._load (lazy, no cycle). Not monkeypatched;
sessions.py re-imports both names.
"""
import os
import shutil

from gitutil import (_git_try, _owned_worktree, _current_branch,
                     _git_state_broken, _repo_hash, WORKTREE_DIRNAME)


def reclaim_worktree(t, log=None, force=False):
    """Give ONE finished card's worktree (and branch) back. Called on a terminal
    transition (accepted/archived): the work is already in the integration
    branch, so the tree and branch are safe to drop. Never touches the primary
    checkout, and KEEPS any tree that still has modified TRACKED files unless
    force (nothing uncommitted is ever lost - untracked build noise doesn't
    count). Best-effort: a git hiccup never breaks the accept/archive."""
    repo, wt, br = t.get("repo"), t.get("worktree"), t.get("branch")
    if not repo or not wt or not os.path.isdir(wt):
        return False
    if os.path.abspath(wt) == os.path.abspath(repo):
        return False                       # never the main checkout
    if not force:
        rc, out, _ = _git_try(wt, "status", "--porcelain", "--untracked-files=no")
        if rc == 0 and out:
            if log:
                log.log("note", "WORKTREE behalten - uncommittete Aenderungen in %s" % wt)
            return False
    _git_try(repo, "worktree", "remove", "--force", wt)
    if os.path.isdir(wt) and _owned_worktree(wt):
        # git refused (admin dir already gone, repo moved, broken .git file).
        # Ownership is proven by the PATH SHAPE, so the reclaim survives broken
        # git state (Paseo deletePaseoWorktree: rm falls through when `worktree
        # remove` fails). The dirty check above already ran its veto.
        shutil.rmtree(wt, ignore_errors=True)
    if os.path.isdir(wt):                   # remove refused (locked?) - leave it be
        if log:
            log.log("note", "WORKTREE nicht entfernbar (gesperrt?): %s" % wt)
        return False
    integ = _current_branch(repo)
    if br and br not in ("main", "master") and integ != br:
        # Delete the branch ONLY if it is merged into the integration branch -
        # an archived-but-unmerged card keeps its branch so its commits survive
        # (the worktree is regenerable from the branch; unmerged commits are not).
        if integ and _git_try(repo, "merge-base", "--is-ancestor", br, integ)[0] == 0:
            _git_try(repo, "branch", "-D", br)
        elif log:
            log.log("note", "BRANCH behalten - nicht gemergt: %s (Worktree entfernt, Commits bleiben)" % br)
    _git_try(repo, "worktree", "prune")
    if log:
        log.log("note", "WORKTREE zurueckgeholt: %s (branch %s) - Arbeit ist gelandet." % (wt, br))
    return True


def sweep_worktrees():
    """Startup backstop + one-shot cleanup: reclaim EVERY merged, clean card
    worktree across the repos we know. Complements the per-card reclaim by
    catching trees left by builds from before reclamation existed.

    NOT independent of card status (despite what this docstring used to
    claim - found live 2026-08-14, a real data-loss bug): a branch can be
    merged (an earlier commit landed, e.g. via fast-track) while its CARD is
    still open on the board and actively being steered - this git-only check
    tore an in-progress COWORK card's live worktree out from under it
    (deregistered .git, deleted most files, orphaned a live eas-cli/Chrome
    process's locked files as an empty app/ husk) while the owner was mid-
    conversation with it. reclaim_worktree (the per-card path, called only on
    accept/archive) was always correctly scoped; this backstop was not.
    A worktree currently referenced by a NON-terminal card (not archived, not
    in the done lane) is now kept regardless of git's merge verdict - "is
    anyone still using this" is the daemon's own fact, and it must win over
    what git alone can see. Returns the number reclaimed."""
    import sessions
    tracks = sessions._load()
    repos = {t.get("repo") for t in tracks if t.get("repo")}
    referenced = {os.path.realpath(t["worktree"]) for t in tracks if t.get("worktree")}
    # path -> is this card still ACTIVE (open, non-terminal)? Only paths NOT
    # in this set (or mapped to False) are eligible for reclaim below.
    active_by_path = {}
    for t in tracks:
        if not t.get("worktree"):
            continue
        p = os.path.realpath(t["worktree"])
        terminal = bool(t.get("archived")) or t.get("lane") == "done"
        active_by_path[p] = active_by_path.get(p, False) or not terminal
    n = 0
    for repo in repos:
        if not repo or not os.path.isdir(repo):
            continue
        integ = _current_branch(repo)
        rc, out, _ = _git_try(repo, "worktree", "list", "--porcelain")
        if rc != 0:
            continue
        wt, pairs = None, []
        for line in out.splitlines():
            if line.startswith("worktree "):
                wt = line[len("worktree "):].strip()
            elif line.startswith("branch "):
                pairs.append((line[len("branch "):].strip().replace("refs/heads/", ""), wt))
        for br, path in pairs:
            if (not path or not br or br in ("main", "master", integ)
                    or os.path.abspath(path) == os.path.abspath(repo)):
                continue
            if active_by_path.get(os.path.realpath(path)):
                continue                    # a non-terminal card still owns this tree - keep
            if _git_try(repo, "merge-base", "--is-ancestor", br, integ)[0] != 0:
                continue                    # not merged - keep
            rc3, dirty, _ = _git_try(path, "status", "--porcelain", "--untracked-files=no")
            if rc3 == 0 and dirty:
                continue                    # dirty tracked - keep
            _git_try(repo, "worktree", "remove", "--force", path)
            if not os.path.isdir(path):
                _git_try(repo, "branch", "-D", br)
                n += 1
        # ORPHANS the git-driven pass can never see: trees whose link to the
        # repo is severed (admin dir pruned, half-removed, repo moved), so
        # `worktree list` no longer reports them and `worktree remove` fails.
        # Ownership by path shape + a provably broken .git is the reclaim
        # ticket; a tree ANY card still references is kept (nothing-lost).
        known = {os.path.realpath(p) for _, p in pairs if p}
        hashdir = os.path.join(os.path.abspath(os.path.join(repo, "..", WORKTREE_DIRNAME)),
                               _repo_hash(repo))
        if os.path.isdir(hashdir):
            for name in os.listdir(hashdir):
                path = os.path.join(hashdir, name)
                if (not os.path.isdir(path)
                        or os.path.realpath(path) in known
                        or os.path.realpath(path) in referenced
                        or not _owned_worktree(path)
                        or not _git_state_broken(path)):
                    continue
                shutil.rmtree(path, ignore_errors=True)
                if not os.path.isdir(path):
                    n += 1
        _git_try(repo, "worktree", "prune")
    return n
