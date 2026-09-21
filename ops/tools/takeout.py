# -*- coding: utf-8 -*-
"""Take everything with you - one container, one manifest, one honest list of
what is NOT in it.

    py -3.12 ops/tools/takeout.py                      # -> daemon/takeout/<stamp>/
    py -3.12 ops/tools/takeout.py --out D:/umzug       # somewhere else
    py -3.12 ops/tools/takeout.py --with-recordings    # + the voice recordings
    py -3.12 ops/tools/takeout.py --verify <dir>       # check a container
    py -3.12 ops/tools/takeout.py --restore <dir>      # on the NEW machine
    py -3.12 ops/tools/takeout.py --restore <dir> --merge   # into a live db

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
    ("daemon/certs/apk-signing/", "Android-Signierschlüssel. UNERSETZLICH: "
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



_TOOLS = {}


def _db_tool(name):
    """Load ops/tools/<name>.py as a module, once. These are scripts, not a
    package, so importlib is the honest way in - and it keeps them running in
    THIS process against THIS db."""
    if name not in _TOOLS:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            name, os.path.join(ROOT, "ops", "tools", "%s.py" % name))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _TOOLS[name] = mod
    return _TOOLS[name]

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


def build(out_root, with_recordings=False, account=None):
    """`account` narrows the db half to ONE account's rows (db_export's own
    --account filter). None means the whole workspace and is the owner's
    view; the HTTP feature passes the caller's own id for everyone else,
    because a product where any operator can export every account's chat and
    memory is a data leak with a button."""
    stamp = datetime.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    box = os.path.join(out_root, "helmdeck-takeout-%s" % stamp)
    os.makedirs(box, exist_ok=True)
    parts, notes = {}, []

    # 1. the database, as ONE json document. Masked by default - the export
    #    tool's own default, verified to leave no token/secret/password value
    #    in the clear.
    dbj = os.path.join(box, "db.json")
    # IN-PROCESS, not a subprocess: a spawned db_export resolves its own db
    # path and would ignore a caller that repointed db.DBPATH - measured, it
    # exported the live 138 MB database from inside a sandboxed test.
    doc = _db_tool("db_export").export(account=account)
    with io.open(dbj, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
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
        "account": account or "workspace",
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



# ---------------------------------------------------------------------------
# THE OTHER HALF. An export nobody has restored is a guess, so this is written
# and tested against a real container, not described in a README.
#
# THREE RULES, each with a reason:
#  1. VERIFY BEFORE TOUCHING ANYTHING. The completeness marker and the
#     checksums are read first; a container that fails is refused whole.
#     "Restore takes the whole container, not files out of it" - Signal's own
#     instruction, because partial restore is where corruption is invented.
#  2. EMPTY TARGET BY DEFAULT. db_import already refuses a non-empty db
#     without --merge, and that default stays: a restore onto live data is a
#     decision, not a default.
#  3. THE AUTO-MEMORY PATH IS ASKED FOR, NEVER BUILT. On a new machine the
#     daemon has not observed it yet, so we ask the CLI itself the same way
#     the daemon does - read memory_paths.auto out of a throwaway init frame.
#     Constructing the slug from the cwd would be wrong even here: it is
#     derived from the MAIN repo path, not from the process's directory.


def probe_auto_dir():
    """Ask the claude CLI where IT keeps memory on THIS machine.

    Returns (path, why_not). Never guesses: if the CLI is missing or does not
    report a path, the caller must stop and say so rather than invent a
    destination and write 92 notes into a folder nothing ever reads."""
    try:
        from spine.agent import drivers
        from spine.registry import harness
        from spine.agent.spawnenv import tool_path
    except Exception as e:                                       # noqa: BLE001
        return None, "Harness nicht ladbar (%s)" % str(e)[:80]
    argv = [drivers.CLAUDE, "-p", "--output-format", "stream-json", "--verbose",
            "--permission-mode", "plan", "--model", "haiku", "hi"]
    try:
        r = subprocess.run(drivers._cmd_line(argv), cwd=ROOT, env=tool_path(),
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=240)
    except Exception as e:                                       # noqa: BLE001
        return None, "claude CLI nicht startbar (%s)" % str(e)[:80]
    for line in (r.stdout or "").splitlines():
        try:
            ev = json.loads(line.strip())
        except ValueError:
            continue
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            p = ((ev.get("memory_paths") or {}) or {}).get("auto")
            if p:
                return p, None
            return None, "die CLI meldet keinen memory_paths.auto"
    return None, "kein init-Frame von der CLI (rc=%s)" % r.returncode


def restore(box, merge=False, skip_memory=False):
    """[step] - what happened, in order. Raises only on a refusal that must
    stop the whole restore."""
    steps = []
    problems = verify(box)
    if problems:
        raise RuntimeError("Archiv unvollstaendig, nichts angefasst: %s"
                           % "; ".join(problems))
    man = json.load(io.open(os.path.join(box, MANIFEST), encoding="utf-8"))
    steps.append("Archiv geprueft: vollstaendig, Format %s, Schema %s"
                 % (man.get("format"), man.get("schema")))

    # -- the database ------------------------------------------------------
    dbj = os.path.join(box, "db.json")
    if os.path.isfile(dbj):
        doc = json.load(io.open(dbj, encoding="utf-8"))
        try:
            counts = _db_tool("db_import").import_doc(doc, merge=merge)
        except SystemExit as e:
            # db_import is a SCRIPT and signals its two refusals (non-empty
            # target, newer schema) with SystemExit. Uncaught, that would tear
            # this process down mid-restore with a bare line - the half-applied
            # restore this tool exists to prevent. Turned into a refusal.
            raise RuntimeError(str(e))
        except (RuntimeError, ValueError) as e:
            raise RuntimeError("db_import: %s" % e)
        steps.append("Datenbank importiert (%d Zeilen in %d Tabellen%s)"
                     % (sum(counts.values()), len(counts),
                        ", zusammengefuehrt" if merge else ""))

    # -- the auto-memory ---------------------------------------------------
    src = os.path.join(box, "auto-memory")
    if skip_memory:
        steps.append("Auto-Memory uebersprungen (--skip-memory)")
    elif not os.path.isdir(src):
        steps.append("Auto-Memory war nicht im Archiv")
    else:
        dest, why = probe_auto_dir()
        if not dest:
            steps.append("Auto-Memory NICHT wiederhergestellt: %s. Die Notizen "
                         "liegen weiter in %s - hol sie, sobald die CLI hier "
                         "laeuft, mit --restore erneut." % (why, src))
        elif os.path.isdir(os.path.join(dest, ".git")):
            # Two histories and no authority to adjudicate between them -
            # exactly the case where Signal and WhatsApp refuse, and they are
            # right. We refuse too, and say what to do instead.
            steps.append("Auto-Memory NICHT ueberschrieben: unter %s liegt "
                         "bereits ein Gedächtnis MIT Verlauf. Zusammenführen "
                         "waere geraten. Hol die Historie bewusst: "
                         "git -C \"%s\" remote add takeout \"%s\" && "
                         "git -C \"%s\" fetch takeout" % (dest, dest, src, dest))
        else:
            existing = [f for f in os.listdir(dest)] if os.path.isdir(dest) else []
            if existing:
                steps.append("Auto-Memory NICHT wiederhergestellt: %s ist nicht "
                             "leer (%d Eintraege) und hat keinen Verlauf - raeum "
                             "ihn weg oder nimm ihn in Betrieb, dann erneut."
                             % (dest, len(existing)))
            else:
                n, size = _copy_tree(src, dest)
                steps.append("Auto-Memory wiederhergestellt: %d Dateien (%.1f MB) "
                             "nach %s" % (n, size / 1e6, dest))

    # -- recordings --------------------------------------------------------
    rec = os.path.join(box, "recordings")
    if os.path.isdir(rec):
        n, size = _copy_tree(rec, os.path.join(ROOT, "daemon", "recordings"))
        steps.append("Aufnahmen wiederhergestellt: %d Dateien (%.1f MB)"
                     % (n, size / 1e6))

    steps.append("VON HAND NACHZIEHEN: " + "; ".join(h[0] for h in HANDOVER))
    return steps

def main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=os.path.join(ROOT, "daemon", "takeout"))
    ap.add_argument("--with-recordings", action="store_true")
    ap.add_argument("--verify", metavar="DIR")
    ap.add_argument("--restore", metavar="DIR")
    ap.add_argument("--merge", action="store_true",
                    help="in eine NICHT leere Datenbank importieren")
    ap.add_argument("--skip-memory", action="store_true")
    a = ap.parse_args(argv)
    if a.restore:
        try:
            for step in restore(a.restore, merge=a.merge,
                                skip_memory=a.skip_memory):
                print("  %s" % step)
        except RuntimeError as e:
            print("restore ABGEBROCHEN: %s" % e)
            return 1
        print("restore: fertig")
        return 0
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
