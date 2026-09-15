# -*- coding: utf-8 -*-
"""Henry's on-demand brief sections (card chat-henry-kontext-pruning, part 2,
2026-09-15). Same pattern as henry_memory_get.py: the brief's always-loaded
CORE carries a one-line index of these sections; the full text is read
exactly when its trigger fires, through the one Bash pattern the copilot
settings allowlist. Measured before the split: the rendered brief was
36.8k chars of a 58.8k-token fixed base on every spawn - most of it verb
prose and pipeline/grilling/planning discipline a given turn never needs.

    py -3.12 ops/tools/henry_brief_get.py list
    py -3.12 ops/tools/henry_brief_get.py get <name>

Read-only by construction. The sections live next to the brief, in
cells/copilot/harness/agents/board-copilot.d/<name>.md, so they ship with
every bundle the brief ships with (cells/**/*.md) and are versioned with it."""
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
SECTIONS = os.path.join(ROOT, "cells", "copilot", "harness", "agents", "board-copilot.d")
_NAME = re.compile(r"^[a-z][a-z0-9-]{0,40}$")


def main(argv):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                            # noqa: BLE001
        pass
    cmd = argv[1] if len(argv) > 1 else "list"
    if cmd == "list":
        for fn in sorted(os.listdir(SECTIONS)):
            if fn.endswith(".md"):
                with open(os.path.join(SECTIONS, fn), encoding="utf-8") as f:
                    print("%-10s %s" % (fn[:-3], f.readline().strip()[:100]))
        return 0
    if cmd == "get" and len(argv) > 2 and _NAME.match(argv[2]):
        p = os.path.join(SECTIONS, argv[2] + ".md")
        if not os.path.isfile(p):
            print("no such section: %s (try: list)" % argv[2], file=sys.stderr)
            return 1
        with open(p, encoding="utf-8") as f:
            sys.stdout.write(f.read())
        return 0
    print("usage: henry_brief_get.py list | get <name>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
