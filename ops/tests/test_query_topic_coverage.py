"""Every app query root is refreshed by a board topic - or declared not to be.

2026-10-19: board events now name WHAT moved and the app refetches only the
query roots a topic maps to (surfaces/app/src/data/invalidate.ts TOPIC_KEYS).
A hand-kept table invites one silent failure: a NEW screen whose query root is
in no topic never refetches on a board change again. This scans the app and
cells UI for `queryKey: ["<root>"` and fails on any root that is neither in
TOPIC_KEYS nor in NOT_BOARD_KEYS (the chat streams, immutable images).

Run: py -3.12 ops/tests/test_query_topic_coverage.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP = os.path.join(ROOT, "surfaces", "app", "src")
INV = os.path.join(APP, "data", "invalidate.ts")

src = open(INV, encoding="utf-8").read()
table = src[src.index("export const TOPIC_KEYS"):src.index("export const NOT_BOARD_KEYS")]
nonb = src[src.index("export const NOT_BOARD_KEYS"):src.index("export function keysFor")]
covered = set(re.findall(r'"([A-Za-z_-]+)"', table.split("=", 1)[1]))
declared = set(re.findall(r'"([A-Za-z_-]+)"', nonb.split("=", 1)[1]))

roots = {}
dirs = [APP] + [os.path.join(ROOT, "cells", c, "ui") for c in os.listdir(os.path.join(ROOT, "cells"))]
for d in dirs:
    for dp, dn, fn in os.walk(d):
        dn[:] = [x for x in dn if x != "node_modules" and not x.startswith(".")]
        for f in fn:
            if not f.endswith((".ts", ".tsx")) or "selftest" in f:
                continue
            p = os.path.join(dp, f)
            for m in re.finditer(r'queryKey: \["([A-Za-z_-]+)"', open(p, encoding="utf-8").read()):
                roots.setdefault(m.group(1), os.path.relpath(p, ROOT))

fails = 0


def check(c, m):
    global fails
    print(("ok   " if c else "FAIL ") + m)
    fails += 0 if c else 1


check(len(roots) > 30, "scanned the app's query roots (%d)" % len(roots))
missing = sorted(r for r in roots if r not in covered and r not in declared)
check(not missing, "every query root has a topic or is a declared non-board key%s"
      % ("" if not missing else " - MISSING: " + ", ".join("%s (%s)" % (r, roots[r]) for r in missing)))
both = sorted(covered & declared)
check(not both, "no root is both board-refreshed and declared non-board%s" % (" - " + ", ".join(both) if both else ""))
print("RESULT:", "PASS" if not fails else "FAIL (%d)" % fails)
sys.exit(1 if fails else 0)
