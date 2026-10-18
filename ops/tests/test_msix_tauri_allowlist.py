# -*- coding: utf-8 -*-
"""The Tauri Store package carries ONLY source, never runtime state or secrets.

The Electron installer once shipped a Firebase private key, live session tokens and a sqlite
backup because its file list was a denylist. ops/deploy/build_msix_tauri.py uses the allowlist
electron-builder.yml settled on, then scans the stage and refuses to package. This pins both:

  1. staging the REAL repo copies source only: nothing from daemon/ subfolders (state, takeout,
     checkpoints, backups), no *.db, no settings.json/users.json, no __pycache__;
  2. the scanner refuses a stage with a secret-shaped NAME or CONTENT, and lets the harness's own
     policy json through.

Run: py -3.12 ops/tests/test_msix_tauri_allowlist.py
"""
import importlib.util
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
spec = importlib.util.spec_from_file_location("bmt", os.path.join(ROOT, "ops", "deploy", "build_msix_tauri.py"))
bmt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bmt)

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def main():
    stage = tempfile.mkdtemp(prefix="hd-msix-stage-")
    bmt.STAGE = stage
    try:
        n = bmt.copy_allowlist()
        files = []
        for dp, _, fs in os.walk(stage):
            files += [os.path.relpath(os.path.join(dp, f), stage).replace(os.sep, "/") for f in fs]
        check(n == len(files) and n > 100, "the real repo stages %d source files" % n)
        daemon_nested = [f for f in files if f.startswith("daemon/") and f.count("/") > 1]
        check(not daemon_nested, "nothing from daemon/ subfolders (state, takeout, checkpoints, backups): %s" % daemon_nested[:3])
        bad = [f for f in files if f.endswith((".db", ".sqlite", ".pyc")) or f.split("/")[-1] in ("settings.json", "users.json", "sessions.json")]
        check(not bad, "no db, cache or settings/users/sessions file: %s" % bad[:3])
        check(all(f.endswith((".py", ".md", ".json", ".txt")) for f in files), "only source extensions")
        check("daemon/swarm.py" in files, "...and the daemon launcher itself is there")
        check(bmt.scan_for_secrets() == [], "the real stage passes the secret scan")

        # plant secrets: the scanner must refuse
        os.makedirs(os.path.join(stage, "spine", "x"), exist_ok=True)
        open(os.path.join(stage, "spine", "x", "settings.json"), "w").write("{}")
        open(os.path.join(stage, "spine", "x", "fcm_service_account.json"), "w").write("{}")
        open(os.path.join(stage, "spine", "x", "notes.md"), "w").write("-----BEGIN RSA PRIVATE KEY-----\nabc\n")
        open(os.path.join(stage, "spine", "x", "cfg.json"), "w").write('{"private_key": "x"}')
        open(os.path.join(stage, "spine", "x", "backup.db"), "w").write("")
        hits = bmt.scan_for_secrets()
        for name in ("settings.json", "fcm_service_account.json", "notes.md", "cfg.json", "backup.db"):
            check(any(name in h for h in hits), "a planted %s is refused" % name)
        harness = [h for h in hits if "/harness/settings/" in h.replace(os.sep, "/")]
        check(not harness, "the harness's own policy json is not mistaken for a secret: %s" % harness)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    print()
    if _fails:
        print("=== %d FAILED ===" % len(_fails))
        return 1
    print("msix-tauri allowlist: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
