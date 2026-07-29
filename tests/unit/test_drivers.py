# -*- coding: utf-8 -*-
"""Driver layer meta extraction - every driver must return
(session_id, reply, meta) with meta = {usage, cost_usd, models}, because the
measured-economics law hangs card costs off exactly these fields.

The claude driver holds ONE long-lived stream-json process per card
(_ClaudeSession): a turn is a user message pushed onto stdin and the terminal
`result` event read off stdout by the pump thread. The fake Popen below speaks
that protocol; the http driver goes through a fake urlopen; the cmd driver
through a fake subprocess.run. No CLI, no network, no real processes."""
import json
import os
import queue
import threading

import pytest

import drivers
from conftest import FIXTURES


def load_fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


def track(**kw):
    t = {"id": "trk-test", "worktree": "."}
    t.update(kw)
    return t


class FakeStream:
    """A blocking line stream standing in for the CLI's stdout/stderr pipe.
    Iteration blocks on a queue the way a live pipe does; close() ends it, and
    `drained` fires once a reader has consumed everything."""
    _EOF = object()

    def __init__(self, lines=(), closed=False):
        self.q = queue.Queue()
        self.drained = threading.Event()
        for ln in lines:
            self.q.put(ln)
        if closed:
            self.close()

    def feed(self, line):
        self.q.put(line)

    def close(self):
        self.q.put(FakeStream._EOF)

    def __iter__(self):
        return self

    def __next__(self):
        item = self.q.get()
        if item is FakeStream._EOF:
            self.drained.set()
            raise StopIteration
        return item


class FakePopen:
    """Stands in for the long-lived claude stream-json process: records the
    command line, answers the pushed user message with the armed stdout events
    (empty out = the stream ends with no result, i.e. the process died), and
    honours the soft `interrupt` control request with a control_response plus
    a terminal result, the way the real CLI winds a turn down."""
    last = None

    def __init__(self, cmd, cwd=None, out="", err="", on_prompt=None, **kw):
        self.cmd, self.cwd, self.input = cmd, cwd, None
        self.pid = 4242
        self.out, self.on_prompt = out, on_prompt
        self.stdout = FakeStream()
        self.stderr = FakeStream([err] if err else [], closed=True)
        self.stdin = _FakeStdin(self)
        FakePopen.last = self

    def poll(self):
        return None                      # looks alive; kill is a no-op in tests

    def terminate(self):
        pass

    def on_stdin(self, s):
        msg = json.loads(s)
        if msg.get("type") == "control_request":
            self.stdout.feed(json.dumps({
                "type": "control_response",
                "response": {"request_id": msg["request_id"],
                             "subtype": "success"}}))
            self.stdout.feed(json.dumps({"type": "result",
                                         "result": "(interrupted)"}))
            return
        self.input = msg["message"]["content"]
        if self.on_prompt:
            self.on_prompt()
        self.stderr.drained.wait(2)      # err_tail must land before the turn ends
        if (self.out or "").strip():
            for line in self.out.strip().splitlines():
                self.stdout.feed(line)
        else:
            self.stdout.close()


class _FakeStdin:
    def __init__(self, popen):
        self.popen = popen

    def write(self, s):
        self.popen.on_stdin(s)

    def flush(self):
        pass


@pytest.fixture
def claude_cli(monkeypatch):
    """Patch Popen and neutralise the real-process plumbing (pid bookkeeping in
    driver_pids.json, taskkill tree-kill, the Windows cmd.exe wrapper - so
    p.cmd stays an argv list); returns a setter for the fake CLI's output.
    Sessions are per-test: the module cache is cleared, and leftover pump
    threads are unblocked on teardown."""
    monkeypatch.setattr(drivers, "_record_pid", lambda *a, **kw: None)
    monkeypatch.setattr(drivers, "_forget_pid", lambda *a, **kw: None)
    monkeypatch.setattr(drivers, "_tree_kill", lambda proc: None)
    monkeypatch.setattr(drivers, "_cmd_line", lambda argv: argv)
    drivers._sessions.clear()

    def arm(out, err="", on_prompt=None):
        if out.strip():                  # the pump parses stream-json PER LINE
            out = json.dumps(json.loads(out))
        def popen(cmd, cwd=None, **kw):
            return FakePopen(cmd, cwd=cwd, out=out, err=err, on_prompt=on_prompt)
        monkeypatch.setattr(drivers.subprocess, "Popen", popen)

    yield arm
    for s in list(drivers._sessions.values()):
        try:
            s.proc.stdout.close()
        except Exception:
            pass
    drivers._sessions.clear()


