# -*- coding: utf-8 -*-
"""The card_tool_guard PreToolUse hook must resolve from ANY session cwd.

2026-09-12: Henry's chat turns run with cwd=daemon/, so the CLI set
CLAUDE_PROJECT_DIR=daemon/ and the shipped hook command
`py -3.12 "$CLAUDE_PROJECT_DIR/ops/tools/card_tool_guard.py"` pointed at
daemon/ops/tools/card_tool_guard.py - "can't open file", exit 2, which the
CLI treats as a BLOCKING hook error: every Read/Bash in Henry's turn died.
The same command breaks a card whose worktree is not a HelmDeck checkout.

This runs the REAL command string out of every shipped settings layer through
Git Bash (the shell the CLI runs hooks in) with the REAL spawn env
(spawnenv.tool_path) and the CLAUDE_PROJECT_DIR the CLI would set for that
cwd, feeding a harmless Read payload. Must exit 0 and not deny.

Run: py -3.12 ops/tests/test_guard_hook_cwd.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from spine.agent.spawnenv import tool_path  # noqa: E402
from spine.registry import harness  # noqa: E402


def _git_bash():
    p = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")
    if p and os.path.exists(p):
        return p
    git = shutil.which("git") or r"C:\Program Files\Git\cmd\git.exe"
    base = os.path.dirname(os.path.dirname(git))          # ...\Git
    if os.path.basename(base).lower() == "mingw64":
        base = os.path.dirname(base)
    return os.path.join(base, "bin", "bash.exe")


def main():
    bash = _git_bash()
    fails = []
    payload = json.dumps({"tool_name": "Read", "hook_event_name": "PreToolUse",
                          "tool_input": {"file_path": os.path.join(ROOT, "ARCHITECTURE.md")}})
    kill = json.dumps({"tool_name": "Bash", "hook_event_name": "PreToolUse",
                       "tool_input": {"command": "taskkill /PID 999999 /T /F"}})
    foreign = tempfile.mkdtemp(prefix="hd-foreign-cwd-")
    for key in ("copilot", "pm", "card"):
        with open(harness._settings_path(key), encoding="utf-8") as f:
            cmds = [h["command"] for blk in json.load(f)["hooks"]["PreToolUse"]
                    for h in blk["hooks"] if "card_tool_guard" in h["command"]]
        if not cmds:
            fails.append("%s.json: no card_tool_guard hook found" % key)
        for cmd in cmds:
            for cwd in (os.path.join(ROOT, "daemon"), ROOT, foreign):
                env = tool_path()
                env["CLAUDE_PROJECT_DIR"] = cwd       # what the CLI sets = session cwd
                env.pop("HELMDECK_WORKTREE", None)
                p = subprocess.run([bash, "-c", cmd], cwd=cwd, env=env, input=payload,
                                   capture_output=True, text=True, timeout=60)
                good = p.returncode == 0 and '"deny"' not in p.stdout
                print("%s %s.json cwd=%s rc=%s %s" % ("ok  " if good else "FAIL", key, cwd,
                                                     p.returncode, (p.stderr or p.stdout).strip()[:160]))
                if not good:
                    fails.append("%s.json from %s" % (key, cwd))
                # and the fence is still ARMED from here, not just "not failing"
                p = subprocess.run([bash, "-c", cmd], cwd=cwd, env=env, input=kill,
                                   capture_output=True, text=True, timeout=60)
                if '"deny"' not in p.stdout:
                    print("FAIL %s.json cwd=%s: taskkill /T not denied" % (key, cwd))
                    fails.append("%s.json from %s: not armed" % (key, cwd))
    shutil.rmtree(foreign, ignore_errors=True)
    print("\n%d failure(s)" % len(fails) if fails else "\nall guard-hook cwd checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
