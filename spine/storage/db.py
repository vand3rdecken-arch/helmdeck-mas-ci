# -*- coding: utf-8 -*-
"""SQLite storage - pays the json-storage debt. Tracks are rows (per-track
upserts in transactions kill the lost-update race), events are an indexed
append-only table (dashboard stops re-parsing history). WAL mode so readers
never block the writer. Existing tracks.json / events.jsonl are imported on
first start and renamed *.imported - originals preserved, per the safeguard
rule."""
import json, os, sqlite3, threading

from daemon.paths import DAEMON_ROOT as ROOT
DBPATH = os.path.join(ROOT, "helmdeck.db")

# The HelmDeck rename (2026) changed the DB filename from swarmdeck.db. Carry the
# existing data over on first start so no cards are lost. Copy (not move) so the
# original stays as a backup; include the WAL sidecars so recent writes come too.
_LEGACY_DB = os.path.join(ROOT, "swarmdeck.db")
if not os.path.exists(DBPATH) and os.path.exists(_LEGACY_DB):
    import shutil
    shutil.copy2(_LEGACY_DB, DBPATH)
    for _ext in ("-wal", "-shm"):
        if os.path.exists(_LEGACY_DB + _ext):
            shutil.copy2(_LEGACY_DB + _ext, DBPATH + _ext)

_local = threading.local()
_version = 0                      # bumped on every write; SSE waits on it
# The CHAT transcript's own cursor, deliberately SEPARATE from _version.
#
# The chat log is not a table in this database - it is a JSON file written by
# copilot._append_log - so no writer below could ever move _version for it, and
# for a long time nothing did: every surface fell back to a fixed-interval
# refetch (phone 8s, watch 15s) for the one stream the owner actually watches.
#
# A second counter rather than folding chat into _version, because _version's
# consumer invalidates the WHOLE query cache on every tick. Every Henry sentence
# would have refetched the board, the dashboard and the card lists on every
# paired device - trading a poll for a broadcast. Two cursors let a client wake
# on exactly the stream it is reading.
_chat_version = 0
# The GLASSES conversation's own cursor - a THIRD counter, for the same reason
# there is a second one.
#
# What moves it is not a stored row and not the chat log: it is the live state of
# a voice turn on the lens (mic open, words heard, Henry thinking, answered),
# which glassturn.py owns. That state changes several times per spoken sentence,
# so folding it into _chat_version would wake the phone and the watch - and
# invalidate their transcript - on every partial recognition result the glasses
# produce. Folding it into _version would do the same to every board query on
# every paired device.
#
# Three cursors, three streams: a client holds ONE hanging request and is woken
# by exactly the stream it reads. The lens waits on chat+glass (wait_glass); the
# phone and the watch never subscribe to this one and are untouched by it.
_glass_version = 0
_version_cond = threading.Condition()

def conn():
    c = getattr(_local, "c", None)
    if c is None:
        c = sqlite3.connect(DBPATH, timeout=15)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        _local.c = c
    return c

def bump():
    global _version
    with _version_cond:
        _version += 1
        _version_cond.notify_all()

def bump_chat():
    """The chat transcript moved. ONE caller by construction: copilot._append_log,
    which is already this repo's single writer of the chat log - so the cursor is
    folded at EVENT TIME at exactly one owner, never reconstructed by re-reading
    the file or inferred from a stored flag (CLAUDE.md's no-monkey-patches law,
    same shape as drivers.turn_active and sessions.record_bg)."""
    global _chat_version
    with _version_cond:
        _chat_version += 1
        _version_cond.notify_all()

def bump_glass():
    """The glasses voice turn moved. ONE caller by construction:
    spine/ops/glassturn.py's _set(), which is the single owner of that state -
    so this cursor is folded at EVENT TIME at exactly one owner, never
    reconstructed and never inferred (CLAUDE.md's no-monkey-patches law, same
    shape as bump_chat above)."""
    global _glass_version
    with _version_cond:
        _glass_version += 1
        _version_cond.notify_all()


