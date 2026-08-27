# -*- coding: utf-8 -*-
"""Driver layer meta extraction - every driver must return
(session_id, reply, meta) with meta carrying {usage, cost_usd, models},
because the measured-economics law hangs card costs off exactly these fields.

The claude driver holds ONE long-lived `claude --input-format stream-json`
process per card (_ClaudeSession): a turn is a user message pushed onto its
stdin, a pump thread drains stdout events, and the terminal `result` event
carries the economics. The fake below stands in for that process - blocking
line queues for stdout/stderr and a script that answers stdin messages -
fed with the fixture event stream. The http driver runs through a fake
urlopen; the cmd driver through a fake subprocess.run. No CLI, no network,
no real processes, no pid-file writes outside tmp_path."""
import json
import os
import queue
import time

import pytest

import drivers
from conftest import FIXTURES


def load_fixture_events(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def track(**kw):
    t = {"id": "trk-test", "worktree": "."}
    t.update(kw)
    return t


class _Stream:
    """A pipe end the pump/drain threads iterate: blocks until a line is
    pushed, ends on close() - exactly how a live process's stdout behaves."""

    def __init__(self):
        self.q = queue.Queue()

    def push(self, line):
        self.q.put(line)

    def close(self):
        self.q.put(None)

    def __iter__(self):
        return self

    def __next__(self):
        item = self.q.get()
        if item is None:
            raise StopIteration
        return item


class FakeClaude:
    """Stands in for the persistent claude CLI process: records the command
    line, parses each stdin line, and lets a per-test script decide what
    events to stream back."""
    last = None

    def __init__(self, cmd, cwd=None, **kw):
        self.cmd, self.cwd = cmd, cwd
        self.pid = 424242
        self.stdout, self.stderr = _Stream(), _Stream()
        self.received = []          # parsed stdin messages, in order
        self.on_message = None      # script: (proc, msg) -> None
        self.stdin = _FakeStdin(self)
        FakeClaude.last = self

    def poll(self):
        return None                 # alive until the harness closes stdout

    def emit(self, ev):
        self.stdout.push(json.dumps(ev) + "\n")


class _FakeStdin:
    def __init__(self, proc):
        self.proc, self._buf = proc, []

    def write(self, s):
        self._buf.append(s)

    def flush(self):
        # each driver write is one complete json line + newline
        while self._buf:
            msg = json.loads(self._buf.pop(0))
            self.proc.received.append(msg)
            if self.proc.on_message:
                self.proc.on_message(self.proc, msg)


@pytest.fixture
def claude_session(monkeypatch, tmp_path):
    """Headless _ClaudeSession harness: Popen -> FakeClaude, pid registry
    redirected to tmp_path, tree-kill neutered, session registry isolated per
    test. Returns a setter for the fake CLI's stdin->stdout script."""
    fakes = []
    monkeypatch.setattr(drivers, "_PIDFILE", str(tmp_path / "pids.json"))
    monkeypatch.setattr(drivers, "_tree_kill", lambda proc: None)
    monkeypatch.setattr(drivers, "_cmd_line", lambda argv: argv)
    monkeypatch.setattr(drivers, "_sessions", {})
    drivers._cancelled.clear()

    def arm(on_message):
        def popen(cmd, cwd=None, **kw):
            p = FakeClaude(cmd, cwd=cwd, **kw)
            p.on_message = on_message
            fakes.append(p)
            return p
        monkeypatch.setattr(drivers.subprocess, "Popen", popen)
    yield arm
    for p in fakes:                 # let the pump/drain threads exit
        p.stdout.close()
        p.stderr.close()
    drivers._cancelled.clear()


def reply_with(events):
    """Script: answer every user message by streaming the given events."""
    def on_message(proc, msg):
        if msg.get("type") == "user":
            for ev in events:
                proc.emit(ev)
    return on_message


RESULT_MIN = {"type": "result", "result": "ok"}


# --- claude driver ---------------------------------------------------------

def test_claude_extracts_meta_from_result_event(claude_session, tmp_path):
    claude_session(reply_with(load_fixture_events("claude_stream_events.jsonl")))
    sid, reply, meta = drivers.run({"type": "claude"},
                                   track(run_dir=str(tmp_path)), "do the thing")
    assert sid == "sess-fixture-0001"
    assert reply == "Done - endpoint added and the smoke test passes."
    assert meta["cost_usd"] == 0.2153
    assert meta["usage"]["output_tokens"] == 2694
    assert meta["usage"]["cache_read_input_tokens"] == 154820
    assert sorted(meta["models"]) == \
        ["claude-haiku-4-5-20251001", "claude-sonnet-5"]
    # clean turn: the structured failure signal is quiet
    assert meta["subtype"] == "success"
    assert meta["is_error"] is False and meta["error"] == ""


def test_claude_meta_defaults_when_event_is_sparse(claude_session, tmp_path):
    # a minimal result event (older CLI) must not crash billing
    claude_session(reply_with([{"type": "result", "result": "ok",
                                "session_id": "s-1"}]))
    sid, reply, meta = drivers.run({}, track(run_dir=str(tmp_path)), "p")
    assert (sid, reply) == ("s-1", "ok")
    assert meta == {"usage": {}, "cost_usd": None, "models": [],
                    "subtype": None, "is_error": False, "error": ""}


def test_claude_error_result_carries_structured_error(claude_session, tmp_path):
    claude_session(reply_with([{"type": "result",
                                "subtype": "error_during_execution",
                                "is_error": True, "result": "",
                                "errors": ["tool crashed", "turn aborted"],
                                "session_id": "s-err"}]))
    _, _, meta = drivers.run({}, track(run_dir=str(tmp_path)), "p")
    assert meta["is_error"] is True
    assert meta["subtype"] == "error_during_execution"
    assert meta["error"] == "tool crashed; turn aborted"


def test_claude_prompt_is_streamed_and_resume_flag(claude_session, tmp_path):
    claude_session(reply_with([RESULT_MIN]))
    drivers.run({}, track(run_dir=str(tmp_path), session_id="prior-sess"),
                "the prompt")
    p = FakeClaude.last
    assert p.received[0] == {"type": "user",
                             "message": {"role": "user",
                                         "content": "the prompt"}}
    assert p.cmd[p.cmd.index("--output-format") + 1] == "stream-json"
    assert p.cmd[p.cmd.index("--input-format") + 1] == "stream-json"
    assert p.cmd[p.cmd.index("--resume") + 1] == "prior-sess"
    assert "--fork-session" not in p.cmd


def test_claude_adopted_card_forks_the_source_session(claude_session, tmp_path):
    # a card still pointing at its SOURCE session must not write into the
    # desktop's live conversation
    claude_session(reply_with([RESULT_MIN]))
    drivers.run({}, track(run_dir=str(tmp_path), session_id="src-1",
                          adopted_source="src-1"), "p")
    assert "--fork-session" in FakeClaude.last.cmd


def test_claude_allowed_tools_flag(claude_session, tmp_path):
    claude_session(reply_with([RESULT_MIN]))
    drivers.run({"allowed_tools": ["mcp__windows-mcp__*"]},
                track(run_dir=str(tmp_path)), "p")
    p = FakeClaude.last
    assert p.cmd[p.cmd.index("--allowedTools") + 1] == "mcp__windows-mcp__*"


def test_claude_session_persists_across_turns(claude_session, tmp_path):
    claude_session(reply_with([RESULT_MIN]))
    t = track(run_dir=str(tmp_path))
    drivers.run({}, t, "first")
    first = FakeClaude.last
    drivers.run({}, t, "second")
    assert FakeClaude.last is first     # same process, no respawn
    assert [m["message"]["content"] for m in first.received
            if m["type"] == "user"] == ["first", "second"]


def test_claude_hung_turn_kills_session_and_raises(claude_session, tmp_path):
    claude_session(lambda proc, msg: None)      # the CLI never answers
    with pytest.raises(RuntimeError, match="exceeded"):
        drivers.run({"timeout": 0.2}, track(run_dir=str(tmp_path)), "p")
    # the hung session was killed so the next steer respawns + resumes
    assert not drivers._sessions["trk-test"].alive()


def test_claude_dead_stream_raises_with_stderr(claude_session, tmp_path):
    def die(proc, msg):
        proc.stderr.push("spawn EPERM: claude.cmd\n")
        s = drivers._sessions["trk-test"]
        for _ in range(200):                    # let the drain thread catch up
            if s.err_tail:
                break
            time.sleep(0.005)
        proc.stdout.close()                     # process exited, no result
    claude_session(die)
    with pytest.raises(RuntimeError, match="spawn EPERM"):
        drivers.run({}, track(run_dir=str(tmp_path)), "p")


def test_claude_cancel_returns_clean_turn_not_error(claude_session, tmp_path):
    def script(proc, msg):
        if msg.get("type") == "user":
            drivers.cancel("trk-test")          # Stop pressed mid-turn
        elif msg.get("type") == "control_request":
            # soft interrupt: claude ends the turn with a terminal result
            assert msg["request"]["subtype"] == "interrupt"
            proc.emit({"type": "result", "subtype": "success", "result": ""})
    claude_session(script)
    sid, reply, meta = drivers.run(
        {}, track(run_dir=str(tmp_path), session_id="keep-this"), "p")
    assert sid == "keep-this"                   # session survives the stop
    assert "cancelled" in reply
    assert meta == {"usage": {}, "cost_usd": None, "models": []}
    assert "trk-test" not in drivers._cancelled  # flag consumed, next turn clean


def test_cancel_idle_track_is_false_and_idempotent():
    assert drivers.cancel("trk-idle") is False
    assert drivers.cancel("trk-idle") is False
    drivers._cancelled.discard("trk-idle")


# --- http driver -----------------------------------------------------------

class FakeHTTPResponse:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_http_posts_context_and_extracts_meta(monkeypatch):
    seen = {}

    def urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["body"] = json.loads(req.data)
        return FakeHTTPResponse(json.dumps({
            "reply": "drafted", "session_id": "paseo-7",
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "cost_usd": 0.01, "models": ["gpt-x"]}).encode())
    monkeypatch.setattr(drivers.urllib.request, "urlopen", urlopen)
    t = track(session_id="prior", worktree="C:/wt")
    sid, reply, meta = drivers.run(
        {"type": "http", "url": "http://orchestrator/turn"}, t, "draft it")
    assert seen["url"] == "http://orchestrator/turn"
    assert seen["body"] == {"track": "trk-test", "worktree": "C:/wt",
                            "prompt": "draft it", "session_id": "prior"}
    assert (sid, reply) == ("paseo-7", "drafted")
    assert meta == {"usage": {"input_tokens": 10, "output_tokens": 5},
                    "cost_usd": 0.01, "models": ["gpt-x"]}


def test_http_keeps_prior_session_and_defaults_meta(monkeypatch):
    # stateless endpoint: empty body -> keep continuation key, empty meta shape
    monkeypatch.setattr(drivers.urllib.request, "urlopen",
                        lambda req, timeout=None: FakeHTTPResponse(b""))
    sid, reply, meta = drivers.run({"type": "http", "url": "http://x"},
                                   track(session_id="prior"), "p")
    assert (sid, reply) == ("prior", "")
    assert meta == {"usage": {}, "cost_usd": None, "models": []}


# --- cmd driver ------------------------------------------------------------

def _arm_cmd(monkeypatch, stdout, stderr=""):
    seen = {}

    def run(command, cwd=None, shell=None, input=None, **kw):
        seen.update(command=command, cwd=cwd, shell=shell, input=input)
        return type("R", (), {"stdout": stdout, "stderr": stderr})()
    monkeypatch.setattr(drivers.subprocess, "run", run)
    return seen


def test_cmd_stdout_is_reply_session_passthrough(monkeypatch):
    seen = _arm_cmd(monkeypatch, "the answer\n")
    sid, reply, meta = drivers.run({"type": "cmd", "command": "mytool"},
                                   track(session_id="s-9"), "the prompt")
    assert seen["command"] == "mytool" and seen["input"] == "the prompt"
    assert (sid, reply) == ("s-9", "the answer")
    assert meta == {"usage": {}, "cost_usd": None, "models": []}


def test_cmd_falls_back_to_stderr(monkeypatch):
    _arm_cmd(monkeypatch, "", stderr="tool crashed\n")
    _, reply, _ = drivers.run({"type": "cmd", "command": "mytool"},
                              track(), "p")
    assert reply == "tool crashed"


# --- dispatch --------------------------------------------------------------

def test_unknown_driver_type_raises():
    with pytest.raises(RuntimeError, match="unknown driver type"):
        drivers.run({"type": "carrier-pigeon"}, track(), "p")
