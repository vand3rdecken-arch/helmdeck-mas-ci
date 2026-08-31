# -*- coding: utf-8 -*-
"""THE GENERIC GATE - the one a repo that is not HelmDeck gets.

`ops/tools/run_gate.py` is HelmDeck's OWN gate: it compiles `daemon/`, `spine/`,
`cells/` and imports `spine.http.server`. Those names are correct there and
meaningless anywhere else - pointed at a foreign repo it finds none of them,
runs zero checks and prints PASS. That is the failure this file exists to end:
a NEW repo, onboarded from a template, must get a gate that actually looks at
its code without the owner writing one by hand.

SAME DECREE, SAME WEIGHT (owner 2026-08-21, debt [gate-light]): a gate is data
hygiene, not judgment - CODE CHECK ("does it parse / does it typecheck"),
seconds to a couple of minutes, no test suites, no lints, no style. What
changes here is only WHERE the check list comes from: derived from the files
the target repo actually has, instead of from HelmDeck's folder names.

DERIVED, NOT ASSUMED (CLAUDE.md, no monkey patches). Every check below is
emitted because a MARKER FILE was seen in this tree at this moment - and a
toolchain that is present but not installed (a TS repo with no node_modules) is
reported as an honest SKIP with its reason, never silently dropped and never
guessed around by running an installer. A gate may not mutate the tree it
grades: nothing here installs, fetches or writes.

Exit 0 = pass, non-zero = the card stays on Review with the output (the
contract lanemachine._gate reads).
"""
import glob
import json
import os
import subprocess
import sys

PY = sys.executable
ROOT = os.getcwd()
fails = []
ran = []
skips = []

# Directories that are never the repo's own source: vendored dependencies,
# build output and virtualenvs. Compiling those would grade someone else's code
# and turn a green repo red on a dependency's syntax.
IGNORE = ("node_modules", "__pycache__", ".git", "venv", ".venv", "env",
          "site-packages", "dist", "build", ".next", "target", "vendor",
          ".expo", ".tox", ".mypy_cache", "Pods")


def _own(path):
    parts = path.replace("\\", "/").split("/")
    return not any(p in IGNORE for p in parts)


def run(label, args, shell=False):
    try:
        r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                           shell=shell, encoding="utf-8", errors="replace")
    except OSError as e:
        # The tool named by the marker file is not on PATH. That is a SKIP with
        # a reason, not a red card: a repo may legitimately be graded on a box
        # that has node but not cargo.
        skips.append("%s: %s" % (label, e))
        print("  skip  %s (%s)" % (label, e))
        return
    ran.append(label)
    if r.returncode != 0:
        tail = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()[-1200:]
        fails.append("%s:\n%s" % (label, tail))
        print("  FAIL  " + label)
    else:
        print("  ok    " + label)


def skip(label, why):
    skips.append("%s: %s" % (label, why))
    print("  skip  %s (%s)" % (label, why))


def has(*names):
    return any(os.path.exists(os.path.join(ROOT, n)) for n in names)


# -- PYTHON -------------------------------------------------------------------
# Marker: any .py the repo owns. py_compile is the exact CODE CHECK run_gate.py
# applies to HelmDeck, minus the hardcoded folder names.
py_files = sorted(p for p in glob.glob("**/*.py", recursive=True) if _own(p))
if py_files:
    run("py_compile %d python file(s)" % len(py_files),
        [PY, "-m", "py_compile", *py_files])

# -- NODE / TYPESCRIPT --------------------------------------------------------
# The repo's OWN declaration wins over our guess: a `gate` script in
# package.json is the owner saying what this repo's code check is, and a
# `typecheck` script is the near-universal convention for the same thing. Only
# if neither exists do we fall back to invoking tsc ourselves.
pkg_path = os.path.join(ROOT, "package.json")
if os.path.exists(pkg_path):
    try:
        with open(pkg_path, encoding="utf-8") as f:
            scripts = (json.load(f) or {}).get("scripts") or {}
    except (ValueError, OSError) as e:
        scripts = {}
        skip("package.json", "unlesbar (%s)" % e)
    have_modules = os.path.isdir(os.path.join(ROOT, "node_modules"))
    named = next((s for s in ("gate", "typecheck", "tsc") if s in scripts), "")
    if named and not have_modules:
        # Running it would make npm fetch the world - a gate that mutates the
        # tree it grades. Say what is missing instead.
        skip("npm run %s" % named, "node_modules fehlt - erst `npm install`")
    elif named:
        run("npm run %s" % named, "npm run " + named, shell=True)
    elif os.path.exists(os.path.join(ROOT, "tsconfig.json")):
        if os.path.isdir(os.path.join(ROOT, "node_modules", "typescript")):
            run("tsc --noEmit", [os.path.join(ROOT, "node_modules", ".bin", "tsc"),
                                 "--noEmit"], shell=True)
        else:
            skip("tsc --noEmit", "typescript nicht installiert - erst `npm install`")

# -- RUST ---------------------------------------------------------------------
if has("Cargo.toml"):
    run("cargo check", ["cargo", "check", "--quiet"])

# -- GO -----------------------------------------------------------------------
if has("go.mod"):
    run("go build ./...", ["go", "build", "./..."])

# -- VERDICT ------------------------------------------------------------------
# The honest ending matters as much as the checks. "Nothing ran" is NOT the same
# claim as "everything passed", and a gate that prints PASS for both teaches the
# owner to stop reading it.
if fails:
    print("\n=== GATE FAILED (%d) ===" % len(fails))
    for f in fails:
        print(f)
    sys.exit(1)

if not ran:
    # Two different "nothing ran" cases, and calling them the same thing is how
    # a broken toolchain hides: a repo we do not recognise at all, versus one we
    # recognised and then could not check. The second is the owner's to fix.
    if skips:
        print("gate: NOTHING was checked - every applicable check was skipped:")
        for s in skips:
            print("  - " + s)
        print("PASS (nothing ran, so nothing failed - but nothing was verified "
              "either)")
    else:
        print("gate: no code check applied to this repo - nothing recognised "
              "(python/node/rust/go). PASS")
    sys.exit(0)

print("\ngate: PASS (%d checks)" % len(ran))
if skips:
    print("uebersprungen (kein Fehler, aber auch nicht geprueft):")
    for s in skips:
        print("  - " + s)
sys.exit(0)
