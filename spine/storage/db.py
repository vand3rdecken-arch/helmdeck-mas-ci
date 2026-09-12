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
    # Process TEMPLATES (config-consolidation, process/config split 2026-09-03,
    # owner decree: "das ist auch config" - the reusable step SHAPE of a
    # process, deliberately separate from the `processes` table above, which
    # is a RUN (request/client/due/status/cost/steps-with-runtime-fields).
    # A template's `data` is a CLOSED doc {name, description, steps:[{title,
    # desc, mode, days}]} - runtime fields (done/lane/track/state/ready/
    # auto_dispatched) never enter this table; see cells/engineer/chains/
    # processes.py's _clean_template_steps, the one writer. Exported by
    # /harness/export like every other config plane; a run is not.
    c.execute("""CREATE TABLE IF NOT EXISTS process_template(
        id TEXT PRIMARY KEY, data TEXT NOT NULL,
        updated_at TEXT NOT NULL, actor TEXT NOT NULL)""")
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
    # WORKSPACE config rows (config-consolidation, owner decree 2026-09-03:
    # "alles was harness config ist gehoert ins db"). One row per TOP-LEVEL
    # settings key (capacity, policy, pm, relay, ...), value = the JSON
    # subtree. Same shape as user_config/project_config above, one layer UP
    # the resolution chain - this is the store events.settings() overlays on
    # its code defaults. Shape/validation stay in spine/storage/events.py.
    c.execute("""CREATE TABLE IF NOT EXISTS workspace_config(
        key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    # The composed live POLICY document (policy_live.json's successor), one
    # row by construction. The tracked policy_seed.json stays a FILE - it is
    # the code default; this row is the current composed value policy.swap()
    # mutates. Whole-doc rather than per-key: policy.load() always reads the
    # complete document and swap() rewrites it under its own lock, so rows
    # per key would only invent merge questions nothing asks.
    c.execute("""CREATE TABLE IF NOT EXISTS policy_doc(
        id TEXT PRIMARY KEY CHECK(id='live'),
        json TEXT NOT NULL, version INTEGER NOT NULL, updated_at TEXT NOT NULL)""")
    # HENRY'S MEMORY, store of record (same decree: harness config must be
    # exportable - "wenn es hier bleibt erreicht es niemanden"). One row per
    # note. No filesystem surface exists for it at all: Henry writes via a
    # <memory-save>/<memory-delete> sentinel in his own turn output, parsed
    # by cells/copilot/chat/copilot_memory.py and applied here directly (one
    # event per mutation, the one owner). The brief digest, /harness/export,
    # and a full-note read (ops/tools/henry_memory_get.py) all read THIS.
    c.execute("""CREATE TABLE IF NOT EXISTS memory(
        name TEXT PRIMARY KEY, content TEXT NOT NULL,
        updated_at TEXT NOT NULL, actor TEXT NOT NULL)""")
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
    _apply_migrations()
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
        from cells.engineer.cards import sessions
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
    numbered sibling instead.

    Lands in ROOT/backups/ (config-consolidation phase 7: daemon/ had 30+
    loose *.imported.N files at its root before this) rather than beside the
    original - `backups/` already existed as a concept (checkpoints.py's
    restore points live there too), this just gives every archived legacy
    file the same home instead of littering the directory it was retired
    from."""
    bdir = os.path.join(os.path.dirname(path) or ".", "backups")
    os.makedirs(bdir, exist_ok=True)
    dest = os.path.join(bdir, os.path.basename(path) + ".imported")
    if os.path.exists(dest):
        n = 2
        while os.path.exists("%s.%d" % (dest, n)):
            n += 1
        dest = "%s.%d" % (dest, n)
    os.replace(path, dest)
    return dest


# config-consolidation phase 7 (owner decree: daemon/ was ~20 loose json/
# jsonl files with no grouping). Every (old flat name, new subfolder) this
# daemon used to write straight into ROOT, now written into ROOT/state or
# ROOT/content by the modules themselves (daemon.paths.state_dir()/
# content_dir()) - this list is ONLY the one-time physical move of a file
# that already exists at the old flat path, run once at boot before any
# module gets a chance to write its own fresh copy at the NEW path (which
# would otherwise make the move look like data loss: old file sits unread
# at the flat path, new module starts a fresh empty one next to it).
_RELOCATE_STATE = ("sessions.json", "copilot_sessions.json", "copilot_log.json",
                   "copilot_stats.json", "copilot_models.json", "driver_pids.json",
                   "recorder_pids.json", "models_cache.json", "escalations.jsonl")
# board_directives.json is DELIBERATELY NOT here: unlike everything above it
# is TRACKED, real repo data (cardadmin.py: "shipped as repo DATA" - policy
# is data, this is a card worker's board-change deliverable applied once at
# boot), the same reason policy_seed.json also stays flat at ROOT. Moving a
# git-tracked file into an otherwise git-ignored state/ folder would need a
# .gitignore carve-out for one file inside an ignored directory - messier
# than just leaving it where its git history already is.
_RELOCATE_CONTENT = ("henry_memory", "copilot_runs", "voice_cache", "models_stt")


def _relocate_daemon_layout():
    """Move each known flat file/dir into state/ or content/ if the OLD path
    exists and the NEW one does not - archive-don't-clobber, same spirit as
    db._archive() elsewhere in this module, but a plain move (not a rename
    to .imported): these are not retired formats, they are the SAME file at
    a new address, and every module above already points at the new address
    on its next read/write. Both destination dirs are created here since no
    individual module creates its own before writing (see auth.py/copilot.py
    etc. - unchanged from their pre-move behaviour of assuming the flat ROOT
    already existed)."""
    state_dir = os.path.join(ROOT, "state")
    content_dir = os.path.join(ROOT, "content")
    os.makedirs(state_dir, exist_ok=True)
    os.makedirs(content_dir, exist_ok=True)
    for name in _RELOCATE_STATE:
        old, new = os.path.join(ROOT, name), os.path.join(state_dir, name)
        if os.path.exists(old) and not os.path.exists(new):
            try:
                os.replace(old, new)
                print("db: relocated %s -> state/" % name)
            except OSError as e:
                print("db: relocate %s failed:" % name, e)
    for name in _RELOCATE_CONTENT:
        old, new = os.path.join(ROOT, name), os.path.join(content_dir, name)
        if os.path.isdir(old) and not os.path.exists(new):
            try:
                import shutil
                shutil.move(old, new)
                print("db: relocated %s/ -> content/" % name)
            except OSError as e:
                print("db: relocate %s/ failed:" % name, e)


def _migrate():
    # BELT+SUSPENDERS: every import below reads/archives files under `ROOT`,
    # while the db itself lives at `DBPATH`. A sandbox that repoints only one
    # of the two (measured 2026-09-03: a test patched DBPATH but left ROOT
    # bound to the real daemon.paths.DAEMON_ROOT from db.py's own import time)
    # would run this against an EMPTY sandboxed table but the REAL daemon's
    # settings.json/events.jsonl/tracks.json - archiving live data a test
    # never meant to touch. If the two disagree, refuse outright: a skipped
    # migration is recoverable (the files just stay put), a wrong-target one
    # is not.
    if os.path.dirname(os.path.abspath(DBPATH)) != os.path.abspath(ROOT):
        print("db: _migrate() SKIPPED - ROOT (%s) and DBPATH's directory (%s) "
              "disagree; a caller repointed one without the other" %
              (ROOT, os.path.dirname(DBPATH)))
        return
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
    # daemon/henry_memory/*.md -> memory table, store of record (config-
    # consolidation phase 5, owner decree: "das muss ins db... wenn es hier
    # bleibt erreicht es niemanden"; flipped fully DB-authoritative, then
    # (2026-09-11) the directory itself removed - no filesystem surface for
    # memory exists at all anymore, full notes are read via
    # ops/tools/henry_memory_get.py, straight from this table). FIRST-START
    # ONLY, same rule as every migration above: an empty table + files on
    # disk means this install predates the db store. This import is the
    # one-time bridge for notes written before either the db or the sentinel
    # write path (cells/copilot/chat/copilot_memory.py) existed; the
    # directory is never archived or written to again afterward.
    mdir = os.path.join(ROOT, "henry_memory")
    if (os.path.isdir(mdir)
            and c.execute("SELECT 1 FROM memory LIMIT 1").fetchone() is None):
        try:
            n = 0
            for fname in os.listdir(mdir):
                if not fname.endswith(".md"):
                    continue
                fpath = os.path.join(mdir, fname)
                try:
                    with open(fpath, encoding="utf-8") as f:
                        content = f.read()
                except OSError:
                    continue
                memory_put(fname[:-3], content, actor="migration")
                n += 1
            if n:
                print("db: imported %d memory notes from henry_memory/" % n)
        except Exception as e:
            print("db: memory import failed:", e)
    # settings.json -> workspace_config (config-consolidation phase 2,
    # owner decree 2026-09-03). FIRST-START ONLY, same rule as events above:
    # an empty table + an existing file means this install predates the db
    # store; a populated table means the db is already the truth and the file
    # (if any reappeared) is not - never re-import over live config. One row
    # per top-level key; the file is archived, not deleted.
    sj = os.path.join(ROOT, "settings.json")
    if (os.path.exists(sj)
            and c.execute("SELECT 1 FROM workspace_config LIMIT 1").fetchone() is None):
        try:
            with open(sj, encoding="utf-8") as f:
                sdoc = json.load(f)
            if isinstance(sdoc, dict):
                import datetime
                now = datetime.datetime.now().isoformat(timespec="seconds")
                with c:
                    for k, v in sdoc.items():
                        c.execute("INSERT OR REPLACE INTO workspace_config"
                                  "(key,value,updated_at) VALUES(?,?,?)",
                                  (k, json.dumps(v), now))
                _archive(sj)
                print("db: imported %d settings keys from settings.json" % len(sdoc))
        except Exception as e:
            print("db: settings import failed:", e)

    # LAST, on purpose: every migration above reads its own flat ROOT path
    # (settings.json, henry_memory/, ...) BEFORE this runs, so a fresh
    # install's one-time content import still finds its source. Only once
    # every migration has had its look does the physical layout move.
    _relocate_daemon_layout()

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


# -- workspace config -------------------------------------------------------
# Same division of labour as user_config above: rows, atomicity and the
# version bump here; defaults, shape and the diff/audit trail one layer up in
# spine/storage/events.py (settings()/save_settings() keep being THE api -
# only their backing store lives here now).

def workspace_config_all():
    """Every stored workspace key, {key: decoded subtree}. Absent keys are
    absent - overlaying them on the code defaults is events.settings()'s job.
    Tolerant of a missing table (a caller racing ahead of init() reads empty,
    which resolves to pure defaults - today's behaviour for a missing file)."""
    try:
        rows = conn().execute("SELECT key,value FROM workspace_config").fetchall()
    except sqlite3.OperationalError:
        return {}
    out = {}
    for k, v in rows:
        try:
            out[k] = json.loads(v)
        except ValueError:
            continue          # a hand-corrupted row reads as absent, not a crash
    return out


def workspace_config_replace(doc):
    """Replace the WHOLE store with `doc` ({key: subtree}) in one transaction.
    The wholesale write path: /harness/import and test/sandbox seeding - the
    db-era equivalent of overwriting settings.json."""
    import datetime
    now = datetime.datetime.now().isoformat(timespec="seconds")
    with conn() as c:
        c.execute("DELETE FROM workspace_config")
        for k, v in (doc or {}).items():
            c.execute("INSERT INTO workspace_config(key,value,updated_at) "
                      "VALUES(?,?,?)", (k, json.dumps(v), now))
    bump()


def workspace_config_put(pairs):
    """Write `pairs` ({top-level key: full subtree}) in one transaction.
    A key whose subtree is None is DELETED (absent means default, the same
    absent-means-inherited rule project_config lives by)."""
    import datetime
    now = datetime.datetime.now().isoformat(timespec="seconds")
    with conn() as c:
        for k, v in pairs.items():
            if v is None:
                c.execute("DELETE FROM workspace_config WHERE key=?", (k,))
            else:
                c.execute(
                    "INSERT OR REPLACE INTO workspace_config(key,value,updated_at) "
                    "VALUES(?,?,?)", (k, json.dumps(v), now))
    bump()


# -- policy doc -------------------------------------------------------------

def policy_doc_get():
    """The composed live policy document, or None when nothing was ever
    composed (first boot: policy.load() then composes from the tracked seed
    file and writes it here)."""
    try:
        r = conn().execute("SELECT json FROM policy_doc WHERE id='live'").fetchone()
    except sqlite3.OperationalError:
        return None
    if not r:
        return None
    try:
        doc = json.loads(r[0])
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def policy_doc_put(doc):
    """Store the whole composed document. Locking/authority live in
    spine/auth/policy.py (its _LOCK wraps every load-mutate-put cycle)."""
    import datetime
    now = datetime.datetime.now().isoformat(timespec="seconds")
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO policy_doc(id,json,version,updated_at) "
                  "VALUES('live',?,?,?)",
                  (json.dumps(doc), int(doc.get("version", 1)), now))
    bump()


