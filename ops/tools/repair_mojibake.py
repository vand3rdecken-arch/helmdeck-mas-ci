# -*- coding: utf-8 -*-
"""One-time repair: card task/description texts that were stored DOUBLE-ENCODED
(UTF-8 bytes read as latin-1 and re-encoded - "prÃ¼fen" for "prüfen").

Measured 2026-09-13 in the conversation list: 16 of the tracks imported from
the 2026-08 file era carry it; the chat table has none. Only the two mutable
text fields of a track are touched; the timeline (append-only transcript) is
left as it is. Idempotent: a repaired row no longer round-trips, so a second
run changes nothing.

    py -3.12 ops/tools/repair_mojibake.py            # dry run: list
    py -3.12 ops/tools/repair_mojibake.py --apply    # rewrite
"""
import json
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB = os.path.join(ROOT, "daemon", "helmdeck.db")


def fix(s):
    """The original text if `s` is a double-encoded UTF-8 string, else None."""
    if not isinstance(s, str) or ("Ã" not in s and "Â" not in s):
        return None
    try:
        out = s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None
    return out if out != s else None


def main():
    apply = "--apply" in sys.argv
    c = sqlite3.connect(DB, timeout=15)
    rows = c.execute("SELECT id, data FROM tracks").fetchall()
    touched = 0
    for tid, data in rows:
        j = json.loads(data)
        changed = False
        for k in ("task", "description"):
            f = fix(j.get(k))
            if f is not None:
                j[k] = f
                changed = True
        if changed:
            touched += 1
            print(("fix " if apply else "would fix ") + tid + ": " + (j.get("task") or "")[:60].replace("\n", " "))
            if apply:
                c.execute("UPDATE tracks SET data=? WHERE id=?", (json.dumps(j, ensure_ascii=False), tid))
    if apply:
        c.commit()
    print("%s %d track(s)" % ("repaired" if apply else "affected", touched))


if __name__ == "__main__":
    main()
