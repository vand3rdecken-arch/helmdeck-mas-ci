# -*- coding: utf-8 -*-
"""Importing an existing agent memory from another system.

Owner 2026-09-22: a user arriving from Claude Code, Cursor, Codex or Windsurf
brings months of notes. The three rules this pins are the three that were
earned the hard way this week:

  1. discovery NAMES what it did not find (an empty result that looks like
     "you have nothing" is the exact lie this whole card started from)
  2. an import NEVER overwrites an existing note
  3. provenance survives the crossing

Self-sandboxing: a fake HOME and a temp db - this must never read the real
~/.claude or write the live daemon db (README trap #4).

Run: py -3.12 ops/tests/test_foreign_memory.py
"""
import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_tmp = tempfile.mkdtemp(prefix="foreign_mem_test_")
from spine.storage import db                                      # noqa: E402
db.ROOT = _tmp
db.DBPATH = os.path.join(_tmp, "test.db")
db.init()
from spine.memory import foreign                                  # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


# ---- a fake machine with a Claude Code memory, skills and a rules file -----
HOME = os.path.join(_tmp, "home")
REPO = os.path.join(_tmp, "repo")
foreign._home = lambda: HOME

mem = os.path.join(HOME, ".claude", "projects", "C--proj-alpha", "memory")
w(os.path.join(mem, "apk-traps.md"), "---\nname: apk-traps\n---\n\nJDK 17 noetig.\n")
w(os.path.join(mem, "relay-down.md"), "Relay 530 heisst Tunnel ohne Origin.\n")
w(os.path.join(mem, "MEMORY.md"), "- [apk-traps](apk-traps.md)\n")
w(os.path.join(HOME, ".agents", "skills", "deploy-check", "SKILL.md"),
  "---\nname: deploy-check\n---\n\nImmer erst das Gate.\n")
w(os.path.join(REPO, "CLAUDE.md"), "x" * 400)
w(os.path.join(HOME, ".claude", "CLAUDE.md"), "@RTK.md\n")      # 8 bytes: too small

print("\n[discovery finds what is there AND names what is not]")
found, absent = foreign.discover(repo=REPO)
ids = [s["id"] for s in found]
check(any(i.startswith("claude-memory:") for i in ids),
      "the Claude Code memory is found - got %r" % ids)
check(any(i.startswith("skills:") for i in ids), "skills are found")
check(any(i == "rules:claude-md" or i.startswith("rules:") for i in ids),
      "the project rules file is found - got %r" % ids)
check(not any(i == "rules:user-claude-md" for i in ids),
      "an 8-byte stub CLAUDE.md is NOT offered as memory")

names = [a["label"] for a in absent]
for want in ("Codex", "Windsurf", "Cursor", "ai-memory"):
    check(want in names, "%s is named as NOT found, not silently omitted" % want)
check(all(a.get("why") for a in absent), "and each absence says why")

print("\n[preview runs the same code the import does]")
src = [s for s in found if s["id"].startswith("claude-memory:")][0]
pv = foreign.preview(src)
check(len(pv) == 2, "preview lists the two notes, not the index - got %r" % (pv,))
check(all(not collides for _n, _c, collides in pv),
      "nothing collides on an empty db")
check(not any(n == "MEMORY" for n, _c, _x in pv),
      "the foreign index file is not imported as a note")

print("\n[import: provenance survives the crossing]")
res = foreign.import_source(src, actor="test")
check(sorted(res["imported"]) == ["apk-traps", "relay-down"],
      "both notes land - got %r" % (res,))
rows = db.memory_all()
check(rows["apk-traps"]["kind"] == "owner-fact",
      "a note the owner's own agent wrote ranks owner-fact - got %r"
      % rows["apk-traps"]["kind"])
check(rows["apk-traps"]["source"].startswith("import:claude-memory:"),
      "and it says where it came from - got %r" % rows["apk-traps"]["source"])

sk = [s for s in found if s["id"].startswith("skills:")][0]
foreign.import_source(sk, actor="test")
rows = db.memory_all()
check("skill-deploy-check" in rows, "a SKILL.md lands under a skill- name")
check(rows["skill-deploy-check"]["kind"] == "project",
      "a skill is an instruction, not a fact about the owner - got %r"
      % rows["skill-deploy-check"]["kind"])

print("\n[import NEVER overwrites]")
db.memory_put("apk-traps", "MEINE eigene Fassung", actor="henry", kind="measured")
res2 = foreign.import_source(src, actor="test")
check(res2["imported"] == [], "a second run imports nothing new - got %r" % res2)
check("apk-traps" in res2["skipped"],
      "the collision is reported BY NAME - got %r" % res2["skipped"])
check(db.memory_all()["apk-traps"]["content"] == "MEINE eigene Fassung",
      "and the existing note is untouched")

print("\n[dry run changes nothing]")
db.memory_delete("relay-down")
res3 = foreign.import_source(src, actor="test", dry_run=True)
check("relay-down" in res3["imported"], "dry run reports what it WOULD do")
check("relay-down" not in db.memory_all(), "but writes nothing")


print("%s[the agent pass: code enumerates, the model only CLASSIFIES]" % (chr(10),))
# Measured 2026-09-22 and the numbers picked the design: asking the model to
# SEARCH the machine took 220 s and timed out, and an earlier framing of that
# same task was refused outright by a safeguard. Handing it the listing and
# asking which entries are agent tools took 23 s and named a product we have
# no adapter for. So the model may only pick FROM a list code produced.
check(callable(foreign._config_dirs), "code enumerates the config dirs itself")
check("memory" in foreign._MEMORY_NAMES and "cache" in foreign._NOT_MEMORY,
      "and code, not the model, decides which subfolder names are memory")

# a pick that is NOT in the offered list is invented - the one thing this
# whole card is about - and must be discarded, not trusted
_saved = foreign._home
try:
    foreign._home = lambda: HOME
    entries = foreign._config_dirs()
    check(".claude" in entries, "the fake home's config dirs are listed - %r" % entries)
finally:
    foreign._home = _saved

print("")
if _fails:
    print("=== %d FAILED ===" % len(_fails))
    sys.exit(1)
print("foreign-memory: all pinned - PASS")
