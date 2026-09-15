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
# voice_model. Measured over the last 8 compaction windows: zero board calls
# on haiku, so "stay-fast" guarded a model never used, and a 1M voice model
# would have silently lifted the mark to 800k. Same value as before (168k =
# haiku window - headroom), so nothing moved the day this landed.
mark, why = copilot._compact_mark({"ctx_window": 1_000_000})
ok(why == "cost-line", "a 1M session is governed by the cost line, not overflow")
ok(mark == copilot.COMPACT_COST_LINE == 168_000,
   "the mark IS the cost line, and it equals the old haiku-derived value (%d)" % mark)
ok(mark == turnopts.model_window("claude-haiku-4-5") - turnopts.CTX_HEADROOM,
   "...which is still haiku's window minus headroom - documented, not derived at runtime")
ok(HENRY_CTX >= mark,
   "Henry at 615,889 compacts (old overflow-only rule: %s)" % (HENRY_CTX >= 800_000))

# a small-window session must keep the overflow guard - stay-fast would be
# LOOSER there (168k vs 160k) and must not be allowed to relax the wall.
small, why_small = copilot._compact_mark({"ctx_window": 200_000})
ok(why_small == "overflow" and small == 160_000,
   "a 200k session keeps the stricter overflow guard (%d, %s)" % (small, why_small))

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
ok(src.index("_save_memory(user, sid)") < src.index('p.stdin.write("/compact")'),
   "memory is written BEFORE the history is compacted")
ok('"--permission-mode", henry_pmode()' in src,
   "the save turn runs with hands (acceptEdits), not in plan mode")

print("\n%s (%d checks, %d failed)" % ("PASS" if not fails else "FAIL", 13, len(fails)))
sys.exit(1 if fails else 0)
