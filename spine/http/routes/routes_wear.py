# -*- coding: utf-8 -*-
"""Wear OS routes - the watch's own board summary + advisory Henry chat.
Bearer/session-authed (the watch pairs as a real per-device client, see
ops/docs/backlog/wear-os-integration/README.md §4.6) - NOT glance_token-gated
the way routes_glance.py is. That mechanism exists only because the Ray-Ban
glasses' webview cannot run real NaCl client crypto; the watch can and does
(its own device token from POST /relay/pair/code, routes_relay.py).

GET /wear/board reuses glance_payload() UNCHANGED (spine/ops/glances.py) -
the same small, curated, wearable-safe board read the glasses already get,
reached through a different door rather than re-derived.

POST /wear/talk mirrors routes_glance.py's glance_talk almost exactly
(allow_actions=False, the same ask.parse() extraction so the CLIENT never
has to parse a <helmdeck-ask> block itself) but enforces the owner decree
recorded in the wear-os-integration card §4.7 (2026-08-29): wearables talk
to Henry, ADVISORY ONLY, never the worker directly - imported from the
glasses' own proven pattern, not re-decided per surface.
"""
import json
import re

# Wear OS quality bar (README.md §7.2): fits a 192dp circle, no keyboard,
# tap-to-answer or dictation only - the same CLASS of constraint GLASS_BRIEF
# encodes for the glasses, but this is a DIFFERENT device (no
# speechSynthesis-less-webview quirks, no lens-specific facts), so it gets
# its own text rather than reusing GLASS_BRIEF's glasses-specific claims
# verbatim.
WEAR_BRIEF = (
    "SURFACE: you are being read on a WEAR OS WATCH, not the phone.\n"
    "- The watch is a small round screen with NO keyboard. Keep the prose to "
    "at most 2 short sentences - what is true right now, and what you would "
    "do. No lists, no markdown, no headings.\n"
    "- The owner CANNOT TYPE here; dictation is his only text input, and "
    "tapping an option is his fastest input. So you MUST end every reply "
    "with a <helmdeck-ask> block offering 2-6 next moves, exactly as a card "
    "worker would:\n"
    "<helmdeck-ask>\n"
    '{"questions": [{"question": "<what to do next>", "header": "<max 24 chars>", '
    '"options": [{"label": "<short>", "description": "<what it means>"}]}]}\n'
    "</helmdeck-ask>\n"
    "Ending without that block strands him - it is a defect, not a hand-off. "
    "Always include a way to go wider (e.g. 'Something else') so a wrong "
    "guess is never a trap.\n"
    "- This surface is ADVISORY: any actions block you emit is DROPPED, not "
    "run. Never claim you changed the board. To actually move work, offer it "
    "as an option and say it will run from the phone."
)


# Per-section cap. The wrist is a triage surface, not a backlog reader; the
# totals ride alongside so "3 von 12" stays honest without sending 12 rows.
WEAR_LIST_MAX = 5

# How much of a card's own text the watch may carry. The CARD SCREEN scrolls
# (TransformingLazyColumn), unlike the glasses' one-card lens, so this is far
# above glance_payload's 160-char `detail` - but still a payload bound: it rides
# sealed through the relay inside the board response, once per listed card.
#
# Raised 700 -> 1200 after the owner read a real turn report on the watch and
# said "Message abgeschnitten": a DELIVERED summary is the thing he opens a card
# to read, and 700 lost it mid-thought. Scrolling costs him a flick; a missing
# half costs him the answer.
WEAR_BODY_MAX = 1200

# The `detail` line the watch shows above the body. Same number glance_payload
# already caps it at, so this only ever re-cuts text that arrived at the wall.
WEAR_DETAIL_MAX = 160

# The markup the phone RENDERS and a watch would show as literal characters.
# Headings and list bullets are matched per line (re.M); emphasis and code ticks
# anywhere. Deliberately NOT a markdown parser - this only removes the markers
# that would otherwise read as '**DELIVERED**' on a 240dp screen.
_WEAR_MD = re.compile(r"^\s{0,3}#{1,6}\s*|^\s{0,3}[-*+]\s+|\*\*|__|`+", re.M)


