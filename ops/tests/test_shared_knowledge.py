# -*- coding: utf-8 -*-
"""Card memory-as-knowledge-system: the SHARED half.

Owner decision 2026-09-21 - a team shares useful knowledge, personal notes
stay private, and the shared half lives as markdown in the user's project
repo. Every check here fails on the pre-2026-09-21 code, which had one store
and no notion of shared at all.

Self-sandboxing: db.ROOT/db.DBPATH point at a temp dir and every "repo" is a
temp dir too - this test must never write into the real tree or the live db
(README trap #4).

Run: py -3.12 ops/tests/test_shared_knowledge.py   (from the repo root)
"""
import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_tmp = tempfile.mkdtemp(prefix="shared_knowledge_test_")
from spine.storage import db                                      # noqa: E402
db.ROOT = _tmp
db.DBPATH = os.path.join(_tmp, "test.db")
db.init()
from cells.copilot.chat import knowledge as k                     # noqa: E402
from cells.copilot.chat import copilot_memory as m                # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _repo():
    return tempfile.mkdtemp(prefix="repo_", dir=_tmp)


def _write(repo, name, text):
    d = k.shared_dir(repo)
    os.makedirs(d, exist_ok=True)
    with io.open(os.path.join(d, name), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return os.path.join(d, name)


print("\n[promote: personal -> shared is a MOVE, not a copy]")
repo = _repo()
db.memory_put("apk-build-traps", "Forward-slash in local.properties, JDK 17.",
              actor="henry", kind="measured")
path = k.promote("apk-build-traps", repo)
check(os.path.isfile(path), "the note is written into the project repo")
check("apk-build-traps" not in db.memory_all(),
      "the personal row is GONE - one owner per note, so no merge can arise")
_notes, _probs = k.scan(repo)
check("apk-build-traps" in _notes and not _probs,
      "and it reads back as shared knowledge - got %r / %r"
      % (list(_notes), _probs))
check("kind: measured" in _notes["apk-build-traps"]["content"],
      "the provenance travels into the file's frontmatter")

idx = io.open(os.path.join(k.shared_dir(repo), k.INDEX_NAME), encoding="utf-8").read()
check("apk-build-traps" in idx, "the index is written")
check("Forward-slash" in idx,
      "the index hook is the note's own first REAL line, not its frontmatter")

print("\n[a file the harness refuses is NAMED, never silently missing]")
_write(repo, "broken.md", "a\n<<<<<<< HEAD\nx\n=======\ny\n>>>>>>> b\n")
_notes, _probs = k.scan(repo)
check("broken" not in _notes, "a file with conflict markers is NOT loaded")
check(any("KONFLIKT" in p for p in _probs),
      "and the refusal says so - got %r" % _probs)
check("apk-build-traps" in _notes,
      "one bad file does not take the healthy ones down with it")

_write(repo, "huge.md", "x" * (k.MAX_FILE_CHARS + 10))
_notes, _probs = k.scan(repo)
check("huge" not in _notes and any("Grenze" in p for p in _probs),
      "over the size cap is refused and reported - got %r" % _probs)

print("\n[secrets must not enter the half that leaves the machine]")
db.memory_put("leaky", "api_key: sk-abcdefghijklmnop1234567890", actor="henry")
try:
    k.promote("leaky", repo)
    check(False, "a secret-looking note must NOT be promotable")
except ValueError as e:
    check("Geheimnis" in str(e), "promote refuses it with a reason - %s" % e)
check("leaky" in db.memory_all(), "and the personal note survives the refusal")

_write(repo, "sneaky.md", "token: ghp_abcdefghijklmnopqrstuvwxyz01\n")
check(any("Geheimnis" in p for p in k.lint(repo)),
      "lint catches a secret written into the dir by hand - got %r" % k.lint(repo))

print("\n[precedence: personal is read LAST and wins]")
repo2 = _repo()
_write(repo2, "same-name.md", "die geteilte Fassung\n")
db.memory_put("same-name", "die persoenliche Fassung", actor="henry")
db.project_put({"id": "p-test", "name": "t", "repo": repo2})
rows = m.all_notes()
check(rows.get("same-name", {}).get("content", "").startswith("die persoenliche"),
      "the personal note wins the name - got %r"
      % (rows.get("same-name", {}).get("content", "")[:40],))
check(rows["same-name"].get("also_in") == "shared",
      "and the shared twin is FLAGGED, not silently dropped - got %r"
      % rows["same-name"].get("also_in"))

print("\n[the overview counts the shared half and names refusals]")
_write(repo2, "team-fact.md", "etwas, das dem Team hilft\n")
_ov = m.overview()
check("geteilt im Projekt-Repo" in _ov, "the overview reports a shared count")
_write(repo2, "conflicted.md", "<<<<<<< HEAD\na\n=======\nb\n>>>>>>> x\n")
_ov = m.overview()
check("NICHT geladen" in _ov,
      "a refused shared file is announced in the turn, not swallowed - %r"
      % _ov[-160:])


print("\n[a worktree resolves to the MAIN repo, not to itself]")
import subprocess as _sp
_main = tempfile.mkdtemp(prefix="mainrepo_", dir=_tmp)
_sp.run(["git", "init", "-q", _main], check=False)
_sp.run(["git", "-C", _main, "config", "user.email", "t@t"], check=False)
_sp.run(["git", "-C", _main, "config", "user.name", "t"], check=False)
with io.open(os.path.join(_main, "x.txt"), "w") as f:
    f.write("x")
_sp.run(["git", "-C", _main, "add", "-A"], check=False)
_sp.run(["git", "-C", _main, "commit", "-qm", "init"], check=False)
_wt = os.path.join(_tmp, "wt")
_r = _sp.run(["git", "-C", _main, "worktree", "add", "-q", "--no-track",
              "-b", "probe", _wt, "HEAD"], capture_output=True, text=True)
if os.path.isdir(_wt):
    check(os.path.normcase(k.shared_dir(_wt)) == os.path.normcase(k.shared_dir(_main)),
          "knowledge written from a worktree lands in the MAIN repo - got %r"
          % k.shared_dir(_wt))
    db.memory_put("from-a-worktree", "Ein Fakt, den eine Karte im Worktree lernte.",
                  actor="henry", kind="measured")
    k.promote("from-a-worktree", _wt)
    check(os.path.isfile(os.path.join(k.shared_dir(_main), "from-a-worktree.md")),
          "and the file really is in the main tree, where the reclaim cannot eat it")
    check(not os.path.isdir(os.path.join(_wt, ".helmdeck")),
          "nothing was written into the worktree itself")
else:
    check(False, "worktree fixture could not be created: %s" % (_r.stderr or "")[:80])

print("")
if _fails:
    print("=== %d FAILED ===" % len(_fails))
    sys.exit(1)
print("shared-knowledge: all pinned - PASS")
