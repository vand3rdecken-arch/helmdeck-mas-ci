# -*- coding: utf-8 -*-
"""GET /tracks?since= (board delta sync, 2026-09-29). Owner: 'Warum nicht
gecacht auf Handy' - the phone re-downloaded the whole ~1.6 MB list per open.

Pins: (1) with a current cursor the reply is tiny and carries only the card
that moved; (2) archived/deleted cards go to `gone`; (3) a cursor from another
daemon process (epoch) or none re-baselines with the non-archived board;
(4) the legacy call without `since` still returns the plain full array.
Pure in-memory: sessions/db reads are faked, nothing touches the live db.

Run: py -3.12 ops/tests/test_tracks_delta.py
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from spine.storage import db
from cells.engineer.cards import sessions
from cells.engineer.routes import routes_tracks

_fails = []
def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)

STORE = {"c%03d" % i: {"id": "c%03d" % i, "title": "x" * 300, "last_reply": "y" * 900} for i in range(400)}
STORE["c000"]["archived"] = True
sessions.list_tracks = lambda: list(STORE.values())
sessions.present = lambda t: t
db.track_get = lambda tid: STORE.get(tid)

class H:
    def __init__(self, path): self.path = path; self.body = None
    def _send(self, code, body, ctype=None): self.body = json.loads(body)

def get(path):
    h = H(path)
    routes_tracks.tracks_list_get(h, {"role": "owner", "name": "o"})
    return h.body, len(json.dumps(h.body))

for tid in STORE: db.bump(tid)
base, base_len = get("/tracks?since=0&epoch=0")
ok(base["full"] and len(base["changed"]) == 399 and base["gone"] == ["c000"], "baseline = every non-archived card")
cur = base["v"]

STORE["c005"]["title"] = "moved"; db.bump("c005")
d, n = get("/tracks?since=%d&epoch=%d" % (cur, db.TRACK_EPOCH))
ok(not d["full"] and [t["id"] for t in d["changed"]] == ["c005"] and d["gone"] == [], "delta = only the moved card")
ok(n < base_len / 50, "delta reply is small (%d B vs %d B baseline)" % (n, base_len))

STORE["c006"]["archived"] = True; db.bump("c006")
del STORE["c007"]; db.bump("c007")
d, _ = get("/tracks?since=%d&epoch=%d" % (d["v"], db.TRACK_EPOCH))
ok(sorted(d["gone"]) == ["c006", "c007"] and d["changed"] == [], "archived + deleted cards land in gone")

d, _ = get("/tracks?since=5&epoch=%d" % (db.TRACK_EPOCH + 1))
ok(d["full"] and len(d["changed"]) == 397, "foreign epoch re-baselines")
legacy, _ = get("/tracks")
ok(isinstance(legacy, list) and len(legacy) == 399, "no since = legacy full array (old apps)")

print("\n%d FAILED" % len(_fails) if _fails else "\nall ok")
sys.exit(1 if _fails else 0)
