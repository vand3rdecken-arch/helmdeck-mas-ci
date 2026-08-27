# -*- coding: utf-8 -*-
"""The memory auto-commit Stop hook: does it version notes without ever wedging a turn?

ops/tools/memory_autocommit.py runs after EVERY turn of every interactive session, so
its failure mode is not "a missing commit", it is "a stuck agent". That asymmetry
drives what is checked here:

1. IT WORKS. A memory dir with notes gets a repo and a baseline commit; later
   edits get their own commits; a clean dir produces no empty commit.
2. IT KNOWS WHAT IS NOT ITS BUSINESS. A directory already inside somebody else's
   git repo is left completely alone - no nested repo, no commits.
3. IT CANNOT WEDGE A TURN. Fed a missing root, an unreadable dir, a repo mid-
   merge, and a git that does not exist, main() must still exit 0 - because a
   Stop hook exiting 2 BLOCKS the turn.
4. IT NEVER PUSHES. No remote is ever configured; the file contains no push.

Self-sandboxing: temp dirs and a real `git` binary. The real ~/.claude is never
read or written - memory_dirs() takes its root as a parameter precisely so this
test cannot touch it.

Run: py -3.12 ops/tests/test_memory_autocommit.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "ops", "tools"))

import memory_autocommit as mac

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def have_git():
    try:
        return subprocess.run(["git", "--version"], capture_output=True,
                              timeout=15).returncode == 0
    except Exception:                                        # noqa: BLE001
        return False


def make_root():
    """A fake ~/.claude/projects tree."""
    tmp = tempfile.mkdtemp(prefix="hd-mem-test-")
    return tmp


def project(root, slug, files=None):
    d = os.path.join(root, slug, "memory")
    os.makedirs(d, exist_ok=True)
    for name, body in (files or {}).items():
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            f.write(body)
    return d


def log_of(d):
    rc, out, _ = mac.git(d, "log", "--oneline")
    return out.splitlines() if rc == 0 else []


def test_bootstraps_and_commits():
    print("1. a memory dir with notes gets a repo and a baseline commit")
    root = make_root()
    try:
        d = project(root, "proj-a", {"MEMORY.md": "# index\n", "a.md": "note a\n"})
        mac._log[:] = []
        done = mac.sweep(root=root, session_id="sess-123")
        check(os.path.isdir(os.path.join(d, ".git")), "a git repo was created")
        check(len(done) == 1, "one project reported as committed: %s" % done)
        check(len(log_of(d)) == 1, "exactly one commit exists")
        rc, msg, _ = mac.git(d, "log", "-1", "--pretty=%B")
        check("memory: 2 file(s) changed" in msg, "the message counts the files")
        check("sess-123" in msg,
              "the session id is recorded - provenance is what makes a later "
              "revert decidable")

        # idempotent: a second sweep with nothing changed must not commit
        done2 = mac.sweep(root=root, session_id="sess-123")
        check(done2 == [], "a clean tree produces NO second commit")
        check(len(log_of(d)) == 1, "still exactly one commit")

        # an edit lands as its own commit
        with open(os.path.join(d, "a.md"), "a", encoding="utf-8") as f:
            f.write("edited\n")
        done3 = mac.sweep(root=root, session_id="sess-456")
        check(len(done3) == 1 and len(log_of(d)) == 2, "an edit gets its own commit")

        # and the PRIOR content is recoverable - the entire point
        rc, old, _ = mac.git(d, "show", "HEAD~1:a.md")
        check(rc == 0 and old.strip() == "note a",
              "the previous version is recoverable from history")

        # a deletion is captured too (the worst case: a note silently vanishing)
        os.remove(os.path.join(d, "a.md"))
        mac.sweep(root=root)
        rc, old, _ = mac.git(d, "show", "HEAD~1:a.md")
        check(rc == 0, "a DELETED note is still recoverable from history")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_multiple_projects_and_empty_dirs():
    print("2. every project is covered; empty dirs are not littered with repos")
    root = make_root()
    try:
        a = project(root, "proj-a", {"a.md": "a\n"})
        b = project(root, "proj-b", {"b.md": "b\n"})
        empty = project(root, "proj-empty", {})
        mac.sweep(root=root)
        check(os.path.isdir(os.path.join(a, ".git")), "project a got a repo")
        check(os.path.isdir(os.path.join(b, ".git")), "project b got a repo")
        check(not os.path.isdir(os.path.join(empty, ".git")),
              "an EMPTY memory dir gets no repo - a new project is not littered "
              "with an empty one before it has a single note")
        check(len(mac.memory_dirs(root)) == 3, "all three dirs are discovered")

        # a project created LATER is picked up with no extra action - the whole
        # reason this is a generic sweep and not a per-project setup step
        c = project(root, "proj-created-later", {"c.md": "c\n"})
        mac.sweep(root=root)
        check(os.path.isdir(os.path.join(c, ".git")),
              "a project that did not exist at install time is covered anyway")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_leaves_foreign_repos_alone():
    print("3. a dir already inside ANOTHER repo is not touched")
    root = make_root()
    try:
        # git init the PARENT, so memory/ is already tracked by somebody else
        outer = os.path.join(root, "proj-outer")
        os.makedirs(outer, exist_ok=True)
        subprocess.run(["git", "init"], cwd=outer, capture_output=True, timeout=30)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=outer,
                       capture_output=True, timeout=15)
        subprocess.run(["git", "config", "user.name", "t"], cwd=outer,
                       capture_output=True, timeout=15)
        d = project(root, "proj-outer", {"a.md": "a\n"})

        check(mac.repo_state(d) == "foreign", "the dir is recognised as foreign")
        mac._log[:] = []
        done = mac.sweep(root=root)
        check(not os.path.isdir(os.path.join(d, ".git")),
              "NO nested repo is created inside the other repo's working tree")
        check(done == [], "and nothing is committed on its behalf")
        check(any("another git repo" in x for x in mac._log),
              "the skip is logged, not silent")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_never_pushes():
    print("4. no remote is ever configured, and the source contains no push")
    root = make_root()
    try:
        d = project(root, "proj-a", {"a.md": "a\n"})
        mac.sweep(root=root)
        rc, remotes, _ = mac.git(d, "remote")
        check(rc == 0 and not remotes.strip(),
              "the created repo has NO remote - these are private notes")
        src = open(os.path.join(ROOT, "ops", "tools", "memory_autocommit.py"),
                   encoding="utf-8").read()
        code = "\n".join(l for l in src.splitlines()
                         if not l.strip().startswith("#"))
        code = code.split('"""', 2)[-1]          # drop the module docstring
        check('"push"' not in code and "'push'" not in code,
              "the file never invokes git push")
        check('"remote"' not in code.replace('git(d, "remote")', ""),
              "and never adds a remote")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_cannot_wedge_a_turn():
    print("5. THE LAW: every failure path still exits 0")
    # A Stop hook that exits 2 BLOCKS the turn. Nothing below may reach that.
    root = make_root()
    try:
        # (a) a root that does not exist
        check(mac.memory_dirs(os.path.join(root, "nope")) == [],
              "a missing projects root -> no dirs, no exception")
        check(mac.sweep(root=os.path.join(root, "nope")) == [],
              "and sweep() over it is a clean no-op")

        # (b) a FILE where a memory dir should be
        weird = os.path.join(root, "proj-weird")
        os.makedirs(weird, exist_ok=True)
        with open(os.path.join(weird, "memory"), "w", encoding="utf-8") as f:
            f.write("not a directory")
        check(mac.sweep(root=root) == [], "a FILE named 'memory' is skipped, not fatal")

        # (c) a repo stuck mid-merge must not be committed on top of
        d = project(root, "proj-busy", {"a.md": "a\n"})
        mac.sweep(root=root)
        with open(os.path.join(d, "a.md"), "a", encoding="utf-8") as f:
            f.write("more\n")
        open(os.path.join(d, ".git", "MERGE_HEAD"), "w").close()
        before = len(log_of(d))
        mac._log[:] = []
        mac.sweep(root=root)
        check(len(log_of(d)) == before, "a repo mid-merge is left alone")
        check(any("merge/rebase" in x for x in mac._log), "and says why")
        os.remove(os.path.join(d, ".git", "MERGE_HEAD"))

        # (d) git missing from PATH entirely
        real = mac.git
        mac.git = lambda repo, *a, **k: (127, "", "git not found on PATH")
        try:
            check(mac.sweep(root=root) == [], "no git binary -> no crash, no commits")
        finally:
            mac.git = real

        # (e) an exploding sweep must still exit 0 from main()
        real_sweep = mac.sweep
        mac.sweep = lambda **kw: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            check(mac.main() == 0,
                  "main() returns 0 even when sweep() raises - a Stop hook that "
                  "exits 2 would BLOCK the turn")
        finally:
            mac.sweep = real_sweep
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_end_to_end_as_the_hook_runs_it():
    print("6. invoked the way the hook actually is: JSON on stdin, exit code checked")
    root = make_root()
    try:
        project(root, "proj-a", {"a.md": "a\n"})
        env = dict(os.environ)
        # point the module's real constant at the temp tree for the subprocess
        script = os.path.join(ROOT, "ops", "tools", "memory_autocommit.py")
        runner = (
            "import sys, json;"
            "sys.path.insert(0, %r);"
            "import memory_autocommit as m;"
            "m.PROJECTS = %r;"
            "sys.exit(m.main())" % (os.path.join(ROOT, "ops", "tools"), root)
        )
        r = subprocess.run([sys.executable, "-c", runner],
                           input='{"session_id":"abc-123","hook_event_name":"Stop"}',
                           capture_output=True, text=True, timeout=90, env=env)
        check(r.returncode == 0, "exit code 0 (anything else risks blocking a turn)")
        d = os.path.join(root, "proj-a", "memory")
        check(len(log_of(d)) == 1, "the note was committed by the real entry point")
        rc, msg, _ = mac.git(d, "log", "-1", "--pretty=%B")
        check("abc-123" in msg, "the session id from stdin JSON reached the commit")

        # malformed stdin must not matter
        with open(os.path.join(d, "a.md"), "a", encoding="utf-8") as f:
            f.write("x\n")
        r2 = subprocess.run([sys.executable, "-c", runner],
                            input="not json at all",
                            capture_output=True, text=True, timeout=90, env=env)
        check(r2.returncode == 0, "malformed stdin -> still exit 0")
        check(len(log_of(d)) == 2, "and the commit still happened")
    finally:
        shutil.rmtree(root, ignore_errors=True)


if not have_git():
    print("git not available - skipping (the gate runs where git exists)")
    sys.exit(0)

for fn in (test_bootstraps_and_commits, test_multiple_projects_and_empty_dirs,
           test_leaves_foreign_repos_alone, test_never_pushes,
           test_cannot_wedge_a_turn, test_end_to_end_as_the_hook_runs_it):
    fn()

print(("FAILED: %d" % len(_fails)) if _fails else "\nall memory-autocommit checks passed")
sys.exit(1 if _fails else 0)