def _wear_clip(text, cap):
    """Cut at a boundary, and SAY that it was cut.

    Owner, 2026-08-29, reading a turn report on the watch: "Message
    abgeschnitten." A plain text[:cap] ends mid-word - the screen showed
    "... (`wear-debug.apk`, 13:24" and simply stopped, which reads as a bug in
    the message rather than as a bound on the screen.

    Prefer a sentence end; fall back to a word boundary; the ellipsis is added
    either way so a cut is never mistaken for the end of the thought. The
    sentence end is only accepted in the second half of the budget - otherwise a
    single early full stop would throw away most of what fits.
    """
    text = text or ""
    if len(text) <= cap:
        return text
    head = text[:cap]
    end = -1
    for mark in (". ", "! ", "? ", ".\n", "!\n", "?\n"):
        end = max(end, head.rfind(mark))
    if end >= cap // 2:
        return head[:end + 1].rstrip() + " ..."
    sp = head.rfind(" ")
    if sp <= 0:
        return head.rstrip() + "..."
    return head[:sp].rstrip(" ,;:-") + " ..."


def _wear_text(raw, cap=WEAR_BODY_MAX):
    """A card's own prose, made readable on a wrist.

    Three things are stripped, each for a reason already established on another
    surface rather than invented here:

     1. the <helmdeck-ask> block, via the SAME ask.parse() wear_talk_post and
        wear_chat_get already use. The stored reply keeps the block verbatim, and
        rendering it raw is exactly the '{"label": ...' screenful the owner
        photographed on 2026-08-29.
     2. fenced blocks. ```actions is machine syntax and a code fence is
        unreadable at this width; taking the EVEN split segments drops the
        fenced halves and keeps the prose between them.
     3. markdown markers, which only a renderer makes invisible.

    Blank-line structure is KEPT (collapsed to one), because paragraph breaks are
    the only thing left telling the eye where a thought ends. Whitespace inside a
    line is collapsed - a wrapped 240dp line has no use for the phone's columns.
    """
    from spine.ops import ask
    _q, prose = ask.parse(raw or "")
    text = prose or raw or ""
    text = "".join(text.split("```")[0::2])
    text = _WEAR_MD.sub("", text)
    out, blank = [], False
    for line in text.splitlines():
        line = " ".join(line.split())
        if not line:
            blank = True
            continue
        if out and blank:
            out.append("")
        blank = False
        out.append(line)
    return _wear_clip("\n".join(out).strip(), cap)


def _wear_body(t):
    """What this card is ABOUT, for a screen that has room for it.

    The last thing the machine SAID on the card, which for a running card is the
    previous turn's report and for a finished one is the delivery. Falls back to
    the card's description for a card that has never run (the `yours` bucket),
    where there is no reply yet but the owner still needs to know what he is
    looking at before he starts it.
    """
    t = t or {}
    return _wear_text(t.get("last_reply") or t.get("description") or "")


def _wear_pipeline(tracks, taken_ids):
    """The two buckets glance_payload deliberately leaves out, added for the
    WATCH ONLY.

    Owner, 2026-08-29: "macht es mehr Sinn karten im backlog, in arbeit und
    review zu zeigen bzw. Karten die mich brauchen als erstes?" - yes, and this
    is the right place for it. glance_payload answers "what wants ME" and is
    shared with the GLASSES (surfaces/glasses/app.js reads /glance, its worker
    proxies only /glance*), so widening it would change a payload another
    surface depends on. /wear/board is the watch's own route and always was -
    it merely re-served glance_payload unchanged until now.

    REVIEW is deliberately absent as a section: a card resting on Review for an
    accept is already a blocker (blockers.blocker()), so it is in `needs_you`
    where it belongs - listing it twice would be the same card shouting twice.

    present() first, for the same reason owner_blockers does: a card whose turn
    died still says `running` in storage, and calling that "in Arbeit" on a
    watch would be a lie the owner cannot see through. Anything already in
    needs_you/yours is skipped so no card appears in two sections.
    """
    from cells.engineer import sessions
    working, backlog = [], []
    for t in tracks or ():
        t = sessions.present(t or {})
        if t.get("archived") or t.get("id") in taken_ids:
            continue
        status = t.get("status")
        # `body` and `status` ride along because tapping one of these rows opens
        # the SAME CardScreen a needs_you card opens - and these carry no
        # blocker, so without them that screen had literally nothing to show but
        # the title. Owner, 2026-08-29, on the running machine card: "wenn ich
        # auf Karte gehe ist nichts da."
        row = {"id": t.get("id"), "task": (t.get("task") or "")[:60],
               "status": status, "body": _wear_body(t)}
        if status == "running":
            working.append(row)
        elif status == "queued":
            backlog.append(row)
    return {"working": working[:WEAR_LIST_MAX], "working_total": len(working),
            "backlog": backlog[:WEAR_LIST_MAX], "backlog_total": len(backlog)}


