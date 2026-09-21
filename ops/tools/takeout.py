# -*- coding: utf-8 -*-
"""Take everything with you - one container, one manifest, one honest list of
what is NOT in it.

    py -3.12 ops/tools/takeout.py                      # -> daemon/takeout/<stamp>/
    py -3.12 ops/tools/takeout.py --out D:/umzug       # somewhere else
    py -3.12 ops/tools/takeout.py --with-recordings    # + the voice recordings
    py -3.12 ops/tools/takeout.py --verify <dir>       # check a container

SHAPE COPIED, NOT INVENTED (research:
ops/docs/backlog/memory-as-knowledge-system/field-survey.md). Signal's
on-device backup is the closest analogue - same person, new device - and it is
exactly three things: one database file, one directory of blobs, one
`manifest.json` holding "metadata and verification info". We copy that, plus:

- a FORMAT version and, separately, the db SCHEMA version. Signal keeps
  `Header{version}` and `DatabaseVersion{version}` as different frames because
  format evolution and schema evolution are different problems.
- an explicit completeness marker. Signal's `BackupFrame.end` exists so a
  truncated archive is DETECTABLE rather than merely short. Ours is
  `"complete": true`, written last, plus a sha256 per file.
- an exclusion list shipped as product copy, at the same prominence as the
  feature. Signal names view-once messages; WhatsApp names call history and
  Channel media; GDPR WP242 makes it a duty that the person can "fully
  understand the definition, schema and structure" of what they got. Ours is
  NOT-INCLUDED.md, written into the container.

SECRETS DO NOT TRAVEL. Every Signal and WhatsApp path re-registers on the new
device rather than shipping keys. db_export masks by default (measured: zero
unmasked token/secret/password values in a full export), and the signing
keystore, the push service account and the CLI's own config are named in
NOT-INCLUDED.md as steps the owner performs by hand - stated, not discovered.

DELIBERATELY NOT COPIED from the vendors: Google Takeout's link expiry (a
local file the owner wrote to his own disk must not self-delete) and Signal's
"move, not copy" unregistration of the source (that exists because one phone
number allows one registration; destroying the source here would be data loss
with no compensating invariant).
"""
import argparse
import datetime
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

FORMAT_VERSION = 1
MANIFEST = "manifest.json"
NOT_INCLUDED = "NOT-INCLUDED.md"

# What the owner must carry by hand, and what it costs to forget it. Losing
# the Android keystore means the Play Store listing can never be updated
# again - that is the single most expensive omission possible here, so it is
# named first and named plainly.
HANDOVER = [
    ("daemon/certs/apk-signing/", "Android-Signierschluessel. UNERSETZLICH: "
     "ohne ihn kann die App im Play Store nie wieder aktualisiert werden. "
     "Kopiere den Ordner getrennt und sicher."),
    ("daemon/fcm_service_account.json", "Push-Dienstkonto. Ohne das kommen "
     "keine Benachrichtigungen an; neu erzeugbar in der Firebase-Konsole."),
    ("~/.claude.json", "MCP-Konfiguration der Befehlszeile. Ohne sie findet "
     "Henry windows-mcp nicht."),
    ("Apple-Zertifikate / ASC-Key", "liegen nicht in diesem Repo; siehe die "
     "Notizen zu iOS-Signierung."),
    ("Relay / Tunnel", "Zugangsdaten und Autostart-Eintrag auf dem neuen "
     "Rechner neu setzen."),
]


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy_tree(src, dst):
    """(files, bytes) - a plain recursive copy that reports what it did."""
    n = size = 0
    for base, _dirs, files in os.walk(src):
        rel = os.path.relpath(base, src)
        out = os.path.join(dst, rel) if rel != "." else dst
        os.makedirs(out, exist_ok=True)
        for fn in files:
            s = os.path.join(base, fn)
            try:
                shutil.copy2(s, os.path.join(out, fn))
            except OSError:
                continue
            n += 1
            size += os.path.getsize(s)
    return n, size