def wait_glass(chat_last, glass_last, timeout=20):
    """Block until EITHER the chat transcript or the glasses turn moves.

    The lens's half of wait_any: it reads the same Henry transcript the phone
    does (so it must wake on `c`) AND the live turn state only it renders (so it
    must wake on `g`). One hanging request, two cursors, same condition - see
    wait_any for why that beats a second long-poll.

    Returns the CURRENT pair, never a delta; a spurious or timed-out wake costs
    one round trip and cannot lose an event, exactly as wait_any documents.

    The timeout is SHORTER than wait_any's 22s on purpose: this request is
    proxied by the Cloudflare Worker in front of the daemon, and a reply that
    arrives comfortably inside the edge's patience is worth more here than the
    two seconds of idle saved."""
    with _version_cond:
        if _chat_version > chat_last or _glass_version > glass_last:
            return _chat_version, _glass_version
        _version_cond.wait(timeout)
        return _chat_version, _glass_version


def current_glass_version():
    return _glass_version


def wait_version(last, timeout=25):
    """Block until the data version passes `last` (or timeout). SSE fuel."""
    with _version_cond:
        if _version > last:
            return _version
        _version_cond.wait(timeout)
        return _version

def wait_any(board_last, chat_last, timeout=22):
    """Block until EITHER cursor passes the client's value, and report both.

    One waiter, one condition, two cursors: a client holds a single hanging
    request and is woken by whichever stream it is subscribed to actually moved.
    That is the whole point - the alternative (a second long-poll for chat) would
    double every device's idle connection count to say the same thing.

    Returns the CURRENT pair, not a delta. Condition.wait may return spuriously
    or on timeout, exactly as wait_version already tolerates; the client compares
    the numbers it gets back against the ones it sent and re-arms either way, so
    a spurious wake costs one round trip and can never lose an event."""
    with _version_cond:
        if _version > board_last or _chat_version > chat_last:
            return _version, _chat_version
        _version_cond.wait(timeout)
        return _version, _chat_version

def current_version():
    return _version

def current_chat_version():
    return _chat_version

