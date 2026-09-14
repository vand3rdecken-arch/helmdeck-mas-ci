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
import time
from urllib.parse import parse_qs, urlparse


def chat_history_get(self, user):
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    from cells.copilot.chat import copilot
    # Opening the board chat fetches the transcript through THIS route - the
    # same "a question is coming" signal voice mode gives via /notify/speak.
    # Warm the process NOW, while the owner is still reading and typing,
    # instead of on the clock of their first message. Fire-and-forget, a no-op
    # when the process is already warm, and self-throttled against this route's
    # 8s fallback poll (copilot._PREWARM_COOLDOWN).
    copilot.prewarm(user["name"], spoken=False)
    return self._send(200, json.dumps(copilot.history(user["name"])))


def chat_threads_get(self, user):
    """Conversations = card threads + the inbox, grouped by process
    (cells/copilot/chat/threads.py). Same audience as the history."""
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    from cells.copilot.chat import threads
    return self._send(200, json.dumps(threads.threads(user["name"])))


def chat_live_get(self, user):
    # the board agent's STREAMING prose reply while a turn runs, so
    # the board chat streams like a card (one shared surface). Polled
    # by the chat only while busy.
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    from cells.copilot.chat import copilot
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
    from cells.copilot.chat import copilot
    return self._send(200, json.dumps({"cancelled": copilot.cancel(user["name"])}))


def _route_to_card(self, user, text, tid, mid=""):
    """The owner answered a MIRRORED card message in the Henry chat: send it to
    that card instead of running a Henry turn (owner decree 2026-08-29).

    Bound by the `card` id the mirror stamped on the chat entry, NEVER by
    reading the text. Guessing which card a reply belongs to is the one design
    this decree rules out by name, and rightly: the failure mode is silent and
    unrecoverable - a steer delivered to the wrong worker is already executing
    by the time anyone can notice.

    Two destinations, because a card that ASKED is in a different state from one
    that merely reported:
      * a single pending question -> POST-equivalent of /tracks/<id>/answer, so
        the question is SETTLED. ask.validate_answers takes free text as the
        owner's own words (the 'Other' escape hatch), which is exactly what a
        typed chat reply is. Without this the question would stay open next to a
        loose remark and the card would ask again.
      * anything else (no question, or a multi-question ask one line cannot
        settle) -> a plain steer.
    Falling back rather than erroring matters: the owner typed a sentence at his
    inbox, and "that was not a valid answer" is not a useful thing to say to a
    person who just answered.

    Backgrounded exactly like the REST routes it stands in for - both RUN a turn
    on the card, and holding the HTTP request would block the chat for its
    length."""
    from cells.engineer.cards import sessions
    from spine.auth import auth
    from spine.http import server
    t = sessions.get_track(tid)
    if not t:
        # The transcript still binds replies to a card the store no longer has
        # (deleted before say_closed existed, or a race with the delete). The
        # failed lookup IS the evidence - fold it in as a card-bound CLOSED
        # line so the composer's derived target releases the ghost on the next
        # history poll instead of dead-ending on every send. Then still 404:
        # the words were not delivered and must not pretend to be.
        try:
            from cells.copilot.chat import card_mirror
            card_mirror.say_closed({"id": tid, "task": ""}, "deleted", "system")
        except Exception:
            pass
        return self._send(404, json.dumps({"error": "no such card"}))
    if not auth.owns_card(user, t):
        return self._send(403, json.dumps({"error": "not your card"}))
    actor = user["name"]
    # ONE rule for which door, shared with /wear/talk - see sessions.reply_door.
    routed, answers, rid = sessions.reply_door(t, text)
    if routed == "answer":
        server._bg("track:answer:" + tid, lambda: sessions.answer_question(
            # this route logs the owner's words itself, verbatim and with the
            # app's `mid` - see answer_question's echo_chat note
            tid, answers, request_id=rid, actor=actor, echo_chat=False))
    else:
        server._bg("track:steer:" + tid, lambda: sessions.steer(
            tid, text, actor=actor))
    # The Henry transcript must still show what the owner said and where it
    # went, or the inbox would swallow his own message: he types into the board
    # chat, the words execute on a card, and the surface he typed at shows
    # nothing. `card` rides on the `you` entry too, so a follow-up reply keeps
    # the same binding without the client having to re-send it.
    from cells.copilot.chat import copilot, card_mirror
    try:
        copilot._append_log(user["name"], [dict(
            {"cls": "you", "text": text, "ts": time.strftime("%H:%M"),
             "card": tid, "to": "worker"},
            **({"client_msg_id": mid[:64]} if mid else {}))])
        card_mirror.say_card(
            t, card_mirror.KIND_RESULT,
            ("Antwort an '%s' geschickt." if routed == "answer"
             else "Anweisung an '%s' geschickt.") % card_mirror.short_name(t))
    except Exception:
        pass
    return self._send(200, json.dumps(
        {"reply": "", "actions": [], "routed": {"card": tid, "as": routed}}))