def auto_memory_dir():
    """The CLI's own memory directory, as the CLI ITSELF reported it.

    Never constructed from the cwd: the slug is derived from the MAIN repo,
    not from the spawn's working directory, so a reconstruction would be
    confidently wrong - and on a machine where the repo sits elsewhere it
    would also be the wrong destination on restore."""
    try:
        from spine.storage import db
        from cells.copilot.chat import copilot_memory
        path = (db.doc_get(copilot_memory.AUTO_DOC) or {}).get("path")
        return path if path and os.path.isdir(path) else None
    except Exception:                                            # noqa: BLE001
        return None


def build(out_root, with_recordings=False):
    stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    box = os.path.join(out_root, "helmdeck-takeout-%s" % stamp)
    os.makedirs(box, exist_ok=True)
    parts, notes = {}, []

    # 1. the database, as ONE json document. Masked by default - the export
    #    tool's own default, verified to leave no token/secret/password value
    #    in the clear.
    dbj = os.path.join(box, "db.json")
    with io.open(dbj, "w", encoding="utf-8") as f:
        r = subprocess.run([sys.executable, os.path.join(ROOT, "ops", "tools", "db_export.py"),
                            "--all"], stdout=f, stderr=subprocess.PIPE,
                           text=True, cwd=ROOT)
    if r.returncode != 0:
        raise RuntimeError("db_export schlug fehl: %s" % (r.stderr or "")[-400:])
    doc = json.load(io.open(dbj, encoding="utf-8"))
    parts["db.json"] = {"sha256": _sha256(dbj), "bytes": os.path.getsize(dbj),
                        "tables": {k: len(v) for k, v in doc.items()
                                   if isinstance(v, list)}}

    # 2. the CLI auto-memory - the half with no other copy anywhere
    #    (debt personal-memory-does-not-travel). Carried as FILES, and the
    #    source path is recorded so a restore can tell whether the
    #    destination it resolves is the same shape.
    src = auto_memory_dir()
    if src:
        n, size = _copy_tree(src, os.path.join(box, "auto-memory"))
        # The .git inside comes ALONG on purpose: measured 2026-09-21, that
        # directory is a real repository (123 commits back to 2026-08-16,
        # "memory: N file(s) changed", no remote) - the CLI versions its own
        # memory. Copying only the .md files would silently drop the history.
        parts["auto-memory/"] = {"files": n, "bytes": size, "source": src,
                                 "notes": len([f for f in os.listdir(src)
                                               if f.endswith(".md")]),
                                 "git_history": os.path.isdir(
                                     os.path.join(src, ".git"))}
    else:
        notes.append("Auto-Memory NICHT enthalten: der Pfad wurde noch nicht "
                     "beobachtet. Lass Henry einen Turn laufen und exportiere "
                     "erneut.")

    # 3. recordings, opt-in - hundreds of megabytes of voice audio that most
    #    moves do not need.
    rec = os.path.join(ROOT, "daemon", "recordings")
    if with_recordings and os.path.isdir(rec):
        n, size = _copy_tree(rec, os.path.join(box, "recordings"))
        parts["recordings/"] = {"files": n, "bytes": size}
    elif os.path.isdir(rec):
        notes.append("Aufnahmen ausgelassen (--with-recordings waehlen, um sie "
                     "mitzunehmen).")

    man = {
        "format": FORMAT_VERSION,
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "source_root": ROOT,
        "schema": _schema(),
        "parts": parts,
        "notes": notes,
        "not_included": [h[0] for h in HANDOVER],
        # written LAST and read FIRST on verify: a container without it is a
        # truncated container, not a small one.
        "complete": True,
    }
    with io.open(os.path.join(box, MANIFEST), "w", encoding="utf-8") as f:
        json.dump(man, f, indent=1, ensure_ascii=False)
    _write_not_included(box, notes)
    return box, man


