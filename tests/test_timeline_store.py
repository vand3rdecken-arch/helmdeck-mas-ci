# -*- coding: utf-8 -*-
"""Card 2 (docs/multi-engine-build-plan.md): the event-time timeline store.

Pins two things:
1. timeline_store.append/read: partial-patch folding, first-seen ordering,
   the internal _id never leaking into a returned step.
2. _ClaudeSession._fold_timeline: the live-stream fold produces the SAME
   TStep shapes claude_sessions.read_transcript derives from a re-parsed
   .jsonl, for every kind the build plan's Card 2 verify line names - text,
   thinking, a tool call through all 4 states, todos, usage, a <helmdeck-ask>
   question (stripped, matching _clean_text), and a cancel.

Self-sandboxing: no real CLI, no real daemon - _on_event driven directly on a
_ClaudeSession built the same way daemon/test_p1_runtime.py's make_session
does (real __init__, only _spawn stubbed).
"""
import os, shutil, sys, tempfile, threading, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from daemon.spine.agent import drivers, timeline_store
from daemon.spine.agent.drivers import _ClaudeSession

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
    def __init__(self, pid=9001):
        self.pid = pid
        self.stdin = FakeStdin()
        self.stdout = []
        self.stderr = []
    def poll(self):
        return None


drivers._tree_kill = lambda proc, grace=2.0: None
drivers._record_pid = lambda pid, spawn_time=None: None
drivers._forget_pid = lambda pid: None


def make_session(tid, run_dir):
    real_spawn = _ClaudeSession._spawn
    _ClaudeSession._spawn = lambda self: None
    try:
        s = _ClaudeSession({}, {"id": tid, "worktree": ".", "run_dir": run_dir,
                                "session_id": "sess-live"})
    finally:
        _ClaudeSession._spawn = real_spawn
    s.proc = FakeProc()
    s._alive = True
    s.last_used = time.time()
    s.spawn_time = time.time()
    return s


TMP = tempfile.mkdtemp(prefix="hd-timeline-")

# ============================================================================
print("timeline_store.append/read - low-level fold semantics:")
rd = os.path.join(TMP, "low-level")
os.makedirs(rd, exist_ok=True)
timeline_store.append(rd, "tool:x1", {"kind": "tool", "tool": "Bash",
                                      "status": "running", "text": "ls"})
timeline_store.append(rd, "s:standalone", {"kind": "text", "text": "hi"})
timeline_store.append(rd, "tool:x1", {"status": "completed", "result": "out"})
steps = timeline_store.read(rd)
check("2 distinct steps (update folded, not a 3rd row)", len(steps) == 2)
check("first-seen order preserved (tool first, then text)",
      steps[0]["kind"] == "tool" and steps[1]["kind"] == "text")
check("patch merged onto the original record (tool field survives)",
      steps[0].get("tool") == "Bash")
check("patch's new field applied (status updated)",
      steps[0].get("status") == "completed" and steps[0].get("result") == "out")
check("internal _id never leaks into a returned step",
      all("_id" not in s for s in steps))
check("empty/missing store reads as []",
      timeline_store.read(os.path.join(TMP, "nonexistent")) == [])

# ============================================================================
print("_fold_timeline - text/thinking:")
rd = os.path.join(TMP, "text-thinking")
os.makedirs(rd, exist_ok=True)
s = make_session("card-tt", rd)
s._on_event({"type": "assistant", "message": {"role": "assistant", "content": [
    {"type": "text", "text": "Hello owner"},
    {"type": "thinking", "thinking": "let me consider this"}]}})
steps = timeline_store.read(rd)
check("one text step", any(x.get("kind") == "text" and x.get("text") == "Hello owner"
                           for x in steps))
check("one thinking step", any(x.get("kind") == "thinking"
                               and x.get("text") == "let me consider this" for x in steps))
check("text step carries role=assistant",
      next(x for x in steps if x["kind"] == "text")["role"] == "assistant")
check("every step is stamped ts/ta at fold time (app's tsLabel/sort key)",
      all(x.get("ts") and isinstance(x.get("ta"), float) for x in steps))

