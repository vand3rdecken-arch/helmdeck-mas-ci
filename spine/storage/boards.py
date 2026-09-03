# -*- coding: utf-8 -*-
"""BOARDS: saved views over the one card pool (accounts-boards-prd phase 2).

Jira's split, which the PRD adopts rather than reinvents: an admin defines the
WORKFLOW, a user defines a BOARD. Here the workflow is the harness itself
(backlog -> working -> gate -> review -> done, gate-before-review, merge rails)
and it stays law-in-code; a board only decides which columns to draw and which
station each one shows. Cards exist once, in `tracks` - a board never owns,
copies or hides a card from the daemon's point of view.

db.py holds the rows. This module owns everything that makes them safe to
expose on a route any authenticated role may call, mirroring userconfig.py:

  - the SHAPE. A column's `station` must be a real lane, checked against the
    Engineer cell's own LANES rather than a list restated here - a board that
    could name a station the lane machine rejects would render a column no
    card can ever be dropped into.
  - the BOUNDS. Self-scoped writes are unmetered by design (no capability to
    revoke), so the caps below are what stop an account from turning its board
    set into free storage on the owner's disk.
  - OWNERSHIP. `owner: ""` is the one shared default board: owner-role writes
    it, everybody reads it, nobody deletes it. `owner: <name>` is personal and
    private to that account. There is no third case, and no board is ever
    addressable by an account that does not own it (see `write`/`delete`).

TWO INVARIANTS WORTH NAMING

1. A COLUMN LABEL MAY BE EMPTY, and empty is not "no label" - it means "render
   this station's own name". That is what keeps a board translatable: a seeded
   default board with baked-in strings would show German columns to an English
   account, which is exactly the mix policy.lang exists to end. The migration
   below therefore copies `policy.lane_labels` ONLY where the owner actually
   renamed something, and leaves the rest empty for the app to translate.

2. THE OVERFLOW COLUMN IS THE CLIENT'S, AND IT IS DERIVED. This module does
   NOT force a board to cover every station, because forcing it would mean
   silently editing a layout the user asked for. Instead the app compares the
   board's stations against the stations its visible cards are actually IN and
   appends a column for each uncovered station that has cards - so a card can
   never become invisible on a board that claims to show it, and the extra
   column disappears by itself when the last card leaves. Derived at render
   time from both live sets, never stored, never a flag: the no-monkey-patches
   law applied to a view.

WHY BOARDS JOIN THE RENAME GUARD: `owner` is an account NAME, for the same
reason user_config rows key on one (userconfig.py's docstring argues it out and
names `boards.owner` as the phase-2 case). `rename_block_reason` there now
counts boards too, so a rename that would orphan a user's whole board set is
refused rather than half-cascaded.
"""
import secrets

# The one shared board. A fixed id, not a minted one: every client must be able
# to name it without first looking it up, and the seed has to be idempotent
# across daemon restarts (db.board_insert_absent keys on exactly this).
DEFAULT_ID = "default"
DEFAULT_NAME = "Board"

MAX_COLUMNS = 12
MAX_BOARDS_PER_USER = 20
MAX_NAME = 60
MAX_LABEL = 40


def stations():
    """The stations a column may show, read from the Engineer cell's own lane
    tuple. DERIVED, not restated: the workflow is that cell's law (PRD section
    3, "no per-user WORKFLOW"), and a copy here would drift the day a lane is
    added and let a board offer a column the lane machine would refuse to move
    a card into. Lazy import for the same cycle-free reason db.py uses one."""
    from cells.engineer.cards import sessions
    return tuple(sessions.LANES)


def _col_id():
    return "c-" + secrets.token_hex(4)


def _board_id():
    return "b-" + secrets.token_hex(8)


def _clean_column(c, seen):
    """(column, error). Unknown keys are REJECTED, not dropped - silently
    discarding half a write is how a client ends up believing it saved a layout
    it did not (userconfig._valid_appearance makes the same call)."""
    if not isinstance(c, dict):
        return None, "each column must be an object"
    extra = set(c) - {"id", "label", "station"}
    if extra:
        return None, "unknown column field: %s" % ", ".join(sorted(extra))[:60]
    st = c.get("station")
    if st not in stations():
        return None, "unknown station: %s" % str(st)[:40]
    label = c.get("label", "")
    if not isinstance(label, str):
        return None, "column label must be text"
    if len(label) > MAX_LABEL:
        return None, "column label longer than %d characters" % MAX_LABEL
    cid = c.get("id") or _col_id()
    if not isinstance(cid, str) or not cid.strip():
        return None, "column id must be text"
    cid = cid.strip()[:40]
    if cid in seen:
        # Column ids address the drag hit-test and the render key; two columns
        # sharing one would make a drop land in whichever the client happened
        # to measure last.
        return None, "duplicate column id: %s" % cid
    seen.add(cid)
    # `label` is stored as given, including "" - see invariant 1 in the module
    # docstring. Whitespace-only collapses to empty so it cannot masquerade as
    # a label that renders as a blank column head.
    return {"id": cid, "label": label.strip(), "station": st}, None