def init(role="tool"):
    """role="daemon" marks THE process that owns the driver sessions (server.
    serve). Only that process may devalue persisted lifecycle state - a test or
    tool process has an empty driver table, so from its viewpoint EVERY running
    card would look dead; letting it 'heal' them would corrupt the live board."""
    c = conn()
    c.execute("""CREATE TABLE IF NOT EXISTS tracks(
        id TEXT PRIMARY KEY, data TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS projects(
        id TEXT PRIMARY KEY, data TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS processes(
        id TEXT PRIMARY KEY, data TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS connector_state(
        id TEXT PRIMARY KEY, data TEXT NOT NULL)""")
    # Per-ACCOUNT profile rows (accounts-boards-prd phase 1). Keyed on the
    # user NAME, which is what users.json calls an account - see
    # spine/storage/userconfig.py for why that makes a rename an identity
    # change rather than an edit. `value` is a JSON scalar/object; the
    # whitelist and the size bound live one layer up, not here.
    c.execute("""CREATE TABLE IF NOT EXISTS user_config(
        user TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
        updated_at TEXT NOT NULL, PRIMARY KEY(user, key))""")
    # Per-PROJECT harness config rows (harness-config-ui phase 1). Deliberately
    # the same shape as user_config above, one layer down the resolution chain:
    #   code default -> seed -> workspace (settings.json) -> PROJECT (here).
    # `project` is projects.repo_key() - the normcased comparison form, because
    # Windows hands us C:\Repo and c:/repo for one directory and the overlay
    # must not depend on which spelling arrived first. `key` is a dotted path
    # (policy.auto_accept_green, rule.initiative.delegate).
    # ABSENT MEANS INHERITED, never "set to null": a cleared value DELETES its
    # row, so the chain can always answer "geerbt" vs "fuer dieses Projekt
    # gesetzt" from the table rather than from a sentinel value. The whitelist,
    # the bounds and that delete rule live one layer up, in
    # spine/storage/projectconfig.py.
    c.execute("""CREATE TABLE IF NOT EXISTS project_config(
        project TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
        updated_at TEXT NOT NULL, PRIMARY KEY(project, key))""")
    # BOARDS: saved VIEWS over the one card pool (accounts-boards-prd phase 2).
    # Cards exist once, in `tracks`; a board only says which columns to draw and
    # which station each one shows. `owner` is the account NAME (or "" for the
    # single shared default board) - the same name-IS-the-identity decision
    # user_config made above, and the reason boards join the rename guard.
    # `name` and `owner` are mirrored out of `json` into real columns purely so
    # this table can be QUERIED by owner; the json blob stays authoritative.
    # Shape, bounds and who-may-edit-which-row live in spine/storage/boards.py.
    c.execute("""CREATE TABLE IF NOT EXISTS boards(
        id TEXT PRIMARY KEY, name TEXT NOT NULL, owner TEXT NOT NULL,
        json TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    c.execute("CREATE INDEX IF NOT EXISTS boards_owner ON boards(owner)")
    c.execute("""CREATE TABLE IF NOT EXISTS events(
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        id TEXT, ts TEXT, kind TEXT, track TEXT, data TEXT)""")
    _ensure_events_id_column(c)
    # UNIQUE, allowing many NULLs (SQLite treats each NULL as distinct in a
    # unique index) - pre-id-era rows imported before this column existed all
    # have id=NULL and none of them collide with each other or with anything
    # new. This is what makes _reconcile_events() safe to run every boot
    # instead of only once: INSERT OR IGNORE on a genuine id conflict is a
    # no-op, not a duplicate.
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS ev_id ON events(id)")
    c.execute("CREATE INDEX IF NOT EXISTS ev_kind ON events(kind)")
    c.execute("CREATE INDEX IF NOT EXISTS ev_track ON events(track)")
    c.commit()
    _migrate()
    _reconcile_events()
    if role == "daemon":
        _devalue_persisted_running()


def _ensure_events_id_column(c):
    """Migrate an EXISTING events table predating the `id` column - CREATE
    TABLE IF NOT EXISTS is a no-op once the table already exists, so an
    installation from before this change never gets the column any other
    way."""
    cols = {r[1] for r in c.execute("PRAGMA table_info(events)")}
    if "id" not in cols:
        c.execute("ALTER TABLE events ADD COLUMN id TEXT")


def _devalue_persisted_running():
    """Paseo agent-archive parity (normalizeArchivedStatus): persisted 'running'/
    'initializing' is NEVER believed when a store is loaded - a fresh daemon by
    definition holds no live turn, so every running/gating card died with the
    previous process. Part of the store's daemon boot (not a step serve() must
    remember): delegating to sessions.sweep_zombies(min_idle_s=0) keeps the
    behaviour identical - bounce + resume note + live-session promotion."""
    try:
        from cells.engineer import sessions
        zombies = sessions.sweep_zombies(min_idle_s=0)
        if zombies:
            print("db: devalued %d persisted running/gating card(s) at load: %s"
                  % (len(zombies), ", ".join(zombies)))
    except Exception as e:
        print("db: boot devaluation failed:", e)

def _archive(path):
    """Retire an imported legacy file WITHOUT destroying an older archive.

    The original code did a bare os.replace(p, p + ".imported"), which silently
    overwrote the archive from a previous run - so the docstring's promise
    ("originals preserved, per the safeguard rule") stopped holding on the second
    boot. Nothing is allowed to eat a backup here, so a taken name gets a
    numbered sibling instead."""
    dest = path + ".imported"
    if os.path.exists(dest):
        n = 2
        while os.path.exists("%s.%d" % (dest, n)):
            n += 1
        dest = "%s.%d" % (dest, n)
    os.replace(path, dest)
    return dest


def _migrate():
    c = conn()
    tj = os.path.join(ROOT, "tracks.json")
    if os.path.exists(tj):
        try:
            with open(tj, encoding="utf-8") as f:
                tracks = json.load(f)
            with c:
                for t in tracks:
                    c.execute("INSERT OR REPLACE INTO tracks(id,data) VALUES(?,?)",
                              (t["id"], json.dumps(t)))
            _archive(tj)
            print("db: imported %d tracks from tracks.json" % len(tracks))
        except Exception as e:
            print("db: tracks import failed:", e)
    # events.jsonl is the ONE legacy file that comes back: events.emit() appends
    # to it on every event while ALSO write-through inserting the same row here
    # (events.py:175-191). The other three files are written once and stay gone.
    #
    # So this block used to duplicate the whole previous session on every boot:
    # import (plain INSERT, no key to dedupe on) -> rename -> emit recreates the
    # file -> next boot imports it all again. Every count over `events` was
    # inflated, which is why the dashboard's cost figures read too high.
    #
    # Import is therefore what the docstring always said it was - a FIRST-START
    # migration - and it only runs against an empty table. A populated table also
    # means the file must stay put: it is the durable append-only record, not a
    # leftover to be retired.
    ej = os.path.join(ROOT, "events.jsonl")
    if os.path.exists(ej) and c.execute("SELECT 1 FROM events LIMIT 1").fetchone() is None:
        try:
            n = 0
            with open(ej, encoding="utf-8") as f, c:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    c.execute("INSERT INTO events(ts,kind,track,data) VALUES(?,?,?,?)",
                              (r.get("ts"), r.get("kind"), r.get("track"),
                               json.dumps({k: v for k, v in r.items()
                                           if k not in ("ts", "kind", "track")})))
                    n += 1
            _archive(ej)
            print("db: imported %d events from events.jsonl" % n)
        except Exception as e:
            print("db: events import failed:", e)
    pj = os.path.join(ROOT, "processes.json")
    if os.path.exists(pj):
        try:
            with open(pj, encoding="utf-8") as f:
                procs = json.load(f)
            with c:
                for p in procs:
                    c.execute("INSERT OR REPLACE INTO processes(id,data) VALUES(?,?)",
                              (p["id"], json.dumps(p)))
            _archive(pj)
            print("db: imported %d processes from processes.json" % len(procs))
        except Exception as e:
            print("db: processes import failed:", e)
    # connectors/_state.json (last-run timestamps keyed by connector name) -
    # the connector CODE files themselves (connectors/<name>.py) stay on disk:
    # they are real importable modules run in a sandboxed subprocess
    # (connectors._run_sandboxed), not JSON records, so they are not a fit for
    # a `data TEXT` row and are deliberately left out of this migration (see
    # daemon/debt.py order 32). Only the small state dict moves.
    csj = os.path.join(ROOT, "connectors", "_state.json")
    if os.path.exists(csj):
        try:
            with open(csj, encoding="utf-8") as f:
                cstate = json.load(f)
            with c:
                c.execute("INSERT OR REPLACE INTO connector_state(id,data) VALUES(?,?)",
                          ("state", json.dumps(cstate)))
            _archive(csj)
            print("db: imported connector state (%d connectors) from connectors/_state.json" % len(cstate))
        except Exception as e:
            print("db: connector state import failed:", e)

# -- tracks --------------------------------------------------------------

def tracks_all():
    rows = conn().execute("SELECT data FROM tracks ORDER BY id DESC").fetchall()
    return [json.loads(r[0]) for r in rows]

def track_get(tid):
    r = conn().execute("SELECT data FROM tracks WHERE id=?", (tid,)).fetchone()
    return json.loads(r[0]) if r else None

def track_put(t):
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO tracks(id,data) VALUES(?,?)",
                  (t["id"], json.dumps(t)))
    bump()

def track_delete(tid):
    with conn() as c:
        c.execute("DELETE FROM tracks WHERE id=?", (tid,))
    bump()

def tracks_replace(tracks):
    with conn() as c:
        c.execute("DELETE FROM tracks")
        for t in tracks:
            c.execute("INSERT INTO tracks(id,data) VALUES(?,?)",
                      (t["id"], json.dumps(t)))
    bump()

# -- projects -------------------------------------------------------------

def projects_all():
    rows = conn().execute("SELECT data FROM projects ORDER BY id DESC").fetchall()
    return [json.loads(r[0]) for r in rows]

def project_get(pid):
    r = conn().execute("SELECT data FROM projects WHERE id=?", (pid,)).fetchone()
    return json.loads(r[0]) if r else None

def project_put(p):
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO projects(id,data) VALUES(?,?)",
                  (p["id"], json.dumps(p)))
    bump()

def project_delete(pid):
    with conn() as c:
        c.execute("DELETE FROM projects WHERE id=?", (pid,))
    bump()

# -- processes --------------------------------------------------------------
# processes.py's every call site is read-all -> mutate one item by id ->
# write-all, so processes_replace (not per-item put/delete) matches its
# existing _load()/_save() contract exactly - zero call-site changes needed.

def processes_all():
    rows = conn().execute("SELECT data FROM processes ORDER BY id DESC").fetchall()
    return [json.loads(r[0]) for r in rows]

def processes_replace(procs):
    with conn() as c:
        c.execute("DELETE FROM processes")
        for p in procs:
            c.execute("INSERT INTO processes(id,data) VALUES(?,?)",
                      (p["id"], json.dumps(p)))
    bump()

# -- connector state -------------------------------------------------------
# connectors.py's _state()/_save_state() contract: one dict {name: last_run},
# read-whole / write-whole, same shape as processes_all/processes_replace but
# a single row (there is only ever one state dict, not one row per id).

def connector_state_get():
    r = conn().execute("SELECT data FROM connector_state WHERE id=?", ("state",)).fetchone()
    return json.loads(r[0]) if r else {}

def connector_state_put(d):
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO connector_state(id,data) VALUES(?,?)",
                  ("state", json.dumps(d)))
    bump()

# -- user config -----------------------------------------------------------
# Dumb storage, exactly like the tables above: no whitelist, no defaults, no
# validation. spine/storage/userconfig.py owns all of that - this layer only
# knows rows, atomicity and the version bump.

def user_config_get(user):
    """Every STORED row for this account, {key: decoded value}. Absent keys are
    absent - resolution against the workspace defaults is userconfig.py's job,
    so a caller can always tell "the account chose German" from "nobody chose"."""
    rows = conn().execute(
        "SELECT key,value FROM user_config WHERE user=?", (user,)).fetchall()
    out = {}
    for k, v in rows:
        try:
            out[k] = json.loads(v)
        except ValueError:
            continue          # a hand-corrupted row reads as absent, not as a crash
    return out


def user_config_put(user, pairs, only_absent=False):
    """Write `pairs` ({key: value}) for one account; return the keys actually
    written, in one transaction.

    `only_absent` is the device->account migration's whole safety property, and
    it is a single INSERT OR IGNORE against the (user,key) primary key rather
    than a read-then-write in Python. That matters: two devices logging in at
    the same second would both read "account has nothing" and both write, and
    the later one would silently overwrite a value the user had already picked
    on the first. SQLite decides it instead, per row, atomically - so "never
    overwrite existing account config" holds under a race, not just in the
    happy path."""
    import datetime
    now = datetime.datetime.now().isoformat(timespec="seconds")
    verb = "INSERT OR IGNORE" if only_absent else "INSERT OR REPLACE"
    written = []
    with conn() as c:
        for k, v in pairs.items():
            cur = c.execute(
                verb + " INTO user_config(user,key,value,updated_at) VALUES(?,?,?,?)",
                (user, k, json.dumps(v), now))
            if cur.rowcount:
                written.append(k)
    if written:
        bump()            # other open devices re-render on the next SSE tick
    return written


def user_config_drop_user(user):
    """Delete every config row for an account. Called from auth.delete_user:
    the rows key on the NAME, so without this a later account created with the
    same name would silently inherit a stranger's profile."""
    with conn() as c:
        cur = c.execute("DELETE FROM user_config WHERE user=?", (user,))
        n = cur.rowcount
    if n:
        bump()
    return n