# ============================================================================
print("_fold_timeline - <helmdeck-ask> question stripped from a text step:")
rd = os.path.join(TMP, "ask-strip")
os.makedirs(rd, exist_ok=True)
s = make_session("card-ask", rd)
ask_block = ("Before I continue, I need a decision.\n\n<helmdeck-ask>\n"
            '{"questions": [{"question": "A or B?", "header": "Choice",'
            ' "options": [{"label": "A"}, {"label": "B"}]}]}\n</helmdeck-ask>')
s._on_event({"type": "assistant", "message": {"role": "assistant",
            "content": [{"type": "text", "text": ask_block}]}})
steps = timeline_store.read(rd)
text_steps = [x for x in steps if x.get("kind") == "text"]
check("question text step exists", len(text_steps) == 1)
check("raw <helmdeck-ask> protocol JSON never reaches the feed",
      len(text_steps) == 1 and "<helmdeck-ask>" not in text_steps[0]["text"])
check("the human-readable lead-in survives the strip",
      len(text_steps) == 1 and "decision" in text_steps[0]["text"])

# ============================================================================
print("_fold_timeline - tool call through all 4 states:")
rd = os.path.join(TMP, "tool-states")
os.makedirs(rd, exist_ok=True)
s = make_session("card-tool", rd)


def tool_use(uid, name="Bash", inp=None):
    s._on_event({"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": uid, "name": name, "input": inp or {"command": "ls"}}]}})


def tool_result(uid, text="", is_error=False):
    s._on_event({"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": uid, "content": text,
         "is_error": is_error}]}})


tool_use("t-run")     # left running, no result
tool_use("t-ok");     tool_result("t-ok", "done")
tool_use("t-fail");   tool_result("t-fail", "boom", is_error=True)
tool_use("t-cancel"); tool_result("t-cancel", "[Request interrupted by user for tool use]")

# 4 near-identical calls (same "command":"ls" summary) aren't addressable by
# content - read back in insertion order, which is what the fold guarantees.
tool_steps = [x for x in timeline_store.read(rd) if x.get("kind") == "tool"]
check("4 distinct tool steps (not merged into one)", len(tool_steps) == 4)
check("1: running, no result yet",
      len(tool_steps) > 0 and tool_steps[0]["status"] == "running"
      and tool_steps[0]["running"] is True and tool_steps[0]["error"] is None)
check("2: completed, ok, result carried",
      len(tool_steps) > 1 and tool_steps[1]["status"] == "completed"
      and tool_steps[1]["ok"] is True and tool_steps[1]["result"] == "done")
check("3: failed, error carries the tool's error text",
      len(tool_steps) > 2 and tool_steps[2]["status"] == "failed"
      and tool_steps[2]["ok"] is False and tool_steps[2]["error"] == "boom")
check("4: an interrupt sentinel is CANCELED, never failed (Paseo 4-state parity)",
      len(tool_steps) > 3 and tool_steps[3]["status"] == "canceled"
      and tool_steps[3]["error"] is None)
check("every tool step carries a human label (from _tool_label)",
      all(x.get("label") for x in tool_steps))

# ============================================================================
print("_fold_timeline - TodoWrite -> todos, ExitPlanMode -> plan:")
rd = os.path.join(TMP, "todos-plan")
os.makedirs(rd, exist_ok=True)
s = make_session("card-todos", rd)
s._on_event({"type": "assistant", "message": {"role": "assistant", "content": [
    {"type": "tool_use", "id": "td1", "name": "TodoWrite", "input": {"todos": [
        {"content": "write the store", "status": "completed"},
        {"content": "wire the fold", "status": "in_progress"}]}}]}})
s._on_event({"type": "assistant", "message": {"role": "assistant", "content": [
    {"type": "tool_use", "id": "pl1", "name": "ExitPlanMode",
     "input": {"plan": "1. build 2. verify 3. ship"}}]}})
steps = timeline_store.read(rd)
todos = [x for x in steps if x.get("kind") == "todos"]
plans = [x for x in steps if x.get("kind") == "plan"]
check("one todos step, 2 items", len(todos) == 1 and len(todos[0]["todos"]) == 2)
check("todo item shape matches TStep (content+status)",
      len(todos) == 1 and todos[0]["todos"][0]["content"] == "write the store")
check("one plan step, text carried", len(plans) == 1
      and "1. build" in plans[0]["text"])
check("TodoWrite/ExitPlanMode never ALSO emit a generic tool step",
      not any(x.get("kind") == "tool" for x in steps))

