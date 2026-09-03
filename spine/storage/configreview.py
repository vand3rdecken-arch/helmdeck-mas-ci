# -*- coding: utf-8 -*-
"""WHAT IS ACTUALLY IN THE STORE - the review half of "policy is data".

Every other config surface in this daemon answers the RESOLVED question: what
value applies here, and which layer did it come from. That is the right question
for someone changing a setting, and it is the wrong question for someone auditing
one, because a resolved answer cannot distinguish "nothing was ever set" from
"a row exists and something above it wins". This module answers the other one:
which rows physically exist, in which table, for which scope.

It is a READER. It resolves nothing, merges nothing and writes nothing - the
chain already has exactly one owner in projectconfig, and a second resolver here
would be the drift this whole layer was built to end.

THREE THINGS IT SHOWS THAT NOTHING ELSE DOES
--------------------------------------------
1. ROWS FOR PROJECTS YOU ARE NOT LOOKING AT. The harness screen resolves one
   project at a time, so a value set against some other repo is invisible there -
   and "I set that months ago and forgot where" is precisely the question a
   review view exists to answer. Every project_config row is listed, with the
   selected project marked rather than filtered.

2. UNDECLARED ROWS. projectconfig.stored() deliberately filters to keys some
   table still declares, so a knob that was retired leaves a row nothing serves.
   That row is not garbage - it is a value the owner set and the daemon silently
   stopped honouring - so it is listed here with `declared: false` instead of
   being hidden. This is the one place in the system where an orphaned row is
   visible at all.

3. THE BOARD SCOPE'S REAL STORE. Board column labels are the one board-scoped
   value there is, and they live in the boards table, not in settings.json.
   Listing them beside the project rows is what makes the scope badges checkable
   against reality rather than taken on trust.

NO SECRETS PASS THROUGH HERE. The tables this reads hold behaviour rules and
column labels; it never echoes settings.json, which is the document that holds
tokens (GET /settings already serves that blob and is owner-gated for it). Adding
a settings.json section to this view would quietly turn an audit screen into a
credential dump, so the file layer is reported as a COUNT and a key list only -
never as values.
"""


def _declared():
    """{path: declaring-table} - projectconfig's own whitelist, not a copy."""
    try:
        from spine.storage import projectconfig
        return projectconfig.overridable()
    except Exception:                                        # noqa: BLE001
        return {}


def project_rows(selected=""):
    """Every row in project_config, newest table order, with two derived flags.

    `declared` is whether some table still declares the key (see 2 above);
    `selected` is whether the row belongs to the project the screen is showing.
    Both are DERIVED here at read time from the live whitelist and the caller's
    argument - neither is stored on the row, which is what keeps this honest
    when a key is retired or the selection changes."""
    from spine.storage import db
    declared = _declared()
    out = []
    for project in sorted(db.project_config_projects()):
        for key, value in sorted(db.project_config_get(project).items()):
            out.append({"project": project, "key": key, "value": value,
                        "declared": key in declared,
                        "selected": bool(selected) and project == selected})
    return out


def board_rows():
    """Every board row, reduced to the board-scoped VALUE it carries: its
    columns' labels. An empty label is reported as empty rather than resolved to
    the station name - that resolution is the app's (boards.py invariant 1), and
    doing it here would make an unlabelled column look like a stored one."""
    from spine.storage import db
    out = []
    try:
        rows = db.boards_all()
    except Exception:                                        # noqa: BLE001
        return out
    for b in rows:
        out.append({
            "id": b.get("id"), "name": b.get("name"),
            "owner": b.get("owner", ""),
            "columns": [{"station": c.get("station"), "label": c.get("label") or ""}
                        for c in (b.get("columns") or [])],
        })
    return out


def legacy_rows():
    """Pre-rules global keys still sitting in settings.json unadopted, with the
    reason where the daemon refused to move one. Normally empty - a non-empty
    list means either the daemon has not restarted since the rules shipped, or a
    value failed its own rule's validator and is being kept rather than dropped."""
    try:
        from spine.storage import legacypolicy
        return [{"key": r["key"], "path": r["path"], "refuse": r["refuse"]}
                for r in legacypolicy.pending()]
    except Exception:                                        # noqa: BLE001
        return []


def review(selected=""):
    """The whole picture, one call. `selected` is the project the screen is
    resolving, used only to MARK rows - never to filter them."""
    return {"projectRows": project_rows(selected),
            "boardRows": board_rows(),
            "legacyRows": legacy_rows()}


__all__ = ["project_rows", "board_rows", "legacy_rows", "review"]
