# -*- coding: utf-8 -*-
"""ops/tools/app_shot.py against a real route yields a screenshot + text file and
leaves no junction behind. Slow (Expo web bundle, up to minutes cold); skips when
the main repo has no node_modules. Run: py -3.12 ops/tests/test_app_shot.py"""
import os, shutil, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if not shutil.which("npx"):
    os.environ["PATH"] = r"C:\Program Files\nodejs" + os.pathsep + os.environ["PATH"]
r = subprocess.run([sys.executable, os.path.join(ROOT, "ops", "tools", "app_shot.py"), "board"],
                   cwd=ROOT, capture_output=True, text=True)
line = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
ok = (line.startswith("route=/board text=") and os.path.getsize(os.path.join(ROOT, ".shots", "board.png")) > 5000
      and not os.path.exists(os.path.join(ROOT, "surfaces", "app", "node_modules")))
print(("ok   " if ok else "FAIL ") + (line or r.stderr[-300:]))
sys.exit(0 if ok else 1)
