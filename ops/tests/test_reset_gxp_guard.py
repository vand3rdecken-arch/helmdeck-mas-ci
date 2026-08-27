# -*- coding: utf-8 -*-
"""Self-sandboxing test for ops/tools/reset.py's GxP guard (phase D).

The finding: reset.py's clear_events() was an ungated `DELETE FROM events` +
delete events.jsonl, with no check of any kind and no record that it ever ran.
That directly violates "append-only audit/events" - a fixed law of this repo
(CLAUDE.md), not a default reset.py gets to override for convenience. Worse:
wipe_cards() deletes whole track rows, and a signature record lives ON the
track (signatures.py) - so a reset could erase a signed approval outright.

What this pins down:
  1. GxP active -> reset.py refuses BEFORE backup() even runs: zero side
     effects, not "backed up then wiped anyway"
  2. events and tracks are byte-for-byte UNCHANGED after a refused reset
  3. GxP off -> the reset proceeds exactly as before (events cleared)
  4. every reset - even a refused one - is not what gets logged; only a
     COMPLETED reset appends to reset-log.jsonl, in a file clear_events()
     itself never touches
  5. running reset twice APPENDS two records, never overwrites (the log
     itself has to be append-only too, or it just moved the problem)

Run: py -3.12 ops/tests/test_reset_gxp_guard.py
"""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_fails = []
def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-resetguard-test-")

    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from spine.storage import events
    events.EV = os.path.join(tmp, "events.jsonl")
    events.SET = os.path.join(tmp, "settings.json")
    from spine.auth import gxp
    gxp.LOCK = os.path.join(tmp, "gxp.lock")
    db.init()

    import ops.tools.reset as reset
    reset.ROOT = tmp
    reset.DAEMON = tmp   # daemon/ files (users.json etc.) also sandboxed here

    # REC must be sandboxed too - the incident this guards against is REAL
    # (2026-08-27): clear_recordings() used to read sessions.REC at call time,
    # which this test never patched, so every suite run emptied the LIVE
    # daemon/recordings/ (102 cards' transcripts/actionlogs, unrecoverable)
    # while everything else stayed sandboxed and green. reset.py now derives
    # the path from its own patched DAEMON; the patches below are the
    # belt-and-suspenders half so even a regression in reset.py cannot reach
    # the real folder from here.
    from spine.ops import runs
    from cells.engineer import sessions as _sessions_mod
    REC = os.path.join(tmp, "recordings")
    os.makedirs(REC, exist_ok=True)
    runs.REC = REC
    _sessions_mod.REC = REC

    subprocess.run(["git", "-C", tmp, "init", "-q"], capture_output=True, text=True)

    events.emit("gate", "t-1", ok=True)
    events.emit("done", "t-1", mode="clean")
    events_before = open(events.EV, encoding="utf-8").read()
    ok(len(events_before.splitlines()) == 2, "fixture: 2 events written")

    def run(argv):
        old = sys.argv
        sys.argv = ["reset.py"] + argv
        try:
            return reset.main()
        finally:
            sys.argv = old

    # ------------------------------------------------------------------ 1 ---
    print("\nGxP active - refuses before backup() runs")
    with open(gxp.LOCK, "w", encoding="utf-8") as f:
        json.dump({"enabled": True, "activated_by": "duy"}, f)
    rc = run(["--yes"])
    ok(rc != 0, "non-zero exit")
    ok(not os.path.isdir(os.path.join(tmp, "daemon", "backups")),
       "no backups/ dir was created - refused BEFORE backup(), not after")

    # ------------------------------------------------------------------ 2 ---
    print("\nevents are byte-for-byte untouched")
    ok(open(events.EV, encoding="utf-8").read() == events_before,
       "events.jsonl unchanged")
    ok(db.conn().execute("SELECT count(*) FROM events").fetchone()[0] == 2,
       "events table unchanged")

    # ------------------------------------------------------------------ 3 ---
    print("\nGxP off - the reset proceeds")
    os.remove(gxp.LOCK)
    rc = run(["--yes"])
    ok(rc == 0, "exit 0")
    ok(not os.path.exists(events.EV), "events.jsonl actually removed")
    ok(db.conn().execute("SELECT count(*) FROM events").fetchone()[0] == 0,
       "events table actually cleared")
    ok(os.path.isdir(os.path.join(tmp, "daemon", "backups")), "a backup WAS made this time")

    # ------------------------------------------------------------------ 4 ---
    print("\nthe reset itself is logged, in a file clear_events() cannot reach")
    logf = os.path.join(tmp, "daemon", "backups", "reset-log.jsonl")
    ok(os.path.exists(logf), "reset-log.jsonl exists")
    rows = [json.loads(l) for l in open(logf, encoding="utf-8") if l.strip()]
    ok(len(rows) == 1, "exactly one entry for the one completed reset (got %d)" % len(rows))
    ok(rows[0]["op"] == "reset" and rows[0]["ts"].endswith("Z"),
       "entry has an op and a UTC timestamp")
    ok(rows[0].get("os_user"), "entry names the OS account that ran it")
    ok("backup" in rows[0], "entry points at the backup that was made")

    # ------------------------------------------------------------------ 5 ---
    print("\na second reset APPENDS, does not overwrite")
    events.emit("gate", "t-2", ok=True)
    rc = run(["--yes"])
    ok(rc == 0, "second reset also succeeds")
    rows = [json.loads(l) for l in open(logf, encoding="utf-8") if l.strip()]
    ok(len(rows) == 2, "now two entries (got %d)" % len(rows))

    print("\nrefused reset was logged nowhere - only completed ones count")
    with open(gxp.LOCK, "w", encoding="utf-8") as f:
        json.dump({"enabled": True}, f)
    run(["--yes"])
    rows = [json.loads(l) for l in open(logf, encoding="utf-8") if l.strip()]
    ok(len(rows) == 2, "still two - the refused attempt did not add a phantom entry")

    print()
    if _fails:
        print("FAILED (%d):" % len(_fails))
        for m in _fails:
            print("  - " + m)
        return 1
    print("all green - %s" % tmp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
