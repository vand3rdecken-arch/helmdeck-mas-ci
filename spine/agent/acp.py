# -*- coding: utf-8 -*-
"""NDJSON JSON-RPC 2.0 client for the Agent Client Protocol (ACP).

Stage-0 transport for engines that speak ACP over stdio (ops/docs/
multi-engine-build-plan.md Card 3). Cursor is the first consumer
(`spine/agent/cursor_driver.py`); Gemini and other ACP engines reuse this.

Wire shape (agentclientprotocol.com v1, measured against `agent acp`
2026-10-02):
  Client -> Agent: initialize, authenticate, session/new|load,
                   session/prompt, session/cancel
  Agent -> Client: session/update (notification), session/request_permission
                   (request - must be answered)

Framing is one JSON object per line on stdin/stdout - the same pattern as
codex_driver._CodexRpc, kept here so ACP engines share one correlator.
"""
import json
import threading


PROTOCOL_VERSION = 1

CLIENT_INFO = {
    "name": "HelmDeck",
    "title": "HelmDeck ACP Driver",
    "version": "0.0.0",
}


class AcpRpc:
    """Bidirectional JSON-RPC 2.0 over a process's stdio (NDJSON).

    Three inbound shapes, dispatched in handle_line:
      - {"id": N, "result"/"error": ...}          response to OUR request
      - {"method": ..., "params": ...}             notification (no id)
      - {"id": N, "method": ..., "params": ...}    REQUEST needing our reply
    """

    def __init__(self, proc):
        self.proc = proc
        self._next_id = 1
        self._pending = {}
        self._lock = threading.Lock()
        self.on_notification = None   # (method, params) -> None
        self.on_request = None        # (method, params) -> result dict

    def request(self, method, params=None, timeout=30.0):
        with self._lock:
            rid = self._next_id
            self._next_id += 1
        ev = threading.Event()
        self._pending[rid] = {"ev": ev, "resp": None}
        msg = {"jsonrpc": "2.0", "id": rid, "method": method,
               "params": params if params is not None else {}}
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        ok = ev.wait(timeout)
        slot = self._pending.pop(rid, None)
        if not ok or slot is None or slot["resp"] is None:
            raise RuntimeError("acp request timed out: %s" % method)
        resp = slot["resp"]
        if "error" in resp and resp["error"]:
            raise RuntimeError("acp error on %s: %s" % (method, resp["error"]))
        return resp.get("result")

    def notify(self, method, params=None):
        msg = {"jsonrpc": "2.0", "method": method,
               "params": params if params is not None else {}}
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def _respond(self, rid, result):
        msg = {"jsonrpc": "2.0", "id": rid, "result": result}
        try:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
        except Exception:
            pass

    def handle_line(self, obj):
        if "id" in obj and "method" not in obj:
            slot = self._pending.get(obj["id"])
            if slot:
                slot["resp"] = obj
                slot["ev"].set()
            return
        if "id" in obj and "method" in obj:
            result = {"outcome": {"outcome": "cancelled"}}
            if self.on_request:
                try:
                    result = self.on_request(obj["method"],
                                             obj.get("params") or {}) or result
                except Exception:
                    pass
            self._respond(obj["id"], result)
            return
        if "method" in obj:
            if self.on_notification:
                try:
                    self.on_notification(obj["method"], obj.get("params") or {})
                except Exception:
                    pass


def pick_permission_outcome(options):
    """Auto-allow for headless cards (Stage 0 / acceptEdits-class). Prefer
    allow_once, then allow_always; else first option; else cancel.
    Paseo: acp-agent.ts selectPermissionOption + Stage-0 auto-pick."""
    options = options or []
    for kind in ("allow_once", "allow_always"):
        for opt in options:
            if opt.get("kind") == kind and opt.get("optionId"):
                return {"outcome": {"outcome": "selected",
                                    "optionId": opt["optionId"]}}
    if options and options[0].get("optionId"):
        return {"outcome": {"outcome": "selected",
                            "optionId": options[0]["optionId"]}}
    return {"outcome": {"outcome": "cancelled"}}


def content_text(update):
    """Text from an agent_message_chunk / agent_thought_chunk content block."""
    c = (update or {}).get("content") or {}
    if isinstance(c, dict) and c.get("type") == "text":
        return c.get("text") or ""
    if isinstance(c, str):
        return c
    return ""
