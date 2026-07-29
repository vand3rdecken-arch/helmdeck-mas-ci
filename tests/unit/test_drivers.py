# -*- coding: utf-8 -*-
"""Driver layer meta extraction - every driver must return
(session_id, reply, meta) with meta = {usage, cost_usd, models}, because the
measured-economics law hangs card costs off exactly these fields.

The claude driver is fed the fixture result event (the terminal event of the
CLI's stream-json/json output) through a fake Popen; the http driver through
a fake urlopen; the cmd driver through a fake subprocess.run. No CLI, no
network, no real processes."""
import json
import os

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


class FakePopen:
    """Stands in for the claude CLI process; records the command line and the
    prompt, replies with canned stdout/stderr."""
    last = None

    def __init__(self, cmd, cwd=None, **kw):
        self.cmd, self.cwd, self.input = cmd, cwd, None
        self.on_communicate = None
        FakePopen.last = self

    def communicate(self, input=None, timeout=None):
        self.input, self.timeout = input, timeout
        if self.on_communicate:
            self.on_communicate()
        return self.out, self.err

    def terminate(self):
        pass


@pytest.fixture
def claude_cli(monkeypatch):
    """Patch Popen; returns a setter for the fake CLI's output."""
    def arm(out, err="", on_communicate=None):
        def popen(cmd, cwd=None, **kw):
            p = FakePopen(cmd, cwd=cwd, **kw)
            p.out, p.err, p.on_communicate = out, err, on_communicate
            return p
        monkeypatch.setattr(drivers.subprocess, "Popen", popen)
    return arm


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
    claude_cli(json.dumps({"result": "ok", "session_id": "s-1"}))
    sid, reply, meta = drivers.run({}, track(), "p")
    assert (sid, reply) == ("s-1", "ok")
    assert meta == {"usage": {}, "cost_usd": None, "models": []}


def test_claude_prompt_goes_to_stdin_and_resume_flag(claude_cli):
    claude_cli(load_fixture("claude_result_event.json"))
    drivers.run({}, track(session_id="prior-sess"), "the prompt")
    p = FakePopen.last
    assert p.input == "the prompt"
    assert p.cmd[p.cmd.index("--resume") + 1] == "prior-sess"
    assert p.cmd[p.cmd.index("--output-format") + 1] == "json"


def test_claude_allowed_tools_and_long_timeout(claude_cli):
    claude_cli(load_fixture("claude_result_event.json"))
    drivers.run({"allowed_tools": ["mcp__windows-mcp__*"]}, track(), "p")
    p = FakePopen.last
    assert p.cmd[p.cmd.index("--allowedTools") + 1] == "mcp__windows-mcp__*"
    assert p.timeout == 1800          # desktop turns get the long leash
    claude_cli(load_fixture("claude_result_event.json"))
    drivers.run({}, track(), "p")
    assert FakePopen.last.timeout == 600


def test_claude_empty_output_raises_with_stderr(claude_cli):
    claude_cli("", err="spawn EPERM: claude.cmd")
    with pytest.raises(RuntimeError, match="spawn EPERM"):
        drivers.run({}, track(), "p")


def test_claude_cancel_returns_clean_turn_not_error(claude_cli):
    t = track(session_id="keep-this")
    claude_cli("", err="killed", on_communicate=lambda: drivers.cancel(t["id"]))
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
