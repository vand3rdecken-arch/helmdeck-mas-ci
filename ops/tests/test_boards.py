# -*- coding: utf-8 -*-
"""Boards: the storage + policy layer (accounts-boards-prd phase 2).

One test per property the PRD actually claims, not per function:

  1. the default board is seeded from policy.lane_labels, ONCE, and only where
     the owner really renamed a lane (the rest stays translatable)
  2. a personal board is private - another account can neither see nor write it
  3. the default board is owner-role only, and cannot be deleted by anyone
  4. the shape is closed: no unknown station, no unknown field, no empty board
  5. a write bumps _version (the SSE cursor device B re-renders on) and emits
     an append-only audit event
  6. deleting an account takes its boards; the rename guard counts them
  7. `stations()` is DERIVED from the Engineer cell's lanes, never restated

SANDBOXED: it repoints daemon.paths at a temp dir BEFORE importing anything
that resolves a path, and refuses to run if that did not take. Same preamble as
test_user_config.py, for the same reason - these tests write.

Run:  py -3.12 ops/tests/test_boards.py
"""
import json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

_SANDBOX = tempfile.mkdtemp(prefix="hd-boards-")
import daemon.paths
daemon.paths.DAEMON_ROOT = _SANDBOX

from spine.storage import boards, db, events, userconfig      # noqa: E402

assert db.DBPATH.startswith(_SANDBOX), \
    "REFUSING TO RUN: db points at %s, not the sandbox" % db.DBPATH
assert events.SET.startswith(_SANDBOX), \
    "REFUSING TO RUN: settings point at %s, not the sandbox" % events.SET

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def workspace(**settings):
    # db store, not settings.json (config-consolidation phase 2) - wholesale
    # replace, the same reset semantics overwriting the file used to have.
    db.workspace_config_replace(settings)


def cols(*stations):
    return [{"label": "", "station": s} for s in stations]


# The owner renamed exactly ONE lane before boards existed - that is the state
# the migration has to carry over without inventing labels for the other three.
# init BEFORE the seed since the workspace store moved into the db (config-
# consolidation phase 2) - the table has to exist to be seeded.
db.init()
workspace(policy={"lane_labels": {"working": "Bei uns"}})


# -- 1. the default board IS the lane_labels migration -----------------------
def test_default_board_is_seeded_from_lane_labels():
    b = boards.ensure_default()
    check(b["id"] == boards.DEFAULT_ID and b["owner"] == "",
          "the default board exists after the first call, owned by nobody "
          '(owner="") - it is the workspace\'s, not an account\'s')
    stations = [c["station"] for c in b["columns"]]
    check(stations == list(boards.stations()),
          "it covers every station in workflow order, so a fresh workspace "
          "renders exactly the board it rendered before boards existed "
          "(got %s)" % stations)
    by_station = {c["station"]: c["label"] for c in b["columns"]}
    check(by_station.get("working") == "Bei uns",
          "the ONE lane the owner renamed in policy.lane_labels came across "
          "as that column's label")
    check(by_station.get("backlog") == "" and by_station.get("done") == "",
          "the lanes the owner never touched stay EMPTY, not baked with a "
          "German string - empty means 'render this station's own name', "
          "which is what keeps the board translatable (invariant 1)")

    before = db.current_version()
    again = boards.ensure_default()
    check(again["columns"] == b["columns"],
          "a second call returns the SAME board, it does not re-seed")
    check(db.current_version() == before,
          "and it does not bump _version - an idempotent seed must not make "
          "every daemon boot look like a board change to every open device")

    # The migration is one-time by construction, not by a flag: change the
    # setting afterwards and the board is unmoved, because the board now owns
    # its labels.
    workspace(policy={"lane_labels": {"working": "Etwas anderes"}})
    check(boards.ensure_default()["columns"] == b["columns"],
          "changing policy.lane_labels AFTER the seed does not silently "
          "rewrite the board - the board owns its labels from then on")
    workspace(policy={"lane_labels": {"working": "Bei uns"}})


