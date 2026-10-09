# -*- coding: utf-8 -*-
"""Headless test for the track + users read cache in spine/storage/db.py.

The trap being closed: tracks_all() json.loads ALL cards on every call, and the
sweep loops, /dashboard and auth.resolve (users_all) called it constantly -
60% of the daemon's CPU in a py-spy profile (2026-10-09), GIL held, so the
bridge to the phone starved. The cache is keyed by a generation advanced by the
ONE set of writers after their commit.

What this pins (against the REAL db functions, temp sqlite):
 1. a second read parses nothing (the cache is really hit);
 2. a caller that mutates its result cannot poison the next caller;
 3. every writer (put / delete / replace) is visible on the very next read;
 4. a write that lands DURING a fill is never filed under the newer key;
 5. tracks_index() answers "which cards are running" from the same cache;
 6. users_replace is visible on the next users_all.

Self-sandboxing: temp DBPATH. Run: py -3.12 ops/tests/test_tracks_cache.py
"""
import json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

SANDBOX = tempfile.mkdtemp(prefix="hd-tc-")
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
db.init()

FAILS = []
def check(ok, label):
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        FAILS.append(label)

class CountLoads:
    """Counts json.loads calls made by db.py (a cache hit makes none)."""
    def __enter__(self):
        self.n = 0
        self.real = db.json.loads
        def counting(*a, **k):
            self.n += 1
            return self.real(*a, **k)
        db.json.loads = counting
        return self
    def __exit__(self, *a):
        db.json.loads = self.real

def main():
    for i in range(5):
        db.track_put({"id": "c%d" % i, "status": "running" if i == 0 else "done",
                      "waiting_on": "background" if i == 1 else None})
    db.tracks_all()                       # fill
    with CountLoads() as c:
        a = db.tracks_all()
    check(c.n == 0 and len(a) == 5, "second read parses nothing (cache hit)")

    a[0]["status"] = "POISON"; a.pop()
    b = db.tracks_all()
    check(len(b) == 5 and all(t["status"] != "POISON" for t in b),
          "mutating a result cannot poison the next caller")

    db.track_put({"id": "c9", "status": "running"})
    check(any(t["id"] == "c9" for t in db.tracks_all()), "track_put visible on the next read")
    db.track_delete("c9")
    check(all(t["id"] != "c9" for t in db.tracks_all()), "track_delete visible on the next read")
    db.tracks_replace([{"id": "r1", "status": "done"}])
    check([t["id"] for t in db.tracks_all()] == ["r1"], "tracks_replace visible on the next read")

    # a write landing mid-fill must not be cached as if it were current
    db.tracks_replace([{"id": "m1", "status": "done"}])
    real, fired = db.json.loads, []
    def racing(*a, **k):
        if not fired:
            fired.append(1)
            db.track_put({"id": "m2", "status": "running"})
        return real(*a, **k)
    db._tracks_cache = (None, b"", {})
    db.json.loads = racing
    try:
        db.tracks_all()
    finally:
        db.json.loads = real
    check(any(t["id"] == "m2" for t in db.tracks_all()),
          "a write during a fill is not hidden behind a stale cache entry")

    idx = db.tracks_index()
    check(idx.get("m2") == ("running", None) and idx.get("m1") == ("done", None),
          "tracks_index reports status + waiting_on from the same cache")

    db.users_replace([{"name": "owner", "role": "owner"}])
    u1 = db.users_all()
    u1[0]["role"] = "POISON"
    check(db.users_all()[0]["role"] == "owner", "users_all hands out copies")
    db.users_replace([{"name": "owner", "role": "owner"}, {"name": "x", "role": "member"}])
    check(len(db.users_all()) == 2, "users_replace visible on the next users_all")

    print("FAIL: %d" % len(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0

if __name__ == "__main__":
    sys.exit(main())
