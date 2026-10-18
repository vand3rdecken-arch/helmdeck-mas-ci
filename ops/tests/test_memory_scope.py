# -*- coding: utf-8 -*-
"""Headless test for SCOPED memory (team-rooms-member stage 2).

The defect this pins (measured by reading the code, 2026-10-04): `memory` was
keyed by name alone and every read returned every row, so a second account's
Henry was handed the OWNER's whole store in every turn - and an INSERT OR
REPLACE on a shared note name would have OVERWRITTEN the owner's note. These
cases run the REAL read/write path (db -> copilot_memory.all_notes ->
recall_block / apply) and fail on the old code:

 1. A restricted viewer never sees the owner's notes - not in all_notes, not in
    the recall block, not in the overview.
 2. The same note NAME in two scopes is two notes: the guest's save cannot
    overwrite the owner's, and her delete cannot delete it.
 3. A viewer reads their own person notes plus the rooms/cards they belong to,
    and NOT another room's.
 4. owner/operator keep the legacy view (viewer None) and memory_all() stays
    the owner's person scope only - the owner-side tools never read hers.
 5. Her save lands in HER scope (person, or the room she is writing in).

Self-sandboxing: temp DB, no network. Run: py -3.12 ops/tests/test_memory_scope.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

SANDBOX = tempfile.mkdtemp(prefix="hd-memscope-")

from spine.storage import db
db.ROOT = SANDBOX   # BOTH, not just DBPATH - see test_hook_idle.py's preamble
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from cells.copilot.chat import copilot_memory as cm

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


# the owner's private store - words a guest's turn must never surface
db.memory_put("depot", "Das Depot enthaelt Aktien AAA und BBB, Summe 50k", actor="henry")
db.memory_put("preferences", "OWNERPREF Antworten kurz und auf Deutsch", actor="henry")

# -- 4. legacy view unchanged -------------------------------------------------
check(cm.viewer_for("owner", "owner") is None,
      "the owner keeps the legacy (unrestricted) view")
check(cm.viewer_for("op", "operator") is not None and cm.viewer_for("member", "client") is not None,
      "the operator is restricted like a guest since the assignment model (2026-10-05)")
check(set(db.memory_all()) == {"depot", "preferences"},
      "memory_all() is the owner's person scope")

# -- 1. a guest sees none of it ----------------------------------------------
member = cm.viewer_for("member", "client", rooms=("room-a",))
check(member is not None and cm.all_notes(member) == {},
      "a guest with no notes of her own sees an EMPTY store, not the owner's")
check(cm.recall_block("Wie steht das Depot mit AAA und BBB", rows=cm.all_notes(member)) == "",
      "the recall block for her turn carries nothing from the owner's depot note")
check(cm.overview(rows=cm.all_notes(member), viewer=member) == "",
      "and the overview does not even count the owner's notes")

# -- 2. same name, two scopes -------------------------------------------------
done = cm.apply([{"op": "save", "name": "preferences", "content": "WIFEPREF immer Englisch",
                  "declared_kind": None}], actor="henry", source="chat:member",
                scope=cm.scope_for(member), viewer=member)
check(len(done) == 1, "her save landed")
check(db.memory_all()["preferences"]["content"].startswith("OWNERPREF"),
      "her save of the SAME name did NOT overwrite the owner's note")
check(cm.all_notes(member).get("preferences", {}).get("content", "").startswith("WIFEPREF"),
      "she reads back her own note")
check("WIFEPREF" not in " ".join(r["content"] for r in db.memory_all().values()),
      "the owner side never reads her note")

cm.apply([{"op": "delete", "name": "preferences"}], actor="henry",
         source="chat:member", scope=cm.scope_for(member), viewer=member)
check("preferences" in db.memory_all(),
      "her delete did NOT delete the owner's same-named note")
check("preferences" not in cm.all_notes(member), "it deleted her own")

# -- 3./5. rooms and cards ----------------------------------------------------
db.memory_put("raum-regel", "ROOMA Standups um 9", actor="henry", scope="room", scope_id="room-a")
db.memory_put("raum-regel", "ROOMB geheim", actor="henry", scope="room", scope_id="room-b")
db.memory_put("karten-stand", "CARD1 wartet auf Freigabe", actor="henry", scope="card", scope_id="c1")
notes = cm.all_notes(member)
check("room:room-a/raum-regel" in notes and "room:room-b/raum-regel" not in notes,
      "she reads the room she is in and NOT another room's note of the same name")
check("card:c1/karten-stand" not in notes,
      "a card she is not a member of stays invisible")
wife2 = cm.viewer_for("member", "client", rooms=("room-a",), cards=("c1",))
check("card:c1/karten-stand" in cm.all_notes(wife2), "adding the card makes its note visible")

sc = cm.scope_for(wife2, room="room-a")
check(sc == {"scope": "room", "scope_id": "room-a", "account": ""},
      "a save made inside a room lands in that room's scope")
check(cm.scope_for(wife2, room="room-zzz")["scope"] == "person",
      "a room she is NOT in falls back to her own person scope, never a foreign room")

# the owner side never sees room/card/guest rows through the legacy readers
check(set(db.memory_all()) == {"depot", "preferences"},
      "memory_all() is still exactly the owner's two notes")

# -- reject bad scopes --------------------------------------------------------
try:
    db.memory_put("x", "y", scope="room", scope_id="")
    check(False, "a room note without a room id is refused")
except ValueError:
    check(True, "a room note without a room id is refused")
try:
    db.memory_put("x", "y", scope="galaxy", scope_id="g")
    check(False, "an unknown scope is refused")
except ValueError:
    check(True, "an unknown scope is refused")

print()
if _fails:
    print("FAILED (%d):" % len(_fails))
    for f in _fails:
        print("  -", f)
    sys.exit(1)
print("MEMORY SCOPE: all pinned - PASS")
