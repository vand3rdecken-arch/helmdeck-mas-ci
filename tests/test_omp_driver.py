# -*- coding: utf-8 -*-
"""The native OMP driver (docs/multi-engine-build-plan.md Card 8).

Pins the wire-protocol fold against REAL frame shapes captured live from
omp.exe v16.1.10 on 2026-08-24 (not invented fixtures - see omp_driver.py's
module docstring for the measurement notes), plus the argv/env assembly.

Self-sandboxing: no real omp.exe spawned - _on_event driven directly on an
_OmpSession built the same way tests/test_p1_runtime.py's make_session does
(real __init__, only _spawn stubbed).
"""
import os, shutil, sys, tempfile, threading, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from spine.agent import omp_driver, timeline_store

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
    def __init__(self, pid=8001):
        self.pid = pid
        self.stdin = FakeStdin()
        self.stdout = []
        self.stderr = []
    def poll(self):
        return None


omp_driver._tree_kill = lambda proc, grace=2.0: None
omp_driver._record_pid = lambda pid, spawn_time=None: None
omp_driver._forget_pid = lambda pid: None


def make_session(tid, run_dir):
    real_spawn = omp_driver._OmpSession._spawn
    omp_driver._OmpSession._spawn = lambda self: None
    try:
        s = omp_driver._OmpSession({}, {"id": tid, "worktree": ".", "run_dir": run_dir})
    finally:
        omp_driver._OmpSession._spawn = real_spawn
    s.proc = FakeProc()
    s._alive = True
    s.last_used = time.time()
    s.spawn_time = time.time()
    return s


TMP = tempfile.mkdtemp(prefix="hd-omp-")

# ============================================================================
print("build_argv - the assembly is byte-inspectable:")
argv = omp_driver.build_argv({"model": "haiku"}, r"C:\work", r"C:\run", brief="BRIEF TEXT")
check("mode rpc-ui", "--mode" in argv and argv[argv.index("--mode") + 1] == "rpc-ui")
check("cwd threaded through", "--cwd" in argv and argv[argv.index("--cwd") + 1] == r"C:\work")
check("session path derived from run_dir",
      "--session" in argv and argv[argv.index("--session") + 1] == os.path.join(r"C:\run", "omp_session"))
check("auto-approve always on (headless, no interactive approval)", "--auto-approve" in argv)
check("model threaded through", "--model" in argv and argv[argv.index("--model") + 1] == "haiku")
check("brief via --append-system-prompt (native, unlike ACP)",
      "--append-system-prompt" in argv and argv[argv.index("--append-system-prompt") + 1] == "BRIEF TEXT")

argv_nomodel = omp_driver.build_argv({}, r"C:\w", r"C:\r")
check("no --model flag when unset (let omp use its own default)",
      "--model" not in argv_nomodel)

# ============================================================================
print("_env - ANTHROPIC_OAUTH_TOKEN defaults from the daemon's own claude credentials:")
_real_oauth = omp_driver._oauth_token
omp_driver._oauth_token = lambda: "FAKE-TOKEN-123"
try:
    env = omp_driver._env({})
    check("token injected when not overridden", env.get("ANTHROPIC_OAUTH_TOKEN") == "FAKE-TOKEN-123")
    env2 = omp_driver._env({"env": {"ANTHROPIC_API_KEY": "sk-explicit"}})
    check("an explicit API key in settings.json wins - no token injected over it",
          "ANTHROPIC_OAUTH_TOKEN" not in env2 and env2.get("ANTHROPIC_API_KEY") == "sk-explicit")
finally:
    omp_driver._oauth_token = _real_oauth

# ============================================================================
print("_tool_label - omp's OWN lowercase tool vocabulary (not claude's):")
lbl, sub = omp_driver._tool_label("read", {"path": "probe.txt"})
check("read -> a real label + the path", lbl and sub == "probe.txt")
lbl2, sub2 = omp_driver._tool_label("bash", {"i": "list files", "command": "ls"})
check("bash prefers the agent's own intent over the raw command", sub2 == "list files")
lbl3, sub3 = omp_driver._tool_label("some_unknown_tool", {"a": 1, "b": 2})
check("unknown tool falls back to its name + arg keys", lbl3 == "some_unknown_tool" and "a" in sub3)

