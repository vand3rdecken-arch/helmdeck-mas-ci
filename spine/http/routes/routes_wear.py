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


def wear_board_get(self, user):
    # Same bar as chat_post's own role check (routes_copilot.py) - a `client`
    # role has no board-wide view to be shown here, on any surface.
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    from cells.engineer import sessions
    from spine.storage import events
    from spine.ops.glances import glance_payload
    tracks = sessions.list_tracks()
    return self._send(200, json.dumps(
        glance_payload(tracks, events.metrics(tracks))))


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
    msgs = (copilot.history(user["name"]) or {}).get("messages") or []
    out = []
    for m in msgs:
        cls = (m or {}).get("cls") or ""
        if cls not in ("you", "bot", "error"):
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
        out.append({"mine": cls == "you", "text": text[:WEAR_CHAT_LINE_MAX],
                    "ts": (m or {}).get("ts") or ""})
    return self._send(200, json.dumps({"messages": out[-WEAR_CHAT_MAX:]}))


def wear_talk_post(self, user, body):
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    msg = (body.get("message") or "").strip()[:400]
    if not msg:
        return self._send(400, json.dumps({"error": "message required"}))
    from cells.copilot import copilot
    try:
        out = copilot.chat(user["name"], msg, role=user["role"],
                           allow_actions=False, extra_system=WEAR_BRIEF,
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