def wear_board_get(self, user):
    # Same bar as chat_post's own role check (routes_copilot.py) - a `client`
    # role has no board-wide view to be shown here, on any surface.
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    from cells.engineer import sessions
    from spine.storage import events
    from spine.ops.glances import glance_payload
    tracks = sessions.list_tracks()
    payload = glance_payload(tracks, events.metrics(tracks))
    # ADDITIVE: every existing key keeps its shape and meaning, so an older
    # installed watch build simply ignores what it does not know.
    taken = {c.get("id") for c in (payload.get("needs_you") or [])}
    taken |= {c.get("id") for c in (payload.get("yours") or [])}
    payload["pipeline"] = _wear_pipeline(tracks, taken)
    # The card's own text, on EVERY bucket. glance_payload's `detail` is capped
    # at 160 chars and shaped for the GLASSES' one-line lens (blockers.py
    # _blocker_text) - it says why a card is stuck, which is not the same thing
    # as what happened on it. `detail` is left exactly as it is: the glasses read
    # that payload too, and widening a shared field for one surface is the drift
    # blockers.py exists to prevent. `body` is the watch's own, added here rather
    # than in glances.py for the same reason `pipeline` is.
    by_id = {t.get("id"): t for t in tracks or ()}
    for bucket in ("needs_you", "yours"):
        for row in payload.get(bucket) or ():
            row["body"] = _wear_body(by_id.get(row.get("id")))
            # `detail` reaches the WATCH cleaned. blockers._blocker_text only
            # collapses whitespace and slices at 160 - it is shaped for a badge
            # and for the glasses' lens, and it hands markdown straight through.
            # On the watch that rendered as a literal "## DELIVERED **Auf der
            # Uhr...**" ending mid-word at "13:24" (owner, on-device
            # 2026-08-29). Mutating the row here touches THIS response only:
            # glance_payload builds a fresh dict per call and the glasses go
            # through routes_glance, which never sees this object.
            if row.get("detail"):
                row["detail"] = _wear_text(row["detail"], WEAR_DETAIL_MAX)
    return self._send(200, json.dumps(payload))


# How many transcript lines the watch may pull. The wrist is not where anyone
# reads back a long conversation, and every line rides through the sealed relay
# in ONE response - so this is a payload bound as much as a UI one.
WEAR_CHAT_MAX = 30
# Per-line cap for the scrollback. 240 chars is roughly six lines of readable
# text on a 240dp round screen - past that the owner is scrolling, not reading.
WEAR_CHAT_LINE_MAX = 240


