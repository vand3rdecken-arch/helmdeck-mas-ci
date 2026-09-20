# -*- coding: utf-8 -*-
"""henry-memory-db-authority: the sentinel write path (phase 1), the
session-scoped digest gate (phase 2), and (2026-09-11 follow-up) the fact
that memory has NO filesystem surface at all anymore - db.memory_all/put/
delete is the only store, and ops/tools/henry_memory_get.py is the only
read path a full note travels, a plain db query with no cache in between.

Self-sandboxing: db.ROOT/db.DBPATH point at a temp dir (db.init() run
against it) - the README's own trap #4 ("tests that patch events.SET alone
write the LIVE db") means this must move or the test would touch the real
daemon.

Run: py -3.12 ops/tests/test_copilot_memory.py   (from the repo root)
"""
import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_tmp = tempfile.mkdtemp(prefix="copilot_memory_test_")
from spine.storage import db, events                                  # noqa: E402
db.ROOT = _tmp
db.DBPATH = os.path.join(_tmp, "test.db")
db.init()
# events.emit() writes the sandboxed events table (state-into-db phase H).
from cells.copilot.chat import copilot_memory as m                    # noqa: E402
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location(
    "henry_memory_get", os.path.join(ROOT, "ops", "tools", "henry_memory_get.py"))
_hmg = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_hmg)

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def _reset_memory():
    for name in list(db.memory_all()):
        db.memory_delete(name)


# -- parse(): the strict sentinel grammar ------------------------------------
print("\n[parse - valid blocks]")
_reset_memory()
cleaned, muts = m.parse(
    'Klar, notiert.\n<memory-save name="repo-x-owner">\n'
    'Repo X gehoert dem Owner.\n</memory-save>\nGern geschehen.')
check(cleaned == "Klar, notiert.\n\nGern geschehen.",
      "save block stripped from the visible reply, prose kept - got %r" % cleaned)
check(muts == [{"op": "save", "name": "repo-x-owner", "content": "Repo X gehoert dem Owner."}],
      "save block parsed with name + content - got %r" % muts)

cleaned, muts = m.parse('Erledigt.\n<memory-delete name="repo-x-owner"/>')
check(cleaned == "Erledigt.", "delete block stripped - got %r" % cleaned)
check(muts == [{"op": "delete", "name": "repo-x-owner"}],
      "delete block parsed - got %r" % muts)

print("\n[parse - multiple blocks, in order]")
cleaned, muts = m.parse(
    '<memory-save name="a">first</memory-save>'
    '<memory-delete name="b"/>'
    '<memory-save name="c">third</memory-save>')
check([mm["name"] for mm in muts] == ["a", "b", "c"],
      "blocks applied in document order - got %r" % [mm["name"] for mm in muts])
check(cleaned == "", "no prose left when the reply is only blocks - got %r" % cleaned)

print("\n[parse - malformed: rejected, never guessed, always stripped]")
cleaned, muts = m.parse('Notiz.\n<memory-save name="bad/name">x</memory-save>')
check(muts == [], "a name with a path separator is rejected, not sanitized")
check(cleaned == "Notiz.", "the raw tag is still stripped from the reply - got %r" % cleaned)

cleaned, muts = m.parse('<memory-save name="empty-note"></memory-save>')
check(muts == [], "empty content is rejected (delete exists for 'nothing here')")

cleaned, muts = m.parse('<memory-save name="huge">%s</memory-save>' % ("x" * (m.MAX_CONTENT_LEN + 1)))
check(muts == [], "content over MAX_CONTENT_LEN is rejected, never truncated")

cleaned, muts = m.parse('<memory-delete name=".."/>')
check(muts == [], "a delete with an unsafe name is rejected the same way as a save")

print("\n[parse - no sentinel present]")
cleaned, muts = m.parse("Ganz normale Antwort ohne Notiz.")
check(cleaned == "Ganz normale Antwort ohne Notiz." and muts == [],
      "plain prose passes through untouched")

# -- apply(): db writes + per-mutation events --------------------------------
print("\n[apply - db writes land, one event per mutation]")
_reset_memory()
from spine.storage import events                                      # noqa: E402
_before = len(events.read_events())
done = m.apply([{"op": "save", "name": "note-a", "content": "fact a"},
                {"op": "save", "name": "MEMORY", "content": "- [note-a](note-a.md) - fact a"}],
               actor="henry")
