# -*- coding: utf-8 -*-
"""GET /tracks?cookie= (board delta pull, Replicache shape, 2026-09-29). Owner: 'Warum nicht
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

def keys(r, op): return sorted(p["key"] for p in r["patch"] if p["op"] == op)

for tid in STORE: db.bump(tid)
base, base_len = get("/tracks?cookie=")
ok(base["patch"][0] == {"op": "clear"} and len(keys(base, "put")) == 399 and "c000" in keys(base, "del"),
   "empty cookie = clear + every non-archived card")
ck = base["cookie"]

STORE["c005"]["title"] = "moved"; db.bump("c005")
d, n = get("/tracks?cookie=" + ck)
ok(len(d["patch"]) == 1 and d["patch"][0]["op"] == "put" and d["patch"][0]["key"] == "c005", "pull with the cookie = only the moved card")
ok(n < base_len / 50, "delta reply is small (%d B vs %d B baseline)" % (n, base_len))

STORE["c006"]["archived"] = True; db.bump("c006")
del STORE["c007"]; db.bump("c007")
d, _ = get("/tracks?cookie=" + d["cookie"])
ok(keys(d, "del") == ["c006", "c007"] and not keys(d, "put"), "archived + deleted cards become del")

d, _ = get("/tracks?cookie=%d.5" % (db.TRACK_EPOCH + 1))
ok(d["patch"][0]["op"] == "clear" and len(keys(d, "put")) == 397, "foreign epoch re-baselines")
d, _ = get("/tracks?cookie=garbage")
ok(d["patch"][0]["op"] == "clear", "malformed cookie re-baselines")
legacy, _ = get("/tracks")
ok(isinstance(legacy, list) and len(legacy) == 399, "no cookie param = legacy full array (old apps)")

print("\n%d FAILED" % len(_fails) if _fails else "\nall ok")
sys.exit(1 if _fails else 0)
