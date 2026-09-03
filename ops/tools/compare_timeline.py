# -*- coding: utf-8 -*-
"""Card 2 dual-write verifier (ops/docs/multi-engine-build-plan.md).

Compares the OLD reader (claude_sessions.read_transcript_live - re-parses
Claude Code's private ~/.claude/projects/**.jsonl) against the NEW event-time
store (timeline_store.read - folded live by drivers.py's _ClaudeSession as
each block completes) for one card, and reports whether they agree.

This is the gate for CUTTING OVER /transcript to the new store: the build
plan's own verify line is "diff EMPTY on real turns covering text, thinking,
tools (all 4 states), todos, usage, a <helmdeck-ask> question, a cancel" -
run this after dispatching turns that exercise those, on a card whose turn
has already ENDED (a running turn's streaming partial has no store
equivalent by design - see _fold_timeline's docstring).

Comparison is on SEMANTIC fields only - ts/ta are excluded because the two
sources timestamp differently on purpose (OLD reads a persisted-file
timestamp; NEW stamps at live-fold time, which is the more literal "event
time" - see _fold_timeline's docstring) and that difference is not a bug.
A documented, NAMED set of step kinds is also excluded because they are a
deliberate Card 2 scope cut (envelope re-attribution for plain role=user
text - command labels, harness-tag notes, notification labels, compaction
dedup) - printed separately as "accepted differences", never silently
dropped (CLAUDE.md: no silent caps).

Usage:
    py -3.12 ops/tools/compare_timeline.py <card-id>
    py -3.12 ops/tools/compare_timeline.py --last     # most recently active card
                                                   # with a timeline.jsonl
"""
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from spine.agent import claude_sessions, timeline_store  # noqa: E402
from cells.engineer.cards import sessions  # noqa: E402

# Step kinds the NEW store does not yet produce for plain role=user text
# (documented scope cut in drivers.py's _fold_timeline docstring). A "system"
# step from the OLD reader is EXPECTED to have no counterpart yet.
_ACCEPTED_OLD_ONLY_KINDS = {"system", "compaction"}

# Fields compared per kind - ts/ta and the legacy running/abandoned aliases
# are excluded (running is redundant with status; ts/ta differ on purpose).
_COMPARE_FIELDS = {
    "text": ("role", "kind", "text"),
    "thinking": ("role", "kind", "text"),
    "tool": ("role", "kind", "tool", "label", "text", "result", "ok", "status", "error"),
    "todos": ("kind", "todos"),
    "plan": ("kind", "text"),
    # tokOut deliberately excluded - MEASURED live 2026-08-24 (see drivers.py's
    # _fold_timeline docstring): a message's live usage.output_tokens can read
    # far lower than the same message's settled value in the persisted .jsonl
    # (2 live vs. 152 in the file, same message id, no later live frame ever
    # carries the correction). tokIn/cacheRead/cacheWrite/ctx are proven
    # identical live vs. file and stay compared - ctx is the only usage field
    # econ.py's context meter actually reads.
    "usage": ("kind", "tokIn", "cacheRead", "cacheWrite", "ctx"),
    "turn": ("kind", "event"),
}


def _norm(step):
    kind = step.get("kind")
    fields = _COMPARE_FIELDS.get(kind)
    if fields is None:
        return dict(step)   # unknown kind - compare everything, don't hide it
    return {k: step.get(k) for k in fields}


def _pick_last():
    """Most recently touched card whose run_dir has a timeline.jsonl - i.e.
    one that has actually run a turn since Card 2 landed."""
    cands = []
    for t in sessions.list_tracks():
        rd = t.get("run_dir") or ""
        p = os.path.join(rd, timeline_store.FILENAME)
        if rd and os.path.exists(p):
            cands.append((os.path.getmtime(p), t))
    if not cands:
        return None
    cands.sort(key=lambda x: x[0], reverse=True)
    return cands[0][1]


def compare(tid):
    t = sessions.get_track(tid)
    if not t:
        print("no such card: %s" % tid)
        return 2
    old_all = claude_sessions.read_transcript_live(t)
    new_all = timeline_store.read(t.get("run_dir") or "")

    old_accepted = [s for s in old_all if s.get("kind") in _ACCEPTED_OLD_ONLY_KINDS]
    old_comparable = [s for s in old_all if s.get("kind") not in _ACCEPTED_OLD_ONLY_KINDS]

    print("card %s - OLD %d steps (%d accepted-scope-cut, %d comparable), NEW %d steps"
          % (tid, len(old_all), len(old_accepted), len(old_comparable), len(new_all)))

    if old_accepted:
        print("\naccepted differences (documented Card 2 scope cut, not failures):")
        for s in old_accepted:
            print("  old-only  kind=%-10s text=%r" % (s.get("kind"), (s.get("text") or "")[:60]))

    diffs = []
    n = max(len(old_comparable), len(new_all))
    for i in range(n):
        o = old_comparable[i] if i < len(old_comparable) else None
        w = new_all[i] if i < len(new_all) else None
        if o is None:
            diffs.append((i, "NEW-only", None, w))
            continue
        if w is None:
            diffs.append((i, "OLD-only", o, None))
            continue
        no, nw = _norm(o), _norm(w)
        if no != nw:
            diffs.append((i, "MISMATCH", no, nw))

    if diffs:
        print("\n%d real diff(s):" % len(diffs))
        for i, kind, o, w in diffs:
            print("  [%d] %s" % (i, kind))
            if o is not None:
                print("      OLD: %s" % o)
            if w is not None:
                print("      NEW: %s" % w)
        print("\nFAIL - dual-write is NOT clean, do not cut over")
        return 1

    print("\nPASS - dual-write is clean for this card")
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    if sys.argv[1] == "--last":
        t = _pick_last()
        if not t:
            print("no card has a timeline.jsonl yet - dispatch one first")
            return 2
        tid = t["id"]
    else:
        tid = sys.argv[1]
    return compare(tid)


if __name__ == "__main__":
    sys.exit(main())
