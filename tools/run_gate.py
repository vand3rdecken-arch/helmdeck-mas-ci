# -*- coding: utf-8 -*-
"""HelmDeck quality gate - run by the DAEMON at Review/Accept (see sessions._gate),
NOT by the card's agent. The harness has full command access, so these checks
always run even when the agent's permission mode gates commands.

LIGHT BY DECREE (owner, 2026-08-21, debt [gate-light]): a gate is data hygiene,
not judgment - CODE CHECK (it parses) + FUNCTION CHECK (the daemon wires up),
seconds not minutes. No lints, no tests, no style. The old form ran every test_*.py per card -
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
# Everything python parses - ALL daemon packages, not just the top level.
# NOTE the lints (design_lint_selftest, i18n_lint) were removed by decree
# 2026-08-21: they are style JUDGMENT, not hygiene - a hardcoded German label
# must not hold a merge hostage. They remain manual tools and belong to the
# e2e-before-build step, where presentation is actually looked at.
daemon_py = sorted(
    p
    for tree in ("daemon", "spine", "cells")
    for p in glob.glob(os.path.join(tree, "**", "*.py"), recursive=True)
    if "__pycache__" not in p
)
if daemon_py:
    run("py_compile daemon/spine/cells **/*.py", [PY, "-m", "py_compile", *daemon_py])

# -- FUNCTION CHECK -----------------------------------------------------------
# The daemon WIRES UP: importing the http server pulls the spine, routes and
# cells transitively, catching what py_compile cannot - a bad import, a
# missing symbol, a module-level wiring error (the exact class of the
# function-local-import UnboundLocalError bug). Import only, never serve.
# daemon.swarm alone no longer suffices: since spine/cells moved to the repo
# root it is a thin launcher whose spine imports are function-local.
if os.path.isdir("daemon"):
    run("daemon wires up (import daemon.swarm)",
        [PY, "-c", "import daemon.swarm"])
if os.path.isdir("spine"):
    run("spine+cells wire up (import spine.http.server)",
        [PY, "-c", "import spine.http.server"])

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