# -- 2. a personal board is private ------------------------------------------
def test_personal_boards_are_private():
    mine, err = boards.write("ada", "operator",
                             {"name": "Meins", "columns": cols("working", "review")})
    check(err is None and mine["owner"] == "ada",
          "an operator creates a personal board, owned by the SESSION account")
    check(mine["id"] and mine["id"] != boards.DEFAULT_ID,
          "with a server-MINTED id (%s) - a caller cannot choose one, so it "
          "cannot squat an id it does not own" % mine.get("id"))

    listed = [b["id"] for b in boards.for_user("ada")]
    check(listed == [boards.DEFAULT_ID, mine["id"]],
          "ada sees the default board first, then her own")
    check([b["id"] for b in boards.for_user("bob")] == [boards.DEFAULT_ID],
          "bob sees only the default board - ada's is not merely unlisted "
          "for him, it is not his to render")

    _, err = boards.write("bob", "operator",
                          {"id": mine["id"], "name": "Geklaut", "columns": cols("done")})
    check(err == "not your board",
          "and bob cannot WRITE it either, by id - the listing is not the "
          "only thing enforcing privacy (got %r)" % err)
    ok, err = boards.delete("bob", "operator", mine["id"])
    check(not ok and err == "not your board",
          "nor delete it (got %r)" % err)
    check(db.board_get(mine["id"])["name"] == "Meins",
          "after both refusals the board is untouched")

    _, err = boards.write("ada", "operator",
                          {"id": "b-doesnotexist", "name": "X", "columns": cols("done")})
    check(err == "no such board",
          "an id nobody owns is a MISS, not a create - otherwise deleting "
          "the default board would let the next caller claim its id "
          "(got %r)" % err)


# -- 3. the default board is the workspace's ---------------------------------
def test_default_board_is_owner_only_and_undeletable():
    d = boards.ensure_default()
    patch = {"id": boards.DEFAULT_ID, "name": "Board", "columns": d["columns"]}
    _, err = boards.write("ada", "operator", patch)
    check(err and "only the owner role" in err,
          "an operator may not rename the default board's columns - it is "
          "what every account lands on, so that would move everyone's screen "
          "(got %r)" % err)

    renamed = [dict(c) for c in d["columns"]]
    renamed[0]["label"] = "Eingang"
    row, err = boards.write("hank", "owner",
                            {"id": boards.DEFAULT_ID, "name": "Board", "columns": renamed})
    check(err is None and row["columns"][0]["label"] == "Eingang",
          "the owner role may (got %r)" % err)
    check(row["owner"] == "",
          'and the board stays owner="" - writing it does not transfer the '
          "workspace's board to the owner's personal set")

    for who, role in (("ada", "operator"), ("hank", "owner")):
        ok, err = boards.delete(who, role, boards.DEFAULT_ID)
        check(not ok and err == "the default board cannot be deleted",
              "%s cannot delete the default board - a fresh login lands "
              "there, so an empty board table would end setup on an empty "
              "screen (got %r)" % (role, err))


# -- 4. the shape is closed --------------------------------------------------
def test_the_shape_is_closed():
    bad = [
        ({"name": "X", "columns": [{"label": "", "station": "gate"}]},
         "a station the lane machine would refuse a card into"),
        ({"name": "X", "columns": [{"label": "", "station": "working", "wip": 3}]},
         "an unknown column field (rejected, not silently dropped)"),
        ({"name": "X", "columns": []},
         "zero columns - a board on which every card is overflow"),
        ({"name": "  ", "columns": cols("working")},
         "a blank name"),
        ({"name": "X" * (boards.MAX_NAME + 1), "columns": cols("working")},
         "a name past the size bound"),
        ({"name": "X", "columns": [{"label": "y" * (boards.MAX_LABEL + 1),
                                    "station": "working"}]},
         "a column label past the size bound"),
        ({"name": "X", "columns": cols("working") * (boards.MAX_COLUMNS + 1)},
         "more columns than the bound"),
        ({"name": "X", "columns": [{"id": "c-1", "station": "working"},
                                   {"id": "c-1", "station": "done"}]},
         "two columns sharing one id (the drag hit-test addresses by id)"),
        ({"name": "X", "columns": cols("working"), "owner": "somebodyelse"},
         "an `owner` smuggled in the body - it comes from the session only"),
    ]
    for patch, why in bad:
        _, err = boards.write("ada", "operator", patch)
        check(bool(err), "refused: %s (said %r)" % (why, err))

    row, err = boards.write("ada", "operator", {
        "name": "  Zwei Spalten  ",
        "columns": [{"label": "  Los  ", "station": "backlog"},
                    {"label": "", "station": "done"}]})
    check(err is None and row["name"] == "Zwei Spalten",
          "a good board lands, with the name trimmed")
    check(row["columns"][0]["label"] == "Los" and row["columns"][1]["label"] == "",
          "labels are trimmed, and an empty one STAYS empty rather than "
          "being back-filled - empty is a meaning, not a missing value")
    check(all(c.get("id") for c in row["columns"]),
          "every column got an id, minted where the client sent none")