# -- memory (Henry's notes, store of record) --------------------------------

def memory_all():
    """{name: {content, updated_at, actor}} for every note. The only store -
    the brief digest, /harness/export, and ops/tools/henry_memory_get.py all
    read this directly; there is no filesystem cache in front of it."""
    try:
        rows = conn().execute(
            "SELECT name,content,updated_at,actor FROM memory").fetchall()
    except sqlite3.OperationalError:
        return {}
    return {r[0]: {"content": r[1], "updated_at": r[2], "actor": r[3]}
            for r in rows}


def memory_put(name, content, actor="henry", account="owner"):
    """`account` (ledger step 4): whose board the note belongs to. Every
    caller today is the owner's Henry; the column exists so a second account's
    notes never land in the same namespace, not because any caller passes it
    yet."""
    import datetime
    now = datetime.datetime.now().isoformat(timespec="seconds")
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO memory(name,content,updated_at,actor,account) "
                  "VALUES(?,?,?,?,?)", (name, content, now, actor, account))
    bump_chat()   # the memory rides Henry's stream, not the board's


def memory_delete(name):
    with conn() as c:
        cur = c.execute("DELETE FROM memory WHERE name=?", (name,))
        n = cur.rowcount
    if n:
        bump_chat()
    return n


# -- process templates (config, not a run) ----------------------------------
# Dumb storage, exactly like user_config above: no schema check, no defaults.
# cells/engineer/chains/processes.py owns the closed step shape - this layer
# only knows rows, atomicity and the version bump.

