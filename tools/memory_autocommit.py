# -*- coding: utf-8 -*-
"""Stop hook: keep EVERY Claude Code project's auto-memory directory in local git.

WHY
---
Claude Code's auto-memory lives in ~/.claude/projects/<slug>/memory/ and is read
into context at the start of every session. That makes it load-bearing state -
but it ships with no version control of its own. Measured 2026-08-16:
`git -C ~/.claude status` says "not a git repository (or any of the parent
directories)", and there is no .git anywhere in that tree. So an edit to a
memory note was unrecoverable: nothing recorded what it said before, who
changed it, or in which session. Every other piece of load-bearing state in
this workflow is diffable; this one was not.

This hook closes that for every project at once, including projects that do not
exist yet - which is the point. A per-project fix would have to be remembered
each time a new project is opened, and the thing being protected is precisely
the memory that would have had to remember it.

THE ONE LAW OF THIS FILE: **it can never break a turn.**
Same law as daemon/harness.py. It runs after EVERY turn of every interactive
session, so a bug here would not be a bad commit, it would be a wedged agent.
Therefore: every git call is bounded by a timeout, every failure is swallowed
into a log line, and main() exits 0 unconditionally - a Stop hook that exits 2
BLOCKS the turn, so that exit code must be unreachable from here. When anything
goes wrong the worst outcome is "this turn was not snapshotted", and the next
turn picks it up.

DELIBERATELY NOT DONE
---------------------
- **No remote, ever, and no push.** These are private notes. This file never
  runs `git remote add` or `git push`, and nothing here would work if it did.
- **No management of a directory somebody else's repo already tracks.** If
  ~/.claude turns out to be inside a git repo, that repo owns those files and
  this hook leaves them alone rather than nesting a second one inside it.
- **No history rewriting.** Append-only, like the audit trail: commits only.

WHERE IT RUNS
-------------
~/.claude/settings.json is the operator's PERSONAL layer, so HelmDeck's own card
and copilot spawns never load it (`--setting-sources project` / `""`). This hook
therefore fires only in interactive sessions - which is exactly right: a card
cannot write to a memory directory at all (harness/settings/card.json denies
Write/Edit there, verified against the real CLI), so there is nothing for it to
commit. Interactive sessions are the only writers, and were the gap the
permission deny never covered.

Canonical copy lives in the HelmDeck repo (tools/) and is deployed to
~/.claude/hooks/ by tools/install_memory_hook.py, which also detects drift
between the two. Fixing untracked state with an untracked script would have been
a joke at its own expense.

Run manually:
    py -3.12 tools/memory_autocommit.py --verbose      # snapshot now
    py -3.12 tools/memory_autocommit.py --dry-run -v   # say what it would do
"""
import json
import os
import subprocess
import sys

HOME = os.path.expanduser("~")
PROJECTS = os.path.join(HOME, ".claude", "projects")
GIT_TIMEOUT = 15          # per git call; a hung git must not hold up the turn
MAX_LIST = 12             # files named in a commit message before it says "and N more"

_log = []


def log(msg):
    _log.append(msg)


