# -*- coding: utf-8 -*-
"""memwatch (spine/ops/memwatch.py) must do its one job: name the code LINE
that holds growing memory, write it to the event log, and switch its own
expensive half off when the window is over.

Run: py -3.12 ops/tests/test_memwatch.py
"""
import os
import sys
import tempfile
import time
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


_LEAK = []


def _the_leaky_line():
    _LEAK.append(bytearray(1024 * 1024))                  # <- the line memwatch must name


def mem_events():
    return [d for d in events.read_events() if d.get("kind") == "mem"]


def test_process_memory_is_read():
    priv, ws = memwatch.process_memory()
    check(priv and priv > 10 and ws and ws > 10, "private/working-set size come back as real numbers (%.0f / %.0f MB)" % (priv or 0, ws or 0))


def test_names_the_growing_line():
    tracemalloc.stop()
    memwatch._baseline = None
    memwatch._started = time.time() - memwatch.BASELINE_AFTER - 1
    tracemalloc.start(1)
    memwatch.sample()                                      # takes the baseline, logs a line
    first = mem_events()
    check(len(first) == 1 and "private" in str(first[0]), "a `mem` event with the process size is written to the event log")
    for _ in range(40):
        _the_leaky_line()
    rep = memwatch.report()
    sites = [g["site"] for g in rep["grew_since_baseline_kib"]]
    check(any(s.endswith("test_memwatch.py:%d" % (_the_leaky_line.__code__.co_firstlineno + 1)) for s in sites[:3]),
          "the leaking line is among the top growers: %s" % (sites[:2],))
    top = rep["grew_since_baseline_kib"][0]
    check(top["plus_kib"] >= 30 * 1024, "...with its growth (%.0f KiB for 40 MiB allocated)" % top["plus_kib"])
    memwatch.sample()
    last = str(mem_events()[-1])
    check("GREW:" in last and "test_memwatch.py" in last, "the logged event names that line too")


def test_the_expensive_half_switches_itself_off():
    memwatch._started = time.time() - memwatch.TRACE_HOURS * 3600 - 5
    memwatch.sample()
    check(not tracemalloc.is_tracing(), "after TRACE_HOURS tracemalloc is stopped")
    check("window over" in str(mem_events()[-1]), "...and the event says so; sampling itself continues")


if __name__ == "__main__":
    test_process_memory_is_read()
    test_names_the_growing_line()
    test_the_expensive_half_switches_itself_off()
    print()
    if _fails:
        print("FAILED: %d check(s)" % len(_fails))
        sys.exit(1)
    print("ALL GREEN - memwatch names the growing line and ends its own cost")
