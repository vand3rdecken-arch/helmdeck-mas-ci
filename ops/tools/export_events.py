# -*- coding: utf-8 -*-
"""Render the audit trail as JSONL - the on-demand file that replaced
daemon/events.jsonl (state-into-db phase H, owner decision 2026-09-12: the
`events` table is the record, a file is a VIEW an auditor asks for).

    py -3.12 ops/tools/export_events.py                    > events.jsonl
    py -3.12 ops/tools/export_events.py --since 2026-09-01 > september.jsonl
    py -3.12 ops/tools/export_events.py --kind auth --track <card-id>

One line per event in table order (seq), the same row shape emit() stores:
ts, kind, track, id, at_utc and every field the emitter attached. Read-only.
Secrets never enter events (auth._audit masks them at the source), so nothing
is masked here - what you see is what the trail holds."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def rows(since=None, kind=None, track=None):
    from spine.storage import db
    where, args = [], []
    if since:
        where.append("ts >= ?"); args.append(since)
    if kind:
        where.append("kind = ?"); args.append(kind)
    if track:
        where.append("track = ?"); args.append(track)
    sql = "SELECT ts,kind,track,id,data FROM events"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY seq"
    for ts, k, tr, rid, data in db.conn().execute(sql, args):
        r = {"ts": ts, "kind": k, "track": tr}
        if rid:
            r["id"] = rid
        try:
            r.update(json.loads(data))
        except ValueError:
            pass
        yield r


def main(argv):
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    opt = lambda flag: argv[argv.index(flag) + 1] if flag in argv else None   # noqa: E731
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    n = 0
    for r in rows(opt("--since"), opt("--kind"), opt("--track")):
        sys.stdout.write(json.dumps(r, ensure_ascii=False) + "\n")
        n += 1
    sys.stderr.write("%d event(s)\n" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
