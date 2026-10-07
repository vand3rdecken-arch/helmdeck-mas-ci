# -*- coding: utf-8 -*-
"""A long run exists ONLY as a registered run_in_background task.

Root cause of the 2026-10-07 stuck cards (20261007-133515, 20261007-134911):
the worker started the run OUTSIDE the harness ('&', Start-Process, ...), so
bg_tasks stayed empty, the turn settled needs_you, and nothing ever woke it.
Pins:
 1. card_tool_guard denies every unregistered detached start, end to end
    through the real hook process, and names the right way.
 2. It judges the PARSED command: prose, heredoc bodies and quoted strings
    never trip it; a `-c`/`-Command` payload does.
 3. Surfaces that legitimately launch things (hands, Henry's chat) are exempt.
 4. The other half of the contract, through the REAL driver code: a
    run_in_background launch folds a running descriptor, the card parks
    waiting_on=background (not delivered), and the task_notification makes the
    sweep steer the card - i.e. a registered task DOES resume the turn.
Sandboxed: temp db/settings, live-db guard stays armed.
Run: py -3.12 ops/tests/test_bg_launch_guard.py
"""
import importlib.util, inspect, json, os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
GUARD = os.path.join(ROOT, "ops", "tools", "card_tool_guard.py")
spec = importlib.util.spec_from_file_location("card_tool_guard", GUARD)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

_fails = []


def ok(cond, msg):
    print(("  ok   - " if cond else "  FAIL - ") + msg)
    if not cond:
        _fails.append(msg)


DETACHED = [
    ("Bash", "npm run build &"),
    ("Bash", "npm run build & echo started"),
    ("Bash", "./gradlew bundleRelease > out.log 2>&1 &"),
    ("Bash", "nohup python x.py > o.log"),
    ("Bash", "setsid python x.py"),
    ("Bash", "python x.py & disown"),
    ("Bash", 'bash -c "python x.py &"'),
    ("PowerShell", "Start-Process py -ArgumentList x.py"),
    ("PowerShell", "start-process notepad; Start-Sleep 5"),
    ("PowerShell", "Start-Job { gradlew bundleRelease }"),
    ("PowerShell", 'powershell -Command "Start-Process py"'),
    ("PowerShell", "cmd /c start py x.py"),
    ("Bash", "cmd /c start py x.py"),
]
FINE = [
    ("Bash", "npm run build"),
    ("Bash", "npm run build 2>&1 | tail -5"),
    ("Bash", "a && b"),
    ("Bash", "python x.py &> out.log"),
    ("Bash", "curl 'http://x/?a=1&b=2'"),
    ("Bash", "git commit -m 'run it with nohup and a trailing &'"),
    ("Bash", "python - <<'EOF'\nprint('nohup x &')\nStart-Process\nEOF"),
    ("Bash", "grep -rn nohup ops/tools/detach.py"),
    ("Bash", "py -3.12 ops/tools/detach.py out.log --title T -- python x.py"),
    ("PowerShell", "Start-Process py -ArgumentList x.py -Wait"),
    ("PowerShell", "& .\\gradlew.bat bundleRelease"),
    ("PowerShell", "cmd /c start /wait py x.py"),
]


def run(tool, command, **env_over):
    env = dict(os.environ)
    env.pop("HELMDECK_WORKTREE", None)
    env.pop("HELMDECK_TOOL_SCOPE", None)
    env.pop("HELMDECK_SURFACE", None)
    env.update(env_over)
    p = json.dumps({"tool_name": tool, "tool_input": {"command": command}})
    r = subprocess.run([sys.executable, GUARD], input=p, capture_output=True,
                       text=True, env=env, timeout=15)
    out = (r.stdout or "").strip()
    return json.loads(out)["hookSpecificOutput"] if out else None


print("guard, real hook process (machine card: no worktree var):")
for tool, c in DETACHED:
    ok((run(tool, c, HELMDECK_SURFACE="card") or {}).get("permissionDecision") == "deny",
       "denied: %s %r" % (tool, c))
for tool, c in FINE:
    ok(run(tool, c, HELMDECK_SURFACE="card") is None, "no opinion: %s %r" % (tool, c))

d = run("Bash", "npm run build &", HELMDECK_SURFACE="card")
ok("run_in_background" in d["permissionDecisionReason"] and "600000" in d["permissionDecisionReason"],
   "the denial names the right way")
ok(run("Bash", "npm run build &", HELMDECK_SURFACE="card", HELMDECK_WORKTREE=ROOT) is not None,
   "also denied on a worktree card")
ok(run("PowerShell", "Start-Process chrome", HELMDECK_TOOL_SCOPE="hands") is None, "hands is exempt")
ok(run("Bash", "nohup x &", HELMDECK_SURFACE="copilot") is None, "Henry's chat surface is exempt")

print("\nregistered task resumes the card (real driver pump + real sweep):")
SANDBOX = tempfile.mkdtemp(prefix="hd-bglg-")
from spine.storage import db
db.DBPATH = os.path.join(SANDBOX, "helmdeck.db")
from spine.storage import events
events.SET = os.path.join(SANDBOX, "settings.json")
db.init()
from spine.ops import runs
runs.REC = os.path.join(SANDBOX, "runs"); os.makedirs(runs.REC, exist_ok=True)
from spine.agent import drivers
from cells.engineer.cards import sessions, turnrunner

sessions.REC = runs.REC
cls = [o for n, o in inspect.getmembers(drivers) if inspect.isclass(o) and hasattr(o, "_scan_bg")][0]
TID = "bglg1"
os.makedirs(os.path.join(runs.REC, TID), exist_ok=True)
ts = [{"id": TID, "task": "t", "status": "running", "lane": "working", "run_dir": os.path.join(runs.REC, TID)}]
sessions._save(ts)


class S:
    tid = TID

    def __init__(self):
        self._bg_candidates, self._bg_open = {}, {}


s = S()
cls._scan_bg(s, {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "u1", "name": "Bash",
    "input": {"command": "py shot.py", "description": "app shot", "run_in_background": True}}]}})
cls._scan_bg(s, {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "u1",
    "content": "Command running in background with ID: b1."}]}})
t = sessions._find(sessions._load(), TID)
ok((t["bg_tasks"]["u1"]["status"]) == "running", "launch folded a running descriptor")
sessions._mutate(TID, lambda tt: tt.update(status="needs_you", waiting_on="background",
                                           background={"n": 1, "names": ["app shot"], "since": time.time()}))
ok(not turnrunner.is_delivered(sessions._find(sessions._load(), TID)),
   "parked on a registered task is NOT 'delivered' (no broker escalation)")

steers = []
drivers.has_session = lambda tid: True    # the worker process is alive
orig = sessions.steer
sessions.steer = lambda tid, text, **kw: steers.append((tid, text, kw))
try:
    sessions._sweep_background()
    time.sleep(0.3)
    ok(not steers, "task still running: card not steered")
    cls._scan_bg(s, {"type": "user", "message": {"content": [{"type": "text", "text":
        "<task-notification><tool-use-id>u1</tool-use-id></task-notification>"}]}})
    sessions._sweep_background()
    for _ in range(40):
        if steers:
            break
        time.sleep(0.1)
    ok(len(steers) == 1 and steers[0][0] == TID and steers[0][2].get("source") == "background-task",
       "task_notification -> sweep resumes the card with a background-done turn")
finally:
    sessions.steer = orig

print()
if _fails:
    print("=== %d FAILED ===" % len(_fails)); sys.exit(1)
print("bg-launch-guard: all pinned - PASS")
