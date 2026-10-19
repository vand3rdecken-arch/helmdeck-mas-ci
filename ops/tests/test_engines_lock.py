"""/engines must not serialise behind the engine CLI (2026-10-19).

engines.entry ran models_of() - i.e. `opencode models`, ~6 s cold - while
holding the registry's _lock, and opencode_models.discover let every queued
cold caller run the CLI again. On the live daemon every relay serve worker sat
there and phone frames waited 12-33 s. Here: 8 parallel snapshots against a
CLI that takes 0.5 s must run it ONCE and finish in about one CLI call."""
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from spine.agent import engines, opencode_models  # noqa: E402

CALLS = []
_real_run = subprocess.run


def slow_run(argv, *a, **kw):
    if len(argv) > 1 and argv[1] == "models":
        CALLS.append(1)
        time.sleep(0.5)
        return subprocess.CompletedProcess(argv, 0, "opencode/test-model\n", "")
    return _real_run(argv, *a, **kw)


opencode_models.subprocess.run = slow_run
opencode_models._exe = lambda: "opencode"
engines._cached_ready = lambda name: True      # take the CLI path for opencode
opencode_models._cache.clear()

fails = 0


def check(cond, msg):
    global fails
    print(("ok   " if cond else "FAIL ") + msg)
    fails += 0 if cond else 1


engines.snapshot()                              # warm the probe cache (not under test)
opencode_models._cache.clear()
CALLS.clear()
t0 = time.time()
ts = [threading.Thread(target=engines.snapshot) for _ in range(8)]
for t in ts:
    t.start()
for t in ts:
    t.join()
took = time.time() - t0
check(len(CALLS) == 1, "8 cold callers ran the CLI once (ran %d)" % len(CALLS))
check(took < 1.5, "and finished in about one CLI call (%.2f s)" % took)
print("RESULT:", "PASS" if not fails else "FAIL (%d)" % fails)
sys.exit(1 if fails else 0)
