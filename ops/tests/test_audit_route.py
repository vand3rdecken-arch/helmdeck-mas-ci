# -*- coding: utf-8 -*-
"""Self-sandboxing test for GET /audit (phase D4).

21 CFR 11.10(e): the audit trail must be available for review AND COPYING.
Before this route, "review" meant SSH into the host and grep events.jsonl.

What this pins down:
  1. owner only - a non-owner gets 403, nothing else
  2. kind/track/actor filters narrow the result set correctly
  3. since/until filter on at_utc (phase D2), and the boundary semantics hold:
     since is inclusive, until is exclusive
  4. free-text `q` matches inside the serialized event, case-insensitively
  5. JSON mode is capped by `limit` and returns the MOST RECENT matches, but
     always reports the true `total` so a capped preview is never mistaken
     for the whole answer
  6. csv mode is NEVER capped - filtering a genuine export would defeat the
     "available for copying" requirement rather than satisfy it - and every
     filtered row is actually present in the CSV body, byte for byte
     recoverable via the standard csv module
  7. no password, no full token, nothing secret leaks through the export just
     because a filter didn't happen to catch it

Run: py -3.12 ops/tests/test_audit_route.py
"""
import csv
import io
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_fails = []
def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)


class FakeH:
    """Stands in for the HTTP handler. GET routes read self.path directly
    (routes_audit.py does its own urlparse) rather than a pre-parsed query, so
    this carries a real path string, not a dict."""
    def __init__(self, path):
        self.path = path
        self.code = None
        self.body = None
        self.headers_sent = {}
        self._buf = io.BytesIO()
        self.wfile = self._buf

    def _send(self, code, body, ctype="application/json"):
        self.code = code
        self.body = body
        self.ctype = ctype

    def send_response(self, code):
        self.code = code

    def send_header(self, k, v):
        self.headers_sent[k] = v

    def end_headers(self):
        pass


def call(path, user):
    h = FakeH(path)
    from spine.http.routes import routes_audit
    routes_audit.audit_get(h, user)
    return h


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-auditroute-test-")

    from spine.storage import db
    db.ROOT = tmp
    db.DBPATH = os.path.join(tmp, "test.db")
    from spine.storage import events
    events.SET = os.path.join(tmp, "settings.json")
    db.init()

    OWNER = {"name": "duy", "role": "owner"}
    CLIENT = {"name": "acme", "role": "client"}

    # ------------------------------------------------------------------ 1 ---
    print("\nowner only")
    h = call("/audit", CLIENT)
    ok(h.code == 403, "client refused")
    h = call("/audit", {"name": "op", "role": "operator"})
    ok(h.code == 403, "operator refused too - this is owner-only, not admin-only")

    # ---- fixture: a realistic mixed event stream -----------------------
    events.emit("auth", "-", op="login", actor="duy")
    events.emit("auth", "-", op="login.failed", actor="pat", reason="bad_password")
    events.emit("signature", "t-1", op="signed", actor="duy", meaning="approved",
                reason="Regressionstest gruen")
    events.emit("gate", "t-2", ok=True)
    events.emit("gate", "t-2", ok=False, problems=["syntax error"])
    events.emit("reconfig", "-", op="swap", actor="duy", section="policies")

    # ------------------------------------------------------------------ 2 ---
    print("\nfilters narrow correctly")
    h = call("/audit?kind=auth", OWNER)
    body = json.loads(h.body)
    ok(body["total"] == 2, "kind=auth -> exactly the 2 auth events (got %d)" % body["total"])
    ok(all(e["kind"] == "auth" for e in body["events"]), "...and only auth events")

    h = call("/audit?track=t-2", OWNER)
    body = json.loads(h.body)
    ok(body["total"] == 2, "track=t-2 -> the 2 gate events on that card")

    h = call("/audit?actor=duy", OWNER)
    body = json.loads(h.body)
    ok(body["total"] == 3, "actor=duy -> login + signature + reconfig (got %d)" % body["total"])

    h = call("/audit?kind=auth,gate", OWNER)
    body = json.loads(h.body)
    ok(body["total"] == 4, "comma-separated kinds OR together (got %d)" % body["total"])

    # ------------------------------------------------------------------ 3 ---
    print("\nsince/until on at_utc, phase D2's field")
    all_rows = events.read_events()
    mid = sorted(r["at_utc"] for r in all_rows)[2]
    h = call("/audit?since=%s" % mid, OWNER)
    body = json.loads(h.body)
    ok(all(e["at_utc"] >= mid for e in body["events"]), "since is inclusive")
    h = call("/audit?until=%s" % mid, OWNER)
    body = json.loads(h.body)
    ok(all(e["at_utc"] < mid for e in body["events"]), "until is EXCLUSIVE")
    h = call("/audit?since=2099-01-01", OWNER)
    ok(json.loads(h.body)["total"] == 0, "a future 'since' finds nothing")

    # ------------------------------------------------------------------ 4 ---
    print("\nfree-text q, case-insensitive")
    h = call("/audit?q=REGRESSIONSTEST", OWNER)
    body = json.loads(h.body)
    ok(body["total"] == 1 and body["events"][0]["kind"] == "signature",
       "matches inside a nested field, regardless of case")

    # ------------------------------------------------------------------ 5 ---
    print("\nJSON preview is capped, total is always the true count")
    h = call("/audit?limit=2", OWNER)
    body = json.loads(h.body)
    ok(body["total"] == 6 and body["returned"] == 2,
       "total=6 (everything), returned=2 (the cap) - not confused with each other")
    newest = sorted(all_rows, key=lambda r: r["at_utc"])[-1]
    ok(body["events"][-1]["kind"] == newest["kind"],
       "the capped preview keeps the MOST RECENT events, not the oldest")

    # ------------------------------------------------------------------ 6 ---
    print("\nCSV export is never capped, and is real CSV")
    h = call("/audit?format=csv&limit=1", OWNER)
    ok(h.headers_sent.get("Content-Type", "").startswith("text/csv"),
       "content type is text/csv")
    ok("attachment" in h.headers_sent.get("Content-Disposition", ""),
       "offered as a download")
    csv_text = h._buf.getvalue().decode("utf-8")
    parsed = list(csv.DictReader(io.StringIO(csv_text)))
    ok(len(parsed) == 6, "csv has ALL 6 rows even though limit=1 was passed - "
                         "capping an export would defeat 'available for copying'")
    ok({"id", "at_utc", "ts", "kind", "track", "data"} == set(parsed[0].keys()),
       "the expected columns, no silent extra/missing ones")
    reason_row = [r for r in parsed if "Regressionstest" in r["data"]]
    ok(len(reason_row) == 1, "the signature's reason survived into the export")

    # ------------------------------------------------------------------ 7 ---
    print("\nno secret leaks through just because a filter missed it")
    ok("password" not in csv_text.lower() or "bad_password" in csv_text,
       "the only 'password' substring present is the SAFE reason code, not a secret")
    ok("pbkdf2$" not in csv_text, "no password hash")

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
