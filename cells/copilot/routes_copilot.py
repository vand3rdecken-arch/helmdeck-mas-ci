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
    from cells.copilot import copilot
    return self._send(200, json.dumps(copilot.history(user["name"])))


def chat_live_get(self, user):
    # the board agent's STREAMING prose reply while a turn runs, so
    # the board chat streams like a card (one shared surface). Polled
    # by the chat only while busy.
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    from cells.copilot import copilot
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
        # `voice_turn` scopes that cursor: seq restarts at 1 every turn, so
        # after a steer the daemon must know WHICH turn the client's seq counts
        # in (voice_stream.take). Absent = an old app, pre-turn-id semantics.
        turn = None
        if "voice_turn" in q:
            try:
                turn = int((q.get("voice_turn") or ["0"])[0])
            except ValueError:
                turn = None
        from spine.media import voice_stream
        clips, pending = voice_stream.take(user["name"], after, turn)
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
    from cells.copilot import copilot
    return self._send(200, json.dumps({"cancelled": copilot.cancel(user["name"])}))


def chat_post(self, user, body):
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    from cells.copilot import copilot
    text = body.get("text", "").strip()
    if not text:
        return self._send(400, json.dumps({"error": "text required"}))
    # IDEMPOTENCY, CLAIMED HERE - the earliest point in the daemon that has the
    # message. Everything below this line (turn, log append, actions) can take
    # minutes, and three transport layers give up long before that and replay
    # the POST; claiming at the END of the turn would leave exactly the window
    # the duplicate arrives in (measured: a replay was already blocked on the
    # turn lock 43ms after turn one's last message). See chat_dedupe's docstring
    # for the evidence this was reconstructed from.
    from cells.copilot import chat_dedupe
    mine, original = chat_dedupe.claim(
        user["name"], text, body.get("card"), body.get("attachments"),
        mid=body.get("mid") or "")
    if original is not None:
        # A replay. No turn, no second `you` entry in the chat log - just the
        # answer the ORIGINAL turn produced (that is what the replaying client
        # was missing). Still running after the bounded wait -> say so and let
        # the client's /chat/history poll deliver it.
        done = chat_dedupe.await_result(original)
        out = dict(done or {"reply": "", "actions": []})
        out["duplicate"] = True
        return self._send(200, json.dumps(out))
    # "stream" = speak sentence by sentence WHILE the turn runs and collect the
    # clips off /chat/live; True = the original one-shot clip in this response.
    # Two modes rather than one because the choice is the CLIENT's: only a
    # caller that actually polls for chunks may ask for streaming, and an app
    # one OTA behind still sends True and must still be answered out loud.
    want_voice = body.get("voice")
    streaming = want_voice == "stream"
    # Spoken turns ride a FAST model (settings `voice_model`, default haiku,
    # empty string = keep the chip's choice): the wait is worn as silence in
    # the owner's ear, and a spoken answer is 2-3 sentences (VOICE_STYLE) -
    # exactly the shape a small model answers well and fast. The model id
    # still walks turnopts.resolve_model's whitelist like every client value.
    model = body.get("model", "")
    if want_voice:
        from spine.storage import events
        vm = events.settings().get("voice_model")
        model = (vm if vm is not None else "haiku") or model
    try:
        out = copilot.chat(
            user["name"], text, role=user["role"], model=model,
            # thinking off while spoken: it buys quality the 3-sentence answer
            # can't spend, and every thinking second is dead air in the ear
            thinking="" if want_voice else body.get("thinking", ""),
            attachments=body.get("attachments"),
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
            from spine.ops import ask
            from spine.media import voice as _voice
            _, prose = ask.parse(out.get("reply") or "")
            clip = _voice.render_b64(
                (prose or out.get("reply") or "").split("```")[0])
            if clip:
                out = dict(out)
                out["voice"] = clip
        # Settle BEFORE the response is written: a replay may already be waiting
        # on this claim, and it must be released with the answer rather than
        # sitting out its full timeout behind a turn that is done.
        chat_dedupe.settle(mine, out)
        return self._send(200, json.dumps(out))
    except Exception as e:
        # Never SETTLE a failed turn - drop the claim, so the owner re-sending
        # after an error gets a real turn instead of a 10-minute hole. Harmless
        # if the turn actually succeeded and it was `self._send` that raised
        # (a client that hung up): fail() refuses to drop a settled claim.
        chat_dedupe.fail(mine)
        return self._send(500, json.dumps({"error": str(e)[:300]}))


def notify_speak_post(self, user, body):
    # Speak text the phone ALREADY holds - the proactive-blocker half of phone
    # voice (surfaces/app/src/data/push.ts). A push arrives sealed (notify.card_event
    # authored the title/body once, server-side); the phone decrypts it
    # locally and, if the owner turned the toggle on, hands that exact text
    # back here to be rendered as speech and played through whatever audio
    # route the phone is on right now - ordinary Bluetooth media playback
    # when paired with the glasses. No DAT, no companion project: this reuses
    # the SAME daemon-renders/client-plays split as /chat's voice:true and
    # glance_banner_voice (ops/docs/glasses-reference.md SS4/SS11.6).
    #
    # Owner/operator only, same gate as /chat - a client role has no
    # board-wide notification stream to speak from. Bounded to a short
    # phrase: this speaks an announcement, never a document.
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    text = (body.get("text") or "").strip()[:300]
    if not text:
        return self._send(400, json.dumps({"error": "text required"}))
    # Opening voice mode fetches the greeting through THIS route - use the
    # signal: prewarm the chat process (spawn + hidden cache-prefill turn) in
    # the background NOW, so the first real question hits a warm process
    # instead of paying node boot + a 128k resume prefill (~20s measured).
    # Harmless on the other caller (push read-aloud): worst case the chat is
    # warm for nothing.
    from cells.copilot import copilot
    copilot.prewarm(user["name"])
    from spine.media import voice
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