# --- claude driver ---------------------------------------------------------

def test_claude_extracts_meta_from_result_event(claude_cli):
    claude_cli(load_fixture("claude_result_event.json"))
    sid, reply, meta = drivers.run({"type": "claude"}, track(), "do the thing")
    assert sid == "sess-fixture-0001"
    assert reply == "Done - endpoint added and the smoke test passes."
    assert meta["cost_usd"] == 0.2153
    assert meta["usage"]["output_tokens"] == 2694
    assert meta["usage"]["cache_read_input_tokens"] == 154820
    assert sorted(meta["models"]) == \
        ["claude-haiku-4-5-20251001", "claude-sonnet-5"]


def test_claude_meta_defaults_when_event_is_sparse(claude_cli):
    # a minimal result event (older CLI, error subtype) must not crash billing
    claude_cli(json.dumps({"type": "result", "result": "ok",
                           "session_id": "s-1"}))
    sid, reply, meta = drivers.run({}, track(), "p")
    assert (sid, reply) == ("s-1", "ok")
    assert meta == {"usage": {}, "cost_usd": None, "models": [],
                    "subtype": None, "is_error": False, "error": ""}


def test_claude_prompt_goes_to_stdin_and_resume_flag(claude_cli):
    claude_cli(load_fixture("claude_result_event.json"))
    drivers.run({}, track(session_id="prior-sess"), "the prompt")
    p = FakePopen.last
    assert p.input == "the prompt"
    assert p.cmd[p.cmd.index("--resume") + 1] == "prior-sess"
    assert p.cmd[p.cmd.index("--output-format") + 1] == "stream-json"
    assert p.cmd[p.cmd.index("--input-format") + 1] == "stream-json"


def test_claude_allowed_tools_and_long_timeout(claude_cli, monkeypatch):
    # the leash is the timeout handed to the turn's done-event wait; record
    # every Event.wait timeout and look for it (drivers shares the real
    # threading module, so patch its Event with a recording subclass)
    waits = []

    class Recorder(threading.Event):
        def wait(self, timeout=None):
            waits.append(timeout)
            return super().wait(timeout)

    monkeypatch.setattr(drivers.threading, "Event", Recorder)
    claude_cli(load_fixture("claude_result_event.json"))
    drivers.run({"allowed_tools": ["mcp__windows-mcp__*"]}, track(), "p")
    p = FakePopen.last
    assert p.cmd[p.cmd.index("--allowedTools") + 1] == "mcp__windows-mcp__*"
    assert 1800 in waits              # desktop turns get the long leash
    waits.clear()
    claude_cli(load_fixture("claude_result_event.json"))
    drivers.run({}, track(), "p")
    assert 600 in waits


def test_claude_empty_output_raises_with_stderr(claude_cli):
    claude_cli("", err="spawn EPERM: claude.cmd")
    with pytest.raises(RuntimeError, match="spawn EPERM"):
        drivers.run({}, track(), "p")


def test_claude_cancel_returns_clean_turn_not_error(claude_cli):
    t = track(session_id="keep-this")
    claude_cli("", err="killed", on_prompt=lambda: drivers.cancel(t["id"]))
    sid, reply, meta = drivers.run({}, t, "p")
    assert sid == "keep-this"                  # session survives the stop
    assert "cancelled" in reply
    assert meta == {"usage": {}, "cost_usd": None, "models": []}
    assert t["id"] not in drivers._cancelled   # flag consumed, next turn clean


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
