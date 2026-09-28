# -*- coding: utf-8 -*-
"""Root cause pinned: the Microsoft Store (MSIX) build of the Windows desktop
app installs into a READ-ONLY WindowsApps folder, but the Python daemon used
to resolve EVERY writable-state path (sqlite db, settings.json, recordings,
caches, session/auth files, ...) relative to daemon.paths.DAEMON_ROOT - which
for an MSIX install IS that read-only install directory. Every write would
have raised PermissionError the moment a Store user touched the app.

THE FIX (see daemon/paths.py's own docstring): a new daemon.paths.DATA_ROOT
constant, identical to DAEMON_ROOT (a complete no-op) unless the environment
carries HELMDECK_DATA_ROOT - which only happens when the Electron shell
detects it is running as an MSIX package and points the daemon at a writable
per-user folder instead. Every writable-state module (spine.storage.db,
spine.storage.events, spine.ops.runs, and the rest of the sweep) now imports
DATA_ROOT instead of DAEMON_ROOT for the paths it WRITES.

Verified to FAIL against the pre-fix code: daemon.paths had no DATA_ROOT
attribute at all, so setting HELMDECK_DATA_ROOT changed nothing - db.DBPATH
(and every sibling state path) stayed glued to DAEMON_ROOT, i.e. the
read-only install dir on an MSIX box.

Hermetic and cheap - no daemon boot, no network, no live db. The two
consumer modules under test (spine.storage.db, spine.storage.events,
spine.ops.runs) are reloaded, never merely re-imported, because
HELMDECK_DATA_ROOT is read once at daemon.paths import time (its own
docstring) and each consumer binds its own ROOT-alias from that at ITS OWN
import time too (this repo's documented no-shared-helper pattern - every
module joins its state path onto a name it imported itself, so sandboxing
happens per-module, never via a central helper). Reloading daemon.paths
first, then each consumer, reproduces a fresh process boot under each
scenario.

Never opens db.conn() (only inspects the db.DBPATH string), so
spine.storage.db's own _refuse_live_db_from_tests() guard - which fires on
conn(), not on reading the constant - is never tripped even though this
process argv lives under ops/tests/ and, in the "unset" half of this test,
db.DBPATH legitimately equals the real daemon/helmdeck.db path.

Run: py -3.12 ops/tests/test_msix_data_root.py
"""
import importlib
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

_fails = []


def check(cond, msg):
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        _fails.append(msg)


def _reload_all():
    """Reload daemon.paths (recomputes DATA_ROOT from the CURRENT
    environment), then every consumer under test, so each rebinds its own
    ROOT-alias from the fresh value - exactly what happens on a real process
    start, never a shared helper anyone could forget to call."""
    import daemon.paths
    importlib.reload(daemon.paths)
    import spine.storage.db as db
    importlib.reload(db)
    import spine.storage.events as events
    importlib.reload(events)
    import spine.ops.runs as runs
    importlib.reload(runs)
    return daemon.paths, db, events, runs


def main():
    print("MSIX data root: writable state follows HELMDECK_DATA_ROOT, never the read-only install dir")

    # 1. DEFAULT (unset) - the backward-compat proof. Every existing build
    #    (dev, NSIS, mas) never sets this env var, so every writable-state
    #    path must resolve EXACTLY where it always has: under DAEMON_ROOT.
    os.environ.pop("HELMDECK_DATA_ROOT", None)
    paths, db, events, runs = _reload_all()
    check(paths.DATA_ROOT == paths.DAEMON_ROOT,
          "unset HELMDECK_DATA_ROOT: DATA_ROOT == DAEMON_ROOT exactly (a no-op)")
    check(os.path.dirname(os.path.abspath(db.DBPATH)) == os.path.abspath(paths.DAEMON_ROOT),
          "unset: db.DBPATH still resolves under the real DAEMON_ROOT")
    check(os.path.dirname(os.path.abspath(events.SET)) == os.path.abspath(paths.DAEMON_ROOT),
          "unset: events.SET (settings.json) still resolves under the real DAEMON_ROOT")
    check(os.path.dirname(os.path.abspath(events.RELAY_FEED)) == os.path.abspath(paths.DAEMON_ROOT),
          "unset: events.RELAY_FEED still resolves under the real DAEMON_ROOT")
    check(os.path.dirname(os.path.abspath(runs.REC)) == os.path.abspath(paths.DAEMON_ROOT),
          "unset: runs.REC (recordings/) still resolves under the real DAEMON_ROOT")

    # 2. SET (the MSIX case) - the Electron shell detected a Store package
    #    (its install dir is read-only) and pointed the daemon at a writable
    #    per-user folder instead.
    tmp = tempfile.mkdtemp(prefix="hd-msix-dataroot-")
    os.environ["HELMDECK_DATA_ROOT"] = tmp
    try:
        paths, db, events, runs = _reload_all()
        check(paths.DATA_ROOT == tmp,
              "set: daemon.paths.DATA_ROOT picks up HELMDECK_DATA_ROOT")
        check(paths.DAEMON_ROOT != tmp,
              "set: DAEMON_ROOT is UNCHANGED (still the real install/code dir) - only DATA_ROOT moves")
        check(os.path.dirname(os.path.abspath(db.DBPATH)) == os.path.abspath(tmp),
              "set: db.DBPATH moves under HELMDECK_DATA_ROOT, off the read-only install dir")
        check(os.path.dirname(os.path.abspath(db._LEGACY_DB)) == os.path.abspath(tmp),
              "set: db._LEGACY_DB (swarmdeck.db migration source) moves too")
        check(os.path.dirname(os.path.abspath(events.SET)) == os.path.abspath(tmp),
              "set: events.SET (settings.json) moves under HELMDECK_DATA_ROOT")
        check(os.path.dirname(os.path.abspath(events.RELAY_FEED)) == os.path.abspath(tmp),
              "set: events.RELAY_FEED moves under HELMDECK_DATA_ROOT")
        check(os.path.dirname(os.path.abspath(runs.REC)) == os.path.abspath(tmp),
              "set: runs.REC (recordings/) moves under HELMDECK_DATA_ROOT")
    finally:
        # Leave every reloaded module pointed at the real root again - good
        # hygiene even though this script always runs as its own process.
        os.environ.pop("HELMDECK_DATA_ROOT", None)
        _reload_all()

    print()
    if _fails:
        print("FAILED: %d" % len(_fails))
        for f in _fails:
            print("  - " + f)
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
