# -*- coding: utf-8 -*-
"""A stand-in for the `claude` CLI in stream-json mode, for driver tests.

Reads user messages (one JSON object per line) from stdin and, for each, writes
the same stream-json events the real CLI emits: a one-time system/init (carrying
the session_id), a text delta, and a result. Stays alive across messages exactly
like `claude --input-format stream-json` - which is what the persistent-session
port relies on. Set FAKE_HANG=1 to emit init then never produce a result (to
exercise the turn-timeout / tree-kill path)."""
import sys, os, json, time

SID = "fake-session-123"


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main():
    first = True
    while True:
        line = sys.stdin.readline()
        if not line:            # stdin closed -> exit like the real CLI
            return
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        content = (msg.get("message") or {}).get("content")
        text = content if isinstance(content, str) else ""
        if first:
            emit({"type": "system", "subtype": "init", "session_id": SID})
            first = False
        if os.environ.get("FAKE_HANG") == "1":
            time.sleep(3600)
            continue
        emit({"type": "stream_event",
              "event": {"type": "content_block_delta",
                        "delta": {"type": "text_delta", "text": "echo:"}}})
        emit({"type": "result", "subtype": "success", "result": "echo:" + text,
              "total_cost_usd": 0.001,
              "usage": {"input_tokens": 1, "output_tokens": 1},
              "modelUsage": {"claude-fake": {}}, "session_id": SID})


if __name__ == "__main__":
    main()
