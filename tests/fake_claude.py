# -*- coding: utf-8 -*-
"""A stand-in for the `claude` CLI in stream-json mode, for driver tests.

Reads user messages and control_requests (one JSON object per line) from stdin
and emits the same stream-json events the real CLI does. Modelled on the real
binary's verified behaviour:
  - user message           -> system/init (once) + text delta + result
  - user content "__ERR__" -> a failure result (is_error, errors[]) for the
                              structured-error path
  - FAKE_HANG=1            -> init but NO result (turn hangs) until interrupted
  - control_request interrupt          -> ends a hung turn with an
                              error_during_execution result + a success
                              control_response (exactly like the real CLI)
  - control_request set_model / set_permission_mode -> success control_response
Stays alive across messages, like `claude --input-format stream-json`."""
import sys, os, json

SID = "fake-session-123"


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main():
    first = True
    hanging = False
    for line in iter(sys.stdin.readline, ""):
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        typ = msg.get("type")

        if typ == "control_request":
            req = msg.get("request") or {}
            rid = msg.get("request_id")
            st = req.get("subtype")
            if st == "interrupt":
                if hanging:
                    hanging = False
                    emit({"type": "result", "subtype": "error_during_execution",
                          "is_error": True, "result": "Interrupted", "session_id": SID})
                emit({"type": "control_response",
                      "response": {"subtype": "success", "request_id": rid,
                                   "response": {"still_queued": []}}})
            elif st in ("set_model", "set_permission_mode"):
                resp = {"subtype": "success", "request_id": rid}
                if st == "set_permission_mode":
                    resp["response"] = {"mode": req.get("mode")}
                emit({"type": "control_response", "response": resp})
            else:
                emit({"type": "control_response",
                      "response": {"subtype": "success", "request_id": rid}})
            continue

        if typ != "user":
            continue
        content = (msg.get("message") or {}).get("content")
        text = content if isinstance(content, str) else ""
        if first:
            emit({"type": "system", "subtype": "init", "session_id": SID})
            first = False
        if os.environ.get("FAKE_HANG") == "1" or text == "__HANG__":
            hanging = True
            continue
        if text == "__ERR__":
            emit({"type": "result", "subtype": "error_during_execution",
                  "is_error": True, "errors": ["boom: usage limit reached"],
                  "result": "", "session_id": SID})
            continue
        if text.startswith("__SLOW__"):
            # A long-but-PRODUCTIVE turn: dribble a delta every 0.4s N times
            # (default 8 => ~3.2s of activity) BEFORE the result, so the
            # inactivity watchdog is exercised - each delta must reset it.
            import time as _t
            try: n = int(text.split(":", 1)[1])
            except (IndexError, ValueError): n = 8
            for _ in range(n):
                _t.sleep(0.4)
                emit({"type": "stream_event",
                      "event": {"type": "content_block_delta",
                                "delta": {"type": "text_delta", "text": "."}}})
            emit({"type": "result", "subtype": "success", "result": "slow-done",
                  "total_cost_usd": 0.001, "usage": {"input_tokens": 1, "output_tokens": 1},
                  "modelUsage": {"claude-fake": {}}, "session_id": SID})
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