def user_config_users():
    """Accounts that hold at least one config row. The rename guard reads this
    (userconfig.rename_block_reason) - derived from the table, never a flag."""
    return [r[0] for r in conn().execute(
        "SELECT DISTINCT user FROM user_config").fetchall()]


# -- project config --------------------------------------------------------
# Same division of labour as user_config above: rows, atomicity and the version
# bump here; the whitelist, the bounds and the resolution chain one layer up in
# spine/storage/projectconfig.py.

def project_config_get(project):
    """Every STORED row for this project, {key: decoded value}. Absent keys are
    absent - resolving them against the workspace is projectconfig.py's job, so
    a caller can always tell "this project chose it" from "nobody chose"."""
    rows = conn().execute(
        "SELECT key,value FROM project_config WHERE project=?", (project,)).fetchall()
    out = {}
    for k, v in rows:
        try:
            out[k] = json.loads(v)
        except ValueError:
            continue          # a hand-corrupted row reads as absent, not as a crash
    return out


def project_config_put(project, pairs):
    """Write `pairs` ({key: value}) for one project in one transaction; return
    the keys actually written."""
    import datetime
    now = datetime.datetime.now().isoformat(timespec="seconds")
    written = []
    with conn() as c:
        for k, v in pairs.items():
            c.execute(
                "INSERT OR REPLACE INTO project_config(project,key,value,updated_at)"
                " VALUES(?,?,?,?)", (project, k, json.dumps(v), now))
            written.append(k)
    if written:
        bump()            # other open devices re-render on the next SSE tick
    return written


