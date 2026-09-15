# -*- coding: utf-8 -*-
"""Export the db to ONE JSON document - the proof of the owner decree that
harness config and records are exportable ("wenn es hier bleibt erreicht es
niemanden"; state-into-db phase A, 2026-09-12).

    py -3.12 ops/tools/db_export.py --all                 > export.json
    py -3.12 ops/tools/db_export.py --account owner       > owner.json
    py -3.12 ops/tools/db_export.py --project <id>        > project.json
    py -3.12 ops/tools/db_export.py --all --with-secrets  # NOT masked - for a
                                                          # same-owner move only

Every table becomes {"table": [row, ...]} with the row as a column dict; blob
columns (`data`, `json`, `value`) are emitted as parsed JSON so the file is
readable and diffable. SECRETS ARE MASKED by default: any key named token,
sk, secret, api_token, password, key_b64, pw or th, or ending in
_token/_secret, at any depth, becomes "***". Generated (virtual) columns are
skipped - they are derived from `data` and db_import recomputes them.

--account keeps only rows scoped to that account (boards.owner, user_config.
user, memory.account, and later chat/auth tables); --project keeps rows scoped
to that project (tracks.project_id, project_config.project, projects.id).
Workspace-level tables (policy_doc, workspace_config, process_template,
schema_migrations) ride along in every mode - they ARE the exportable
harness config.

Read-only. Prints to stdout; redirect it."""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# pw/th (state-into-db ledger step 13): the users table's pbkdf2 password
# hash and a device token's sha256 hash - never in the clear even masked-off,
# now that accounts are a db table this export walks like any other.
_SECRET_KEY = re.compile(r"^(token|sk|secret|api_token|password|key_b64|pw|th)$|_(token|secret)$")
_BLOB_COLS = ("data", "json", "value", "content")
_SKIP_TABLES = ("sqlite_sequence",)
# scope column per table: which column carries the account / the project
_ACCOUNT_COL = {"boards": "owner", "user_config": "user", "memory": "account",
                "chat": "account", "auth_sessions": "account", "devices": "account"}
_PROJECT_COL = {"tracks": "project_id", "project_config": "project", "projects": "id"}


def mask(v):
    if isinstance(v, dict):
        return {k: ("***" if _SECRET_KEY.search(str(k)) and isinstance(val, str) and val
                    else mask(val)) for k, val in v.items()}
    if isinstance(v, list):
        return [mask(x) for x in v]
    return v


def _parse(col, v):
    if col in _BLOB_COLS and isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def export(account=None, project=None, secrets=False):
    from spine.storage import db
    c = db.conn()
    out = {"_meta": {"schema": db.schema_head(), "user_version":
                     c.execute("PRAGMA user_version").fetchone()[0],
                     "account": account, "project": project, "masked": not secrets}}
    tables = [r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    for t in tables:
        if t in _SKIP_TABLES:
            continue
        # PRAGMA table_xinfo: hidden=2/3 marks generated columns - skip them
        cols = [r[1] for r in c.execute("PRAGMA table_xinfo(%s)" % t) if r[6] == 0]
        where, args = "", ()
        if account and t in _ACCOUNT_COL:
            where, args = " WHERE %s=?" % _ACCOUNT_COL[t], (account,)
        elif project and t in _PROJECT_COL:
            where, args = " WHERE %s=?" % _PROJECT_COL[t], (project,)
        elif (account or project) and t in ("tracks", "boards", "user_config", "memory",
                                            "project_config", "projects", "events"):
            continue   # scoped export: a table scoped to the OTHER axis is left out
        rows = c.execute("SELECT %s FROM %s%s" % (",".join(cols), t, where), args).fetchall()
        recs = [{col: _parse(col, v) for col, v in zip(cols, r)} for r in rows]
        out[t] = recs if secrets else mask(recs)
    return out


def main(argv):
    if "-h" in argv or "--help" in argv or not argv:
        print(__doc__)
        return 0
    account = argv[argv.index("--account") + 1] if "--account" in argv else None
    project = argv[argv.index("--project") + 1] if "--project" in argv else None
    doc = export(account, project, secrets="--with-secrets" in argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    json.dump(doc, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
