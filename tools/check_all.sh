#!/usr/bin/env bash
# One-command local check mirroring the build loop (loop_state EXECUTE checks
# + the run_gate.py suite):
#
#   bash tools/check_all.sh
#
# Runs, in order: daemon py_compile, app/ (Expo) tsc --noEmit, design-lint
# selftest, design_lint over the git-dirty files (the same set the loop
# lints), the self-sandboxed tests/test_*.py (e2e_* skipped - they need
# :3300), and the tests/unit pytest suite. Any failure -> nonzero exit; each
# check is skipped (not failed) when its inputs are absent so the script
# works on any branch.
set -o pipefail        # NOT -u: Git Bash may leave Windows env vars unset
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

NODE_DIR="/c/Program Files/nodejs"
export PATH="$NODE_DIR:$PATH"

# Same interpreter the repo uses everywhere (CLAUDE.md: py -3.12).
if command -v py >/dev/null 2>&1; then PY="py -3.12"
elif command -v python3 >/dev/null 2>&1; then PY=python3
else PY=python
fi

ok=(); fail=(); skip=()

run() {   # run <label> <cmd...>  - print output only on failure
  local label="$1"; shift
  local out
  if out=$("$@" 2>&1); then
    ok+=("$label"); echo "  ok    $label"
  else
    fail+=("$label"); echo "  FAIL  $label"
    echo "$out" | tail -n 30 | sed 's/^/        /'
  fi
}

# 1. daemon compiles
daemon_py=(daemon/*.py)
if [ -e "${daemon_py[0]}" ]; then
  run "py_compile daemon/*.py" $PY -m py_compile "${daemon_py[@]}"
else
  skip+=("py_compile (no daemon/*.py)")
fi

# 2. app/ (Expo) types - the only frontend now (web/ Next.js is archived).
if [ -d app/node_modules ]; then
  run "app tsc --noEmit" bash -c 'cd app && npx tsc --noEmit -p tsconfig.json'
else
  skip+=("app tsc (no app/node_modules - run npm install in app/)")
fi

# 3. design lint: the selftest proves the linter, then the linter runs over
#    the dirty files exactly as tools/loop_state.py does in EXECUTE.
if [ -f tools/design_lint_selftest.py ]; then
  run "design_lint selftest" $PY tools/design_lint_selftest.py
fi
run "design_lint (dirty files)" $PY -c '
import subprocess, sys
sys.path.insert(0, "tools")
import design_lint
out = subprocess.run(["git", "status", "--porcelain"],
                     capture_output=True, text=True).stdout
touched = [l[3:].strip().strip("\"") for l in out.splitlines() if len(l) > 3]
problems = design_lint.lint(touched)
for p in problems:
    print("design: " + p)
sys.exit(1 if problems else 0)
'

# 4. self-sandboxed unit tests (live-server e2e_* skipped, as in run_gate.py)
for t in tests/test_*.py; do
  [ -e "$t" ] || continue
  run "$(basename "$t")" $PY "$t"
done

# 5. headless pytest suite
if [ -d tests/unit ]; then
  if $PY -m pytest --version >/dev/null 2>&1; then
    run "pytest tests/unit" $PY -m pytest tests/unit -q
  else
    skip+=("pytest tests/unit (pytest not installed for $PY)")
  fi
fi

echo
echo "===== check summary ====="
for s in "${skip[@]:-}"; do [ -n "$s" ] && echo "  skip  $s"; done
for f in "${fail[@]:-}"; do [ -n "$f" ] && echo "  FAIL  $f"; done
if [ ${#fail[@]} -gt 0 ]; then
  echo "check_all: FAIL (${#fail[@]} of $((${#ok[@]} + ${#fail[@]})) checks)"
  exit 1
fi
echo "check_all: PASS (${#ok[@]} checks)"
