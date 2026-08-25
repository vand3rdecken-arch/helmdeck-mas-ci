# -*- coding: utf-8 -*-
"""Git + worktree filesystem primitives — extracted from sessions.py (the 3.9k
line orchestrator) as the first real module seam of the modularization. These
are PURE helpers: they operate on repo/worktree PATHS and stdlib only, with no
dependency on the track store or orchestrator state, so they carry no risk of a
circular import. sessions.py re-imports these names, so every existing
`sessions._git(...)` / `sessions.is_git_repo(...)` caller is unchanged.
"""
import os
import re
import shutil
import subprocess

WORKTREE_DIRNAME = "helmdeck-worktrees"

# Identity for commits the HARNESS makes on a model's behalf. Without it git
# inherits the host's user.name/user.email, so agent work lands in the history
# authored by whoever owns the machine - the log then asserts a HUMAN author for
# MACHINE work. That is false attribution, which is worse than none, and it is
# what disqualifies git as an audit trail (ops/docs/gxp-mode-design.md 2.0).
#
# Passed per call as `-c` options (git accepts them after -C, before the
# subcommand) rather than set globally or through the daemon's env: either of
# those would also relabel commits a HUMAN triggers in the same checkout.
# Who ASKED for the commit stays in the message; who MADE it is the author.
AGENT_IDENT = ("-c", "user.name=HelmDeck Agent",
               "-c", "user.email=agent@helmdeck.local")


def _git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), r.stderr.strip()))
    return r.stdout.strip()


def _git_try(repo, *args):
    """Run git, return (returncode, stdout, stderr) without raising."""
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _branch_exists(repo, branch):
    r = subprocess.run(["git", "-C", repo, "rev-parse", "--verify", branch],
                       capture_output=True, text=True)
    return r.returncode == 0


def _import_bundle(repo, bundle_path, branch):
    """Import a git bundle's <branch> ref into `repo` as a local branch - how
    a remote device's finished work re-enters the central checkout (ops/docs/
    backlog/remote-device-execution). Two safety properties, both mandatory
    given the upload comes from a machine outside HelmDeck's own worktree
    isolation:
      - VERIFY before touching the repo (`git bundle verify`) - a corrupt or
        adversarial upload fails loudly here, not mid-fetch.
      - REFUSE to clobber an existing branch of the same name - a device
        must never silently overwrite history already in the central repo.
        The caller passes a fresh, per-card branch name (dispatch.py already
        guarantees uniqueness for every card), so a collision here means
        something is wrong, not that a retry should just overwrite.
    After this call, `branch` exists in `repo` exactly as if a normal
    worktree card had created it there directly - dispatch.py's
    _ensure_worktree (unmodified) can `git worktree add` from it, and
    everything downstream (gate/merge/GxP) treats it identically to a local
    card's branch."""
    code, out, err = _git_try(repo, "bundle", "verify", bundle_path)
    if code != 0:
        raise RuntimeError("bundle failed verification: %s" % (err or out))
    if _branch_exists(repo, branch):
        raise RuntimeError("branch %r already exists in %r - refusing to "
                           "overwrite" % (branch, repo))
    _git(repo, "fetch", bundle_path, "%s:%s" % (branch, branch))


def is_git_repo(path):
    """Intake check: dispatch needs `git worktree add`, so a non-repo path must
    be rejected when the card is filed, not discovered mid-dispatch."""
    if not path or not os.path.isdir(path):
        return False
    r = subprocess.run(["git", "-C", path, "rev-parse", "--git-dir"],
                       capture_output=True, text=True)
    return r.returncode == 0