def validate(board):
    """(cleaned, error). Everything a caller may set; `owner` and `created` are
    assigned by `write`, never accepted from the wire."""
    if not isinstance(board, dict):
        return None, "board must be an object"
    extra = set(board) - {"id", "name", "columns"}
    if extra:
        return None, "unknown board field: %s" % ", ".join(sorted(extra))[:60]
    name = board.get("name")
    if not isinstance(name, str) or not name.strip():
        return None, "board name required"
    if len(name.strip()) > MAX_NAME:
        return None, "board name longer than %d characters" % MAX_NAME
    cols = board.get("columns")
    if not isinstance(cols, list) or not cols:
        # Zero columns is not "a minimal board", it is a board on which every
        # card is overflow - a layout that renders as an error either way, so
        # it is refused at the door rather than shipped to the client to cope.
        return None, "a board needs at least one column"
    if len(cols) > MAX_COLUMNS:
        return None, "too many columns (max %d)" % MAX_COLUMNS
    out, seen = [], set()
    for c in cols:
        col, err = _clean_column(c, seen)
        if err:
            return None, err
        out.append(col)
    bid = board.get("id") or ""
    if not isinstance(bid, str):
        return None, "board id must be text"
    return {"id": bid.strip()[:64], "name": name.strip(), "columns": out}, None


# ---- the default board ----------------------------------------------------

def _seed_columns():
    """The four stations in workflow order, labelled from `policy.lane_labels`
    where - and only where - the owner actually renamed one.

    This IS the migration the PRD asks for: the setting was the only per-
    workspace column rename that existed, so it becomes the default board's
    labels the first time the board is minted. Everything the owner never
    touched stays EMPTY so the app keeps translating it (invariant 1). The
    settings key itself stays readable for one release as the app's fallback
    for an unlabelled column, then retires."""
    from spine.storage import events
    ll = (events.settings().get("policy") or {}).get("lane_labels") or {}
    cols = []
    for st in stations():
        raw = ll.get(st)
        label = raw.strip() if isinstance(raw, str) else ""
        cols.append({"id": "c-" + st, "label": label[:MAX_LABEL], "station": st})
    return cols


def default_record():
    """The default board AS IT WOULD BE SEEDED, without touching the store.

    Split out of ensure_default so the record's shape has exactly one
    definition: the ts-contract test in ops/tests/test_harness_layer.py holds
    the app's `Board` interface against THIS, and a hand-written sample there
    would drift from what the daemon really serves - which is the one thing
    that test exists to catch."""
    return {"id": DEFAULT_ID, "name": DEFAULT_NAME, "owner": "",
            "columns": _seed_columns(), "created": _now()}


def ensure_default():
    """The shared default board, minted from `policy.lane_labels` if absent.

    ONE OWNER for this state, two callers: the daemon calls it at boot so the
    migration is a startup event as the PRD specifies, and the read path calls
    it so a store created by anything else (a test, a tool, a fresh sandbox)
    still resolves a board instead of an empty screen. Idempotent by
    construction - db.board_insert_absent only writes when the id is free, so a
    second call neither re-runs the migration nor bumps the version."""
    from spine.storage import db
    b = db.board_get(DEFAULT_ID)
    if b:
        return b
    seeded = default_record()
    if db.board_insert_absent(seeded):
        from spine.storage import events
        events.emit("board", "-", op="seed", board=DEFAULT_ID, owner="",
                    actor="system", columns=len(seeded["columns"]),
                    migrated_labels=sorted(
                        c["station"] for c in seeded["columns"] if c["label"]))
    # Re-read rather than return `seeded`: if another thread won the insert,
    # the row on disk is the truth and this call must answer with it.
    return db.board_get(DEFAULT_ID) or seeded


def _now():
    import datetime
    return datetime.datetime.now().isoformat(timespec="seconds")


# ---- reads ----------------------------------------------------------------