# -- 5. a write reaches the other device -------------------------------------
def test_version_bump_and_audit():
    before = db.current_version()
    row, _ = boards.write("ada", "operator",
                          {"name": "Tick", "columns": cols("review")})
    check(db.current_version() > before,
          "a board write bumps _version, so device B re-renders on the next "
          "SSE tick (the PRD's phase-2 acceptance)")

    before = db.current_version()
    boards.write("ada", "operator",
                 {"id": row["id"], "name": "Tack", "columns": cols("review", "done")})
    check(db.current_version() > before, "so does renaming/re-columning it")

    rows = [e for e in db.events_all() if e.get("kind") == "board"]
    check(bool(rows), "every write emits an append-only audit event")
    last = rows[-1]
    check(last.get("actor") == "ada" and last.get("board") == row["id"]
          and last.get("op") == "update",
          "the audit line names WHO, WHICH board and WHICH op (got %r)" % last)
    check("name" not in last and "labels" not in last,
          "it records the board's STRUCTURE, not the user's wording - the "
          "same line userconfig.write draws between keys and values")
    check(any(e.get("op") == "seed" for e in rows),
          "the one-time default-board seed is auditable too")

    n = len(rows)
    boards.delete("ada", "operator", row["id"])
    after = [e for e in db.events_all() if e.get("kind") == "board"]
    check(len(after) == n + 1 and after[-1].get("op") == "delete",
          "and so is a delete")
    check(db.board_get(row["id"]) is None, "which really removes the row")


# -- 6. the account name is the identity -------------------------------------
def test_delete_and_rename_account():
    boards.write("zoe", "operator", {"name": "Zoes", "columns": cols("working")})
    check(boards.personal_count("zoe") == 1,
          "zoe owns one personal board (the default board is excluded - it "
          "has no personal owner to orphan)")

    reason = userconfig.rename_block_reason("zoe")
    check(bool(reason) and "board" in reason,
          "renaming her is BLOCKED and the reason says why, even though she "
          "has no profile rows at all - one guard answering for every "
          "name-keyed store, not one per store (got %r)" % reason)

    from spine.auth import auth
    try:
        auth.create_user("zoe", "hunter2hunter2", "operator")
    except ValueError:
        pass
    auth.delete_user("zoe", actor="hank")
    check(boards.personal_count("zoe") == 0,
          "deleting the account takes its boards with it - otherwise a later "
          "account with that name inherits a stranger's views")
    check(db.board_get(boards.DEFAULT_ID) is not None,
          "and the shared default board survives - it outlives its creator, "
          "which is what lets an owner be replaced")


# -- 7. the station list is derived, not restated ----------------------------
def test_stations_are_derived_from_the_lane_machine():
    from cells.engineer import sessions
    check(tuple(boards.stations()) == tuple(sessions.LANES),
          "boards.stations() IS the Engineer cell's lane tuple - a copy here "
          "would let a board offer a column the lane machine refuses to move "
          "a card into the day a lane is added")
    for st in boards.stations():
        row, err = boards.write("drift", "operator",
                                {"name": st, "columns": cols(st)})
        check(err is None, "every lane the machine knows is a legal column "
                           "station (%s: %r)" % (st, err))


for fn in (test_default_board_is_seeded_from_lane_labels,
           test_personal_boards_are_private,
           test_default_board_is_owner_only_and_undeletable,
           test_the_shape_is_closed,
           test_version_bump_and_audit,
           test_delete_and_rename_account,
           test_stations_are_derived_from_the_lane_machine):
    print(fn.__name__)
    fn()

print(("FAILED: %d" % len(_fails)) if _fails else "all board checks passed")
sys.exit(1 if _fails else 0)
