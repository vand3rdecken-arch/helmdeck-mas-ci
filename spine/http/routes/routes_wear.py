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
    return self._send(200, json.dumps({
        # the prose WITHOUT the block - ask.parse already strips it, so the
        # watch renders `reply` as plain text and never sees raw JSON
        "reply": (prose or reply)[:600],
        # the tappable half; None when the agent ignored the brief, which the
        # watch must show as a dead end rather than hide (same rule
        # glance_talk already applies for the glasses)
        "question": _glance_question({"question": q}) if q else None,
        "refused": out.get("refused") or [],
    }))


GET_ROUTES = {"/wear/board": wear_board_get}
POST_ROUTES = {"/wear/talk": wear_talk_post}
