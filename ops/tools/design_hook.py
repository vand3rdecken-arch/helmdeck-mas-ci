# -*- coding: utf-8 -*-
"""PostToolUse hook: after any Edit/Write, run the design lint on the current
tree and surface violations immediately. Advisory feedback (never blocks a
single edit); the hard gate is the Stop hook via loop_state's EXECUTE state.
Two layers: fast feedback here, deterministic commit-gate there."""
import json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    json.load(sys.stdin)   # drain payload
except Exception:
    pass
sys.path.insert(0, os.path.join(ROOT, "ops", "tools"))
try:
    import design_lint
    r = subprocess.run(["git", "-C", ROOT, "status", "--porcelain"],
                       capture_output=True, text=True)
    touched = [l[3:].strip().strip('"') for l in r.stdout.splitlines() if len(l) > 3]
    v = design_lint.lint(touched)
    if v:
        print("[design-lint] %d issue(s) - fix before the loop will let you rest:" % len(v))
        for x in v:
            print("  - " + x)
except Exception:
    pass
sys.exit(0)