def _answer_text(user, request_id, answers):
    """(text, error, status) - the owner's next chat message, rendered from an
    answer he TAPPED on one of Henry's own <helmdeck-ask> questions.

    The tap does not get a private channel: it is turned into a message here and
    then walks the ordinary chat path - dedupe, turn, log - so an answer is the
    owner's next message in every sense, exactly as a typed one is. That is also
    why the wording is rendered on THIS side: the app would otherwise have to
    own a second copy of it, and the two would drift the first time either
    changed (ask.chat_answer_text's docstring has the rest).

    The two 409s are the same guards /tracks/<id>/answer and /glance/answer
    apply, for the same reason: a panel left open on a phone in a pocket must
    not be able to answer a question the conversation has already moved past."""
    from spine.ops import ask
    from cells.copilot.chat import copilot
    q = copilot.open_question(user["name"])
    if not q:
        return "", "no pending question", 409
    if request_id != (q.get("id") or ""):
        return "", "this question was already answered or replaced", 409
    picks, err = ask.validate_answers(q, answers)
    if err:
        return "", err, 400
    text = ask.chat_answer_text(picks).strip()
    if not text:
        return "", "empty answer", 400
    return text, "", 0


def chat_post(self, user, body):
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    from cells.copilot.chat import copilot
    text = body.get("text", "").strip()
    # TAPPED ANSWER to one of HENRY's questions. `answer_to` is the question id,
    # so this cannot be confused with `reply_to_card` below (that one routes a
    # message to a WORKER and never runs a Henry turn); this one is a Henry turn
    # whose text the daemon writes.
    answer_to = str(body.get("answer_to") or "").strip()
    if answer_to:
        text, err, code = _answer_text(user, answer_to, body.get("answers") or {})
        if err:
            return self._send(code, json.dumps({"error": err}))
    if not text:
        return self._send(400, json.dumps({"error": "text required"}))
    # INLINE ANSWER (owner decree 2026-08-29). Deliberately a DIFFERENT field
    # from `card` below: `card` means "the owner is looking at this card, so
    # resolve 'it' against it" and must keep reaching Henry, while this means
    # "do not ask Henry at all, this belongs to the worker". Overloading the one
    # field would have silently turned every card-scoped Henry question into a
    # steer at the worker - the card chat's Henry tab would have stopped
    # existing, with nothing in the UI to show why.
    reply_to = str(body.get("reply_to_card") or "").strip()
    if reply_to:
        return _route_to_card(self, user, text, reply_to,
                              mid=str(body.get("mid") or ""))
    # IDEMPOTENCY, CLAIMED HERE - the earliest point in the daemon that has the
    # message. Everything below this line (turn, log append, actions) can take
    # minutes, and three transport layers give up long before that and replay
    # the POST; claiming at the END of the turn would leave exactly the window
    # the duplicate arrives in (measured: a replay was already blocked on the
    # turn lock 43ms after turn one's last message). See chat_dedupe's docstring
    # for the evidence this was reconstructed from.
    from cells.copilot.chat import chat_dedupe
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
    # A voice turn's pinned fast model is a per-turn override, not the
    # conversation's choice - tell chat() so it does not RECORD it as the
    # sticky tier (copilot._save_model_pref). model_source stays "user" when
    # voice_model="" (= keep the chip's pick): then the model IS the user's.
    model_source = "user"
    if want_voice:
        from spine.storage import events
        vm = events.settings().get("voice_model")
        if (vm if vm is not None else "haiku"):
            model_source = "voice"
        model = (vm if vm is not None else "haiku") or model
    try:
        out = copilot.chat(
            user["name"], text, role=user["role"], model=model,
            model_source=model_source,
            # thinking off while spoken: it buys quality the 3-sentence answer
            # can't spend, and every thinking second is dead air in the ear
            thinking="" if want_voice else body.get("thinking", ""),
            mode=str(body.get("mode") or ""),
            attachments=body.get("attachments"),
            card=body.get("card"), voice_stream=streaming,
            # REUSES `mid`, the id the app already mints once per /chat call
            # (client.ts) and which chat_dedupe.claim() above already reads as a
            # replay detector. It is exactly the identity Paseo calls
            # clientMessageId - minting a SECOND id for the same message would
            # have been a new field to keep in sync with an existing one, i.e.
            # the wheel this repo already has. Echoed back on the persisted `you`
            # entry so the app can retire its optimistic copy by identity rather
            # than by comparing text.
            # Truncated because it is an opaque token, not content - a client
            # sending something huge must not grow every log line.
            client_msg_id=str(body.get("mid") or "")[:64],
            # spoken turns get the hard brevity overlay - a minute of options
            # read aloud is not an answer (owner report 2026-08-21)
            extra_system=copilot.voice_style() if want_voice else "")
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
        # A failed turn must be VISIBLE in the transcript on every device: the
        # POST's error lands in the app's optimistic turn, which the user-row
        # echo has usually retired by then - i.e. nowhere (2026-09-14 12:45).
        try:
            copilot._append_log(user["name"], [{"cls": "error", "ts": time.strftime("%H:%M"),
                                                "text": "Henry hat nicht geantwortet: %s" % str(e)[:200]}])
        except Exception:                                    # noqa: BLE001
            pass
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
    from cells.copilot.chat import copilot
    copilot.prewarm(user["name"])
    from spine.media import voice
    return self._send(200, json.dumps({"clip": voice.render_b64(text)}))


GET_ROUTES = {
    "/chat/history": chat_history_get,
    "/chat/live": chat_live_get,
    "/chat/threads": chat_threads_get,
}
POST_ROUTES = {
    "/chat/cancel": chat_cancel_post,
    "/chat": chat_post,
    "/notify/speak": notify_speak_post,
}