def process_template_all():
    """{id: {name, description, steps, updated_at, actor}} for every template."""
    try:
        rows = conn().execute(
            "SELECT id,data,updated_at,actor FROM process_template").fetchall()
    except sqlite3.OperationalError:
        return {}
    out = {}
    for tid, data, updated_at, actor in rows:
        try:
            doc = json.loads(data)
        except ValueError:
            continue          # a hand-corrupted row reads as absent, not a crash
        doc["updated_at"] = updated_at
        doc["actor"] = actor
        out[tid] = doc
    return out


def process_template_get(tid):
    r = conn().execute(
        "SELECT data,updated_at,actor FROM process_template WHERE id=?", (tid,)).fetchone()
    if not r:
        return None
    try:
        doc = json.loads(r[0])
    except ValueError:
        return None
    doc["updated_at"] = r[1]
    doc["actor"] = r[2]
    return doc


def process_template_put(tid, doc, actor="owner"):
    """Store one template doc (name/description/steps only - the caller's job
    to have already stripped anything else)."""
    import datetime
    now = datetime.datetime.now().isoformat(timespec="seconds")
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO process_template(id,data,updated_at,actor) "
                  "VALUES(?,?,?,?)", (tid, json.dumps(doc), now, actor))
    bump()


def process_template_delete(tid):
    with conn() as c:
        cur = c.execute("DELETE FROM process_template WHERE id=?", (tid,))
        n = cur.rowcount
    if n:
        bump()
    return bool(n)


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


