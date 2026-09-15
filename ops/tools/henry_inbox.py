# -*- coding: utf-8 -*-
"""What has the owner seen in the board chat since Henry's own last reply -
the ON-DEMAND half of the old "chat_since" block (card
chat-henry-kontext-pruning, "voller Umbau", 2026-09-15).

The board chat is ONE inbox transcript the owner reads top to bottom, but
THREE writers fill it: Henry's own turns (which his session already has),
the broker's follow-up reports (cls "pm"), and card mirrors (cls "card") -
plus dispatched action results (cls "act"/"error"). Only the first ever
reaches Henry's own resumed session; the other three used to ride every
turn automatically. So the owner could ask "ist es normal, dass es so lange
braucht?" right under a broker report Henry never saw, or return after being
away to a card that finished without Henry knowing - see BIAS TO ACTION
rule 3 in the brief: call THIS before answering, whenever you delegated work
that might have moved or the owner could be reacting to something you did
not write yourself.

There is NO second implementation of this text: it calls
cells.copilot.chat.copilot._inbox_since, the exact function/ordering the
removed inline block used.

    py -3.12 ops/tools/henry_inbox.py           # last 8 such entries
    py -3.12 ops/tools/henry_inbox.py 20         # last N entries

Read-only: nothing here writes."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                            # noqa: BLE001
        pass
    limit = 8
    if len(argv) > 1:
        try:
            limit = max(1, min(40, int(argv[1])))
        except ValueError:
            print("usage: henry_inbox.py [limit]", file=sys.stderr)
            return 2
    from cells.copilot.chat.copilot import _inbox_since, owner_name
    user = owner_name()
    if not user:
        print("no owner account found", file=sys.stderr)
        return 1
    out = _inbox_since(user, limit=limit)
    sys.stdout.write((out or "nichts Neues seit deiner letzten Antwort") + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
