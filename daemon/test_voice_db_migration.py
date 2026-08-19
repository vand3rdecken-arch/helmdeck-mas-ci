# -*- coding: utf-8 -*-
"""Self-sandboxing test for voice.py's ROOT-based storage.

Decision recorded here (see daemon/debt.py order 32): voice.py is NOT
migrated into db.py's `data TEXT` row shape. voice.CACHE holds binary mp3
files (edge-tts renders) served two ways - by URL (`/glance/voice/<id>.mp3`,
a raw file read) and inline as base64 (render_b64, a raw bytes read for the
phone's sealed-JSON channel). Forcing these into a `data TEXT` column would
mean base64-encoding audio into SQLite text for no functional gain (path_for()
already does exactly the traversal-safe id check a "row lookup" would give
you, at zero cost); this is the same class of call as checkpoints.py's
directory-snapshot shape, not the processes.json JSON-blob shape.

What DOES matter for test isolation (the actual incident this debt item is
about) is that CACHE is a module-level global computed from voice.py's own
__file__, independent of db.ROOT - exactly like CDIR/VDIR in connectors.py
and CPDIR in checkpoints.py. This test proves voice.py is safely sandboxable
by patching CACHE alone, and exercises path_for()/stats()/_prune() against a
temp directory to lock in that no code path falls back to the real ROOT.
render()/render_b64() are NOT exercised here (they need edge_tts + network,
which is exactly the "fails soft" path voice.py already documents) - this
test covers the filesystem-touching surface that could otherwise leak into
daemon/voice_cache/.

Run: py -3.12 test_voice_db_migration.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_fails = []
def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)


def main():
    tmp = tempfile.mkdtemp(prefix="helmdeck-voicedb-test-")

    from daemon.spine import voice
    cache = os.path.join(tmp, "voice_cache")
    voice.CACHE = cache
    # do NOT create `cache` up front - path_for()/stats() must tolerate a
    # not-yet-existing CACHE dir (mirrors a fresh daemon that never spoke).

    ok(voice.path_for("not-a-real-id") is None,
       "path_for() on a nonexistent id resolves to None without creating CACHE")
    ok(not os.path.isdir(cache), "path_for() never creates the cache dir as a side effect")

    st = voice.stats()
    ok(st["cached"] == 0, "stats() on an empty/missing sandboxed CACHE reports 0 cached files")

    # simulate two prior renders landing in the sandboxed cache (synthetic
    # bytes, never a real edge-tts network call).
    os.makedirs(cache, exist_ok=True)
    vid_a, vid_b = "a" * 20, "b" * 20
    for vid in (vid_a, vid_b):
        with open(os.path.join(cache, vid + ".mp3"), "wb") as f:
            f.write(b"\x00" * 600)

    ok(voice.path_for(vid_a) == os.path.join(cache, vid_a + ".mp3"),
       "path_for() resolves an existing sandboxed cache entry")
    ok(voice.stats()["cached"] == 2, "stats() counts the sandboxed cache files, not the real one")

    # traversal guard: a crafted id must never escape CACHE via path_for().
    ok(voice.path_for("../../etc") is None, "path_for() rejects a non-alnum id (traversal guard)")
    ok(voice.path_for("x" * 40) is None, "path_for() rejects an over-length id")

    # _prune() respects MAX_FILES against the SANDBOXED cache only.
    old_max = voice.MAX_FILES
    voice.MAX_FILES = 1
    try:
        voice._prune()
        remaining = [f for f in os.listdir(cache) if f.endswith(".mp3")]
        ok(len(remaining) == 1, "_prune() trims the sandboxed cache down to MAX_FILES")
    finally:
        voice.MAX_FILES = old_max

    print(("\n%d FAILURE(S)" % len(_fails)) if _fails else "\nALL PASS")
    sys.exit(1 if _fails else 0)


if __name__ == "__main__":
    main()
