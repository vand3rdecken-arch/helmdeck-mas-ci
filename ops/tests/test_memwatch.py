# -*- coding: utf-8 -*-
"""memwatch (spine/ops/memwatch.py): the cheap sampler that stays after the
tracemalloc diagnosis window was removed (2026-10-15).

  - process_memory reads real private / working-set / peak numbers via ctypes;
  - sample() writes ONE `mem` event with them into the event log;
  - the peak working set is a high-water mark: it SEES a transient spike that a
    10-minute raster would miss (the old prune loaded 374 MB for two seconds);
  - starting memwatch never turns tracemalloc on (it slowed allocation-heavy
    paths ~2.8x), and report() carries no allocation-site data any more.

Run: py -3.12 ops/tests/test_memwatch.py
"""
import os
import sys
import tempfile
import tracemalloc

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

SANDBOX = tempfile.mkdtemp()
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")          # never the live db
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()

from spine.ops import memwatch

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def mem_events():
    return [d for d in events.read_events() if d.get("kind") == "mem"]


priv, ws, peak = memwatch.process_memory()
check(priv and priv > 10 and ws and ws > 10 and peak and peak >= ws,
      "private / working set / peak come back as real numbers (%.0f / %.0f / %.0f MB)" % (priv or 0, ws or 0, peak or 0))

memwatch.sample()
ev = mem_events()
check(len(ev) == 1 and "private" in str(ev[0]) and "peak" in str(ev[0]) and "threads" in str(ev[0]),
      "sample() writes one `mem` event with size, peak and thread count")

before = memwatch.process_memory()[2]
spike = bytearray(120 * 1024 * 1024)
for i in range(0, len(spike), 4096):                       # touch every page: it must enter the working set
    spike[i] = 1
del spike
after = memwatch.process_memory()
check(after[2] >= before + 100, "a freed 120 MB spike still shows in the peak (%.0f -> %.0f MB) while the live size fell back (%.0f MB)"
      % (before, after[2], after[1]))

check(not tracemalloc.is_tracing(), "memwatch does not turn tracemalloc on")
memwatch.start(every=3600)
check(not tracemalloc.is_tracing(), "...nor does start()")
rep = memwatch.report()
check(rep["private_mb"] and "peak_working_set_mb" in rep and "grew_since_baseline_kib" not in rep,
      "report() is the cheap shape (no allocation-site data)")

print()
if _fails:
    print("FAILED: %d check(s)" % len(_fails))
    sys.exit(1)
print("ALL GREEN - memwatch samples size and peak, and costs nothing between samples")