check(len(done) == 2, "both mutations reported as applied")
all_notes = db.memory_all()
check(all_notes.get("note-a", {}).get("content") == "fact a", "note-a landed in the db")
check(all_notes.get("note-a", {}).get("actor") == "henry", "actor recorded as henry")
check(all_notes.get("MEMORY", {}).get("content", "").startswith("- [note-a]"),
      "the index note landed too")
_after_save = len(events.read_events())
check(_after_save - _before == 2, "one 'memory' event per mutation (got %d)" % (_after_save - _before))

m.apply([{"op": "delete", "name": "note-a"}], actor="henry")
check("note-a" not in db.memory_all(), "delete actually removes the row")
_after_delete = len(events.read_events())
check(_after_delete - _after_save == 1, "delete emits its own event too")

# -- digest(): a DERIVED index, never the notes themselves ------------------
# REWRITTEN 2026-09-20. The old contract was "digest() returns whatever Henry
# last stored under the name MEMORY", and that contract IS the defect: the
# stored index froze on 2026-09-15 because every rewrite exceeded
# MAX_CONTENT_LEN and parse() drops a bad block silently, so for five days he
# read a 40-line index of 115 notes and concluded he had never been told
# things he had written down himself. An index is a VIEW over the notes and
# is now computed. The invariant the old tests reached for - the NEWEST entry
# must never be the one cut - is pinned harder here, because a derived index
# is sorted newest-first by construction.
print("\n[digest]")
_reset_memory()
check(m.digest() == "", "no digest when there are no notes at all")
db.memory_put("note-a", "fact a", actor="henry")
d = m.digest()
check("note-a" in d, "digest lists the note - got %r" % d)
check("fact a" in d, "digest carries each note own description line")
db.memory_put("MEMORY", "- [hand-written](x.md) - stale, never rewritten", actor="henry")
check("stale" not in m.digest(),
      "a stored MEMORY note can no longer BE the index - it is ignored")
_reset_memory()
for i in range(60):
    db.memory_put("note-%03d" % i, "x" * 80, actor="henry")
db.memory_put("newest-note", "IOS APPROVED", actor="henry")
d = m.digest()
check(len(d) > 5000, "a 61-note index is big - %d chars" % len(d))
check(all(("note-%03d" % i) in d for i in range(60)) and "newest-note" in d,
      "every note is listed - an index cannot go stale on a note it never saw")

# -- henry_memory_get.py: the only read path for a full note, no cache -------
print("\n[henry_memory_get - read-only, no filesystem surface]")
_reset_memory()
db.memory_put("real-note", "the actual fact", actor="henry")
db.memory_put("MEMORY", "- [real-note](real-note.md) - the actual fact", actor="henry")

import io, contextlib

def _run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = _hmg.main(["henry_memory_get.py"] + list(argv))
    return rc, out.getvalue()

rc, out = _run("list")
check(rc == 0 and "real-note" in out, "list surfaces the note name - got %r" % out)
check("MEMORY" not in out.splitlines(), "list hides the index note itself")

rc, out = _run("get", "real-note")
check(rc == 0 and "the actual fact" in out, "get returns the exact db content - got %r" % out)
check(rc == 0 and out.splitlines()[0].startswith("[db |"),
      "get labels WHICH store the note came from - got %r" % out.splitlines()[:1])

rc, out = _run("get", "no-such-note")
check(rc == 1, "get on a missing note exits non-zero, not a guess")

check(not any("henry_memory" in p for p in os.listdir(_tmp) if os.path.isdir(os.path.join(_tmp, p))),
      "no henry_memory directory exists anywhere - the read path never touches disk")

# marker()/digest_due() (the session-establishment gate for Henry's own
# auto-pushed digest) were REMOVED with the push itself (card
# chat-henry-kontext-pruning, "voller Umbau", 2026-09-15): digest() now has
# exactly one caller (cells/copilot/planning/pm.py's planner context), which
# reads it fresh every time it plans - no gate needed, nothing to test here.

# ---------------------------------------------------------------------------
# 2026-09-20, owner: "alle Infos zu Claude und db sollten zugaenglich sein".
# Henry told the owner three times that Jev has no text API while the
# correction sat in the CLI's own auto-memory directory and the wrong card
# report sat in his db. Two stores, no reconciliation, and an index that had
# been frozen since 2026-09-15 because every rewrite was silently rejected.
# Each check below FAILS on the pre-fix code.
print("\n-- derived index + the second store --")