def project_config_delete(project, keys):
    """Remove rows so their keys INHERIT again. This is the whole reason a
    cleared value is a DELETE and not a stored null: with a null row the chain
    would have to treat one particular value as "means absent", and every
    consumer would have to agree on which. Deleting makes "absent" a property
    of the table."""
    n = 0
    with conn() as c:
        for k in keys:
            cur = c.execute(
                "DELETE FROM project_config WHERE project=? AND key=?", (project, k))
            n += cur.rowcount
    if n:
        bump()
    return n


def project_config_drop(project):
    """Delete every config row for one project. Called when a project record is
    removed - the rows key on the repo path, so without this a repo later added
    back at the same path would silently inherit a stale overlay."""
    with conn() as c:
        cur = c.execute("DELETE FROM project_config WHERE project=?", (project,))
        n = cur.rowcount
    if n:
        bump()
    return n


def project_config_projects():
    """Projects that hold at least one config row. Derived from the table, never
    a flag - the harness screen counts overlays with it."""
    return [r[0] for r in conn().execute(
        "SELECT DISTINCT project FROM project_config").fetchall()]


# -- boards ----------------------------------------------------------------
# Same division of labour as user_config above: rows, atomicity and the version
# bump here; the record shape, the bounds and every ownership rule one layer up
# in spine/storage/boards.py. A board is stored as its own JSON blob, so this
# layer never has to know what a column is.