def wear_chat_get(self, user):
    """The owner's REAL Henry transcript - the same copilot session the phone
    renders, not a watch-local one.

    Owner, 2026-08-29: "Ich will den Chat Verlauf mit Henry sehen und
    Nachrichten verschicken." The sending half already worked: wear_talk_post
    below calls copilot.chat() with the SAME user, so a watch message has
    always landed in the same Claude session (copilot_sessions.json) the phone
    resumes. Only the READING half was missing, which is why the watch looked
    like a separate, amnesiac chat.

    Trimmed to the shape a round screen can use: `cls` collapses to who spoke,
    and the internal classes the board chat renders as chrome ("act" =
    action receipts) are dropped rather than shown as if Henry had said them.
    """
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    from cells.copilot import copilot
    from spine.ops import ask
    from spine.ops.glances import _glance_question
    msgs = (copilot.history(user["name"]) or {}).get("messages") or []
    out = []
    for m in msgs:
        # The log is a FILE this route only reads; a truncated write or a
        # hand-edit can leave anything in the array. `(m or {})` below already
        # reached for that robustness but only covered None - a string entry
        # still raised AttributeError and cost the watch its whole transcript
        # for one bad line. Found by ops/tests/test_chat_date_stamp.py, not in
        # the field.
        if not isinstance(m, dict):
            continue
        cls = (m or {}).get("cls") or ""
        # "card" and "pm" JOINED the allowlist on 2026-08-29 (the one-inbox
        # decree). "card" is the event mirror - a card's question, result or
        # blocker - and it is the entire reason the watch has a chat: card
        # navigation does not exist on the wrist, so a mirrored line the watch
        # filtered out would be unreachable there by construction.
        #
        # "pm" came in with it, and that was a latent defect rather than a new
        # feature. This filter's own docstring justifies dropping only "act"
        # (action receipts, genuine chrome); "pm" is Henry's proactive VOICE -
        # every lane outcome, every broker decision, every PM alert - and it was
        # being discarded as chrome alongside it. The watch has been showing a
        # conversation with Henry's half of it missing.
        if cls not in ("you", "bot", "error", "card", "pm"):
            continue
        text = ((m or {}).get("text") or "").strip()
        if not text:
            continue
        if cls == "bot":
            # The STORED text still carries the raw <helmdeck-ask> block; only
            # the live path strips it (wear_talk_post does `q, prose =
            # ask.parse(reply)` a few lines below). Reading the log verbatim put
            # a screenful of '{"label": ...' JSON on the watch - seen on-device
            # 2026-08-29. Same parse, same reason: the block is an interaction,
            # not something anyone reads.
            _q, prose = ask.parse(text)
            text = (prose or "").strip() or text
        # A scrollback line, not the live answer: long enough to recognise the
        # turn, short enough that 30 of them stay a conversation instead of a
        # wall. The full text is always one tap away on the phone.
        # `date` is "YYYY-MM-DD" and is ABSENT on every entry written before
        # copilot._append_log started stamping it (2026-08-29). "" therefore
        # means "not recorded", not "today" - the watch draws no separator above
        # such a line rather than filing it under a day it cannot know.
        # _wear_text, not a bare slice: it strips markdown and fenced blocks and
        # says " ..." when it cut. The scrollback used to slice raw, so the
        # markdown the board chat renders as formatting arrived on the wrist as
        # literal '**' and '###' - the exact defect d243545 fixed for
        # /wear/board while this route kept its own, weaker clip. One wrist-text
        # policy, one function.
        row = {"mine": cls == "you", "text": _wear_text(text, WEAR_CHAT_LINE_MAX),
               "ts": (m or {}).get("ts") or "",
               "date": (m or {}).get("date") or ""}
        if cls == "card":
            # The LABEL the watch draws instead of a sender name ("Frage ·
            # Kartenname"). Sent as its parts, not as a rendered string: the
            # wrist composes it into a TitleCard title, and a pre-rendered label
            # would have to guess that layout from the server.
            row["kind"] = (m or {}).get("kind") or ""
            row["cardName"] = (m or {}).get("cardName") or ""
            row["card"] = (m or {}).get("card") or ""
            q = (m or {}).get("question")
            if q:
                # Same trimming the glasses and /wear/talk already use, so the
                # watch has exactly ONE shape of question to render whether it
                # came from a live talk or from the mirrored inbox.
                row["question"] = _glance_question({"question": q})
        out.append(row)
    return self._send(200, json.dumps({"messages": out[-WEAR_CHAT_MAX:]}))