# ============================================================================
print("_on_event - message_end (REAL captured shape) folds text/thinking/toolCall:")
rd = os.path.join(TMP, "message-end")
os.makedirs(rd, exist_ok=True)
s = make_session("card-msg", rd)
# Captured live 2026-08-24 (omp_tool_probe.jsonl line 35) - trimmed to the
# fields the fold reads, values unchanged.
s._on_event({"type": "message_start", "message": {"role": "user", "content": [
    {"type": "text", "text": "please read probe.txt"}], "attribution": "user"}})
s._on_event({"type": "message_end", "message": {"role": "user", "content": [
    {"type": "text", "text": "please read probe.txt"}], "attribution": "user"}})
s._on_event({"type": "message_end", "message": {
    "role": "assistant",
    "content": [
        {"type": "thinking", "thinking": "I should read the file first."},
        {"type": "text", "text": "Reading probe.txt now."},
        {"type": "toolCall", "id": "toolu_017bdGjVx7irUJUG18WKnMed", "name": "read",
         "arguments": {"path": "probe.txt", "i": "Read probe.txt"}},
    ],
    "api": "anthropic-messages", "provider": "anthropic", "model": "claude-haiku-4-5",
    "usage": {"input": 10, "output": 264, "cacheRead": 40963, "cacheWrite": 519,
             "totalTokens": 41756,
             "cost": {"input": 1e-05, "output": 0.00132, "cacheRead": 0.0041,
                      "cacheWrite": 0.00065, "total": 0.006075}},
}})
steps = timeline_store.read(rd)
check("user text folded (from the ECHOED message, omp mirrors what we sent)",
      any(x.get("kind") == "text" and x.get("role") == "user"
          and x.get("text") == "please read probe.txt" for x in steps))
check("assistant thinking folded", any(x.get("kind") == "thinking" for x in steps))
check("assistant text folded", any(x.get("kind") == "text" and x.get("role") == "assistant"
                                   and x.get("text") == "Reading probe.txt now." for x in steps))
tool_steps = [x for x in steps if x.get("kind") == "tool"]
check("tool call folded as running (result comes later via tool_execution_end)",
      len(tool_steps) == 1 and tool_steps[0]["status"] == "running"
      and tool_steps[0]["tool"] == "read")
usage_steps = [x for x in steps if x.get("kind") == "usage"]
check("usage folded with REAL token counts", len(usage_steps) == 1
      and usage_steps[0]["tokIn"] == 10 and usage_steps[0]["tokOut"] == 264)
check("ctx = input + cacheRead + cacheWrite (same formula as the claude driver)",
      usage_steps[0]["ctx"] == 10 + 40963 + 519)
# real cost_usd accumulation is exercised end-to-end via run_turn below,
# where meta["cost_usd"] is the actually-observable contract.

# ============================================================================
print("_on_event - tool_execution_end updates the SAME tool step (completed/failed):")
rd = os.path.join(TMP, "tool-exec")
os.makedirs(rd, exist_ok=True)
s = make_session("card-tool", rd)
s._on_event({"type": "message_end", "message": {"role": "assistant", "content": [
    {"type": "toolCall", "id": "t-ok", "name": "read", "arguments": {"path": "a.txt"}},
    {"type": "toolCall", "id": "t-fail", "name": "bash", "arguments": {"command": "false"}},
    {"type": "toolCall", "id": "t-cancel", "name": "bash", "arguments": {"command": "sleep 30"}},
]}})
s._on_event({"type": "tool_execution_end", "toolCallId": "t-ok", "toolName": "read",
            "result": {"content": [{"type": "text", "text": "file contents here"}]},
            "isError": False})
s._on_event({"type": "tool_execution_end", "toolCallId": "t-fail", "toolName": "bash",
            "result": {"content": [{"type": "text", "text": "command failed: exit 1"}]},
            "isError": True})
# Real sentinel captured live 2026-08-24 (sent `abort` mid-Bash-sleep).
s._on_event({"type": "tool_execution_end", "toolCallId": "t-cancel", "toolName": "bash",
            "result": {"content": [{"type": "text", "text": "[Command cancelled]\n"}]},
            "isError": True})
tool_steps = [x for x in timeline_store.read(rd) if x.get("kind") == "tool"]
check("3 distinct tool steps, not merged", len(tool_steps) == 3)
check("completed: ok, result carried",
      tool_steps[0]["status"] == "completed" and tool_steps[0]["ok"] is True
      and tool_steps[0]["result"] == "file contents here")
check("failed: not ok, error carried",
      tool_steps[1]["status"] == "failed" and tool_steps[1]["ok"] is False
      and "exit 1" in tool_steps[1]["error"])