_reset_memory()
for i in range(120):
    db.memory_put("note-%03d" % i, "fact %d" % i)
db.memory_put("MEMORY", "- [stale](old.md) - written by hand on 2026-09-15")
_idx = m.digest()
check(all(("note-%03d" % i) in _idx for i in range(120)),
      "the index is DERIVED: all 120 notes appear, not the 1-line stored MEMORY note")
check("stale" not in _idx, "the hand-written MEMORY note is no longer the index")
rc, out = _run("get", "MEMORY")
check(rc == 0 and "note-119" in out, "get MEMORY serves the derived index too - got %r" % out[:120])

# the CLI's auto-memory: read ONLY from a path the CLI itself reported
_auto = os.path.join(_tmp, "cli_memory")
os.makedirs(_auto, exist_ok=True)
with io.open(os.path.join(_auto, "jev-browser-verdict.md"), "w", encoding="utf-8") as f:
    f.write("---\nname: jev-browser-verdict\ndescription: Jev has a score API\n---\n\nbody here\n")
check(m.auto_dir() is None,
      "an UNOBSERVED directory is invisible - the path is never derived from cwd")
check(m.auto_notes() == {}, "no observation, no notes - an honest empty, not a guess")

m.observe_auto_dir({"type": "system", "subtype": "init", "session_id": "s1",
                    "memory_paths": {"auto": _auto}})
check(m.auto_dir() == _auto, "the path is taken from the CLI's OWN init event")
_all = m.all_notes()
check("jev-browser-verdict" in _all, "a CLI note is now readable alongside the db")
check(_all["jev-browser-verdict"].get("source") == "cli", "a CLI note is labelled as such")
check("Jev has a score API" in m.digest(), "the CLI note shows up in the index")
# ORDER IS THE WHOLE POINT OF THE OLD BUG: the stored index was APPENDED
# to, so a length cut removed the newest entries - the ones just saved.
# Derived, it is sorted newest-first, so a cut can only ever lose the
# stalest. Pinned with real, distinct mtimes rather than same-second ties.
import time as _t
_reset_memory()   # only the CLI store in play, so the ordering is the thing tested
for _fn, _age in (("ancient-note.md", 200000), ("fresh-note.md", 10)):
    _fp = os.path.join(_auto, _fn)
    with io.open(_fp, "w", encoding="utf-8") as f:
        f.write("body of " + _fn)
    os.utime(_fp, (_t.time() - _age, _t.time() - _age))
_short = m.digest(limit=120)
check("fresh-note" in _short and "ancient-note" not in _short,
      "a truncated index keeps the NEWEST and drops the stalest - got %r" % _short[-160:])
rc, out = _run("find", "score")
check(rc == 0 and "jev-browser-verdict" in out, "find searches BOTH stores - got %r" % out[:160])

db.memory_put("jev-browser-verdict", "db version wins")
_all = m.all_notes()
check(_all["jev-browser-verdict"].get("source") == "db",
      "on a name clash the store of record wins")
check(_all["jev-browser-verdict"].get("also_in") == "cli",
      "the losing twin is FLAGGED, not silently dropped")

m.observe_auto_dir({"type": "system", "subtype": "init",
                    "memory_paths": {"auto": os.path.join(_tmp, "gone")}})
check(m.auto_dir() is None, "an observed path that no longer exists reads as absent")
m.observe_auto_dir({"type": "system", "memory_paths": {"auto": _auto}})

print("\n-- the write path reports back --")
_cleaned, _muts = m.parse('<memory-save name="huge">%s</memory-save>' % ("x" * (m.MAX_CONTENT_LEN + 1)))
check(m.last_rejects() == ["huge"], "a rejected block is readable by the caller, not only an event")
_line = m.feedback(_muts, m.last_rejects())
check("VERWORFEN" in _line and "huge" in _line,
      "the next turn is TOLD the save was dropped - got %r" % _line)
_cleaned, _muts = m.parse('<memory-save name="kept">fact</memory-save>')
check(m.last_rejects() == [], "a clean turn reports no rejects")
check("gespeichert: kept" in m.feedback(_muts, m.last_rejects()),
      "a successful save is reported too")
check(m.feedback([], []) == "", "a turn that saved nothing adds no line")

print("")
if _fails:
    print("=== %d FAILED ===" % len(_fails))
    sys.exit(1)
print("copilot-memory: all pinned - PASS")
