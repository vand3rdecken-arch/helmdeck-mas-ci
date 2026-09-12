# -*- coding: utf-8 -*-
"""One-off repair for the 2026-08-27 recordings wipe (root cause fixed in
bb516c6: test_reset_gxp_guard.py's unsandboxed sessions.REC ran the real
reset.clear_recordings() against daemon/recordings/ on every suite run).

The lost transcript/actionlog CONTENT is gone for good - there is no backup
to restore from (reset.py's own backup went to a Temp sandbox, not here).
What this script does is the honest, derivable half: for every card whose
run_dir vanished (turns > 0 on the DB row, but the folder is missing or has
no actions.jsonl/timeline.jsonl), recreate the folder and append ONE system
note recording the fact and the turn count at the time of discovery - not a
reconstruction of what was said, just a real, timestamped observation of
what the runtime currently shows. Idempotent: a card already carrying this
exact note is skipped.

Run with the daemon preferably idle (no card mid-turn) - append-only writes
are safe either way, but this avoids interleaving with a live turn's own
timeline_store writes. Dry-run by default; pass --yes to actually write.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

NOTE_MARKER = "Verlauf nicht wiederherstellbar"
NOTE = ("⚠ %s: recordings-Ordner wurde extern gelöscht (Fund "
        "2026-08-27, Ursache in bb516c6 behoben - ein Test hat die Karten-"
        "Historie live gewischt statt in seine eigene Sandbox). %d Turn(s) "
        "liefen vor diesem Zeitpunkt ohne erhaltene Aufzeichnung.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="write for real (default: dry-run)")
    a = ap.parse_args()

    from spine.storage import db
    from spine.ops.actionlog import ActionLog, read_timeline

    tracks = [json.loads(row[0]) for row in
              db.conn().execute("SELECT data FROM tracks").fetchall()]

    affected = []
    for t in tracks:
        rd, turns = t.get("run_dir"), t.get("turns", 0)
        if not rd or not turns:
            continue
        # records are rows since state-into-db phase F; the dir only holds media
        from spine.ops.runs import run_id_of
        rid = run_id_of(rd)
        has_content = db.actions_count(rid) > 0 or db.timeline_max_seq(rid) > 0
        if not has_content:
            affected.append(t)

    print("%d card(s) with turns>0 but no recorded content" % len(affected))
    skipped, written = 0, 0
    for t in affected:
        already = any(NOTE_MARKER in (r.get("detail") or "")
                       for r in read_timeline(t["run_dir"]))
        if already:
            skipped += 1
            continue
        msg = NOTE % (NOTE_MARKER, t.get("turns", 0))
        print(("[dry-run] " if not a.yes else "[write]   ") +
              "%s (turns=%d): %s" % (t["id"], t.get("turns", 0), t.get("task", "")[:60]))
        if a.yes:
            ActionLog(t["run_dir"]).log("note", msg)
            written += 1
    print("written: %d, already noted: %d, dry-run: %s" % (written, skipped, not a.yes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
