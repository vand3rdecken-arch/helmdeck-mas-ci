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

# 2b. one language, no leftovers (the mix creeps back one hardcoded label at a time)
if os.path.exists(os.path.join("tools", "i18n_lint.py")):
    run("i18n_lint", [PY, "tools/i18n_lint.py"])

# 3. self-sandboxed unit tests (skip the live-server e2e_* ones)
#
# BOTH directories. daemon/test_*.py used to be run by nobody: six files sat
# next to the modules they cover and no gate, hook or workflow ever executed
# them. Two had quietly rotted - test_p1_runtime.py's fake session hand-listed
# attributes that _ClaudeSession.__init__ had since outgrown, so it died on an
# AttributeError partway through and every check after that point silently
# stopped running, one of them pinning a rendering the code had legitimately
# moved past. A test nothing runs is not coverage, it is a comment that costs
# maintenance - so they run here, where a red result actually holds a card on
# Review.
for d in ("tests", "daemon"):
    for path in sorted(glob.glob(os.path.join(d, "test_*.py"))):
        name = os.path.basename(path)
        if name.startswith("e2e"):
            continue
        run("%s/%s" % (d, name), [PY, path])

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
