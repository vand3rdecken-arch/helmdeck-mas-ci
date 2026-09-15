# -*- coding: utf-8 -*-
"""The snapshot-delta seam must actually collapse.

MEASURED 2026-09-15 on the live board session (b085da2d, Claude Code's own
per-call usage): the post-compaction floor was 60-82k (fixed base), and the
climb to 171k came at ~9k tokens per owner turn - every one of 10 turns
re-sent the full 10-15 KB board snapshot. Two reasons, both in the hashed
identity: the minute-stamped "BOARD SNAPSHOT (%Y-%m-%d %H:%M)" header rode
inside _snap_body, and each card line carries a drifting ai=$ cost. The
"unchanged" branch could only ever match two turns inside the same minute
on a board where no worker spent a cent. Old tool results, the thing card
chat-henry-kontext-pruning set out to prune, were 9k of those 171k.

    py -3.12 ops/tests/test_snapshot_delta.py
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from cells.copilot.chat import copilot                                 # noqa: E402

fails = []


def ok(cond, what):
    print(("  ok    " if cond else "  FAIL  ") + what)
    if not cond:
        fails.append(what)


print("snapshot delta seam")
# a board of realistic size (the live one is 10-15 KB): a two-card board
# would make one moved card >60% of the text, where falling back to the full
# snapshot is the DESIGNED behaviour, not the case under test
BOARD = ("POLICY: {}\nCAPACITY: WIP 2/4, headroom 2 cards\nCARDS:\n"
         "- id=a1 repo=helmdeck branch=x lane=build status=running prio=- due=- mode=- ai=$0.12 task=fix login\n"
         "- id=b2 repo=helmdeck branch=y lane=review status=needs_you prio=- due=- mode=- ai=$1.50 task=new icon\n"
         + "".join("- id=c%d repo=helmdeck branch=z%d lane=backlog status=idle prio=- due=- mode=- ai=$0.00 task=card %d\n" % (i, i, i)
                   for i in range(10))
         + "PROCESSES:\n- id=p1 status=running client=- due=- steps=1/3 done request=ship it\n")
h0, l0 = copilot._snap_stable(BOARD)
h1, _ = copilot._snap_stable(BOARD)
ok(h0 == h1, "same board -> same identity")
drift = BOARD.replace("ai=$0.12", "ai=$0.97")
h2, _ = copilot._snap_stable(drift)
ok(h2 == h0, "a worker spending money does NOT change the identity (cost drift stripped)")
moved = BOARD.replace("lane=build status=running", "lane=review status=needs_you")
h3, l3 = copilot._snap_stable(moved)
ok(h3 != h0, "a card moving lanes DOES change the identity")
delta = copilot._snapshot_delta(l0, l3)
ok(delta.count("\n") == 1 and delta.startswith("- ") and "\n+ " in delta and "a1" in delta and "b2" not in delta,
   "the delta is exactly the moved card's old and new line, nothing else:\n        %s" % delta.replace("\n", "\n        "))
ok(copilot._snapshot_delta(l0, copilot._snap_stable(BOARD + "\n\n")[1]) == "",
   "whitespace-only change -> no delta (caller falls back to the full snapshot)")
ok(copilot._snapshot_delta(l0, copilot._snap_stable("ENTIRELY\nDIFFERENT\nBOARD\nTEXT\nHERE\nNOW\n")[1]) == "",
   "a rewrite bigger than ~60% of the snapshot -> no delta (full one is cheaper to read)")

src = inspect.getsource(copilot.chat)
ok("_snap_body = _snapshot()" in src and "_snap_body = snapshot_block" not in src,
   "chat() hashes the board BODY, never the minute-stamped header (the 2026-09-15 defect)")
ok("_snap_seen[skey] = (_snap_hash, _snap_when, _snap_lines)" in src,
   "the seen entry carries the lines a later delta diffs against")
ok("_ovl_seen.get(skey) == _ovl_hash" in src and "_ovl_hash = None" in src,
   "the project overlay rides once per continuous session, hash initialised before the try")

print("\n" + ("FAIL (%d)" % len(fails) if fails else "snapshot-delta: all pinned - PASS"))
sys.exit(1 if fails else 0)