check("an abort's own tool call is CANCELED, never failed (4-state Paseo parity)",
      tool_steps[2]["status"] == "canceled" and tool_steps[2]["ok"] is True
      and tool_steps[2]["error"] is None)

# ============================================================================
print("run_turn - full flow: text reply, real cost_usd, and a cancelled turn:")


def _drive(s, prompt, rd, events):
    def _run():
        try:
            s._last_result = s.run_turn(prompt, rd)
        except Exception as e:
            s._last_result = e
    th = threading.Thread(target=_run, daemon=True)
    th.start()
    time.sleep(0.15)
    if s._cur is not None:
        for ev in events:
            s._on_event(ev)
    th.join(timeout=5.0)
    return getattr(s, "_last_result", None)


rd = os.path.join(TMP, "run-turn-ok")
os.makedirs(rd, exist_ok=True)
s = make_session("card-run", rd)
final_msg = {"role": "assistant", "content": [{"type": "text", "text": "All done."}],
            "model": "claude-haiku-4-5",
            "usage": {"input": 5, "output": 3, "cacheRead": 0, "cacheWrite": 0,
                     "cost": {"total": 0.00042}}}
# message_end fires before turn_end with the SAME message (measured live) -
# _fold_usage (and its cost accumulation onto cur) only runs off message_end.
# agent_end (not turn_end) is the completion signal - see below for why.
result = _drive(s, "do the thing", rd,
                [{"type": "message_end", "message": final_msg},
                 {"type": "turn_end", "message": final_msg},
                 {"type": "agent_end", "messages": [final_msg]}])
check("run_turn returns the reply text", isinstance(result, tuple) and result[1] == "All done.")
check("meta carries models", isinstance(result, tuple) and result[2]["models"] == ["claude-haiku-4-5"])
check("REAL cost_usd accumulated from message.usage.cost.total - the whole point of going native",
      isinstance(result, tuple) and result[2]["cost_usd"] == 0.00042)
check("prompt written to stdin verbatim as a typed prompt request",
      any('"type": "prompt"' in l and "do the thing" in l for l in s.proc.stdin.lines))

rd2 = os.path.join(TMP, "run-turn-cancel")
os.makedirs(rd2, exist_ok=True)
s2 = make_session("card-cancel", rd2)
aborted_msg = {"role": "assistant", "content": [], "stopReason": "aborted"}
result2 = _drive(s2, "do something long", rd2,
                 [{"type": "turn_end", "message": aborted_msg},
                  {"type": "agent_end", "messages": [aborted_msg]}])
check("stopReason:aborted -> the structured cancel signal (matches claude/ACP shape)",
      isinstance(result2, tuple) and result2[2].get("canceled") is True)

# ============================================================================
print("run_turn - MULTI-TURN tool loop: the FIRST turn_end is narration, not the answer:")
# Measured live 2026-08-24 (docs/multi-engine-build-plan.md Card 8): a single
# prompt needing tool calls produces MULTIPLE turn_start/turn_end pairs. The
# real bug this pins: an earlier version of this driver latched onto the
# FIRST turn_end and returned "I'll read probe.txt and then create result.txt"
# as the reply instead of the actual final answer.
rd3 = os.path.join(TMP, "run-turn-multiturn")
os.makedirs(rd3, exist_ok=True)
s3 = make_session("card-multi", rd3)
narration = {"role": "assistant", "content": [
    {"type": "text", "text": "I'll read probe.txt and then create result.txt for you."}]}
real_answer = {"role": "assistant", "content": [
    {"type": "text", "text": "Done! probe.txt contained test data; result.txt was created."}],
    "model": "claude-haiku-4-5", "usage": {"input": 5, "output": 3}}
result3 = _drive(s3, "read then write", rd3,
                 [{"type": "turn_end", "message": narration},   # 1st internal turn - a decoy
                  {"type": "turn_end", "message": real_answer}, # 2nd internal turn - the real one
                  {"type": "agent_end", "messages": [narration, real_answer]}])
check("the reply is the FINAL answer, not the first turn_end's narration",
      isinstance(result3, tuple) and result3[1] == real_answer["content"][0]["text"])
check("specifically NOT the narration text",
      isinstance(result3, tuple) and "I'll read probe.txt" not in result3[1])

shutil.rmtree(TMP, ignore_errors=True)

# ============================================================================
if FAILS:
    print("FAILED:", len(FAILS))
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("\nomp-driver: all pinned - PASS")