# ============================================================================
print("_fold_timeline - per-turn usage:")
rd = os.path.join(TMP, "usage")
os.makedirs(rd, exist_ok=True)
s = make_session("card-usage", rd)
s._on_event({"type": "assistant", "message": {"role": "assistant", "content": [
    {"type": "text", "text": "ok"}],
    "usage": {"input_tokens": 1200, "output_tokens": 340,
             "cache_read_input_tokens": 500, "cache_creation_input_tokens": 0}}})
steps = timeline_store.read(rd)
usage = [x for x in steps if x.get("kind") == "usage"]
check("one usage step", len(usage) == 1)
check("token fields match message.usage exactly",
      len(usage) == 1 and usage[0]["tokIn"] == 1200 and usage[0]["tokOut"] == 340
      and usage[0]["cacheRead"] == 500)
check("ctx = input + cache_read + cache_creation (read_transcript's own formula)",
      len(usage) == 1 and usage[0]["ctx"] == 1200 + 500 + 0)

# ============================================================================
print("_fold_timeline - a zero-usage assistant message emits NO usage step:")
rd = os.path.join(TMP, "usage-zero")
os.makedirs(rd, exist_ok=True)
s = make_session("card-usage0", rd)
s._on_event({"type": "assistant", "message": {"role": "assistant",
            "content": [{"type": "text", "text": "x"}],
            "usage": {"input_tokens": 0, "output_tokens": 0}}})
steps = timeline_store.read(rd)
check("no usage step when everything is 0 (matches read_transcript's `if ctx or out`)",
      not any(x.get("kind") == "usage" for x in steps))

# ============================================================================
print("run_turn - the submitted prompt folds as text, a harness-tagged one as a system note:")
from daemon.spine.ops import ask as _ask


def _drive_turn(s, prompt, rd):
    def _run():
        try:
            s.run_turn(prompt, rd)
        except Exception:
            pass
    th = threading.Thread(target=_run, daemon=True)
    th.start()
    time.sleep(0.15)               # let run_turn write to stdin and fold the prompt
    if s._cur is not None:
        s._on_event({"type": "result", "subtype": "success", "result": "ok"})
    th.join(timeout=5.0)


rd = os.path.join(TMP, "prompt-fold")
os.makedirs(rd, exist_ok=True)
s = make_session("card-prompt", rd)
_drive_turn(s, "please build the feature", rd)
steps = timeline_store.read(rd)
check("a plain human prompt folds as role=user text",
      any(x.get("kind") == "text" and x.get("role") == "user"
          and x.get("text") == "please build the feature" for x in steps))

rd2 = os.path.join(TMP, "prompt-fold-harness")
os.makedirs(rd2, exist_ok=True)
s2 = make_session("card-prompt-h", rd2)
_drive_turn(s2, _ask.harness_msg("ask-repair", "STOP - restate as a question"), rd2)
steps2 = timeline_store.read(rd2)
check("a harness-tagged prompt is re-attributed to a system note, not raw protocol text",
      any(x.get("kind") == "system" and "Rückfrage" in (x.get("text") or "")
          for x in steps2)
      and not any(x.get("kind") == "text" and "[[helmdeck:" in (x.get("text") or "")
                 for x in steps2))

# ============================================================================
print("cancel -> {kind:turn, event:canceled} folded (Card 2's structured-signal path):")
rd = os.path.join(TMP, "cancel")
os.makedirs(rd, exist_ok=True)
s = make_session("card-cancel", rd)


def _run():
    try:
        s.run_turn("do something", rd)
    except Exception:
        pass


t = threading.Thread(target=_run, daemon=True)
t.start()
time.sleep(0.2)                    # let run_turn reach its wait loop, cur is set
drivers._cancelled.add(s.tid)
if s._cur is not None:
    s._cur["done"].set()
t.join(timeout=5.0)
steps = timeline_store.read(rd)
turn_steps = [x for x in steps if x.get("kind") == "turn"]
check("a turn-canceled step landed", any(x.get("event") == "canceled" for x in turn_steps))

shutil.rmtree(TMP, ignore_errors=True)

# ============================================================================
if FAILS:
    print("FAILED:", len(FAILS))
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("\ntimeline-store: all pinned - PASS")