def wear_talk_post(self, user, body):
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    msg = (body.get("message") or "").strip()[:400]
    if not msg:
        return self._send(400, json.dumps({"error": "message required"}))
    # INLINE REPLY from the wrist (one-inbox decree). The watch now shows
    # MIRRORED card questions in the Henry transcript, and tapping one of a
    # card's options has to reach THAT card - without this it would arrive as a
    # bare "A" in Henry's advisory session, which cannot settle the question and
    # reads to Henry as a non-sequitur, while the card goes on waiting.
    #
    # This is the one thing the watch sends that is NOT advisory, and it is the
    # same exception §4.7 of the Wear study already carved out for
    # /glance/answer: a structured answer to a question the worker itself asked
    # is a decision, not the free-text authorship that stays off a wearable.
    reply_to = str(body.get("reply_to_card") or "").strip()
    if reply_to:
        from cells.engineer import sessions
        from spine.auth import auth
        from spine.http import server
        t = sessions.get_track(reply_to)
        if not t:
            return self._send(404, json.dumps({"error": "no such card"}))
        if not auth.owns_card(user, t):
            return self._send(403, json.dumps({"error": "not your card"}))
        actor = user["name"]
        routed, answers, rid = sessions.reply_door(t, msg)
        if routed == "answer":
            server._bg("track:answer:" + reply_to, lambda: sessions.answer_question(
                reply_to, answers, request_id=rid, actor=actor))
        else:
            server._bg("track:steer:" + reply_to,
                       lambda: sessions.steer(reply_to, msg, actor=actor))
        # No voice clip and no Henry turn: nothing was said TO the owner here.
        # The card's own answer comes back as a mirrored result on the next
        # /wear/chat poll, which is the surface he is already looking at.
        return self._send(200, json.dumps(
            {"reply": "", "question": None, "refused": [],
             "routed": {"card": reply_to, "as": routed}}))
    from cells.copilot import copilot
    try:
        out = copilot.chat(user["name"], msg, role=user["role"],
                           allow_actions=False, extra_system=WEAR_BRIEF,
                           # This response IS the delivery: the reply comes back
                           # in `resp` below and is ALWAYS spoken (see the voice
                           # note further down). A notification would buzz the
                           # wrist about the sentence it is reading out loud.
                           # The phone door needs no such flag - its app reports
                           # presence and suppresses itself.
                           announce=False,
                           # optional: CardScreen passes the card the owner
                           # tapped into, so Henry's advice is scoped to it -
                           # chat_post already supports this same kwarg for
                           # the phone's own card-scoped Henry tab.
                           card=body.get("card"))
    except Exception as e:                       # noqa: BLE001
        return self._send(502, json.dumps({"error": str(e)[:200]}))
    reply = out.get("reply") or ""
    from spine.ops import ask
    from spine.ops.glances import _glance_question
    # copilot.chat now parses the block at EVENT TIME and hands back both halves
    # (`reply` already prose, `question` typed). Re-parsing a cleaned reply here
    # would find nothing and silently drop the watch's buttons, so prefer what
    # it computed; ask.parse stays the fallback for a reply that somehow still
    # carries a block, and is a no-op on one that does not.
    q, prose = out.get("question"), reply
    if not q:
        q, prose = ask.parse(reply)
    spoken = (prose or reply)[:600]
    resp = {
        # the prose WITHOUT the block - ask.parse already strips it, so the
        # watch renders `reply` as plain text and never sees raw JSON
        "reply": spoken,
        # the tappable half; None when the agent ignored the brief, which the
        # watch must show as a dead end rather than hide (same rule
        # glance_talk already applies for the glasses)
        "question": _glance_question({"question": q}) if q else None,
        "refused": out.get("refused") or [],
    }
    # ALWAYS render voice, no opt-in flag - unlike /chat (which has a screen
    # worth reading), the watch is a small round display with no keyboard;
    # there is no case where making the owner read Henry's reply there beats
    # hearing it. Same unconditional choice glance_talk already makes for
    # the glasses, for the identical reason.
    #
    # render_b64, NOT render()+a URL: the watch talks through the SEALED
    # RELAY (RelayClient.kt's authedCall), exactly like the phone's own
    # /chat - one JSON request/response, no second channel for a client to
    # fetch a binary from, and a URL pointing at localhost means nothing
    # across the internet anyway. voice.py's own docstring says this
    # explicitly for the phone; it applies to the watch for the identical
    # reason, not a new one.
    from spine.media import voice as _voice
    clip = _voice.render_b64(spoken)
    if clip:
        resp["voice"] = clip
    return self._send(200, json.dumps(resp))


GET_ROUTES = {"/wear/board": wear_board_get, "/wear/chat": wear_chat_get}
POST_ROUTES = {"/wear/talk": wear_talk_post}
