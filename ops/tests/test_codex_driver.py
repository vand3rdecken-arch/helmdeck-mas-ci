# -*- coding: utf-8 -*-
"""The native Codex driver (ops/docs/multi-engine-build-plan.md Card 6).

UNVERIFIED AGAINST A REAL codex CLI (owner decree 2026-08-24, "test accounts
later" - no codex account exists on this box). Pins the driver against the
EXACT request/notification shapes read from Paseo's real source
(codex-app-server-agent.ts, providers/codex/tool-call-mapper.ts - see
codex_driver.py's own module docstring for the file:line citations), so
this test suite is "protocol-correct-per-specification", not "proven
against the real binary" the way test_omp_driver.py is. Card 6's own
verify step (a real dispatched turn, once an OpenAI/Codex account exists)
is what upgrades this module to the same confidence level omp_driver.py
has - and per that module's own history, live testing found bugs no amount
of spec-reading caught, so do NOT skip that step when the account exists.

Self-sandboxing: no real codex spawned - a FakeProc whose stdout is a
pre-canned list of JSON-RPC lines lets _spawn's real (blocking) initialize
handshake complete against a fake "server", then the rest of each test
drives _on_notification/_on_request directly.
"""
import os, shutil, sys, tempfile, threading, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from spine.agent import codex_driver, timeline_store

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
    """stdout is a real queue.Queue-backed iterator so the pump thread can
    block waiting for lines a test pushes AFTER spawn, not just a static
    pre-canned list - needed because _spawn's `initialize` request must be
    answered while _pump is already running."""
    def __init__(self, pid=9001):
        import queue
        self.pid = pid
        self.stdin = FakeStdin()
        self._q = queue.Queue()
        self.stdout = self
        self.stderr = []
    def push(self, obj):
        import json
        self._q.put(json.dumps(obj) + "\n")
    def close(self):
        self._q.put(None)
    def __iter__(self):
        return self
    def __next__(self):
        line = self._q.get()
        if line is None:
            raise StopIteration
        return line
    def poll(self):
        return None


codex_driver._tree_kill = lambda proc, grace=2.0: None
codex_driver._record_pid = lambda pid, spawn_time=None: None
codex_driver._forget_pid = lambda pid: None


def make_session(tid, run_dir, session_id=None):
    """Builds a REAL _CodexSession, letting the real (blocking) `initialize`
    handshake run against a FakeProc - answers it on a background thread so
    __init__ doesn't deadlock, then returns once spawn has settled."""
    fp = FakeProc()
    real_popen = codex_driver.subprocess.Popen
    codex_driver.subprocess.Popen = lambda *a, **k: fp

    def _answer_handshake():
        time.sleep(0.05)
        fp.push({"id": 1, "result": {}})   # initialize response
        if session_id:
            fp.push({"id": 2, "result": {}})   # thread/resume response
    threading.Thread(target=_answer_handshake, daemon=True).start()
    try:
        s = codex_driver._CodexSession({}, {"id": tid, "worktree": ".",
                                            "run_dir": run_dir, "session_id": session_id})
    finally:
        codex_driver.subprocess.Popen = real_popen
    time.sleep(0.1)
    s.last_used = time.time()
    s.spawn_time = time.time()
    return s, fp


TMP = tempfile.mkdtemp(prefix="hd-codex-")

# ============================================================================
print("build_argv - no cwd/session in argv (both are per-RPC-call params):")
argv = codex_driver.build_argv({})
check("argv is just [codex, app-server]", argv[-1] == "app-server" and len(argv) == 2)

# ============================================================================
print("_normalize_tool_status - the shared cross-provider vocabulary:")
check("failed synonyms", codex_driver._normalize_tool_status("error", False) == "failed")
check("canceled synonyms", codex_driver._normalize_tool_status("aborted", False) == "canceled")
check("completed synonyms", codex_driver._normalize_tool_status("success", False) == "completed")
check("unknown status -> running (matches the running-until-told-otherwise default)",
      codex_driver._normalize_tool_status("something_new", False) == "running")
check("an error field always wins, regardless of status text",
      codex_driver._normalize_tool_status("success", True) == "failed")

# ============================================================================
print("spawn - the real (blocking) initialize handshake completes against a fake server:")
rd = os.path.join(TMP, "spawn")
os.makedirs(rd, exist_ok=True)
s, fp = make_session("card-spawn", rd)
check("session is alive after a successful handshake", s.alive())
check("initialize was actually sent on the wire",
      any('"method": "initialize"' in l for l in fp.stdin.lines))
check("initialized notification followed (no response expected)",
      any('"method": "initialized"' in l for l in fp.stdin.lines))
fp.close()

# ============================================================================
print("_fold_item - agentMessage/reasoning/commandExecution (REAL Codex item shapes):")
rd = os.path.join(TMP, "fold-item")
os.makedirs(rd, exist_ok=True)
s2, fp2 = make_session("card-fold", rd)
ts, ta = "12:00:00", 1.0
# agentMessage - tool-call-mapper.ts:1789-1798 - text is on item.text directly.
s2._fold_item({"type": "agentMessage", "id": "m1", "text": "All done."}, True, ts, ta)
# reasoning - the thinking equivalent.
s2._fold_item({"type": "reasoning", "id": "r1", "text": "Let me think about this."}, True, ts, ta)
# commandExecution, RUNNING (item_started) - tool-call-mapper.ts:135-146.
s2._fold_item({"type": "commandExecution", "id": "c1", "command": "ls -la",
              "status": "in_progress"}, False, ts, ta)