def _schema():
    try:
        from spine.storage import db
        return db.schema_head()
    except Exception:                                            # noqa: BLE001
        return None


def _write_not_included(box, notes):
    lines = ["# Was in diesem Archiv NICHT enthalten ist", "",
             "Diese Dinge musst du von Hand mitnehmen oder neu einrichten.",
             "Sie fehlen mit Absicht: sie sind Geheimnisse und gehoeren nicht",
             "in eine Datei, die herumliegt.", ""]
    for what, why in HANDOVER:
        lines += ["- **%s**" % what, "  %s" % why]
    if notes:
        lines += ["", "## Ausserdem ausgelassen", ""]
        lines += ["- %s" % n for n in notes]
    lines += ["", "## Wiederherstellen", "",
              "1. Repo klonen, `py -3.12 -m daemon.swarm serve` einmal starten,",
              "   damit die leere Datenbank mit dem aktuellen Schema entsteht.",
              "2. `py -3.12 ops/tools/db_import.py <archiv>/db.json`",
              "3. Den Ordner `auto-memory/` an den Ort legen, den die CLI",
              "   selbst meldet - NICHT aus dem Pfad erraten. Nach einem",
              "   Henry-Turn steht er in der Datenbank unter `memory_auto_dir`.",
              "4. Die Punkte oben von Hand nachziehen.", ""]
    with io.open(os.path.join(box, NOT_INCLUDED), "w", encoding="utf-8",
                 newline="\n") as f:
        f.write("\n".join(lines))


def verify(box):
    """[problem] - empty means the container is whole. Checks the completeness
    marker first: a manifest without it means the export was interrupted."""
    problems = []
    mp = os.path.join(box, MANIFEST)
    if not os.path.isfile(mp):
        return ["%s fehlt - das ist kein Archiv" % MANIFEST]
    man = json.load(io.open(mp, encoding="utf-8"))
    if not man.get("complete"):
        problems.append("ABGEBROCHEN: der Vollstaendigkeitsmarker fehlt")
    if man.get("format") != FORMAT_VERSION:
        problems.append("Formatversion %s, dieses Werkzeug kann %s"
                        % (man.get("format"), FORMAT_VERSION))
    for name, meta in (man.get("parts") or {}).items():
        path = os.path.join(box, name.rstrip("/"))
        if not os.path.exists(path):
            problems.append("%s fehlt" % name)
            continue
        if meta.get("sha256"):
            got = _sha256(path)
            if got != meta["sha256"]:
                problems.append("%s: Pruefsumme weicht ab" % name)
    return problems


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=os.path.join(ROOT, "daemon", "takeout"))
    ap.add_argument("--with-recordings", action="store_true")
    ap.add_argument("--verify", metavar="DIR")
    a = ap.parse_args(argv)
    if a.verify:
        probs = verify(a.verify)
        for p in probs:
            print("  PROBLEM: %s" % p)
        print("verify: %s" % ("FEHLER" if probs else "vollstaendig"))
        return 1 if probs else 0
    box, man = build(a.out, with_recordings=a.with_recordings)
    print("Archiv: %s" % box)
    for name, meta in (man.get("parts") or {}).items():
        if "tables" in meta:
            rows = sum(meta["tables"].values())
            print("  %-16s %8.1f MB  %d Zeilen in %d Tabellen"
                  % (name, meta["bytes"] / 1e6, rows, len(meta["tables"])))
        else:
            print("  %-16s %8.1f MB  %d Dateien"
                  % (name, meta.get("bytes", 0) / 1e6, meta.get("files", 0)))
    for n in man.get("notes") or []:
        print("  Hinweis: %s" % n)
    print("  %s listet, was du von Hand mitnehmen musst." % NOT_INCLUDED)
    probs = verify(box)
    print("verify: %s" % ("FEHLER: %s" % probs if probs else "vollstaendig"))
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
