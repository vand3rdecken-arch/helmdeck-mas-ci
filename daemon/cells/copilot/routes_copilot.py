# -*- coding: utf-8 -*-
"""Copilot/board-chat routes - Nth slice of server.py's dispatch-table split
(see routes_auth.py for the pattern/rationale). GET /chat/history, GET
/chat/live (streaming prose while a turn runs), POST /chat/cancel, POST
/chat (the real model turn - owner/operator only, with optional voice
rendering of the prose half), POST /notify/speak (render text the phone
already holds, for the proactive-blocker voice path - see below). Bodies
are byte-identical to the inline blocks they replace.
"""
import json
from urllib.parse import parse_qs, urlparse


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
    out = copilot.live(user["name"])
    # VOICE CHUNKS ride this same poll (voice_stream.py): `?voice_from=<seq>` is
    # a READ CURSOR the client owns, so the daemon keeps exactly one copy of the
    # truth and a dropped poll or a second reader can never desynchronise it.
    # Absent param = the text-only caller the board chat has always been, which
    # keeps paying nothing for a feature it does not use - the clips are by far
    # the heavy part of this response.
    q = parse_qs(urlparse(self.path).query)
    if "voice_from" in q:
        try:
            after = int((q.get("voice_from") or ["0"])[0])
        except ValueError:
            after = 0
        from daemon.spine.media import voice_stream
        clips, pending = voice_stream.take(user["name"], after)
        out = dict(out)
        out["voice"] = clips
        # `running` alone cannot end the client's loop: the turn can be over
        # while the last chunk is still rendering, and stopping there would
        # swallow the final sentence exactly when the render lagged the model.
        out["voice_pending"] = pending
    return self._send(200, json.dumps(out))


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
    # "stream" = speak sentence by sentence WHILE the turn runs and collect the
    # clips off /chat/live; True = the original one-shot clip in this response.
    # Two modes rather than one because the choice is the CLIENT's: only a
    # caller that actually polls for chunks may ask for streaming, and an app
    # one OTA behind still sends True and must still be answered out loud.
    want_voice = body.get("voice")
    streaming = want_voice == "stream"
    try:
        out = copilot.chat(
            user["name"], text, role=user["role"], model=body.get("model", ""),
            thinking=body.get("thinking", ""), attachments=body.get("attachments"),
            card=body.get("card"), voice_stream=streaming,
            # spoken turns get the hard brevity overlay - a minute of options
            # read aloud is not an answer (owner report 2026-08-21)
            extra_system=copilot.VOICE_STYLE if want_voice else "")
        # VOICE MODE (phone). The client asks per-request rather than
        # by a server setting, because it is the client that knows
        # whether the owner is looking at the screen or driving. Only
        # Henry's PROSE is spoken - never the ```actions block, which
        # is machine syntax and unlistenable.
        if want_voice and not streaming:
            from daemon.spine.ops import ask
            from daemon.spine.media import voice as _voice
            _, prose = ask.parse(out.get("reply") or "")
            clip = _voice.render_b64(
                (prose or out.get("reply") or "").split("```")[0])
            if clip:
                out = dict(out)
                out["voice"] = clip
        return self._send(200, json.dumps(out))
    except Exception as e:
        return self._send(500, json.dumps({"error": str(e)[:300]}))


def notify_speak_post(self, user, body):
    # Speak text the phone ALREADY holds - the proactive-blocker half of phone
    # voice (app/src/data/push.ts). A push arrives sealed (notify.card_event
    # authored the title/body once, server-side); the phone decrypts it
    # locally and, if the owner turned the toggle on, hands that exact text
    # back here to be rendered as speech and played through whatever audio
    # route the phone is on right now - ordinary Bluetooth media playback
    # when paired with the glasses. No DAT, no companion project: this reuses
    # the SAME daemon-renders/client-plays split as /chat's voice:true and
    # glance_banner_voice (docs/glasses-reference.md SS4/SS11.6).
    #
    # Owner/operator only, same gate as /chat - a client role has no
    # board-wide notification stream to speak from. Bounded to a short
    # phrase: this speaks an announcement, never a document.
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    text = (body.get("text") or "").strip()[:300]
    if not text:
        return self._send(400, json.dumps({"error": "text required"}))
    from daemon.spine.media import voice
    return self._send(200, json.dumps({"clip": voice.render_b64(text)}))


GET_ROUTES = {
    "/chat/history": chat_history_get,
    "/chat/live": chat_live_get,
}
POST_ROUTES = {
    "/chat/cancel": chat_cancel_post,
    "/chat": chat_post,
    "/notify/speak": notify_speak_post,
}
