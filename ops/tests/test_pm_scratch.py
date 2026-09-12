# -*- coding: utf-8 -*-
"""The planner cannot leave a file in the repo (state-into-db phase B).

The trigger (2026-09-11 22:01Z, daemon/board_full.txt): the PM planner ran
`board_state.py --full`, could not search 105k chars in one turn, and
redirected the output to a file so it could grep it. A `:*` prefix rule
cannot see a `>` redirect, and its cwd was daemon/ - so the dump landed in
the tree and surfaced in the owner's diff view a day later.

Proven to FAIL on the old code: case 1 runs pm._ask(hands=True) with a fake
CLI that does exactly that (`echo dump > leak.txt` in its cwd) and asserts
the repo tree is byte-identical afterwards. On the old code cwd was daemon/
and leak.txt appeared there.

  1. a hands-on planning turn runs in a scratch cwd OUTSIDE the repo that
     holds only hd.py; a stray write lands there; the folder is gone after
     the turn; the repo's untracked set is unchanged
  2. the wrapper dispatches the three evidence tools by absolute path and
     nothing else (an unknown verb exits 2)
  3. the pm.json allowlist grants exactly the wrapper, nothing path-relative
  4. board_state --card output is capped
  5. loop_state.state_leaks() flags an untracked file under daemon/ and
     hygiene_problems() names it

Run:  py -3.12 ops/tests/test_pm_scratch.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "ops", "tools"))

from spine.storage import db                      # noqa: E402
db.DBPATH = os.path.join(tempfile.mkdtemp(prefix="hd-pmscratch-"), "test.db")
db.init()

from cells.copilot.planning import pm             # noqa: E402
import loop_state                                 # noqa: E402

_fails = []


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def untracked():
    r = subprocess.run(["git", "-C", ROOT, "status", "--porcelain", "--untracked-files=all"],
                       capture_output=True, text=True)
    return sorted(l for l in r.stdout.splitlines() if l.startswith("??"))


print("1. a hands-on turn cannot leak into the repo")
FAKE_CLI = os.path.join(tempfile.mkdtemp(prefix="hd-fakecli-"), "fake_claude.py")
with open(FAKE_CLI, "w", encoding="utf-8") as f:
    f.write('import json, os, sys\n'
            'open("leak.txt", "w").write("dump")\n'          # the redirect, in cwd
            'sys.stdout.write(json.dumps({"result": json.dumps({"summary": "s", "milestones": [], '
            '"next": [], "risks": [], "seen_cwd": os.getcwd(), "has_wrapper": os.path.exists("hd.py")}),'
            ' "num_turns": 1}))\n')
seen = {}
_real_popen = pm.subprocess.Popen


def fake_popen(cmd, cwd=None, **kw):
    seen["cwd"] = cwd
    seen["wrapper_before"] = os.path.exists(os.path.join(cwd or ".", "hd.py"))
    return _real_popen([sys.executable, FAKE_CLI], cwd=cwd, **kw)


before = untracked()
pm.subprocess.Popen = fake_popen
try:
    out = pm._ask("plan", "", system="role", hands=True, timeout=60)
finally:
    pm.subprocess.Popen = _real_popen
after = untracked()
cwd = seen.get("cwd") or ""
check(bool(cwd) and os.path.abspath(cwd).lower().startswith(os.path.abspath(tempfile.gettempdir()).lower()),
      "the planner ran in a scratch cwd under the OS temp dir (%s)" % cwd)
check(not os.path.abspath(cwd).lower().startswith(ROOT.lower()), "...which is outside the repo")
check(seen.get("wrapper_before") is True and out.get("has_wrapper") is True,
      "the scratch cwd held hd.py when the CLI started")
check(out.get("seen_cwd", "").lower() == os.path.abspath(cwd).lower(), "the CLI really ran there")
check(not os.path.exists(cwd), "the scratch folder is gone after the turn (leak.txt with it)")
check(before == after, "the repo's untracked set is unchanged - nothing leaked into the tree")
check(not os.path.exists(os.path.join(ROOT, "daemon", "leak.txt")), "daemon/leak.txt does not exist")

print("2. the wrapper dispatches only the evidence tools")
wdir = pm._scratch_cwd()
try:
    src = open(os.path.join(wdir, "hd.py"), encoding="utf-8").read()
    check(repr(ROOT) in src or ROOT.replace("\\", "\\\\") in src, "the wrapper bakes in this repo's absolute root")
    r = subprocess.run([sys.executable, "hd.py", "rm", "-rf"], cwd=wdir, capture_output=True, text=True)
    check(r.returncode == 2 and "usage" in r.stdout, "an unknown verb is refused with usage, exit 2")
    r = subprocess.run([sys.executable, "hd.py", "log"], cwd=wdir, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    check(r.returncode == 0 and len(r.stdout.splitlines()) >= 1, "`hd.py log` runs git log in the repo")
    r = subprocess.run([sys.executable, "hd.py", "board", "--find", "zzz-no-such-term"], cwd=wdir,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, HELMDECK_ALLOW_LIVE_DB="1"))
    check(r.returncode == 0 and "no card matches" in r.stdout, "`hd.py board --find` reaches board_state.py")
    check(sorted(os.listdir(wdir)) == ["hd.py"] or set(os.listdir(wdir)) <= {"hd.py", "__pycache__"},
          "the scratch folder holds only the wrapper")
finally:
    import shutil
    shutil.rmtree(wdir, ignore_errors=True)

print("3. the allowlist grants exactly the wrapper")
cfg = json.load(open(os.path.join(ROOT, "cells", "copilot", "harness", "settings", "pm.json"), encoding="utf-8"))
allow = cfg["permissions"]["allow"]
check(all("hd.py" in a for a in allow), "every allow rule is the wrapper (%s)" % allow)
check(not any("../" in a or "ops/tools" in a or "git log" in a for a in allow),
      "no path-relative or bare-git rule is left")
check("hd.py" in pm.EVIDENCE_TOOLS and "../ops" not in pm.EVIDENCE_TOOLS,
      "EVIDENCE_TOOLS names the wrapper commands only")

print("4. --card output is capped")
import board_state                                # noqa: E402
big = board_state.format_card({"id": "x", "task": "t", "last_reply": "y" * 20000})
check(len(big) < 8200 and "capped" in big, "a 20k-char card renders at most ~8k (%d)" % len(big))

print("5. loop_state flags an untracked file under daemon/")
leak = os.path.join(ROOT, "daemon", "zz_state_leak_test.txt")
try:
    open(leak, "w").write("x")
    leaks = loop_state.state_leaks()
    check(any("zz_state_leak_test.txt" in l for l in leaks), "state_leaks() sees it (%s)" % leaks)
    probs = loop_state.hygiene_problems()
    check(any("state leak" in p and "zz_state_leak_test.txt" in p for p in probs),
          "hygiene_problems() names it as a state leak")
finally:
    try:
        os.remove(leak)
    except OSError:
        pass
check(not any("zz_state_leak_test.txt" in l for l in loop_state.state_leaks()), "and it is clean again once removed")

print()
if _fails:
    print("FAILED: %d" % len(_fails))
    for f in _fails:
        print("  - " + f)
    sys.exit(1)
print("ALL OK")
