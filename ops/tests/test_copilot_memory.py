# -*- coding: utf-8 -*-
"""henry-memory-db-authority: the sentinel write path (phase 1), the
session-scoped digest gate (phase 2) and the db->dir cache regen (phase 3).

Self-sandboxing: db.ROOT/db.DBPATH point at a temp dir (db.init() run against
it) and copilot_memory.MEMORY_DIR is redirected to a temp dir too - the
README's own trap #4 ("tests that patch events.SET alone write the LIVE db")
means BOTH must move, and the memory cache-regen test would otherwise clobber
the real daemon/content/henry_memory/ on whichever machine runs this.

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
# events.emit() write-throughs to db.event_insert regardless (sandboxed above),
# but its own jsonl append uses events.EV, bound at events.py's OWN import of
# daemon.paths.DAEMON_ROOT - a SEPARATE constant db.ROOT does not move (the
# README's trap #4, the other direction: sandboxing only db still hits the
# real events.jsonl unless EV moves too).
events.EV = os.path.join(_tmp, "events.jsonl")

from cells.copilot.chat import copilot_memory as m                    # noqa: E402
m.MEMORY_DIR = os.path.join(_tmp, "henry_memory")

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

# -- regenerate_cache(): clobber dir <- db, never db <- dir ------------------
print("\n[regenerate_cache]")
_reset_memory()
os.makedirs(m.MEMORY_DIR, exist_ok=True)
stray = os.path.join(m.MEMORY_DIR, "planted-by-someone-else.md")
with open(stray, "w", encoding="utf-8") as f:
    f.write("an unauthenticated write - must never reach the db")
db.memory_put("real-note", "the actual fact", actor="henry")
m.regenerate_cache()
check(not os.path.exists(stray), "a file with no matching db row is removed on regen")
got = os.path.join(m.MEMORY_DIR, "real-note.md")
check(os.path.exists(got), "a db row IS written to disk as a cache file")
with open(got, encoding="utf-8") as f:
    check(f.read() == "the actual fact", "cache file content matches the db row")
check("planted-by-someone-else" not in db.memory_all(),
      "the planted file never made it INTO the db - regen is one-directional")

# -- marker()/digest_due(): the session-establishment gate -------------------
print("\n[marker / digest_due - session-establishment gate]")
check(m.marker(None, None) == ("", None), "no session yet normalizes to an empty sid")
check(m.digest_due(None, m.marker(None, None), None) is True,
      "a fresh spawn (no sid) is always due, regardless of any stored marker")

mk1 = m.marker("sess-a", 5)
check(m.digest_due("sess-a", mk1, mk1) is False,
      "an unchanged (sid, compacted_at_turn) is NOT due - the resumed transcript has it")
check(m.digest_due("sess-a", mk1, None) is True,
      "never delivered before (no stored marker) -> due")

mk2 = m.marker("sess-b", 5)                       # rotated/detached resume
check(m.digest_due("sess-b", mk2, mk1) is True,
      "a rotated session id is due even though compacted_at_turn is unchanged")

mk3 = m.marker("sess-a", 6)                       # IN-PLACE compaction: same sid
check(m.digest_due("sess-a", mk3, mk1) is True,
      "an in-place compaction (same sid, compacted_at_turn bumped) is still due - "
      "the trap a sid-only key would miss (see test_copilot_compact.py case 3)")
check(m.digest_due("sess-a", mk3, mk3) is False,
      "once stamped with the post-compaction marker, the next resumed turn is not due")

print("")
if _fails:
    print("=== %d FAILED ===" % len(_fails))
    sys.exit(1)
print("copilot-memory: all pinned - PASS")
