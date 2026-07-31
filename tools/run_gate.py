# -*- coding: utf-8 -*-
"""HelmDeck quality gate - run by the DAEMON at Review/Accept (see sessions._gate),
NOT by the card's agent. That is the whole point: the harness has full command
access, so tests always run even when the agent's permission mode gates commands.

Runs from the card's worktree. Non-zero exit == gate fails == the card stays on
Review with the failing output. Checks (each skipped if absent so it works on any
branch): daemon py_compile, the design-lint selftest, and every self-sandboxed
tests/test_*.py (the live-server e2e_* tests are skipped - they need :3300)."""
import glob
import os
import subprocess
import sys

PY = sys.executable
ROOT = os.getcwd()
fails = []
ran = []


def run(label, args):
    r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    ran.append(label)
    if r.returncode != 0:
        tail = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()[-1200:]
        fails.append("%s:\n%s" % (label, tail))
        print("  FAIL  " + label)
    else:
        print("  ok    " + label)


# 1. daemon compiles
daemon_py = sorted(glob.glob(os.path.join("daemon", "*.py")))
if daemon_py:
    run("py_compile daemon/*.py", [PY, "-m", "py_compile", *daemon_py])

# 2. design-lint selftest
if os.path.exists(os.path.join("tools", "design_lint_selftest.py")):
    run("design_lint_selftest", [PY, "tools/design_lint_selftest.py"])

# 3. self-sandboxed unit tests (skip the live-server e2e_* ones)
for path in sorted(glob.glob(os.path.join("tests", "test_*.py"))):
    name = os.path.basename(path)
    if name.startswith("e2e"):
        continue
    run(name, [PY, path])

if not ran:
    print("gate: nothing to run on this branch - PASS")
    sys.exit(0)

if fails:
    print("\n=== GATE FAILED (%d) ===" % len(fails))
    for f in fails:
        print(f)
    sys.exit(1)
print("\ngate: PASS (%d checks)" % len(ran))
sys.exit(0)
