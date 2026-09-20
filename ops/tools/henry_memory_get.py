# -*- coding: utf-8 -*-
"""Henry's memory-read tool (henry-memory-file-authority follow-up, 2026-09-11
owner decree: "no folder, ever - query the db directly").

Replaces the disposable-cache directory entirely: Henry's board turn digest
already carries the MEMORY index (copilot_memory.digest()); when a note in
that index looks relevant, he reads the FULL note by calling this script
through the one Bash pattern his settings allowlist, exactly like his
existing `board_state.py`/`loop_state.py` read tools - no Read/Write on any
memory path, no filesystem surface for a planted file to ever land on.

    py -3.12 ops/tools/henry_memory_get.py list          # the DERIVED index, both stores
    py -3.12 ops/tools/henry_memory_get.py get <name>
    py -3.12 ops/tools/henry_memory_get.py find <term> [term ...]   # notes carrying ALL terms, in full

`find` is the PM planner's fetch-as-needed path (2026-09-12): the plan turn
carries only the INDEX; before it asks the owner anything it searches the
notes for the answer (the timeline question was answered in
helmdeck-launch-planung while the planner kept re-asking it).

Read-only by construction: this script has no write mode. The write path
stays the <memory-save>/<memory-delete> sentinel (copilot_memory.apply),
parsed from Henry's OWN turn output - a Bash call can never mutate memory."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def main(argv):
    from cells.copilot.chat import copilot_memory as mem
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if len(argv) < 2:
        print("usage: henry_memory_get.py list | get <name> | find <terms...>", file=sys.stderr)
        return 2
    cmd = argv[1]
    # BOTH STORES, one view (owner decree 2026-09-20: "alle Infos zu Claude
    # und db sollten zugaenglich sein"). Henry's db is the store of record;
    # the claude CLI keeps its own auto-memory directory and the two held
    # CONTRADICTING notes about Jev with nothing reading across them. Merged
    # here, db wins a name clash, the CLI twin is flagged rather than hidden.
    notes = mem.all_notes()
    if cmd in ("list", "index"):
        # the index is DERIVED, always complete. The hand-maintained "MEMORY"
        # note it replaces had been frozen since 2026-09-15 (every rewrite
        # rejected for length, silently) - that is why this is computed.
        print(mem.digest().strip() or "keine Notizen")
        return 0
    if cmd == "get":
        if len(argv) < 3:
            print("usage: henry_memory_get.py get <name>", file=sys.stderr)
            return 2
        want = argv[2]
        if want == "MEMORY":
            print(mem.digest().strip() or "keine Notizen")
            return 0
        row = notes.get(want)
        if not row:
            near = [n for n in notes if want.casefold() in n.casefold()][:5]
            print("no such note: %s%s" % (want, ("  (aehnlich: %s)" % ", ".join(near)) if near else ""),
                  file=sys.stderr)
            return 1
        print("[%s | %s]" % (row.get("source") or "db", (row.get("updated_at") or "")[:10]))
        print(row.get("content") or "")
        return 0
    if cmd == "find":
        terms = [t.casefold() for t in argv[2:] if t.strip()]
        if not terms:
            print("usage: henry_memory_get.py find <term> [term ...]", file=sys.stderr)
            return 2
        hits = find_notes(notes, terms)
        if not hits:
            print("no note carries ALL of: %s" % " ".join(terms))
            return 0
        print("%d note(s) match %s:" % (len(hits), " ".join(terms)))
        for name, row in hits[:8]:
            print("\n=== %s (%s | %s)\n%s"
                  % (name, row.get("source") or "db", (row.get("updated_at") or "")[:10],
                     (row.get("content") or "").strip()[:2500]))
        return 0
    print("unknown command: %s" % cmd, file=sys.stderr)
    return 2


def find_notes(notes, terms):
    """[(name, row)] whose name or content carries EVERY term (casefold
    substring), newest first. Pure over the dict, so tests feed fixtures."""
    hits = []
    for name, row in notes.items():
        if name == "MEMORY":
            continue
        body = (name + " " + (row.get("content") or "")).casefold()
        if all(t in body for t in terms):
            hits.append((name, row))
    hits.sort(key=lambda nr: nr[1].get("updated_at") or "", reverse=True)
    return hits


if __name__ == "__main__":
    sys.exit(main(sys.argv))