def _current_branch(repo):
    """Name of the checked-out branch, with Paseo's rebase-HEAD guard
    (checkout-git.ts getRebaseHeadBranch): during a rebase `rev-parse
    --abbrev-ref HEAD` says just 'HEAD' (the rebase detaches), which callers
    would misread as 'no base branch' and bounce dispatch/reclaim mid-rebase.
    Recover the branch actually being rebased from rebase-merge/head-name or
    rebase-apply/head-name. Genuinely detached -> 'HEAD' (callers already
    treat that as blocked)."""
    rc, out, _ = _git_try(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0:
        # UNBORN branch (fresh repo, no commit): rev-parse has no commit to
        # abbreviate, but symbolic-ref still names the branch - _base_ref then
        # reports 'no commits yet' instead of a misleading 'detached'.
        rc2, name, _ = _git_try(repo, "symbolic-ref", "--short", "HEAD")
        return name if rc2 == 0 else ""
    if out != "HEAD":
        return out
    for rel in ("rebase-merge/head-name", "rebase-apply/head-name"):
        rc2, p, _ = _git_try(repo, "rev-parse", "--git-path", rel)
        if rc2 != 0 or not p:
            continue
        fp = p if os.path.isabs(p) else os.path.join(repo, p)
        try:
            with open(fp, encoding="utf-8") as f:
                name = f.read().strip()
        except OSError:
            continue
        if name:
            return name[len("refs/heads/"):] if name.startswith("refs/heads/") else name
    return out


def _checkpoint(worktree):
    """A rewindable anchor for the worktree's CURRENT state - a dangling commit
    that snapshots ALL files (tracked AND untracked, minus .gitignore), built in
    a TEMP index so neither history nor the real index is touched. (git stash
    create skips untracked files, which are exactly the ones an agent creates -
    so it can't be used here.) Rewinding restores files from this commit."""
    import tempfile
    # a git worktree's .git is a FILE, so the temp index must live OUTSIDE the
    # worktree (a normal repo would tolerate .git/, a worktree won't).
    fd, idx = tempfile.mkstemp(suffix=".ckptindex")
    os.close(fd)
    try:
        env = dict(os.environ, GIT_INDEX_FILE=idx)

        def g(*a, check=True):
            r = subprocess.run(["git", "-C", worktree, *a], env=env,
                               capture_output=True, text=True)
            if check and r.returncode != 0:
                raise RuntimeError(r.stderr.strip())
            return r.stdout.strip()

        head = _git(worktree, "rev-parse", "HEAD")
        g("read-tree", head)               # seed temp index from HEAD
        g("add", "-A")                     # stage every worktree file into it
        tree = g("write-tree")
        # commit-tree uses the object db, not the index - real env is fine
        commit = _git(worktree, "commit-tree", tree, "-p", head, "-m", "helmdeck checkpoint")
        return commit or None
    except Exception:
        return None
    finally:
        try:
            os.remove(idx)
        except OSError:
            pass


def _seed_worktree(repo, wt):
    """Copy the un-versioned files a build needs into a fresh worktree.

    A worktree only contains TRACKED files, so anything git-ignored is missing -
    and that is exactly where local toolchain config lives (local.properties
    points at the Android SDK, .env holds local settings). Without them a card
    cannot build what the same repo builds fine by hand.

    Configure in settings.json; defaults deliberately carry NO signing material,
    because handing an agent a release keystore should be a decision, not a
    side effect:

        "worktree_seed": ["apk/local.properties", ".env"]
    """
    from spine.storage import events
    patterns = events.settings().get("worktree_seed")
    if patterns is None:
        patterns = ["apk/local.properties", "local.properties"]
    copied = []
    for rel in patterns:
        src = os.path.join(repo, rel)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(wt, rel)
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            copied.append(rel)
        except OSError:
            pass
    return copied


def _repo_hash(repo):
    """8-char base36 fingerprint of the repo IDENTITY (Paseo
    deriveWorktreeProjectHash): sha256 over the realpath of the repo ROOT,
    resolved via `git rev-parse --git-common-dir` so a worktree of the repo
    hashes the same as the repo itself. First 8 digest bytes -> base36 -> 8
    chars. Falls back to hashing the given path when git is unreachable -
    the hash must be computable even over a broken checkout."""
    import hashlib
    try:
        rc, out, _ = _git_try(repo, "rev-parse", "--git-common-dir")
        if rc != 0 or not out:
            raise RuntimeError(out)
        common = os.path.realpath(out if os.path.isabs(out)
                                  else os.path.join(repo, out))
        root = os.path.dirname(common) if os.path.basename(common) == ".git" else common
    except Exception:
        root = os.path.realpath(repo)
    n = int.from_bytes(hashlib.sha256(root.encode("utf-8")).digest()[:8], "big")
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    s = ""
    while n:
        n, r = divmod(n, 36)
        s = digits[r] + s
    return s.zfill(13)[:8]


def _owned_worktree(path):
    """Ownership by PATH SHAPE alone (Paseo isPaseoOwnedWorktreeCwd): may this
    directory be rm'd even when git has forgotten it? Owned iff it sits at
    <...>/helmdeck-worktrees/<8-char-base36-hash>/<name> - that prefix is
    HelmDeck-private, nothing else writes there, so the shape is sufficient
    proof even with git broken. Pre-hash FLAT trees (<...>/helmdeck-worktrees/
    <name>) are NOT owned: only git may manage those (they could be anything)."""
    p = os.path.realpath(path)
    parent = os.path.dirname(p)                    # the <hash> dir
    grand = os.path.dirname(parent)                # the helmdeck-worktrees dir
    return bool(os.path.basename(p)) \
        and os.path.basename(grand) == WORKTREE_DIRNAME \
        and re.fullmatch(r"[0-9a-z]{8}", os.path.basename(parent)) is not None


def _git_state_broken(wt):
    """True when a worktree's link to its repo is severed (the class 4.1
    reclaims): .git missing, unreadable, or pointing at an admin dir that no
    longer exists (half-removed tree, pruned admin dir, moved repo). A .git
    DIRECTORY means a full repo - never 'broken', never ours to judge."""
    gitfile = os.path.join(wt, ".git")
    if os.path.isdir(gitfile):
        return False
    if not os.path.exists(gitfile):
        return True
    try:
        with open(gitfile, encoding="utf-8", errors="replace") as f:
            m = re.search(r"gitdir:\s*(.+)", f.read())
    except OSError:
        return True
    if not m:
        return True
    gd = m.group(1).strip()
    if not os.path.isabs(gd):
        gd = os.path.join(wt, gd)
    return not os.path.isdir(gd)


def _worktree_for(repo, branch):
    from spine.storage.trackstore import _slug
    base = os.path.abspath(os.path.join(repo, "..", WORKTREE_DIRNAME))
    wt = os.path.join(base, _repo_hash(repo), _slug(branch))
    os.makedirs(os.path.dirname(wt), exist_ok=True)
    return wt


def _base_ref(repo):
    """The commit a NEW card branch starts from (Paseo
    resolveBaseBranchForWorktree + normalizeRequiredBaseBranch). Explicit
    instead of implicit: `worktree add -b` with no start point bases the card
    on whatever HEAD happens to be - mid-rebase or detached, that is the wrong
    code. So: name the base branch (rebase-guarded _current_branch), REJECT
    detached/unborn, and prefer origin/<base> only when it is ahead-or-equal
    of the local base. (Paseo always prefers origin because the remote is its
    source of truth; HelmDeck merges cards into the LOCAL checkout, so a stale
    origin must never win over local commits.) The caller passes --no-track so
    the card branch never claims that base as upstream."""
    base = _current_branch(repo)
    if not base or base == "HEAD":
        raise RuntimeError("cannot create the card branch: the repo checkout is "
                           "detached (no base branch) - checkout the base branch first")
    if _git_try(repo, "rev-parse", "--verify", "-q", base)[0] != 0:
        raise RuntimeError("cannot create the card branch: base branch '%s' has "
                           "no commits yet - make an initial commit first" % base)
    origin = "origin/" + base
    if (_git_try(repo, "rev-parse", "--verify", "-q", origin)[0] == 0
            and _git_try(repo, "merge-base", "--is-ancestor", base, origin)[0] == 0):
        return origin
    return base


def _worktree_of_branch(repo, branch):
    """Path of an EXISTING worktree that already has `branch` checked out, or
    None. git refuses to check the same branch out twice, so if a stale worktree
    holds it (e.g. a swarmdeck->helmdeck rename left ../swarmdeck-worktrees),
    dispatch must REUSE that path instead of failing on `git worktree add`."""
    r = subprocess.run(["git", "-C", repo, "worktree", "list", "--porcelain"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    path = None
    for line in r.stdout.splitlines():
        if line.startswith("worktree "):
            path = line[9:].strip()
        elif line.startswith("branch ") and path and line[7:].strip() == "refs/heads/" + branch:
            return path
    return None
