# -*- coding: utf-8 -*-
"""ops/tools/mcp_capper.py — the token-burn-hardening MCP-result capper
(ops/docs/backlog/token-burn-hardening/README.md, Karte A).

Proves the two contracts that matter for a proxy sitting on the live stdio
channel: oversized tool-call RESULTS get truncated with a visible marker
(never silently dropped), and everything else - requests, notifications,
small results, the id<->tool bookkeeping - passes through exactly.

Unit-level (no subprocess): the pure _truncate/_cap_response functions.
End-to-end: spawns the real mcp_capper.py against a tiny fake "server"
script that echoes one oversized JSON-RPC response, and reads what comes
out the capper's own stdout - the actual channel a card's CLI process reads.

Run: py -3.12 ops/tests/test_mcp_capper.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "ops", "tools"))

import mcp_capper as capper

_fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        _fails.append(msg)


def test_truncate_leaves_short_strings_alone():
    obj = {"content": [{"type": "text", "text": "short"}]}
    out = capper._truncate(obj, 50000)
    check(out == obj, "well under the cap comes back unchanged")


def test_truncate_caps_long_strings_with_marker():
    big = "x" * 100
    out = capper._truncate({"content": [{"type": "text", "text": big}]}, 10)
    text = out["content"][0]["text"]
    check(text.startswith("x" * 10), "kept text is the HEAD of the original")
    check(text.endswith(capper.MARKER), "truncated text ends with the marker tail")
    check(len(text) == 10 + len(capper.MARKER), "cap + marker, nothing extra")


def test_truncate_recurses_into_lists_and_nested_dicts():
    big = "y" * 100
    obj = {"a": [{"b": big}, "z"]}
    out = capper._truncate(obj, 10)
    check(out["a"][0]["b"].endswith(capper.MARKER), "nested dict-in-list string capped")
    check(out["a"][1] == "z", "short sibling string untouched")


def test_cap_response_uses_per_tool_override():
    tool_of_id = {7: "Snapshot"}
    msg = {"jsonrpc": "2.0", "id": 7, "result": {"text": "z" * 100}}
    out = capper._cap_response(dict(msg), tool_of_id, 50000, {"Snapshot": 5})
    check(out["result"]["text"] == "z" * 5 + capper.MARKER,
          "a per-tool override wins over the default cap")
    check(7 not in tool_of_id, "the id is consumed (popped) once its response is capped")


def test_cap_response_falls_back_to_default_without_a_known_tool():
    msg = {"jsonrpc": "2.0", "id": 9, "result": {"text": "w" * 100}}
    out = capper._cap_response(dict(msg), {}, 5, {})
    check(out["result"]["text"] == "w" * 5 + capper.MARKER,
          "unknown id (e.g. a non tools/call response) still gets the default cap")


def test_cap_response_caps_error_payloads_too():
    msg = {"jsonrpc": "2.0", "id": 1, "error": {"message": "e" * 100}}
    out = capper._cap_response(dict(msg), {}, 5, {})
    check(out["error"]["message"] == "e" * 5 + capper.MARKER,
          "an oversized error payload is capped exactly like a result")


# -- end-to-end: real subprocess, real stdio framing --------------------

_FAKE_SERVER = '''
import sys, json
for line in iter(sys.stdin.buffer.readline, b""):
    req = json.loads(line)
    if req.get("method") == "tools/call":
        resp = {"jsonrpc": "2.0", "id": req["id"],
                "result": {"content": [{"type": "text", "text": "Q" * 200}]}}
    else:
        resp = {"jsonrpc": "2.0", "id": req.get("id"), "result": {}}
    sys.stdout.buffer.write((json.dumps(resp) + "\\n").encode("utf-8"))
    sys.stdout.buffer.flush()
'''


def test_end_to_end_proxy_truncates_a_real_child_response():
    fake = os.path.join(tempfile.mkdtemp(), "fake_server.py")
    with open(fake, "w", encoding="utf-8") as f:
        f.write(_FAKE_SERVER)
    argv = [sys.executable, os.path.join(ROOT, "ops", "tools", "mcp_capper.py"),
            "--max-chars", "20", "--", sys.executable, fake]
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    req = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": "Snapshot", "arguments": {}}}
    proc.stdin.write((json.dumps(req) + "\n").encode("utf-8"))
    proc.stdin.flush()
    proc.stdin.close()
    line = proc.stdout.readline()
    proc.wait(timeout=10)
    resp = json.loads(line)
    text = resp["result"]["content"][0]["text"]
    check(len(text) == 20 + len(capper.MARKER),
          "the real child's 200-char result arrives capped to 20 + marker (got %d)" % len(text))
    check(text.endswith(capper.MARKER), "marker present on the wire, not just in-process")


if __name__ == "__main__":
    test_truncate_leaves_short_strings_alone()
    test_truncate_caps_long_strings_with_marker()
    test_truncate_recurses_into_lists_and_nested_dicts()
    test_cap_response_uses_per_tool_override()
    test_cap_response_falls_back_to_default_without_a_known_tool()
    test_cap_response_caps_error_payloads_too()
    test_end_to_end_proxy_truncates_a_real_child_response()
    print("OK" if not _fails else "FAILED: %d" % len(_fails))
    sys.exit(1 if _fails else 0)
