# -*- coding: utf-8 -*-
"""The native OpenCode driver, dedicated-server mode
(ops/docs/multi-engine-build-plan.md Card 7).

UNVERIFIED AGAINST A REAL opencode CLI (owner decree 2026-08-24, "test
accounts later" - no opencode binary is installed on this box). See
opencode_driver.py's own module docstring for exactly which parts are
grounded in Paseo's real source (spawn args, ready-signal, dedup, cost
formula, cancel sequence) vs. inferred (the exact REST paths, since
@opencode-ai/sdk is a third-party package not vendored in this checkout).

Self-sandboxing: no real opencode spawned or HTTP call made - _spawn is
stubbed the same way the other native drivers' tests stub it, and
self.client is a FakeClient recording calls instead of a real
_OpenCodeClient making them.
"""
import io, os, shutil, sys, tempfile, threading, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from spine.agent import opencode_driver, timeline_store

FAILS = []


def check(name, cond):
    print(("  ok  " if cond else "  FAIL") + " " + name)
    if not cond:
        FAILS.append(name)


opencode_driver._tree_kill = lambda proc, grace=2.0: None
opencode_driver._record_pid = lambda pid, spawn_time=None: None
opencode_driver._forget_pid = lambda pid: None


class FakeClient:
    """Records every call instead of making a real HTTP request. Tests push
    SSE-shaped events directly at the session's _on_event, simulating what
    a real event stream would deliver."""
    def __init__(self):
        self.calls = []
        self.session_id = "sess-fake-1"
    def create_session(self, directory, timeout=10.0):
        self.calls.append(("create_session", directory))
        return self.session_id
    def prompt_async(self, session_id, directory, parts, model=None, system=None):
        self.calls.append(("prompt_async", session_id, directory, parts, model, system))
    def abort(self, session_id, directory, timeout=5.0):
        self.calls.append(("abort", session_id, directory))
    def permission_reply(self, request_id, directory, reply="once"):
        self.calls.append(("permission_reply", request_id, directory, reply))


class FakeProc:
    def __init__(self, pid=9101):
        self.pid = pid
    def poll(self):
        return None


def make_session(tid, run_dir):
    real_spawn = opencode_driver._OpenCodeSession._spawn
    opencode_driver._OpenCodeSession._spawn = lambda self: None
    try:
        s = opencode_driver._OpenCodeSession({}, {"id": tid, "worktree": ".", "run_dir": run_dir})
    finally:
        opencode_driver._OpenCodeSession._spawn = real_spawn
    s.client = FakeClient()
    s.session_id = s.client.session_id
    s.proc = FakeProc()
    s._alive = True
    s.last_used = time.time()
    s.spawn_time = time.time()
    return s


TMP = tempfile.mkdtemp(prefix="hd-opencode-")
# actions/timeline/runs are db rows (state-into-db phase F): sandbox the store
from spine.storage import db as _sdb
_sdb.DBPATH = os.path.join(TMP, "test.db")
_sdb._local.c = None
_sdb.init()

# ============================================================================
print("_normalize_tool_status - the shared cross-provider vocabulary:")
check("failed synonyms", opencode_driver._normalize_tool_status("error", None, None) == "failed")
check("an error field wins regardless of status text",
      opencode_driver._normalize_tool_status("success", "boom", None) == "failed")
check("canceled synonyms", opencode_driver._normalize_tool_status("interrupted", None, None) == "canceled")
check("completed synonyms", opencode_driver._normalize_tool_status("done", None, None) == "completed")
check("no status but real output present -> completed (matches read_transcript's own rule)",
      opencode_driver._normalize_tool_status(None, None, "some output") == "completed")
check("no status, no output -> running (default)",
      opencode_driver._normalize_tool_status(None, None, None) == "running")

# ============================================================================
print("_free_port - allocates a real, usable ephemeral port:")
p = opencode_driver._free_port()
check("port is in the valid ephemeral range", 1024 < p < 65536)
p2 = opencode_driver._free_port()
check("two calls don't necessarily collide (best-effort, not guaranteed)", isinstance(p2, int))

# ============================================================================
print("_sse_lines - minimal SSE frame parser:")


def _fake_stream(chunks):
    for c in chunks:
        yield c.encode("utf-8")


events = list(opencode_driver._sse_lines(_fake_stream([
    'data: {"type": "session.idle", "properties": {}}\n',
    "\n",
    'data: {"type": "message.part.updated",\n',
    'data: "properties": {"part": {"type": "text"}}}\n',
    "\n",
])))
check("one-line data frame parsed", len(events) >= 1 and events[0]["type"] == "session.idle")
check("multi-line data frame (split across SSE lines) joined and parsed",
      len(events) == 2 and events[1]["type"] == "message.part.updated")

# ============================================================================
print("_fold_part - text/reasoning/tool/step-finish (event shapes per opencode-agent.ts):")
rd = os.path.join(TMP, "fold-part")
os.makedirs(rd, exist_ok=True)
s = make_session("card-fold", rd)
s._cur = {"status": None, "error": None, "cost_usd": 0.0, "running_tools": set(),
         "done": threading.Event(), "last_event": time.time()}
s._fold_part({"part": {"type": "text", "role": "assistant", "id": "t1",
             "text": "Working on it."}}, is_delta=False)
s._fold_part({"part": {"type": "reasoning", "id": "r1",
             "text": "I should check the file first."}}, is_delta=False)