steps = timeline_store.read(rd)
check("agentMessage folds as assistant text", any(
    x.get("kind") == "text" and x.get("role") == "assistant" and x.get("text") == "All done."
    for x in steps))
check("reasoning folds as thinking", any(
    x.get("kind") == "thinking" and x.get("text") == "Let me think about this." for x in steps))
tool_steps = [x for x in steps if x.get("kind") == "tool"]
check("commandExecution folds as a running tool step",
      len(tool_steps) == 1 and tool_steps[0]["status"] == "running"
      and tool_steps[0]["tool"] == "shell")

# then complete it - tool-call-mapper.ts:693-720 (aggregatedOutput/exitCode).
s2._fold_item({"type": "commandExecution", "id": "c1", "command": "ls -la",
              "status": "completed", "aggregatedOutput": "file1.txt\nfile2.txt",
              "exitCode": 0}, True, ts, ta)
tool_steps = [x for x in timeline_store.read(rd) if x.get("kind") == "tool"]
check("still ONE tool step (updated, not duplicated)", len(tool_steps) == 1)
check("completed status + real output carried",
      tool_steps[0]["status"] == "completed" and "file1.txt" in tool_steps[0]["result"])

# a FAILED command.
s2._fold_item({"type": "commandExecution", "id": "c2", "command": "false",
              "status": "in_progress"}, False, ts, ta)
s2._fold_item({"type": "commandExecution", "id": "c2", "command": "false",
              "status": "failed", "error": "exit code 1",
              "aggregatedOutput": ""}, True, ts, ta)
tool_steps2 = [x for x in timeline_store.read(rd) if x.get("kind") == "tool" and x.get("tool") == "shell"]
failed = [x for x in tool_steps2 if x.get("status") == "failed"]
check("a failed command lands status=failed with the error text",
      len(failed) == 1 and "exit code 1" in failed[0]["error"])
fp2.close()

# ============================================================================
print("_on_notification - usage (CamelCase fields, tokens only, no cost):")
rd3 = os.path.join(TMP, "usage")
os.makedirs(rd3, exist_ok=True)
s3, fp3 = make_session("card-usage", rd3)
s3._cur = {"turn_id": None, "status": None, "error": None,
          "done": threading.Event(), "last_event": time.time()}
s3._on_notification("thread/tokenUsage/updated", {"tokenUsage": {
    "last": {"inputTokens": 120, "cachedInputTokens": 30, "outputTokens": 45}}})
steps3 = timeline_store.read(rd3)
usage_steps = [x for x in steps3 if x.get("kind") == "usage"]
check("usage step folded from CamelCase fields (unlike claude's snake_case)",
      len(usage_steps) == 1 and usage_steps[0]["tokIn"] == 120
      and usage_steps[0]["tokOut"] == 45 and usage_steps[0]["cacheRead"] == 30)
fp3.close()

# ============================================================================
print("run_turn - full flow via the real RPC handshake + turn/completed:")
rd4 = os.path.join(TMP, "run-turn")
os.makedirs(rd4, exist_ok=True)
s4, fp4 = make_session("card-run", rd4)


def _drive_run_turn(s, fp, prompt, rd):
    result = {}
    def _run():
        try:
            result["v"] = s.run_turn(prompt, rd)
        except Exception as e:
            result["v"] = e
    th = threading.Thread(target=_run, daemon=True)
    th.start()
    time.sleep(0.1)
    # thread/start response (id assigned by the driver's own counter - the
    # THIRD RPC call after initialize, since no thread_id was resumed).
    fp.push({"id": 2, "result": {"thread": {"id": "thread-abc-123"}}})
    time.sleep(0.1)
    # turn/start response (just an ack - the real content arrives via
    # notifications: turn/started, item/completed, turn/completed).
    fp.push({"id": 3, "result": {}})
    time.sleep(0.05)
    fp.push({"method": "turn/started", "params": {"turn": {"id": "turn-1"}}})
    fp.push({"method": "item/completed", "params": {"item": {
        "type": "agentMessage", "id": "m1", "text": "Task finished successfully."}}})
    fp.push({"method": "turn/completed", "params": {"turn": {"status": "completed"}}})
    th.join(timeout=5.0)
    return result.get("v")


result = _drive_run_turn(s4, fp4, "do the thing", rd4)
check("run_turn returns a tuple, not an exception", isinstance(result, tuple))
if isinstance(result, tuple):
    check("thread id captured from thread/start's response", result[0] == "thread-abc-123")
    check("reply is the agentMessage text (read back from the store, "
          "turn/completed itself carries none)", result[1] == "Task finished successfully.")
    check("cost_usd is None, never a fabricated 0 (Codex has no cost field at all)",
          result[2]["cost_usd"] is None)
fp4.close()

shutil.rmtree(TMP, ignore_errors=True)

# ============================================================================
if FAILS:
    print("FAILED:", len(FAILS))
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("\ncodex-driver: all pinned - PASS")
