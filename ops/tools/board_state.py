# -*- coding: utf-8 -*-
"""Print the board as text - the ON-DEMAND half of Henry's board context.

Why this exists (measured 2026-09-02). The full board snapshot used to ride
inside EVERY chat turn: 83,488 chars / ~23k tokens of uncached input the model
re-read before answering anything at all, which was the bulk of the ~21s warm
turn. Paseo - the reference this harness is ported from - sends only the user's
text and keeps context in the cached system prompt plus TOOLS the agent calls
when it needs them (packages/server/src/server/agent/providers/claude/agent.ts,
the user message is one `content.push({type:"text", text: prompt})`).

So the split is: a chat turn injects the LIVE board (open cards, processes,
policy, debt ids), and the expensive history - finished/archived cards and the
full debt prose, 65% of the old payload - is fetched by running this when a
question is actually about it. Henry runs it himself; it is not wired into the
turn.

There is NO second implementation of the board text here: this calls
cells.copilot.copilot._snapshot(full=True), the same one owner the chat turn
uses, so the two can never drift.

    py -3.12 ops/tools/board_state.py           # live board (what a turn sees)
    py -3.12 ops/tools/board_state.py --full    # + finished/archived + debt text
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))


def main(argv):
    full = "--full" in argv or "-f" in argv
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    # UTF-8 or this tool is useless on Windows: card titles and outcomes carry
    # umlauts and arrows (U+2192), and a bare python.exe stdout is cp1252 - the
    # --full path died on UnicodeEncodeError the first time it was run, which is
    # exactly the trap copilot.py already documents for the driver's own pipes.
    # errors="replace" over a crash: a mangled glyph still answers the question.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    from cells.copilot.copilot import _snapshot
    out = _snapshot(full=full)
    # stdout is the product - print nothing else, this is read by an agent.
    sys.stdout.write(out + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