def boards_all():
    """EVERY board row, shared default first then by owner. The audit read, not
    a render read: boards.for_user() is what a screen draws a board set from and
    it is scoped to one account by design, so nothing above it could ever see
    the table whole. spine/storage/configreview.py needs exactly that view to
    show which board-scoped values physically exist, and building it from
    board_owners() + boards_owned_by() would issue one query per account to
    reassemble a single table scan."""
    rows = conn().execute(
        "SELECT id,owner,json FROM boards ORDER BY owner,updated_at,id").fetchall()
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


# -- schema ledger (state-into-db phase A, 2026-09-12) ------------------------
# Until here every table was `CREATE TABLE IF NOT EXISTS` at boot and the one
# column ever added (events.id) was guarded by hand with PRAGMA table_info.
# `PRAGMA user_version` was 0 on every install - nothing could say what shape
# a db was on, and no phase of the files->db move could be applied exactly
# once. The ledger below is the ONE place a shape change lives: a numbered
# step, applied in its own transaction the first time a db below that version
# boots, recorded in `schema_migrations` and mirrored into user_version.
#
# Rules: a step is idempotent on a FRESH db (init()'s CREATE TABLEs give the
# base shape, the step adds to it) and on an OLD db; a step that imports a
# file verifies its row count and archives the file with _archive() - never
# deletes; the old writer of that file dies in the same commit. A step never
# rewrites a blob's shape - scoping columns over `data` are VIRTUAL generated
# columns (json_extract), so every existing writer keeps writing (id, data)
# and every existing reader keeps json.loads(data), while WHERE/INDEX finally
# see lane/status/project_id/... as real columns.

