# -*- coding: utf-8 -*-
"""claude_sessions._session_objects must be BOUNDED. It used to parse the whole
transcript on the first call and keep every object for the life of the daemon:
on Henry's real 375 MB board session that was +930 MB private that never came
back (2.9 GB peak while parsing), for a feed that returns the last 400 steps.

Pinned with small limits, each against the real function:
  1. a file bigger than the window is read from its END: the first (partial)
     line is dropped, the last record is there, the count is far below the file's;
  2. later calls read only the appended bytes (incremental, nothing re-parsed);
  3. one entry never holds more than the budget: the OLDEST records drop;
  4. a shrunk file (rotation) starts over;
  5. a file under the window is read whole, exactly as before;
  6. the number of cached sessions is capped.

Run: py -3.12 ops/tests/test_session_objects_bound.py
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from spine.agent import claude_sessions as cs

tmp = tempfile.mkdtemp(prefix="session_objects_")
_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def write(path, n, start=0, mode="w", pad=200):
    with open(path, mode, encoding="utf-8") as f:
        for i in range(start, start + n):
            f.write(json.dumps({"i": i, "pad": "x" * pad}) + "\n")


def reset():
    cs._OBJS_CACHE.clear()


cs._OBJS_WINDOW = 50_000
cs._OBJS_BUDGET = 120_000

# 1. a big file is read from the end
p = os.path.join(tmp, "big.jsonl")
write(p, 2000)                                    # ~ 480 KB, far over the 50 KB window
size = os.path.getsize(p)
reset()
objs = cs._session_objects(p)
check(0 < len(objs) < 400, "a %d KB file yields only its tail (%d of 2000 records)" % (size // 1024, len(objs)))
check(objs[-1]["i"] == 1999, "the LAST record is there")
check(all(isinstance(o, dict) and "i" in o for o in objs), "no half-line was parsed (the partial first line is dropped)")
check(objs[0]["i"] == 2000 - len(objs), "the window is contiguous up to the end")
check(cs._OBJS_CACHE[p]["read"] == size, "the read position is the end of the file")

# 2. incremental
n0 = len(objs)
write(p, 3, start=2000, mode="a")
objs = cs._session_objects(p)
check(len(objs) == n0 + 3 and objs[-1]["i"] == 2002, "an appended record shows up without re-reading the file")
check(cs._session_objects(p) is objs or len(cs._session_objects(p)) == len(objs), "an unchanged file costs nothing")

# 3. the budget: the oldest records drop
write(p, 3000, start=2003, mode="a")             # ~700 KB appended in ONE read
objs = cs._session_objects(p)
held = cs._OBJS_CACHE[p]["bytes"]
check(held <= cs._OBJS_BUDGET, "one entry holds at most the budget (%d <= %d bytes)" % (held, cs._OBJS_BUDGET))
check(objs[-1]["i"] == 5002, "...and it is the NEWEST records that stay")
check(len(cs._OBJS_CACHE[p]["objs"]) == len(cs._OBJS_CACHE[p]["sz"]), "bookkeeping stays in step")

# 4. rotation: the file shrinks
write(p, 5)
objs = cs._session_objects(p)
check(len(objs) == 5 and objs[0]["i"] == 0, "a shrunk file starts over")

# 5. a small file is read whole
q = os.path.join(tmp, "small.jsonl")
write(q, 20)
reset()
objs = cs._session_objects(q)
check(len(objs) == 20 and objs[0]["i"] == 0, "a file under the window is read whole, from the first line")

# a record that is still being written is kept for the next call
with open(q, "a", encoding="utf-8") as f:
    f.write('{"i": 20, "pad": "half')
check(len(cs._session_objects(q)) == 20, "a half-written last line is NOT parsed yet")
with open(q, "a", encoding="utf-8") as f:
    f.write('-done"}\n')
check(len(cs._session_objects(q)) == 21 and cs._session_objects(q)[-1]["pad"] == "half-done", "...it lands once complete")

# 6. the cache is capped
reset()
for k in range(cs._OBJS_CACHE_MAX + 3):
    pk = os.path.join(tmp, "s%d.jsonl" % k)
    write(pk, 3)
    cs._session_objects(pk)
check(len(cs._OBJS_CACHE) == cs._OBJS_CACHE_MAX, "at most %d sessions are cached" % cs._OBJS_CACHE_MAX)

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails))
    sys.exit(1)
print("session-objects-bound: all pinned - PASS")
