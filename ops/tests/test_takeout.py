# -*- coding: utf-8 -*-
"""Takeout: export, verify, restore - against a REAL container, in a sandbox.

An export nobody has restored is a guess. This builds a small container from a
sandboxed db, then restores it into a second sandboxed db and checks the rows
arrive; it also checks the refusals, which are the part that matters most
(a restore that silently half-applies is worse than one that stops).

Self-sandboxing: db.ROOT/db.DBPATH point at temp dirs throughout - this must
never touch the live daemon db (README trap #4).

Run: py -3.12 ops/tests/test_takeout.py   (from the repo root)
"""
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

_tmp = tempfile.mkdtemp(prefix="takeout_test_")
from spine.storage import db                                      # noqa: E402
db.ROOT = _tmp
db.DBPATH = os.path.join(_tmp, "source.db")
db.init()

import importlib.util as _ilu                                     # noqa: E402
_spec = _ilu.spec_from_file_location(
    "takeout", os.path.join(ROOT, "ops", "tools", "takeout.py"))
takeout = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(takeout)

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


print("\n[export: the container has a manifest, checksums and a marker]")
db.memory_put("takeout-note-a", "Ein Fakt, den der Umzug mitnehmen muss.",
              kind="measured", source="test")
db.memory_put("takeout-note-b", "Noch einer.", kind="owner-fact")

# a fake auto-memory the export should pick up, WITHOUT touching the real one
_fake_mem = os.path.join(_tmp, "fake-auto-memory")
os.makedirs(_fake_mem, exist_ok=True)
with io.open(os.path.join(_fake_mem, "note.md"), "w", encoding="utf-8") as f:
    f.write("---\nname: note\n---\n\nein notierter Fakt\n")
from cells.copilot.chat import copilot_memory                     # noqa: E402
db.doc_put(copilot_memory.AUTO_DOC, {"path": _fake_mem})

_out = os.path.join(_tmp, "boxes")
box, man = takeout.build(_out)
check(os.path.isdir(box), "a container directory is written")
check(man.get("complete") is True, "the completeness marker is set")
check(man.get("format") == takeout.FORMAT_VERSION, "the format version is recorded")
check(man.get("schema") == db.schema_head(),
      "the DB SCHEMA version is recorded separately from the format version")
check("db.json" in man["parts"] and man["parts"]["db.json"].get("sha256"),
      "the db part carries a checksum")
check(man["parts"].get("auto-memory/", {}).get("files", 0) >= 1,
      "the auto-memory is carried - got %r" % (man["parts"].get("auto-memory/"),))
check(os.path.isfile(os.path.join(box, takeout.NOT_INCLUDED)),
      "the exclusion list ships INSIDE the container")
_ni = io.open(os.path.join(box, takeout.NOT_INCLUDED), encoding="utf-8").read()
check("apk-signing" in _ni and "UNERSETZLICH" in _ni,
      "and it names the irreplaceable signing key first")

print("\n[verify: a damaged container is refused, and says why]")
check(takeout.verify(box) == [], "the fresh container verifies clean")

_mp = os.path.join(box, takeout.MANIFEST)
_good = json.load(io.open(_mp, encoding="utf-8"))
_bad = dict(_good); _bad.pop("complete")
json.dump(_bad, io.open(_mp, "w", encoding="utf-8"))
check(any("ABGEBROCHEN" in p for p in takeout.verify(box)),
      "a missing completeness marker reads as INTERRUPTED, not as small")
json.dump(_good, io.open(_mp, "w", encoding="utf-8"))

with io.open(os.path.join(box, "db.json"), "a", encoding="utf-8") as f:
    f.write(" ")
check(any("Pruefsumme" in p for p in takeout.verify(box)),
      "a tampered part is caught by its checksum")

print("\n[restore refuses a damaged container WHOLE]")
try:
    takeout.restore(box)
    check(False, "a damaged container must not be restored")
except RuntimeError as e:
    check("nichts angefasst" in str(e),
          "and the refusal says nothing was touched - %s" % str(e)[:70])

print("\n[restore: into a FRESH db, the rows arrive]")
box2, _man2 = takeout.build(_out)          # a clean one
check(takeout.verify(box2) == [], "second container verifies clean")

_target = os.path.join(_tmp, "target")
os.makedirs(_target, exist_ok=True)
db.ROOT = _target
db.DBPATH = os.path.join(_target, "helmdeck.db")
# the connection is cached per thread - repointing DBPATH alone would keep
# writing into the SOURCE db, which is how this test first "restored" into
# the very database it had just exported.
try:
    db.conn().close()
except Exception:
    pass
db._local.c = None
db.init()
check(len(db.memory_all()) == 0, "the target db starts empty")

_dest = os.path.join(_tmp, "new-auto-memory")
takeout.probe_auto_dir = lambda: (_dest, None)   # no CLI spawn in a test
steps = takeout.restore(box2)
check(any("Datenbank importiert" in s for s in steps),
      "the db step ran - %r" % steps[:2])
_m = db.memory_all()
check("takeout-note-a" in _m and _m["takeout-note-a"]["kind"] == "measured",
      "the notes arrive WITH their provenance - got %r"
      % (_m.get("takeout-note-a", {}).get("kind"),))
check(os.path.isfile(os.path.join(_dest, "note.md")),
      "the auto-memory landed at the path the CLI reported")
check(any("VON HAND" in s for s in steps),
      "the restore ends by naming what must still be done by hand")

print("\n[restore never overwrites an existing memory with history]")
os.makedirs(os.path.join(_dest, ".git"), exist_ok=True)
steps = takeout.restore(box2, merge=True)
check(any("NICHT ueberschrieben" in s for s in steps),
      "a destination with git history is refused - %r"
      % [s for s in steps if "Auto-Memory" in s])
check(any("remote add" in s for s in steps),
      "and the refusal hands over the exact command to get the history instead")

print("\n[restore refuses a non-empty db unless asked]")
try:
    takeout.restore(box2)                 # target now has rows, no --merge
    check(False, "a non-empty db must not be restored into by default")
except RuntimeError as e:
    check(True, "refused without --merge - %s" % str(e)[:60])


print("\n[a failed export is an EXCEPTION, and exceptions go to Henry]")
# Owner 2026-09-22: "was passiert wenn ein Skript failed". Before this, a
# failure set a flag and painted a red line in a panel nobody may be looking
# at - and the owner wants a backup precisely when something is already wrong.
from spine.http.routes import routes_takeout as rt                # noqa: E402
from spine.registry import escalations                            # noqa: E402

_before = len(escalations.list_open())
rt._escalate_failure("owner", RuntimeError("Kein Platz auf dem Geraet"), None)
_open = escalations.list_open()
check(len(_open) == _before + 1, "the failure raises exactly one escalation")
_e = _open[-1]
check(_e.get("kind") == "takeout_failed",
      "under its own kind, so the broker can route it - got %r" % _e.get("kind"))
check("Kein Platz" in (_e.get("detail") or ""),
      "the real error text travels, not a generic message")

_f = rt._facts()
check("disk_free_mb" in _f and "db_mb" in _f,
      "and CODE gathers the facts a diagnosis needs - got %r" % sorted(_f))
check(isinstance(_f.get("disk_free_mb"), int),
      "measured, not described: free space is a number")

print("")
if _fails:
    print("=== %d FAILED ===" % len(_fails))
    sys.exit(1)
print("takeout: all pinned - PASS")
