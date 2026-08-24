# -*- coding: utf-8 -*-
"""The FULL unit suite - MANUAL tool, nothing schedules or gates on this
(owner decree 2026-08-21 v2, debt [gate-light]). A fix's test runs ONCE at
the fix's own verification, then retires here as replayable documentation.
Run this deliberately when reworking a subsystem and you want the old pins
replayed against your change - never per card, never on a schedule: per-card
it cost ~8 minutes, redded on base breakage a card never touched, and redded
on box load. Recurring verification of the SYSTEM is e2e before builds/ships
(live daemon + web + Playwright), not this file.

Runs every self-sandboxed tests/test_*.py sequentially - ONE home since the
two-mains split moved the daemon-colocated tests here (2026-08-24). The
live-server e2e_* tests still need a running stack and are skipped.

Usage: py -3.12 tools/run_suite.py       (from the repo root)"""
import glob
import os
import subprocess
import sys

PY = sys.executable
ROOT = os.getcwd()
fails = []
ran = []

for d in ("tests",):
    for path in sorted(glob.glob(os.path.join(d, "test_*.py"))):
        name = os.path.basename(path)
        if name.startswith("e2e"):
            continue
        label = "%s/%s" % (d, name)
        r = subprocess.run([PY, path], cwd=ROOT, capture_output=True, text=True)
        ran.append(label)
        if r.returncode != 0:
            tail = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()[-1200:]
            fails.append("%s:\n%s" % (label, tail))
            print("  FAIL  " + label)
        else:
            print("  ok    " + label)

if fails:
    print("\n=== SUITE FAILED (%d/%d) ===" % (len(fails), len(ran)))
    for f in fails:
        print(f)
    sys.exit(1)
print("\nsuite: PASS (%d files)" % len(ran))
sys.exit(0)