def _board_row(r):
    """(json) -> the board dict, or None if the blob is unreadable. `id`/`owner`
    are re-asserted from the indexed columns rather than trusted from the blob:
    they are what every ownership decision reads, and a row whose two copies
    ever disagreed must resolve to the one the WHERE clause matched on."""
    try:
        b = json.loads(r[2])
    except ValueError:
        return None
    if not isinstance(b, dict):
        return None
    b["id"], b["owner"] = r[0], r[1]
    return b


def board_get(bid):
    r = conn().execute(
        "SELECT id,owner,json FROM boards WHERE id=?", (bid,)).fetchone()
    return _board_row(r) if r else None


def boards_owned_by(owner):
    """Every board belonging to one account, oldest first. `owner=""` is the
    shared default board - it is a normal row, not a special case here."""
    rows = conn().execute(
        "SELECT id,owner,json FROM boards WHERE owner=? ORDER BY updated_at,id",
        (owner,)).fetchall()
    return [b for b in (_board_row(r) for r in rows) if b]


def _board_write(board, verb):
    import datetime
    now = datetime.datetime.now().isoformat(timespec="seconds")
    with conn() as c:
        cur = c.execute(
            verb + " INTO boards(id,name,owner,json,updated_at) VALUES(?,?,?,?,?)",
            (board["id"], board.get("name") or "", board.get("owner") or "",
             json.dumps(board), now))
        n = cur.rowcount
    if n:
        bump()            # other open devices re-render on the next SSE tick
    return bool(n)


def board_put(board):
    """Create or replace one board row. Last-write-wins on the WHOLE row, which
    PRD section 8 accepts for v1: a personal board has exactly one editor and
    the default board is owner-only, so the collision surface is one human."""
    return _board_write(board, "INSERT OR REPLACE")


def board_insert_absent(board):
    """Seed a board only if its id is free; True when this call created it.

    INSERT OR IGNORE against the primary key, not a read-then-write: two daemon
    threads reaching the default-board seed at the same moment (boot and a
    first /me) would both read "absent" and both write, and the second would
    silently reset the labels the migration had just produced. SQLite decides
    it, so "seeded exactly once" holds under a race - the same property
    user_config_put's only_absent buys for the device->account migration."""
    return _board_write(board, "INSERT OR IGNORE")


def board_delete(bid):
    with conn() as c:
        n = c.execute("DELETE FROM boards WHERE id=?", (bid,)).rowcount
    if n:
        bump()
    return bool(n)


