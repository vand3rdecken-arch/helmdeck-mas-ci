# -*- coding: utf-8 -*-
"""Copilot/board-chat routes - Nth slice of server.py's dispatch-table split
(see routes_auth.py for the pattern/rationale). GET /chat/history, GET
/chat/live (streaming prose while a turn runs), POST /chat/cancel, POST
/chat (the real model turn - owner/operator only, with optional voice
rendering of the prose half). Bodies are byte-identical to the inline
blocks they replace.
"""
import json


def chat_history_get(self, user):
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    from daemon.cells.copilot import copilot
    return self._send(200, json.dumps(copilot.history(user["name"])))


def chat_live_get(self, user):
    # the board agent's STREAMING prose reply while a turn runs, so
    # the board chat streams like a card (one shared surface). Polled
    # by the chat only while busy.
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    from daemon.cells.copilot import copilot
    return self._send(200, json.dumps(copilot.live(user["name"])))


def chat_cancel_post(self, user, body):
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    from daemon.cells.copilot import copilot
    return self._send(200, json.dumps({"cancelled": copilot.cancel(user["name"])}))


def chat_post(self, user, body):
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    from daemon.cells.copilot import copilot
    text = body.get("text", "").strip()
    if not text:
        return self._send(400, json.dumps({"error": "text required"}))
    try:
        out = copilot.chat(
            user["name"], text, role=user["role"], model=body.get("model", ""),
            thinking=body.get("thinking", ""), attachments=body.get("attachments"),
            card=body.get("card"))
        # VOICE MODE (phone). The client asks per-request rather than
        # by a server setting, because it is the client that knows
        # whether the owner is looking at the screen or driving. Only
        # Henry's PROSE is spoken - never the ```actions block, which
        # is machine syntax and unlistenable.
        if body.get("voice"):
            from daemon.spine import ask
            from daemon.spine import voice as _voice
            _, prose = ask.parse(out.get("reply") or "")
            clip = _voice.render_b64(
                (prose or out.get("reply") or "").split("```")[0])
            if clip:
                out = dict(out)
                out["voice"] = clip
        return self._send(200, json.dumps(out))
    except Exception as e:
        return self._send(500, json.dumps({"error": str(e)[:300]}))


GET_ROUTES = {
    "/chat/history": chat_history_get,
    "/chat/live": chat_live_get,
}
POST_ROUTES = {
    "/chat/cancel": chat_cancel_post,
    "/chat": chat_post,
}