_MIGRATIONS = []


def _migration(version, name):
    def deco(fn):
        _MIGRATIONS.append((version, name, fn))
        return fn
    return deco


def _has_column(c, table, col):
    return col in {r[1] for r in c.execute("PRAGMA table_info(%s)" % table)}


def _add_json_column(c, table, col, path=None, index=True):
    """A VIRTUAL generated column over the row's JSON blob + its index. The
    writer never learns about it; SQLite evaluates json_extract on read and
    keeps the index current on every INSERT OR REPLACE."""
    if not _has_column(c, table, col):
        c.execute("ALTER TABLE %s ADD COLUMN %s TEXT GENERATED ALWAYS AS "
                  "(json_extract(data,'$.%s')) VIRTUAL" % (table, col, path or col))
    if index:
        c.execute("CREATE INDEX IF NOT EXISTS %s_%s ON %s(%s)" % (table, col, table, col))


@_migration(1, "ledger-baseline")
def _m1(c):
    """Records that every table init() creates existed at this point. Nothing
    to do - the row in schema_migrations IS the fact."""


@_migration(2, "tracks-scope-columns")
def _m2(c):
    """Audit finding A2: cards were (id, data) with owner/repo/project/lane/
    status inside the JSON, so every board query loaded all rows and filtered
    in Python. Generated columns + indexes over the same blob."""
    for col in ("project_id", "repo", "lane", "status", "archived", "created", "updated", "client"):
        _add_json_column(c, "tracks", col)
    c.execute("CREATE INDEX IF NOT EXISTS tracks_lane_status ON tracks(lane, status)")
    for col in ("status", "client", "template_id"):
        _add_json_column(c, "processes", col)
    for col in ("repo", "status", "client"):
        _add_json_column(c, "projects", col)


@_migration(3, "workspace-config-drop-dead-users")
def _m3(c):
    """Audit finding A4: a `users` row with plaintext account tokens sat in
    workspace_config although events.py has documented it as a dead mirror of
    auth.py's users.json since config-consolidation phase 4 - nothing read it,
    nothing wrote it, it just kept a secret in the config table. Deleted; the
    accounts have exactly one owner (spine/auth/auth.py)."""
    c.execute("DELETE FROM workspace_config WHERE key='users'")


@_migration(4, "memory-account")
def _m4(c):
    """Data model 2.1: Henry's notes get an account column (default 'owner',
    which is what every existing row is - measured: 47 rows, all actor=henry
    on the owner's board) so a second account never shares them by accident."""
    if not _has_column(c, "memory", "account"):
        c.execute("ALTER TABLE memory ADD COLUMN account TEXT NOT NULL DEFAULT 'owner'")
    c.execute("CREATE INDEX IF NOT EXISTS memory_account ON memory(account)")


@_migration(5, "events-actor-utc-columns")
def _m5(c):
    """Audit finding A3: actor and at_utc lived only inside the blob. Virtual
    columns so audit queries (who/when in UTC) stop json-parsing 8k rows."""
    _add_json_column(c, "events", "actor")
    _add_json_column(c, "events", "at_utc")


def _file_steps_allowed():
    """The A7 guard, for ledger steps that import a file under ROOT: a caller
    that repointed DBPATH but not ROOT (or vice versa) gets the table but not
    the import, loudly - never a live file archived into a sandbox db."""
    ok = os.path.dirname(os.path.abspath(DBPATH)) == os.path.abspath(ROOT)
    if not ok:
        print("db: ledger file import SKIPPED - ROOT (%s) and DBPATH's directory (%s) disagree"
              % (ROOT, os.path.dirname(DBPATH)))
    return ok


def _import_jsonl(c, path, insert):
    """Stream a legacy .jsonl into the db via insert(c, rec) and archive it.
    Nothing-lost: the number of rows inserted must equal the number of
    parsable lines, else the step raises (rolled back, file untouched, retried
    next boot). Returns the count."""
    n_lines = n_rows = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            n_lines += 1
            n_rows += 1 if insert(c, rec) else 0
    if n_rows != n_lines:
        raise RuntimeError("import of %s: %d lines but %d rows inserted" % (path, n_lines, n_rows))
    _archive(path)
    print("db: imported %d rows from %s (archived)" % (n_rows, os.path.basename(path)))
    return n_rows