def git(repo, *args, **kw):
    """Run one git command. Returns (rc, stdout, stderr) and NEVER raises."""
    timeout = kw.get("timeout", GIT_TIMEOUT)
    try:
        r = subprocess.run(["git", "-C", repo] + list(args),
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except FileNotFoundError:
        return 127, "", "git not found on PATH"
    except subprocess.TimeoutExpired:
        return 124, "", "git timed out after %ss" % timeout
    except Exception as e:                                   # noqa: BLE001
        return 1, "", "%s: %s" % (type(e).__name__, str(e)[:120])


def memory_dirs(root=None):
    """Every ~/.claude/projects/<slug>/memory/ that exists, sorted.

    `root` is a parameter rather than the module constant so the test can point
    this at a temp tree - a test that had to touch the real ~/.claude to run
    would be a test nobody dares run."""
    base = root or PROJECTS
    out = []
    try:
        for entry in sorted(os.listdir(base)):
            d = os.path.join(base, entry, "memory")
            if os.path.isdir(d):
                out.append(d)
    except OSError:
        pass
    return out


def _same_path(a, b):
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except OSError:
        return False


def repo_state(d):
    """'ours' | 'foreign' | 'none' - who, if anyone, already versions `d`.

    'foreign' means d sits INSIDE some other repo's working tree (the operator
    git-inited ~/.claude himself, say). Those files already have history and an
    owner; nesting a second repo inside would split it in two and make the outer
    one report a mystery untracked directory. Not ours to manage."""
    rc, top, _ = git(d, "rev-parse", "--show-toplevel")
    if rc != 0 or not top:
        return "none"
    return "ours" if _same_path(top, d) else "foreign"


def _busy(d):
    """A merge/rebase/bisect in progress - never commit on top of that."""
    for marker in ("MERGE_HEAD", "REBASE_HEAD", "CHERRY_PICK_HEAD", "BISECT_LOG",
                   "rebase-merge", "rebase-apply"):
        if os.path.exists(os.path.join(d, ".git", marker)):
            return True
    return False


def ensure_identity(d):
    """A commit needs an author. Inherit the global identity when there is one
    (so these commits look like the owner's, because they are his notes), and
    fall back to a local attributed identity when git was never configured -
    rather than letting `git commit` fail with a message nobody will read."""
    rc, name, _ = git(d, "config", "user.name")
    rc2, mail, _ = git(d, "config", "user.email")
    if rc == 0 and name and rc2 == 0 and mail:
        return True
    git(d, "config", "user.name", "Claude Code")
    git(d, "config", "user.email", "noreply@anthropic.com")
    return True


def init_repo(d, dry=False):
    """git init + a baseline commit. Only for a directory that HAS notes - an
    empty memory dir gets no repo, so we do not litter every project with one."""
    try:
        has_files = any(not f.startswith(".") for f in os.listdir(d))
    except OSError:
        return False
    if not has_files:
        return False
    if dry:
        log("would git init: %s" % d)
        return False
    rc, _, err = git(d, "init")
    if rc != 0:
        log("git init failed (%s): %s" % (d, err[:120]))
        return False
    ensure_identity(d)
    return True


def commit(d, session_id="", dry=False):
    """Commit whatever changed. Returns a short description, or None."""
    if _busy(d):
        log("skipped (merge/rebase in progress): %s" % d)
        return None
    rc, porcelain, err = git(d, "status", "--porcelain")
    if rc != 0:
        log("git status failed (%s): %s" % (d, err[:120]))
        return None
    if not porcelain:
        return None
    if dry:
        n = len(porcelain.splitlines())
        log("would commit %d change(s) in %s" % (n, d))
        return None

    ensure_identity(d)
    rc, _, err = git(d, "add", "-A")
    if rc != 0:
        # index.lock contention: another session's hook is mid-commit. Harmless -
        # whichever wins commits the changes, the loser picks up the rest next turn.
        log("git add failed (%s): %s" % (d, err[:120]))
        return None
    rc, staged, _ = git(d, "diff", "--cached", "--name-status")
    if rc != 0 or not staged:
        return None

    lines = staged.splitlines()
    names = [ln.split("\t", 1)[-1] for ln in lines]
    head = ", ".join(names[:MAX_LIST])
    if len(names) > MAX_LIST:
        head += " and %d more" % (len(names) - MAX_LIST)
    body = ["memory: %d file(s) changed" % len(lines), "", staged]
    if session_id:
        # WHICH session wrote this is the provenance that makes a revert
        # decidable later - "was this me, or an agent turn I did not read?"
        body += ["", "session: %s" % session_id]
    rc, _, err = git(d, "commit", "-m", "\n".join(body))
    if rc != 0:
        log("git commit failed (%s): %s" % (d, err[:160]))
        return None
    return "%s: %d file(s) [%s]" % (os.path.basename(os.path.dirname(d)), len(lines), head)


def sweep(root=None, session_id="", dry=False):
    """Bring every memory directory up to date. Returns a list of descriptions."""
    done = []
    for d in memory_dirs(root):
        state = repo_state(d)
        if state == "foreign":
            log("skipped (already inside another git repo): %s" % d)
            continue
        if state == "none":
            if not init_repo(d, dry=dry):
                continue
            log("initialised local git repo: %s" % d)
        got = commit(d, session_id=session_id, dry=dry)
        if got:
            done.append(got)
    return done


def main():
    argv = sys.argv[1:]
    dry = "--dry-run" in argv or "-n" in argv
    verbose = "--verbose" in argv or "-v" in argv

    # The Stop hook payload arrives as JSON on stdin. It is optional context, not
    # a dependency: reading it must not be able to hang the turn, so a missing or
    # unreadable stdin just means the commit carries no session id.
    session_id = ""
    if not sys.stdin.isatty():
        try:
            raw = sys.stdin.read()
            if raw.strip():
                session_id = (json.loads(raw) or {}).get("session_id") or ""
        except Exception:                                    # noqa: BLE001
            pass

    try:
        done = sweep(session_id=session_id, dry=dry)
    except Exception as e:                                   # noqa: BLE001
        # Belt and braces. sweep() is already total, but this file's whole job is
        # to be unable to wedge a turn, and "unable" should not rest on my having
        # thought of everything below it.
        log("sweep aborted: %s: %s" % (type(e).__name__, str(e)[:160]))
        done = []

    if verbose or dry:
        for line in _log:
            print("[memory] %s" % line)
        for d in done:
            print("[memory] committed %s" % d)
        if not done and not _log:
            print("[memory] nothing to do")
    elif _log:
        # Non-verbose: stay silent on success (this runs after every single turn
        # and must not become noise), but surface real problems on stderr, where
        # a Stop hook's output is shown without being treated as a block.
        sys.stderr.write("\n".join("[memory] %s" % x for x in _log) + "\n")

    # ALWAYS 0. Exit code 2 from a Stop hook BLOCKS the turn.
    return 0


if __name__ == "__main__":
    sys.exit(main())
