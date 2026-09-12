# -*- coding: utf-8 -*-
"""Import a db_export.py document into the db - the other half of the
exportability decree (state-into-db phase A, 2026-09-12).

    py -3.12 ops/tools/db_import.py export.json            # into an EMPTY db only
    py -3.12 ops/tools/db_import.py export.json --merge    # INSERT OR IGNORE into a live db

Refuses a non-empty db without --merge: a restore onto live data is a decision,
not a default. Refuses a document whose schema is NEWER than this code (the
ledger would not know the columns). A document from an OLDER schema is fine -
init() runs the ledger first, then rows land in the upgraded shape.

Masked values ("***") are NEVER written: a row whose blob contains a masked
secret has that key dropped, so an import cannot overwrite a real token with
three asterisks. Blob columns are re-serialised with json.dumps; generated
columns are recomputed by SQLite from `data`."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_BLOB_COLS = ("data", "json", "value", "content")


def _unmask(v):
    if isinstance(v, dict):
        return {k: _unmask(val) for k, val in v.items() if val != "***"}
    if isinstance(v, list):
        return [_unmask(x) for x in v]
    return v


def _empty(c):
    for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'"):
        if t in ("sqlite_sequence", "schema_migrations"):
            continue
        if c.execute("SELECT 1 FROM %s LIMIT 1" % t).fetchone():
            return False
    return True


def import_doc(doc, merge=False):
    from spine.storage import db
    db.init()
    c = db.conn()
    meta = doc.get("_meta") or {}
    if (meta.get("schema") or 0) > db.schema_head():
        raise SystemExit("db_import: document schema %s is newer than this code (%s)"
                         % (meta.get("schema"), db.schema_head()))
    if not merge and not _empty(c):
        raise SystemExit("db_import: db is not empty - pass --merge to INSERT OR IGNORE into it")
    verb = "INSERT OR IGNORE" if merge else "INSERT"
    counts = {}
    with c:
        for t, rows in doc.items():
            if t.startswith("_") or t == "schema_migrations" or not isinstance(rows, list):
                continue
            cols = [r[1] for r in c.execute("PRAGMA table_xinfo(%s)" % t) if r[6] == 0]
            if not cols:
                print("db_import: unknown table %s skipped" % t)
                continue
            n = 0
            for row in rows:
                row = _unmask(row)
                vals = []
                for col in cols:
                    v = row.get(col)
                    if col in _BLOB_COLS and not isinstance(v, str) and v is not None:
                        v = json.dumps(v, ensure_ascii=False)
                    vals.append(v)
                c.execute("%s INTO %s(%s) VALUES(%s)" % (verb, t, ",".join(cols),
                                                         ",".join("?" * len(cols))), vals)
                n += 1
            counts[t] = n
    db.bump()
    return counts


def main(argv):
    if not argv or "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    path = [a for a in argv if not a.startswith("--")][0]
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    counts = import_doc(doc, merge="--merge" in argv)
    for t, n in sorted(counts.items()):
        print("%-20s %d" % (t, n))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
