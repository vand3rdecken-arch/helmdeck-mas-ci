# -*- coding: utf-8 -*-
"""P4 worktree/env robustness (Paseo adoption Phase 4) - pins.

  4.1 Worktree ownership is provable from the PATH SHAPE
      (<...>/helmdeck-worktrees/<8-char-hash>/<slug>), keyed off the git
      common dir, so cleanup survives a BROKEN git state; old flat trees are
      never claimed.
  4.2 Every card gets an auto-allocated, PERSISTED dev port - parallel cards
      never fight over one, and the agent env carries HELMDECK_DEV_PORT.
  4.3 New card branches start --no-track from an EXPLICIT base (origin/<base>
      only when ahead-or-equal), never from "whatever HEAD is"; detached and
      unborn bases are rejected; _current_branch survives a rebase.
  4.4 The agent env is the EXTERNAL model: daemon control keys stripped,
      card overlay applied; the daemon hydrates its own env at launch.

Self-sandboxing: temp git repos, monkeypatched _load/_save_track and
events.settings - no daemon, no real DB writes.
"""
import os, shutil, socket, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DAEMON = os.path.join(os.path.dirname(HERE), "daemon")
sys.path.insert(0, DAEMON)
import db
db.init()
import sessions, drivers, events

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def run(cwd, *args):
    r = subprocess.run(["git", "-C", cwd, "-c", "user.email=t@t", "-c", "user.name=t",
                        *args], capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def mkrepo(name, commit=True):
    d = os.path.join(TMP, name)
    os.makedirs(d, exist_ok=True)
    run(d, "init")
    run(d, "symbolic-ref", "HEAD", "refs/heads/main")   # git 2.27 has no `init -b`
    if commit:
        open(os.path.join(d, "a.txt"), "w").write("a\n")
        run(d, "add", "-A")
        run(d, "commit", "-m", "init")
    return d


TMP = tempfile.mkdtemp(prefix="helmdeck-p4-")

# sandbox the store
store = {}
sessions._load = lambda: list(store.values())
sessions._save_track = lambda t: store.__setitem__(t["id"], dict(t))
events.emit = lambda *a, **k: None

# ---------------------------------------------------------------- 4.1 hash + shape
repo = mkrepo("repo")
h = sessions._repo_hash(repo)
check(len(h) == 8 and all(c in "0123456789abcdefghijklmnopqrstuvwxyz" for c in h),
      "(4.1) _repo_hash is 8-char base36: %s" % h)
check(sessions._repo_hash(repo) == h, "(4.1) _repo_hash is stable")
check(sessions._repo_hash(os.path.join(TMP, "no-such")) != "",
      "(4.1) _repo_hash falls back for a non-repo path (broken git tolerated)")

wt_path = sessions._worktree_for(repo, "my-card")
parent = os.path.dirname(wt_path)
check(os.path.basename(os.path.dirname(parent)) == "helmdeck-worktrees"
      and os.path.basename(parent) == h,
      "(4.1) _worktree_for shape is <...>/helmdeck-worktrees/<hash>/<slug>")
# the hash from INSIDE a worktree matches the repo's (common dir, not cwd)
rc, _, _ = run(repo, "worktree", "add", wt_path, "-b", "my-card", "--no-track", "main")
check(rc == 0, "(4.1) worktree add into the hash dir works")
check(sessions._repo_hash(wt_path) == h,
      "(4.1) _repo_hash from inside a worktree == repo's hash (git-common-dir)")

check(sessions._owned_worktree(wt_path), "(4.1) hash-shaped tree IS owned")
flat = os.path.join(TMP, "helmdeck-worktrees", "flat-card")
os.makedirs(flat, exist_ok=True)
check(not sessions._owned_worktree(flat), "(4.1) old FLAT tree is NOT owned")
check(not sessions._owned_worktree(repo), "(4.1) the repo itself is NOT owned")
check(not sessions._owned_worktree(parent), "(4.1) the <hash> dir itself is NOT owned")

check(not sessions._git_state_broken(repo), "(4.1) healthy repo: git state not broken")
check(not sessions._git_state_broken(wt_path), "(4.1) healthy worktree: not broken")
nogit = os.path.join(TMP, "nogit"); os.makedirs(nogit, exist_ok=True)
check(sessions._git_state_broken(nogit), "(4.1) no .git at all: broken")

# BROKEN git state: sever the admin dir, then reclaim must still remove the tree
admin = os.path.join(repo, ".git", "worktrees")
shutil.rmtree(admin)
check(sessions._git_state_broken(wt_path), "(4.1) severed admin dir detected as broken")
t_card = {"repo": repo, "worktree": wt_path, "branch": "my-card"}
ok = sessions.reclaim_worktree(t_card)
check(ok and not os.path.isdir(wt_path),
      "(4.1) reclaim removes an OWNED tree although `git worktree remove` fails")

# a broken flat tree is NOT rm'd by the ownership fallback (git alone manages it)
open(os.path.join(flat, ".git"), "w").write("gitdir: %s\n" % os.path.join(repo, ".git", "worktrees", "gone"))
t_flat = {"repo": repo, "worktree": flat, "branch": "flat-card"}
sessions.reclaim_worktree(t_flat)
check(os.path.isdir(flat), "(4.1) broken FLAT (unowned) tree is left alone")

# sweep orphan pass: an owned+broken dir git never heard of goes away,
# a tree still referenced by a card stays
hashdir = os.path.join(os.path.abspath(os.path.join(repo, "..", "helmdeck-worktrees")), h)
orphan = os.path.join(hashdir, "orphan-card")
os.makedirs(orphan)
open(os.path.join(orphan, ".git"), "w").write("gitdir: %s\n" % os.path.join(repo, ".git", "worktrees", "gone2"))
kept = os.path.join(hashdir, "kept-card")
os.makedirs(kept)
open(os.path.join(kept, ".git"), "w").write("gitdir: %s\n" % os.path.join(repo, ".git", "worktrees", "gone3"))
store.clear()
store["T-1"] = {"id": "T-1", "repo": repo, "worktree": kept, "branch": "kept-card"}
sessions.sweep_worktrees()
check(not os.path.isdir(orphan), "(4.1) sweep reclaims the git-forgotten orphan")
check(os.path.isdir(kept), "(4.1) sweep keeps a tree a card still references")

# ---------------------------------------------------------------- 4.3 base + guards
repo2 = mkrepo("repo2", commit=False)
try:
    sessions._base_ref(repo2)
    check(False, "(4.3) unborn base branch rejected")
except RuntimeError as e:
    check("no commits" in str(e), "(4.3) unborn base branch rejected: %s" % e)

repo3 = mkrepo("repo3")
check(sessions._base_ref(repo3) == "main", "(4.3) no origin -> local base branch")
rc, head, _ = run(repo3, "rev-parse", "HEAD")
run(repo3, "checkout", "--detach", head)
try:
    sessions._base_ref(repo3)
    check(False, "(4.3) detached HEAD rejected")
except RuntimeError as e:
    check("detached" in str(e), "(4.3) detached HEAD rejected: %s" % e)
run(repo3, "checkout", "main")

# origin ahead-or-equal -> origin wins; origin behind (local ahead) -> local wins
origin = mkrepo("origin-src")
repo4 = os.path.join(TMP, "clone")
subprocess.run(["git", "clone", "-q", origin, repo4], capture_output=True)
check(sessions._base_ref(repo4) == "origin/main",
      "(4.3) origin equal to local -> prefers origin/main")
open(os.path.join(repo4, "b.txt"), "w").write("b\n")
run(repo4, "add", "-A"); run(repo4, "commit", "-m", "local ahead")
check(sessions._base_ref(repo4) == "main",
      "(4.3) local ahead of a stale origin -> local base wins (never lose local work)")

# --no-track: the created card branch must have NO upstream
wt4 = sessions._worktree_for(repo4, "card4")
rc, _, err = run(repo4, "worktree", "add", wt4, "-b", "card4", "--no-track",
                 sessions._base_ref(repo4))
rc2, up, _ = run(repo4, "config", "branch.card4.remote")
check(rc == 0 and rc2 != 0, "(4.3) card branch created --no-track (no upstream remote)")

# rebase-HEAD guard: mid-'rebase', _current_branch names the rebased branch
check(sessions._current_branch(repo3) == "main", "(4.3) _current_branch normal case")
rb = os.path.join(repo3, ".git", "rebase-merge")
os.makedirs(rb, exist_ok=True)
open(os.path.join(rb, "head-name"), "w").write("refs/heads/main\n")
run(repo3, "checkout", "--detach", head)     # rebase detaches HEAD
check(sessions._current_branch(repo3) == "main",
      "(4.3) mid-rebase (HEAD detached + rebase-merge/head-name) -> 'main'")
shutil.rmtree(rb)
check(sessions._current_branch(repo3) == "HEAD",
      "(4.3) genuinely detached (no rebase) -> 'HEAD' (callers block)")

# ---------------------------------------------------------------- 4.2 dev ports
events.settings = lambda: {"dev_port_range": [3951, 3954], "value_per_card": 0}
store.clear()
store["T-A"] = {"id": "T-A", "dev_port": 3951}
store["T-B"] = {"id": "T-B", "dev_port": 3952}
got = {sessions._alloc_dev_port(exclude_tid="T-C") for _ in range(20)}
check(got <= {3953, 3954}, "(4.2) allocator skips ports OTHER cards persist: %s" % got)

blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
blocker.bind(("127.0.0.1", 3953)); blocker.listen(1)
try:
    got = {sessions._alloc_dev_port(exclude_tid="T-C") for _ in range(20)}
    check(got == {3954}, "(4.2) allocator bind-checks (a busy port is skipped): %s" % got)
    store["T-D"] = {"id": "T-D", "dev_port": 3954}
    check(sessions._alloc_dev_port(exclude_tid="T-C") is None,
          "(4.2) exhausted range -> None (card still runs, just unreserved)")
finally:
    blocker.close()

# ---------------------------------------------------------------- 4.4 env models
t_env = {"id": "T-E", "dev_port": 3960, "worktree": "X:/wt", "branch": "card-e"}
overlay = drivers._card_env(t_env)
check(overlay.get("HELMDECK_DEV_PORT") == "3960" and overlay.get("HELMDECK_BRANCH") == "card-e",
      "(4.4) _card_env carries the reserved port + branch")
check("HELMDECK_DEV_PORT" not in drivers._card_env({"id": "M", "machine": True,
                                                    "worktree": "C:/x"}),
      "(4.4) machine cards get no dev port (no worktree dev server)")

os.environ["HELMDECK_TLS_CERT"] = "X:/secret.crt"
os.environ["BASH_ENV"] = "X:/evil.sh"
env = drivers._env({"env": {"JAVA_HOME": "X:/jdk", "PATH+": "X:/tc"}}, overlay)
check("HELMDECK_TLS_CERT" not in env and "BASH_ENV" not in env,
      "(4.4) external env strips daemon control keys (TLS material, BASH_ENV)")
check(env.get("HELMDECK_DEV_PORT") == "3960", "(4.4) card overlay lands in the agent env")
check(env.get("JAVA_HOME") == "X:/jdk" and env["PATH"].startswith("X:/tc" + os.pathsep),
      "(4.4) driver env + PATH+ still win")
del os.environ["HELMDECK_TLS_CERT"]; del os.environ["BASH_ENV"]

# registry hydration: absent vars appear, present vars are NOT clobbered
if os.name == "nt":
    import server
    os.environ["HELMDECK_P4_SENTINEL"] = "keep"
    before_path = os.environ.get("PATH", "")
    server._hydrate_registry_env()
    check(os.environ["HELMDECK_P4_SENTINEL"] == "keep",
          "(4.4) hydration never clobbers an inherited variable")
    check(before_path in os.environ.get("PATH", ""),
          "(4.4) hydration only APPENDS to PATH (inherited order wins)")
    snap = dict(os.environ)
    server._hydrate_registry_env()
    check(dict(os.environ) == snap, "(4.4) hydration is idempotent")
    del os.environ["HELMDECK_P4_SENTINEL"]

# ---------------------------------------------------------------- verdict
shutil.rmtree(TMP, ignore_errors=True)
print()
if _fails:
    print("FAILED: %d pin(s) broken" % len(_fails))
    for m in _fails:
        print("  - " + m)
    sys.exit(1)
print("ALL GREEN - P4 worktree/env pins hold.")
