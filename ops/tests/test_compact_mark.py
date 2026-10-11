# -*- coding: utf-8 -*-
"""Compaction must watch the line that actually costs, not only overflow.

MEASURED 2026-08-30: Henry's board session stood at 615,889 tokens of a 1M
window - 61.6% full. The only compaction trigger was 80% of the window
(800,000), so it never fired. Meanwhile the session had been too large for the
fast model (Haiku, 200k window) since roughly 168,000 tokens, i.e. since 17%
fill. The guard watched a wall the session was nowhere near, while the line that
costs speed and plan-share had been crossed four times earlier and unwatched.

Owner decree the same day ("Kompaktieren und ins Speicher"): compact against the
fast-model line, and write what matters to disk BEFORE the history is verdichtet
- so shrinking the live context is not the same as forgetting.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from cells.copilot.chat import copilot                                 # noqa: E402
from cells.copilot.chat import copilot_memory                     # noqa: E402
from spine.agent import turnopts                                  # noqa: E402

HENRY_CTX = 615_889
fails = []


def ok(cond, what):
    print(("  ok    " if cond else "  FAIL  ") + what)
    if not cond:
        fails.append(what)


print("compaction mark (copilot)")

# 2026-09-15: the line is a NUMBER (COMPACT_COST_LINE), decoupled from
# voice_model (a 1M voice model must not lift the mark to 800k). Owner
# 2026-10-07 set it to 100k (50% of 200k, Gemini CLI's default).
mark, why = copilot._compact_mark({"ctx_window": 1_000_000})
ok(why == "cost-line", "a 1M session is governed by the cost line, not overflow")
ok(mark == copilot.COMPACT_COST_LINE == 100_000,
   "the mark IS the cost line (%d)" % mark)
ok(HENRY_CTX >= mark,
   "Henry at 615,889 compacts (old overflow-only rule: %s)" % (HENRY_CTX >= 800_000))

# a 200k session: the cost line (100k) is stricter than the overflow wall
# (160k), so it governs; the wall is only the binding one under 125k windows.
small, why_small = copilot._compact_mark({"ctx_window": 200_000})
ok(why_small == "cost-line" and small == 100_000,
   "a 200k session is governed by the stricter cost line (%d, %s)" % (small, why_small))

# token-burn-hardening Karte D companion (2026-09-11): _compact_mark takes no
# history, so it must judge the window it is HANDED, not one cached from
# before a reclassification - the exact contract sessions._maybe_compact's own
# re-evaluation now depends on (see test_card_compact_interrupt.py, card
# 20260910-134430, where a stale-window read let a queued retry evaporate).
# Same window floor both lanes share: sessions._CTX_WINDOW.
from cells.engineer.cards import sessions as _sessions            # noqa: E402
ok(copilot._compact_mark({})[0] == copilot._compact_mark(
    {"ctx_window": _sessions._CTX_WINDOW})[0],
   "an absent ctx_window floors to the SAME shared default as an explicit one "
   "(no separate, driftable default in the copilot lane)")

# the memory surface (henry-memory-db-authority, DB-authoritative, no
# filesystem surface at all - see cells/copilot/chat/copilot_memory.py and
# ops/tools/henry_memory_get.py)
ok(not hasattr(copilot_memory, "MEMORY_DIR"),
   "memory has no directory constant left to point at - the db is the only store")
ok(isinstance(copilot_memory.digest(), str),
   "the digest is always a string, even with no memory yet")
ok("<memory-save" in copilot_memory.SAVE_PROMPT,
   "the save prompt teaches the sentinel format, not a file-write instruction")
ok("MEMORY" in copilot_memory.SAVE_PROMPT,
   "the save prompt maintains the index note, not just individual facts")

# ordering is the whole point: save runs BEFORE /compact
src = open(os.path.join(os.path.dirname(copilot.__file__), "copilot.py"),
           encoding="utf-8").read()
ok(src.index("_save_memory(user, sid)") < src.index('p.stdin.write("/compact "'),
   "memory is written BEFORE the history is compacted")
ok('"--permission-mode", henry_pmode()' in src,
   "the save turn runs with hands (acceptEdits), not in plan mode")

# 2026-10-11: an OWNER turn schedules at the cost line too. Commit a9a683bd
# (10.10) had lifted owner turns to the 0.8*window overflow wall on the
# assumption that agent turns compact first - measured the next day: a day
# with ZERO agent turns and 78 owner turns climbed 8.5k -> 797k (13k per
# turn re-read on every call) before the first compaction fired at 800k.
# Owner turns keep the lull (immediate=False); agent turns sit 15k lower.
import threading as _th                                           # noqa: E402
_spawned = []
_orig_thread, _orig_stats = _th.Thread, copilot._stats
try:
    _th.Thread = lambda *a, **k: _spawned.append(k.get("target")) or type(
        "T", (), {"start": lambda self: None})()
    copilot._stats = lambda: {"owner": {"ctx_tokens": 300_000, "ctx_window": 1_000_000, "turns": 10}}
    copilot._compacting.discard("owner")
    copilot._schedule_compact("owner", agent=False)
    ok(len(_spawned) == 1,
       "an owner turn at 300k of 1M (over the 100k line, under the 800k wall) schedules a compaction")
    copilot._compacting.discard("owner")
    copilot._stats = lambda: {"owner": {"ctx_tokens": 90_000, "ctx_window": 1_000_000, "turns": 10}}
    copilot._schedule_compact("owner", agent=False)
    ok(len(_spawned) == 1, "...and at 90k (under the line) it does not")
    copilot._schedule_compact("owner", agent=True)
    ok(len(_spawned) == 2, "an agent turn at 90k does (line minus COMPACT_NEAR_MARGIN)")
finally:
    _th.Thread, copilot._stats = _orig_thread, _orig_stats
    copilot._compacting.discard("owner")

print("\n%s (%d checks, %d failed)" % ("PASS" if not fails else "FAIL", 16, len(fails)))
sys.exit(1 if fails else 0)