@_migration(6, "escalations-table")
def _m6(c):
    """Phase C: the escalation bus (spine/registry/escalations.py) was an
    append-only JSONL folded in full on EVERY list_open() - 1292 lines parsed
    per lane tick, per Henry pass, per PM question. Same records, same
    append-only law (no UPDATE/DELETE path - test_db_schema pins it), folded
    by one indexed query instead."""
    c.execute("""CREATE TABLE IF NOT EXISTS escalations(
        seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL, ts TEXT NOT NULL,
        event TEXT NOT NULL, kind TEXT, track TEXT, data TEXT NOT NULL)""")
    c.execute("CREATE INDEX IF NOT EXISTS esc_id ON escalations(id)")
    c.execute("CREATE INDEX IF NOT EXISTS esc_track ON escalations(track)")
    legacy = os.path.join(ROOT, "state", "escalations.jsonl")
    if os.path.exists(legacy) and _file_steps_allowed():
        def ins(c, r):
            _escalation_insert(c, r)
            return True
        _import_jsonl(c, legacy, ins)


def _escalation_insert(c, rec):
    extra = {k: v for k, v in rec.items() if k not in ("id", "ts", "event", "kind", "card")}
    c.execute("INSERT INTO escalations(id,ts,event,kind,track,data) VALUES(?,?,?,?,?,?)",
              (rec.get("id"), rec.get("ts") or "", rec.get("event") or "", rec.get("kind"),
               rec.get("card"), json.dumps(extra, ensure_ascii=False)))


def escalation_append(rec):
    """ONE row per bus record (open/attempt/note/decision). Append-only."""
    with conn() as c:
        _escalation_insert(c, rec)
    bump()


def escalations_rows():
    """Every record in bus order, as the dicts escalations.py folds - the
    `card` key is the track column, everything else rides in data."""
    rows = conn().execute(
        "SELECT id,ts,event,kind,track,data FROM escalations ORDER BY seq").fetchall()
    out = []
    for rid, ts, ev, kind, track, data in rows:
        r = {"id": rid, "ts": ts, "event": ev}
        if kind is not None:
            r["kind"] = kind
        r["card"] = track
        try:
            r.update(json.loads(data))
        except ValueError:
            pass
        out.append(r)
    return out


def schema_head():
    """The highest ledger version this code knows - what user_version must
    equal after init() on any install."""
    return max(v for v, _, _ in _MIGRATIONS) if _MIGRATIONS else 0


def schema_applied():
    """[(version, name, applied_at)] as recorded in the db, ascending."""
    try:
        return conn().execute(
            "SELECT version,name,applied_at FROM schema_migrations ORDER BY version").fetchall()
    except sqlite3.OperationalError:
        return []


def _apply_migrations():
    import datetime
    c = conn()
    c.execute("""CREATE TABLE IF NOT EXISTS schema_migrations(
        version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)""")
    c.commit()
    have = {r[0] for r in c.execute("SELECT version FROM schema_migrations")}
    for version, name, fn in sorted(_MIGRATIONS):
        if version in have:
            continue
        # One transaction per step: a step that raises leaves the db exactly
        # as it was AND unrecorded, so the next boot retries it - never a
        # half-applied shape with a ledger row claiming otherwise.
        c.execute("BEGIN")
        try:
            fn(c)
            c.execute("INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",
                      (version, name, datetime.datetime.now().isoformat(timespec="seconds")))
            c.execute("PRAGMA user_version=%d" % version)
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
        print("db: schema %d %s applied" % (version, name))


# -- scoped card queries (over the generated columns of migration 2) ----------

def tracks_where(**eq):
    """Cards matching every column=value given (lane, status, project_id,
    repo, archived, client) - an indexed WHERE instead of tracks_all() +
    Python filter. Values are compared as the JSON text json_extract yields
    (booleans arrive as 1/0)."""
    if not eq:
        return tracks_all()
    cols = ("project_id", "repo", "lane", "status", "archived", "created", "updated", "client")
    bad = [k for k in eq if k not in cols]
    if bad:
        raise ValueError("tracks_where: no such scope column %s" % bad)
    where = " AND ".join("%s=?" % k for k in eq)
    rows = conn().execute("SELECT data FROM tracks WHERE %s ORDER BY id DESC" % where,
                          tuple(eq.values())).fetchall()
    return [json.loads(r[0]) for r in rows]
