# -*- coding: utf-8 -*-
"""HelmDeck quality gate - run by the DAEMON at Review/Accept (see sessions._gate),
NOT by the card's agent. The harness has full command access, so these checks
always run even when the agent's permission mode gates commands.

LIGHT BY DECREE (owner, 2026-08-21, debt [gate-light]): a gate is data hygiene,
not judgment - CODE CHECK (it parses and lints) + FUNCTION CHECK (the daemon
wires up), seconds not minutes. The old form ran every test_*.py per card -
66 files, ~8 minutes, growing daily, red on base breakage and on box load
(the Paseo lesson: verification of BEHAVIOR is the owner testing the deploy).
The full suite lives on in tools/run_suite.py as a BASE health monitor - run
it against the trunk on a schedule or after a batch, never per card.

Runs from the card's worktree. Non-zero exit == gate fails == the card stays
on Review with the failing output. Each check is skipped if its files are
absent, so it works on any branch."""
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


# -- CODE CHECK ---------------------------------------------------------------
# 1. everything python parses - ALL daemon packages, not just the top level
daemon_py = sorted(glob.glob(os.path.join("daemon", "**", "*.py"), recursive=True))
daemon_py = [p for p in daemon_py if "__pycache__" not in p]
if daemon_py:
    run("py_compile daemon/**/*.py", [PY, "-m", "py_compile", *daemon_py])

# 2. design-lint selftest
if os.path.exists(os.path.join("tools", "design_lint_selftest.py")):
    run("design_lint_selftest", [PY, "tools/design_lint_selftest.py"])

# 2b. one language, no leftovers (the mix creeps back one hardcoded label at a time)
if os.path.exists(os.path.join("tools", "i18n_lint.py")):
    run("i18n_lint", [PY, "tools/i18n_lint.py"])

# -- FUNCTION CHECK -----------------------------------------------------------
# The daemon WIRES UP: importing the serve entrypoint pulls the spine, routes
# and cells transitively, catching what py_compile cannot - a bad import, a
# missing symbol, a module-level wiring error (the exact class of the
# function-local-import UnboundLocalError bug). Import only, never serve.
if os.path.isdir("daemon"):
    run("daemon wires up (import daemon.swarm)",
        [PY, "-c", "import daemon.swarm"])

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
