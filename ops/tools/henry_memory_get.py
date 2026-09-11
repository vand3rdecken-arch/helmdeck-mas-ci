# -*- coding: utf-8 -*-
"""Henry's memory-read tool (henry-memory-file-authority follow-up, 2026-09-11
owner decree: "no folder, ever - query the db directly").

Replaces the disposable-cache directory entirely: Henry's board turn digest
already carries the MEMORY index (copilot_memory.digest()); when a note in
that index looks relevant, he reads the FULL note by calling this script
through the one Bash pattern his settings allowlist, exactly like his
existing `board_state.py`/`loop_state.py` read tools - no Read/Write on any
memory path, no filesystem surface for a planted file to ever land on.

    py -3.12 ops/tools/henry_memory_get.py list
    py -3.12 ops/tools/henry_memory_get.py get <name>

Read-only by construction: this script has no write mode. The write path
stays the <memory-save>/<memory-delete> sentinel (copilot_memory.apply),
parsed from Henry's OWN turn output - a Bash call can never mutate memory."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def main(argv):
    from spine.storage import db
    if len(argv) < 2:
        print("usage: henry_memory_get.py list | get <name>", file=sys.stderr)
        return 2
    cmd = argv[1]
    notes = db.memory_all()
    if cmd == "list":
        for name in sorted(notes):
            if name != "MEMORY":
                print(name)
        return 0
    if cmd == "get":
        if len(argv) < 3:
            print("usage: henry_memory_get.py get <name>", file=sys.stderr)
            return 2
        row = notes.get(argv[2])
        if not row:
            print("no such note: %s" % argv[2], file=sys.stderr)
            return 1
        print(row.get("content") or "")
        return 0
    print("unknown command: %s" % cmd, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
