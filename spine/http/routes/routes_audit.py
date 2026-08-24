# -*- coding: utf-8 -*-
"""GET /audit - the audit-trail review route (phase D4).

21 CFR 11.10(e): the audit trail must be readily available for review AND
COPYING. Before this, "review" meant SSH into the host and grep events.jsonl -
which is neither, for anyone who is not also a systems administrator. This is
the answer: filter by kind/track/actor/time/free text, and export the match
set as CSV for an actual offline copy.

Owner only, same stance as routes_checkpoints.py's diff/restore: the audit
trail can carry settings values (reconfig events) and identity operations
(auth events), so it is not a "client can read" surface.

Query params, all optional:
  kind    comma-separated event kinds (e.g. "auth,signature")
  track   exact card id
  actor   exact actor name
  since   inclusive lower bound on at_utc, ISO 8601 UTC ("2026-08-01" or
          "2026-08-01T00:00:00Z") - string-compared, which works because
          at_utc's fixed-width zero-padded format sorts lexicographically the
          same as chronologically
  until   exclusive-ish upper bound, same format and same string comparison -
          "until=2026-08-02" excludes events ON 2026-08-02 itself; pass the
          following day (or an explicit end-of-day timestamp) to include it
  q       case-insensitive substring match against the whole serialized event
  format  "json" (default, capped by `limit`) or "csv" (uncapped - the actual
          "available for copying" answer, so filtering it would defeat GDPR/
          Part-11 completeness rather than satisfy it)
  limit   JSON preview cap, default 500, hard max 5000 - does not apply to csv

Filters on `at_utc` (phase D2), not the host-local `ts`: a date-range filter
is exactly the case where an unambiguous timestamp matters - `ts` goes
ambiguous across machines and twice a year at the DST fold.
"""
import csv
import io
import json
from urllib.parse import parse_qs, urlparse


def _matches(e, kinds, track, actor, since, until, text):
    if kinds and e.get("kind") not in kinds:
        return False
    if track and e.get("track") != track:
        return False
    if actor and e.get("actor") != actor:
        return False
    at = e.get("at_utc") or ""
    if since and at < since:
        return False
    if until and at >= until:
        return False
    if text and text not in json.dumps(e, ensure_ascii=False, sort_keys=True).lower():
        return False
    return True


def _to_csv(rows):
    """Fixed core columns + a `data` catch-all for the rest, JSON-encoded.
    Events carry heterogeneous extra fields per kind; a column per field seen
    anywhere would be a sparse, unstable schema. The catch-all stays
    greppable, which is the same standard the audit trail itself is held to
    (surfaces/app/src/i18n/index.ts:1-11 - a technical record must read identically
    everywhere, not paginate its own columns differently per export)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    core = ("id", "at_utc", "ts", "kind", "track")
    w.writerow(list(core) + ["data"])
    for r in rows:
        extra = {k: v for k, v in r.items() if k not in core}
        w.writerow([r.get(k, "") for k in core] + [json.dumps(extra, ensure_ascii=False, sort_keys=True)])
    return buf.getvalue()


def audit_get(self, user):
    if user["role"] != "owner":
        return self._send(403, json.dumps({"error": "owner only"}))

    from spine.storage import events
    q = parse_qs(urlparse(self.path).query)

    def one(name, default=""):
        return (q.get(name) or [default])[0].strip()

    kinds = {k for k in one("kind").split(",") if k}
    track = one("track")
    actor = one("actor")
    since = one("since")
    until = one("until")
    text = one("q").lower()
    fmt = one("format", "json")
    try:
        limit = max(1, min(int(one("limit", "500")), 5000))
    except ValueError:
        limit = 500

    rows = [e for e in events.read_events()
            if _matches(e, kinds, track, actor, since, until, text)]

    if fmt == "csv":
        body = _to_csv(rows).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition",
                         'attachment; filename="helmdeck-audit.csv"')
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)
        return

    # JSON preview is capped and returns the MOST RECENT matches (tail of an
    # ascending-order list), matching what a human reviewing the log actually
    # wants to see first - the export above is the completeness guarantee,
    # this is the interactive one.
    tail = rows[-limit:]
    return self._send(200, json.dumps(
        {"total": len(rows), "returned": len(tail), "events": tail}))


GET_ROUTES = {"/audit": audit_get}
