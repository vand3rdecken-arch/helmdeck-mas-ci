# -*- coding: utf-8 -*-
"""The FULL test suite - the old per-card gate, demoted to a BASE health
monitor (owner decree 2026-08-21, debt [gate-light]). Run it against the
trunk checkout on a schedule or after a night-shift batch - NEVER per card:
per-card it cost ~8 minutes, redded on base breakage a card never touched,
and redded on box load (a Gradle build starved a timing assertion).

Green = silence. Red = base health incident: fix the trunk (or file the card),
do not bounce anyone's work over it.

Runs every self-sandboxed tests/test_*.py and daemon/test_*.py sequentially
(the live-server e2e_* tests still need :3300 and are skipped).

Usage: py -3.12 tools/run_suite.py       (from the repo root)"""
import glob
import os
import subprocess
import sys

PY = sys.executable
ROOT = os.getcwd()
fails = []
ran = []

for d in ("tests", "daemon"):
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