def for_user(name):
    """Every board this account may render: the shared default first, then its
    own. Personal boards are private in v1 (PRD section 2), so another
    account's board is not merely unlisted here - it is unreachable, because
    every write path below re-derives ownership from the session too."""
    from spine.storage import db
    out = [ensure_default()]
    out.extend(b for b in db.boards_owned_by(name) if b.get("id") != DEFAULT_ID)
    return out


def may_edit(user_name, role, board):
    """None if this account may write `board`, else the reason to refuse."""
    owner = (board or {}).get("owner", "")
    if owner == "":
        # The default board is workspace furniture, not a personal view: it is
        # what a brand-new invited account lands on, so an operator renaming
        # its columns would move everyone's screen. Owner role only - the same
        # line POST /settings draws, drawn once more here rather than inherited
        # from a capability, because this row is reachable on a SELF-SCOPED
        # route that deliberately has no capability.
        return None if role == "owner" else \
            "the default board is the workspace's - only the owner role may change it"
    if owner != user_name:
        return "not your board"
    return None


# ---- writes ---------------------------------------------------------------

def write(user_name, role, board, actor=None):
    """Create or replace one board. Returns (board, error).

    SELF-SCOPE IS THE AUTHORIZATION, exactly as for the profile: `owner` is
    taken from the session, never from the body. A create MINTS the id server-
    side rather than accepting one, which is what makes id-squatting a question
    that cannot be asked - an account can only ever address a row it already
    owns, or a brand-new one."""
    from spine.storage import db, events
    cleaned, err = validate(board)
    if err:
        return None, err
    bid = cleaned.pop("id", "")
    if bid:
        existing = db.board_get(bid)
        if not existing:
            # Not "create it under this id": an id the caller invented has no
            # owner, and inventing one from the session would hand any client a
            # way to claim `default` the moment it is deleted or not yet
            # seeded. Unknown id is a miss, full stop.
            return None, "no such board"
        why = may_edit(user_name, role, existing)
        if why:
            return None, why
        owner, created = existing.get("owner", ""), existing.get("created") or _now()
        op = "update"
    else:
        if len(db.boards_owned_by(user_name)) >= MAX_BOARDS_PER_USER:
            return None, "too many boards (max %d)" % MAX_BOARDS_PER_USER
        bid, owner, created, op = _board_id(), user_name, _now(), "create"
    row = {"id": bid, "name": cleaned["name"], "owner": owner,
           "columns": cleaned["columns"], "created": created}
    db.board_put(row)
    # Audit law: who changed which view, when. The board's STRUCTURE is logged
    # (id, owner, how many columns, which stations) and the user's own wording
    # is not - the same line userconfig.write draws between keys and values,
    # for the same reason: the append-only sink is an auditor's, and a column
    # label is the user's.
    events.emit("board", "-", op=op, board=bid, owner=owner,
                actor=actor or user_name, columns=len(row["columns"]),
                stations=sorted({c["station"] for c in row["columns"]}))
    return row, None


def delete(user_name, role, bid, actor=None):
    """Remove one of my boards. Returns (ok, error)."""
    from spine.storage import db, events
    if bid == DEFAULT_ID:
        # Not an ownership question: the default board is where a fresh login
        # lands (PRD section 4.2), so deleting it would end setup on an empty
        # screen for every account at once. Refused for the owner too.
        return False, "the default board cannot be deleted"
    existing = db.board_get(bid)
    if not existing:
        return False, "no such board"
    why = may_edit(user_name, role, existing)
    if why:
        return False, why
    db.board_delete(bid)
    events.emit("board", "-", op="delete", board=bid,
                owner=existing.get("owner", ""), actor=actor or user_name)
    return True, None


def drop_user(name):
    """Delete every board an account owns; returns how many. auth.delete_user
    calls this for the same reason it drops the profile rows - see
    db.boards_drop_user."""
    from spine.storage import db
    return db.boards_drop_user(name)


def personal_count(name):
    """How many personal boards this account owns. The rename guard in
    userconfig.rename_block_reason reads THIS rather than parsing a sentence
    out of this module - derived from the table, never a stored flag. The
    shared default board is excluded: it has no personal owner to orphan."""
    from spine.storage import db
    return len([b for b in db.boards_owned_by(name) if b.get("id") != DEFAULT_ID])


__all__ = ["DEFAULT_ID", "DEFAULT_NAME", "MAX_COLUMNS", "MAX_BOARDS_PER_USER",
           "MAX_NAME", "MAX_LABEL", "stations", "validate", "default_record",
           "ensure_default", "for_user", "may_edit", "write", "delete",
           "drop_user", "personal_count"]
