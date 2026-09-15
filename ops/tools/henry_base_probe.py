"""Measure Henry's FIXED base (system prompt + tools + CLAUDE.md/memory +
rendered brief) with his real spawn shape on a throwaway session: one
trivial turn, the first call's input+cache_creation+cache_read IS the base.
Same cwd shape as the live daemon (DAEMON_ROOT), haiku (the count is
model-independent). Cleans up after itself."""
import json, os, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from spine.agent import drivers, claude_sessions
from spine.agent.agentcli import CLAUDE
from spine.agent.spawnenv import tool_path
from spine.registry import harness
from cells.copilot.chat import copilot
from daemon.paths import DAEMON_ROOT

text = harness.brief("board-copilot")
bf = copilot._brief_file(text)
argv = [CLAUDE, "-p", "--output-format", "json", "--permission-mode", "plan", "--model", "haiku",
        "--append-system-prompt-file", bf] + harness.cli_args("board-copilot") + copilot._lean_mcp_args()
p = subprocess.run(drivers._cmd_line(argv), cwd=DAEMON_ROOT, input="Antworte nur mit 'ok'.",
                   capture_output=True, text=True, encoding="utf-8", errors="replace",
                   env=tool_path(), timeout=180)
r = json.loads(p.stdout)
u = r.get("usage") or {}
base = u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)
print("brief: %d chars | base context on first call: %d tokens (in=%d, cache_create=%d, cache_read=%d)" % (
    len(text), base, u.get("input_tokens", 0), u.get("cache_creation_input_tokens", 0), u.get("cache_read_input_tokens", 0)))
path = claude_sessions._find_transcript(r.get("session_id"))
if path:
    try:
        os.remove(path)
    except OSError:
        pass
try:
    os.remove(bf)
except OSError:
    pass