s._fold_part({"part": {"type": "tool", "id": "tc1", "tool": "bash",
             "state": {"status": "running", "input": "ls -la"}}}, is_delta=False)
steps = timeline_store.read(rd)
check("assistant text folded", any(x.get("kind") == "text" and x.get("role") == "assistant"
                                   and x.get("text") == "Working on it." for x in steps))
check("reasoning folded as thinking", any(x.get("kind") == "thinking" for x in steps))
tool_steps = [x for x in steps if x.get("kind") == "tool"]
check("tool call folded as running, tracked in cur for cancel-time synthesis",
      len(tool_steps) == 1 and tool_steps[0]["status"] == "running"
      and "tc1" in s._cur["running_tools"])

# complete the tool.
s._fold_part({"part": {"type": "tool", "id": "tc1", "tool": "bash",
             "state": {"status": "completed", "output": "file1.txt\nfile2.txt"}}},
            is_delta=False)
tool_steps2 = [x for x in timeline_store.read(rd) if x.get("kind") == "tool"]
check("still one tool step, now completed with real output",
      len(tool_steps2) == 1 and tool_steps2[0]["status"] == "completed"
      and "file1.txt" in tool_steps2[0]["result"])
check("removed from the running-tools cancel-tracking set once settled",
      "tc1" not in s._cur["running_tools"])

# cost / step-finish.
s._fold_part({"part": {"type": "step-finish",
             "tokens": {"input": 100, "output": 20, "cache": {"read": 5, "write": 2}},
             "cost": 0.0042}}, is_delta=False)
usage_steps = [x for x in timeline_store.read(rd) if x.get("kind") == "usage"]
check("usage step folded with real token counts",
      len(usage_steps) == 1 and usage_steps[0]["tokIn"] == 100 and usage_steps[0]["tokOut"] == 20)
check("REAL cost accumulated onto cur - the whole point of going native",
      s._cur["cost_usd"] == 0.0042)

# ============================================================================
print("_fold_delta / _fold_part dedup - a settled part matching a streamed delta is dropped:")
rd2 = os.path.join(TMP, "dedup")
os.makedirs(rd2, exist_ok=True)
s2 = make_session("card-dedup", rd2)
s2._cur = {"status": None, "error": None, "cost_usd": 0.0, "running_tools": set(),
          "done": threading.Event(), "last_event": time.time()}
s2._fold_delta({"partID": "p1", "field": "text"})
check("delta registers the dedup key, folds nothing itself",
      "text:p1" in s2._streamed_keys and not timeline_store.read(rd2))
s2._fold_part({"part": {"type": "text", "id": "p1", "text": "final text"}}, is_delta=False)
check("the matching settled part is DROPPED (already streamed), not double-folded",
      not timeline_store.read(rd2) and "text:p1" not in s2._streamed_keys)
# a DIFFERENT part id is NOT deduped.
s2._fold_part({"part": {"type": "text", "id": "p2", "text": "a fresh part"}}, is_delta=False)
check("an unrelated part id folds normally", any(x.get("text") == "a fresh part"
                                                 for x in timeline_store.read(rd2)))

# ============================================================================
print("run_turn - full flow: system prompt separate from parts, session.idle terminal:")
rd3 = os.path.join(TMP, "run-turn")
os.makedirs(rd3, exist_ok=True)
s3 = make_session("card-run", rd3)


def _drive(s, prompt, rd, events_to_fire):
    result = {}
    def _run():
        try:
            result["v"] = s.run_turn(prompt, rd)
        except Exception as e:
            result["v"] = e
    th = threading.Thread(target=_run, daemon=True)
    th.start()
    time.sleep(0.1)
    for ev in events_to_fire:
        s._on_event(ev)
    th.join(timeout=5.0)
    return result.get("v")


result = _drive(s3, "please build the feature", rd3, [
    {"type": "message.part.updated", "properties": {"part": {
        "type": "text", "role": "assistant", "id": "final", "text": "Built it."}}},
    {"type": "session.idle", "properties": {}},
])
check("run_turn returns a tuple", isinstance(result, tuple))
if isinstance(result, tuple):
    check("reply is the assistant text folded during the turn", result[1] == "Built it.")
last_prompt_call = [c for c in s3.client.calls if c[0] == "prompt_async"][-1]
check("the brief goes through `system`, NOT concatenated into the visible parts",
      last_prompt_call[5] == s3.brief
      and last_prompt_call[3] == [{"type": "text", "text": "please build the feature"}])

# ============================================================================
print("cancel - local abort call + synthesized canceled tool steps:")
rd4 = os.path.join(TMP, "cancel")
os.makedirs(rd4, exist_ok=True)
s4 = make_session("card-cancel", rd4)
s4._cur = {"status": None, "error": None, "cost_usd": 0.0, "running_tools": {"tc-running"},
          "done": threading.Event(), "last_event": time.time()}
timeline_store.append(rd4, "tool:tc-running", {"kind": "tool", "tool": "bash",
                      "status": "running", "running": True})
s4.cancel()
check("abort call reached the client", any(c[0] == "abort" for c in s4.client.calls))
tool_after = [x for x in timeline_store.read(rd4) if x.get("tool") == "bash"]
check("the still-running tool is synthesized canceled, not left spinning forever",
      tool_after and tool_after[0]["status"] == "canceled")
check("cur released", s4._cur["done"].is_set())

shutil.rmtree(TMP, ignore_errors=True)

# ============================================================================
if FAILS:
    print("FAILED:", len(FAILS))
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("\nopencode-driver: all pinned - PASS")