def boards_drop_user(owner):
    """Delete every board an account owns. Called from auth.delete_user for the
    same reason user_config_drop_user is: boards key on the NAME, so a later
    account created with that name would otherwise inherit a stranger's views.
    `owner=""` is never passed here - the default board outlives its creator."""
    if not owner:
        return 0
    with conn() as c:
        n = c.execute("DELETE FROM boards WHERE owner=?", (owner,)).rowcount
    if n:
        bump()
    return n


def board_owners():
    """Accounts that own at least one board. The rename guard reads this -
    derived from the table, never a stored flag."""
    return [r[0] for r in conn().execute(
        "SELECT DISTINCT owner FROM boards WHERE owner!=''").fetchall()]


# -- events --------------------------------------------------------------

def event_insert(row):
    # `id` is deliberately left IN `extra` too (not excluded like ts/kind/track)
    # so events_all()'s json.loads(data) round-trip still surfaces it on the
    # reconstructed dict with no change to that function - it is stored twice
    # on purpose, once as an indexed column for the UNIQUE constraint, once in
    # the blob for read-back fidelity.
    extra = {k: v for k, v in row.items() if k not in ("ts", "kind", "track")}
    with conn() as c:
        # OR IGNORE: a genuine id conflict (this exact event already present -
        # _reconcile_events re-inserting on a later boot, say) is a no-op, not
        # a duplicate row. row.get("id") is None for anything that bypassed
        # events.emit()'s id generation; SQLite treats every NULL in a UNIQUE
        # index as distinct, so those never collide with each other either.
        c.execute("INSERT OR IGNORE INTO events(id,ts,kind,track,data) VALUES(?,?,?,?,?)",
                  (row.get("id"), row.get("ts"), row.get("kind"), row.get("track"),
                   json.dumps(extra)))
    bump()


def _reconcile_events():
    """Boot-time healer: fold into the db any event that made it into
    events.jsonl but whose write-through (events.emit's best-effort
    db.event_insert, wrapped in try/except) was dropped - a disk hiccup, a WAL
    lock timeout. Before `id` existed this was impossible to do safely: the
    file and the table shared no key, so a naive re-import could only either
    skip everything (miss real drops, the bug this closes) or duplicate
    everything (the bug A4 fixed). INSERT OR IGNORE on a UNIQUE id makes
    re-scanning safe, so this can now run on every boot rather than once.

    Cheap by construction: a checkpoint file remembers how many BYTES of
    events.jsonl were already reconciled, so a boot only scans what was
    appended since the last one, not the whole history every time. A file
    that shrank (rotated, truncated) resets the checkpoint to 0 rather than
    skipping the difference."""
    ej = os.path.join(ROOT, "events.jsonl")
    if not os.path.exists(ej):
        return
    ckpt = ej + ".synced"
    start = 0
    if os.path.exists(ckpt):
        try:
            start = int(open(ckpt, encoding="utf-8").read().strip() or "0")
        except ValueError:
            start = 0
    if start > os.path.getsize(ej):
        start = 0
    c = conn()
    healed = 0
    with open(ej, encoding="utf-8") as f:
        f.seek(start)
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            rid = r.get("id")
            if not rid:
                continue   # pre-id-era row - nothing to reconcile it against
            extra = {k: v for k, v in r.items() if k not in ("ts", "kind", "track")}
            cur = c.execute(
                "INSERT OR IGNORE INTO events(id,ts,kind,track,data) VALUES(?,?,?,?,?)",
                (rid, r.get("ts"), r.get("kind"), r.get("track"), json.dumps(extra)))
            if cur.rowcount:
                healed += 1
        end = f.tell()
    c.commit()
    with open(ckpt, "w", encoding="utf-8") as f:
        f.write(str(end))
    if healed:
        print("db: reconciled %d event(s) the write-through had dropped" % healed)

def events_all():
    rows = conn().execute(
        "SELECT ts,kind,track,data FROM events ORDER BY seq").fetchall()
    out = []
    for ts, kind, track, data in rows:
        r = {"ts": ts, "kind": kind, "track": track}
        try:
            r.update(json.loads(data))
        except ValueError:
            pass
        out.append(r)
    return out
