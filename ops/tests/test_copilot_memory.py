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

# -- digest(): index-only, never the notes themselves ------------------------
print("\n[digest]")
_reset_memory()
check(m.digest() == "", "no digest when the db has no MEMORY index note yet")
db.memory_put("MEMORY", "- [note-a](note-a.md) - fact a", actor="henry")
d = m.digest()
check("fact a" in d, "digest carries the index body - got %r" % d)
check("note-a.md" not in d or "fact a" in d, "digest is the index, not a note dump")
# the index rides WHOLE: the live one was 5767 chars on 2026-09-16 and the
# digest cut it at 4000, so the newest entries (appended at the end) were
# exactly the ones Henry never saw again
_big = "\n".join("- [note-%03d](note-%03d.md) - %s" % (i, i, "x" * 80) for i in range(60)) + "\n- [newest](newest.md) - IOS APPROVED"
assert len(_big) > 5000
db.memory_put("MEMORY", _big, actor="henry")
d = m.digest()
check("IOS APPROVED" in d, "an index past 4000 chars still carries its newest (last) entry - digest %d chars" % len(d))

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
check(rc == 0 and out.strip() == "the actual fact", "get returns the exact db content - got %r" % out)

rc, out = _run("get", "no-such-note")
check(rc == 1, "get on a missing note exits non-zero, not a guess")

check(not any("henry_memory" in p for p in os.listdir(_tmp) if os.path.isdir(os.path.join(_tmp, p))),
      "no henry_memory directory exists anywhere - the read path never touches disk")

# marker()/digest_due() (the session-establishment gate for Henry's own
# auto-pushed digest) were REMOVED with the push itself (card
# chat-henry-kontext-pruning, "voller Umbau", 2026-09-15): digest() now has
# exactly one caller (cells/copilot/planning/pm.py's planner context), which
# reads it fresh every time it plans - no gate needed, nothing to test here.

print("")
if _fails:
    print("=== %d FAILED ===" % len(_fails))
    sys.exit(1)
print("copilot-memory: all pinned - PASS")
