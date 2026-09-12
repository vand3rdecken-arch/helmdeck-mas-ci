# -*- coding: utf-8 -*-
"""The native Pi driver - the deferred half of Card 8
(ops/docs/multi-engine-build-plan.md).

UNVERIFIED AGAINST A REAL pi CLI (owner decree 2026-08-24, "test accounts
later" - no pi binary on this box). See pi_driver.py's own module docstring
for exactly which parts are borrowed from omp_driver.py's PROVEN structure
(the agent_end-is-terminal rule, the abort shape) vs. genuinely unverified
even by relation (the fold logic itself, the --mode rpc-ui choice over the
spec default).

Self-sandboxing: no real pi spawned - a FakeProc whose stdout is a
controllable queue, same harness shape as test_omp_driver.py.
"""
import os, shutil, sys, tempfile, threading, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from spine.agent import pi_driver, timeline_store

FAILS = []


def check(name, cond):
    print(("  ok  " if cond else "  FAIL") + " " + name)
    if not cond:
        FAILS.append(name)


class FakeStdin:
    def __init__(self):
        self.lines = []
    def write(self, s):
        self.lines.append(s)
    def flush(self):
        pass


class FakeProc:
    def __init__(self, pid=9201):
        self.pid = pid
        self.stdin = FakeStdin()
        self.stdout = []
        self.stderr = []
    def poll(self):
        return None


pi_driver._tree_kill = lambda proc, grace=2.0: None
pi_driver._record_pid = lambda pid, spawn_time=None: None
pi_driver._forget_pid = lambda pid: None


def make_session(tid, run_dir):
    real_spawn = pi_driver._PiSession._spawn
    pi_driver._PiSession._spawn = lambda self: None
    try:
        s = pi_driver._PiSession({}, {"id": tid, "worktree": ".", "run_dir": run_dir})
    finally:
        pi_driver._PiSession._spawn = real_spawn
    s.proc = FakeProc()
    s._alive = True
    s.last_used = time.time()
    s.spawn_time = time.time()
    return s


TMP = tempfile.mkdtemp(prefix="hd-pi-")
# actions/timeline/runs are db rows (state-into-db phase F): sandbox the store
from spine.storage import db as _sdb
_sdb.DBPATH = os.path.join(TMP, "test.db")
_sdb._local.c = None
_sdb.init()

# ============================================================================
print("build_argv - session path derivation, mode choice, pi-specific flags:")
argv = pi_driver.build_argv({"model": "opus", "thinking": "high",
                             "mcp_config": r"C:\mcp.json", "extensions": ["ext1.js", "ext2.js"]},
                            r"C:\work", r"C:\run", brief="BRIEF")
check("--mode rpc-ui (deliberate choice over the spec default, see docstring)",
      "--mode" in argv and argv[argv.index("--mode") + 1] == "rpc-ui")
check("session path derived from run_dir, own filename (not omp_session)",
      "--session" in argv and argv[argv.index("--session") + 1] == os.path.join(r"C:\run", "pi_session"))
check("cwd threaded through", "--cwd" in argv and argv[argv.index("--cwd") + 1] == r"C:\work")
check("model threaded through", "--model" in argv and argv[argv.index("--model") + 1] == "opus")
check("thinking level (pi-specific, not on omp)",
      "--thinking" in argv and argv[argv.index("--thinking") + 1] == "high")
check("mcp-config (pi-specific)",
      "--mcp-config" in argv and argv[argv.index("--mcp-config") + 1] == r"C:\mcp.json")
check("extensions repeated per entry (pi-specific)",
      argv.count("--extension") == 2 and "ext1.js" in argv and "ext2.js" in argv)
check("brief via --append-system-prompt", "--append-system-prompt" in argv
      and argv[argv.index("--append-system-prompt") + 1] == "BRIEF")

argv_min = pi_driver.build_argv({}, r"C:\w", r"C:\r")
check("no optional flags when unset", "--thinking" not in argv_min
      and "--mcp-config" not in argv_min and "--extension" not in argv_min)

# ============================================================================
print("_on_event - agent_end (not the first turn_end) is the completion signal:")
rd = os.path.join(TMP, "multiturn")
os.makedirs(rd, exist_ok=True)
s = make_session("card-multi", rd)
s._cur = {"result": None, "cost_usd": 0.0, "done": threading.Event(),
         "last_event": time.time()}
narration = {"role": "assistant", "content": [{"type": "text", "text": "I'll check that now."}]}
real_answer = {"role": "assistant", "content": [{"type": "text", "text": "Confirmed: it works."}],
              "model": "pi-default"}
s._on_event({"type": "turn_end", "message": narration})
check("first turn_end recorded but does NOT release done (applies omp's lesson proactively)",
      not s._cur["done"].is_set() and s._cur["result"] == narration)
s._on_event({"type": "turn_end", "message": real_answer})
s._on_event({"type": "agent_end", "messages": [narration, real_answer]})
check("agent_end releases done", s._cur["done"].is_set())
check("agent_end's last assistant message wins, not the first turn_end's narration",
      s._cur["result"] == real_answer)

