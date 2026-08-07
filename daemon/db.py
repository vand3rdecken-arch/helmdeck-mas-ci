# -*- coding: utf-8 -*-
"""SQLite storage - pays the json-storage debt. Tracks are rows (per-track
upserts in transactions kill the lost-update race), events are an indexed
append-only table (dashboard stops re-parsing history). WAL mode so readers
never block the writer. Existing tracks.json / events.jsonl are imported on
first start and renamed *.imported - originals preserved, per the safeguard
rule."""
import json, os, sqlite3, threading

ROOT = os.path.dirname(os.path.abspath(__file__))
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

def wait_version(last, timeout=25):
    """Block until the data version passes `last` (or timeout). SSE fuel."""
    with _version_cond:
        if _version > last:
            return _version
        _version_cond.wait(timeout)
        return _version

def current_version():
    return _version

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
    c.execute("""CREATE TABLE IF NOT EXISTS events(
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT, kind TEXT, track TEXT, data TEXT)""")
    c.execute("CREATE INDEX IF NOT EXISTS ev_kind ON events(kind)")
    c.execute("CREATE INDEX IF NOT EXISTS ev_track ON events(track)")
    c.commit()
    _migrate()
    if role == "daemon":
        _devalue_persisted_running()


def _devalue_persisted_running():
    """Paseo agent-archive parity (normalizeArchivedStatus): persisted 'running'/
    'initializing' is NEVER believed when a store is loaded - a fresh daemon by
    definition holds no live turn, so every running/gating card died with the
    previous process. Part of the store's daemon boot (not a step serve() must
    remember): delegating to sessions.sweep_zombies(min_idle_s=0) keeps the
    behaviour identical - bounce + resume note + live-session promotion."""
    try:
        import sessions
        zombies = sessions.sweep_zombies(min_idle_s=0)
        if zombies:
            print("db: devalued %d persisted running/gating card(s) at load: %s"
                  % (len(zombies), ", ".join(zombies)))
    except Exception as e:
        print("db: boot devaluation failed:", e)

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
            os.replace(tj, tj + ".imported")
            print("db: imported %d tracks from tracks.json" % len(tracks))
        except Exception as e:
            print("db: tracks import failed:", e)
    ej = os.path.join(ROOT, "events.jsonl")
    if os.path.exists(ej):
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
            os.replace(ej, ej + ".imported")
            print("db: imported %d events from events.jsonl" % n)
        except Exception as e:
            print("db: events import failed:", e)

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

# -- events --------------------------------------------------------------

def event_insert(row):
    extra = {k: v for k, v in row.items() if k not in ("ts", "kind", "track")}
    with conn() as c:
        c.execute("INSERT INTO events(ts,kind,track,data) VALUES(?,?,?,?)",
                  (row.get("ts"), row.get("kind"), row.get("track"),
                   json.dumps(extra)))
    bump()

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
