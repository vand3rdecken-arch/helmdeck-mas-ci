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
from spine.agent import turnopts                                  # noqa: E402

HENRY_CTX = 615_889
fails = []


def ok(cond, what):
    print(("  ok    " if cond else "  FAIL  ") + what)
    if not cond:
        fails.append(what)


print("compaction mark (copilot)")

mark, why = copilot._compact_mark({"ctx_window": 1_000_000})
ok(why == "stay-fast", "a 1M session is governed by the fast-model line, not overflow")
ok(mark == turnopts.model_window("claude-haiku-4-5") - turnopts.CTX_HEADROOM,
   "the mark is exactly what the fast model can still carry (%d)" % mark)
ok(mark < 800_000, "the new mark is below the old overflow mark")
ok(HENRY_CTX >= mark,
   "Henry at 615,889 now compacts (old rule: %s)" % (HENRY_CTX >= 800_000))

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

# the memory surface
ok(copilot.MEMORY_DIR.endswith("henry_memory"),
   "memory lives under the daemon's runtime dir, not the CLI's shared auto-memory")
ok("projects" not in copilot.MEMORY_DIR,
   "we never write into ~/.claude/projects/** (card-shares-the-operators-auto-memory)")
ok(isinstance(copilot._memory_digest(), str),
   "the digest is always a string, even with no memory yet")
ok("%s" in copilot._SAVE_PROMPT,
   "the save prompt names the directory it writes to")
ok("MEMORY.md" in copilot._SAVE_PROMPT,
   "the save prompt maintains the index, not just the notes")

# ordering is the whole point: save runs BEFORE /compact
src = open(os.path.join(os.path.dirname(copilot.__file__), "copilot.py"),
           encoding="utf-8").read()
ok(src.index("_save_memory(user, sid)") < src.index('p.stdin.write("/compact")'),
   "memory is written BEFORE the history is compacted")
ok('"--permission-mode", henry_pmode()' in src,
   "the save turn runs with hands (acceptEdits), not in plan mode")

print("\n%s (%d checks, %d failed)" % ("PASS" if not fails else "FAIL", 13, len(fails)))
sys.exit(1 if fails else 0)