# ============================================================================
print("_fold_message / tool_execution_end - same shapes as omp (measured request-side identical):")
rd2 = os.path.join(TMP, "fold")
os.makedirs(rd2, exist_ok=True)
s2 = make_session("card-fold", rd2)
ts, ta = "12:00:00", 1.0
s2._fold_message({"role": "assistant", "content": [
    {"type": "text", "text": "Working on it."},
    {"type": "thinking", "thinking": "Let me plan first."},
    {"type": "toolCall", "id": "tc1", "name": "read", "arguments": {"path": "a.txt"}},
]}, "assistant", ts, ta)
steps = timeline_store.read(rd2)
check("text folded", any(x.get("kind") == "text" and x.get("text") == "Working on it." for x in steps))
check("thinking folded", any(x.get("kind") == "thinking" for x in steps))
tool_steps = [x for x in steps if x.get("kind") == "tool"]
check("tool call folded as running", len(tool_steps) == 1 and tool_steps[0]["status"] == "running")

s2._on_event({"type": "tool_execution_end", "toolCallId": "tc1",
             "result": {"content": [{"type": "text", "text": "file contents"}]},
             "isError": False})
tool_steps2 = [x for x in timeline_store.read(rd2) if x.get("kind") == "tool"]
check("completed via tool_execution_end (same event name/shape as omp)",
      len(tool_steps2) == 1 and tool_steps2[0]["status"] == "completed"
      and tool_steps2[0]["result"] == "file contents")

# a cancelled tool - same "[Command cancelled]"-contains-"cancel" heuristic as omp.
s2._fold_message({"role": "assistant", "content": [
    {"type": "toolCall", "id": "tc2", "name": "bash", "arguments": {"command": "sleep 30"}}]},
    "assistant", ts, ta)
s2._on_event({"type": "tool_execution_end", "toolCallId": "tc2",
             "result": {"content": [{"type": "text", "text": "[Command cancelled]\n"}]},
             "isError": True})
tool2 = [x for x in timeline_store.read(rd2) if x.get("tool") == "bash"]
check("a cancelled tool call is CANCELED, never failed (same rule as omp)",
      tool2 and tool2[0]["status"] == "canceled" and tool2[0]["ok"] is True)

# ============================================================================
print("_fold_stats - get_session_stats response -> real cost_usd:")
rd3 = os.path.join(TMP, "stats")
os.makedirs(rd3, exist_ok=True)
s3 = make_session("card-stats", rd3)
s3._cur = {"result": None, "cost_usd": 0.0, "done": threading.Event(), "last_event": time.time()}
s3._on_event({"type": "response", "command": "get_session_stats", "success": True,
             "data": {"cost": 0.0789, "sessionId": "sess-x"}})
check("cost accumulated from get_session_stats", s3._cur["cost_usd"] == 0.0789)

# ============================================================================
print("cancel - {type:abort} shape (source-confirmed on BOTH pi and omp sides):")
rd4 = os.path.join(TMP, "cancel")
os.makedirs(rd4, exist_ok=True)
s4 = make_session("card-cancel", rd4)
s4._cur = {"result": None, "cost_usd": 0.0, "done": threading.Event(), "last_event": time.time()}
s4.cancel()
check("abort request written to stdin", any('"type": "abort"' in l for l in s4.proc.stdin.lines))

# ============================================================================
print("run_turn - full flow ending on agent_end, and a real cancel:")


def _drive(s, prompt, rd, events):
    result = {}
    def _run():
        try:
            result["v"] = s.run_turn(prompt, rd)
        except Exception as e:
            result["v"] = e
    th = threading.Thread(target=_run, daemon=True)
    th.start()
    time.sleep(0.15)
    if s._cur is not None:
        for ev in events:
            s._on_event(ev)
    th.join(timeout=5.0)
    return result.get("v")


rd5 = os.path.join(TMP, "run-ok")
os.makedirs(rd5, exist_ok=True)
s5 = make_session("card-run", rd5)
final = {"role": "assistant", "content": [{"type": "text", "text": "All done."}],
        "model": "pi-default"}
result = _drive(s5, "do the thing", rd5,
                [{"type": "turn_end", "message": final},
                 {"type": "agent_end", "messages": [final]}])
check("run_turn returns the reply", isinstance(result, tuple) and result[1] == "All done.")
check("prompt written verbatim", any('"type": "prompt"' in l and "do the thing" in l
                                     for l in s5.proc.stdin.lines))

rd6 = os.path.join(TMP, "run-cancel")
os.makedirs(rd6, exist_ok=True)
s6 = make_session("card-run-cancel", rd6)
aborted = {"role": "assistant", "content": [], "stopReason": "aborted"}
result2 = _drive(s6, "long task", rd6,
                 [{"type": "turn_end", "message": aborted},
                  {"type": "agent_end", "messages": [aborted]}])
check("stopReason:aborted -> the structured cancel signal",
      isinstance(result2, tuple) and result2[2].get("canceled") is True)

shutil.rmtree(TMP, ignore_errors=True)

# ============================================================================
if FAILS:
    print("FAILED:", len(FAILS))
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("\npi-driver: all pinned - PASS")
