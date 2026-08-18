# -*- coding: utf-8 -*-
"""Glasses (Meta Ray-Ban Display) routes - fourth slice of server.py's
dispatch-table split (see routes_auth.py for the pattern/rationale). All four
are token-gated (settings.glance_token), not session-cookie-coupled - the lens
authenticates with a single shared secret, not a login. GET /glance (the
board-state read, via glances.glance_payload), GET /glance/voice/<id>.mp3 (the
agent's answer as speech), POST /glance/talk (ADVISORY chat with the board
copilot - allow_actions=False, never touches the board), POST /glance/answer
(the lens's ONLY write - picks among options the worker itself offered).
Bodies are byte-identical to the inline blocks they replace. `_glance_question`
comes from glances.py (already a real module); `_bg` (background-job runner)
stays in server.py since it shares _ctl_lock/_ctl state with many other
routes - reached via a lazy `import server` (no cycle: resolved at call time).
"""
import json
from urllib.parse import parse_qs, quote, urlparse

from glances import glance_payload, _glance_question

GLASS_BRIEF = (
    "SURFACE: you are being read on Meta Ray-Ban DISPLAY GLASSES, not the phone.\n"
    "- The lens is 600x600 and shows ONE thing at a time. Keep the prose to at "
    "most 2 short sentences - what is true right now, and what you would do. No "
    "lists, no markdown, no headings.\n"
    "- The owner CANNOT TYPE and CANNOT DICTATE here. Tapping an option is his "
    "only input. So you MUST end every reply with a <helmdeck-ask> block "
    "offering 2-6 next moves, exactly as a card worker would:\n"
    "<helmdeck-ask>\n"
    '{"questions": [{"question": "<what to do next>", "header": "<max 24 chars>", '
    '"options": [{"label": "<short>", "description": "<what it means>"}]}]}\n'
    "</helmdeck-ask>\n"
    "Ending without that block strands him - it is a defect, not a hand-off. "
    "Always include a way to go wider (e.g. 'Something else') so a wrong guess "
    "is never a trap.\n"
    "- This surface is ADVISORY: any actions block you emit is DROPPED, not run. "
    "Never claim you changed the board. To actually move work, offer it as an "
    "option and say it will run from the phone."
)


def glance_voice(self, user):
    # The agent's answer as SPEECH. Same token as /glance; serving a
    # rendered mp3 is strictly less than what /glance already hands
    # out (it IS the same sentence, spoken), so it needs no extra
    # switch. The id is a content hash minted by voice.render, and
    # voice.path_for refuses anything that is not exactly that shape
    # - the URL must never become a file-read primitive.
    import events, voice
    p = self.path.split("?")[0]
    tok = events.settings().get("glance_token") or ""
    given = (parse_qs(urlparse(self.path).query).get("token") or [""])[0]
    if not tok or given != tok:
        return self._send(403, json.dumps({"error": "glance disabled or bad token"}))
    vid = p.rsplit("/", 1)[-1][:-4] if p.endswith(".mp3") else ""
    fp = voice.path_for(vid)
    if not fp:
        return self._send(404, json.dumps({"error": "no such clip"}))
    data = open(fp, "rb").read()
    self.send_response(200)
    self.send_header("Content-Type", "audio/mpeg")
    self.send_header("Content-Length", str(len(data)))
    self.send_header("Access-Control-Allow-Origin", "*")
    # content-addressed: the id changes when the words change, so it
    # can be cached hard and never go stale
    self.send_header("Cache-Control", "public, max-age=86400")
    self.end_headers()
    self.wfile.write(data)


def glance_get(self, user):
    # glance surface for the Meta Ray-Ban Display webapp (glasses/).
    # Token-gated, cross-origin (CORS on via _send), no session-
    # cookie coupling. Off unless settings.glance_token is set.
    # READS here; the one write is POST /glance/answer, which is
    # separately gated by settings.glance_decide - see there.
    import events, sessions
    tok = events.settings().get("glance_token") or ""
    given = (parse_qs(urlparse(self.path).query).get("token") or [""])[0]
    if not tok or given != tok:
        return self._send(403, json.dumps({"error": "glance disabled or bad token"}))
    # ONE read of the board for both halves - two list_tracks() calls
    # could straddle a write and report a count that disagrees with
    # the list underneath it.
    tracks = sessions.list_tracks()
    return self._send(200, json.dumps(
        glance_payload(tracks, events.metrics(tracks))))


def glance_talk(self, user, body):
    # GLASS MODE conversation with the BOARD AGENT itself - the half
    # /glance cannot be: /glance is a database read (owner_blockers +
    # metrics), so it can only ever show WHAT is stuck, never reason
    # about it. This routes a message to copilot.chat, the same agent
    # the board chat uses, with the live board snapshot it always
    # gets.
    #
    # ADVISORY, enforced in copilot.chat rather than requested in the
    # prompt: allow_actions=False drops every board action, because
    # this surface authenticates with one SHARED token and
    # _run_action reaches machine_task (the whole PC), delete and
    # steer. Refused types come back and are surfaced, so the lens
    # can never report a change that did not happen.
    #
    # Its own switch, not glance_decide: this SPENDS PLAN QUOTA on
    # every tap, which is a different thing to consent to than
    # answering a question a worker already asked.
    import ask, events
    s = events.settings()
    tok = s.get("glance_token") or ""
    given = (body.get("token") or "").strip() or \
        (parse_qs(urlparse(self.path).query).get("token") or [""])[0]
    if not tok or given != tok:
        return self._send(403, json.dumps(
            {"error": "glance disabled or bad token"}))
    if not s.get("glance_talk"):
        return self._send(403, json.dumps(
            {"error": "talking to the board agent from the glasses is "
                      "off (set settings.glance_talk)"}))
    msg = (body.get("message") or "").strip()[:400]
    if not msg:
        return self._send(400, json.dumps({"error": "message required"}))
    import copilot
    try:
        out = copilot.chat("owner", msg, role="owner",
                           allow_actions=False, extra_system=GLASS_BRIEF)
    except Exception as e:                       # noqa: BLE001
        return self._send(502, json.dumps({"error": str(e)[:200]}))
    reply = out.get("reply") or ""
    q, prose = ask.parse(reply)
    spoken = (prose or reply)[:600]
    # SPEAK it. The lens has no speechSynthesis but plays audio, so
    # the answer is rendered here and played there (voice.py). Only
    # the prose is spoken - reading six option labels aloud is
    # slower than glancing at them, and the options are the one part
    # the display is genuinely good at.
    import voice
    vid = voice.render(spoken)
    return self._send(200, json.dumps({
        # the prose WITHOUT the block - ask.parse already strips it
        "reply": spoken,
        # the tappable half; None when the agent ignored the brief,
        # which the lens must show as a dead end rather than hide
        "question": _glance_question({"question": q}) if q else None,
        "refused": out.get("refused") or [],
        # None when speech is unavailable (offline, no edge-tts) -
        # the lens then simply shows the text, never an error
        "voice": ("/glance/voice/%s.mp3?token=%s" % (vid, quote(given)))
                 if vid else None}))


def glance_answer(self, user, body):
    # GLASS MODE's ONLY write. The lens taps one of the options the
    # worker itself offered and the card's session continues - the
    # exact path /tracks/<id>/answer takes, so there is no second
    # answering mechanism to drift out of sync with the first.
    #
    # Before the user gate because the lens carries a token, not a
    # session. Four deliberate bounds, because glance_token is a
    # single SHARED secret and this endpoint RUNS AN AGENT TURN:
    #   1. off unless settings.glance_decide is explicitly true, so
    #      an existing read-only glance token does not silently
    #      become one that can steer agents;
    #   2. FREE TEXT REFUSED here (the phone keeps it) - a shared
    #      token must never inject arbitrary prose into a worker's
    #      next prompt, and the lens cannot type anyway;
    #   3. request_id must match the card's CURRENT question, so a
    #      lens showing a stale screen cannot answer a question the
    #      card has already moved past;
    #   4. it can only ever pick among options the WORKER wrote.
    import ask, events, sessions
    s = events.settings()
    tok = s.get("glance_token") or ""
    given = (body.get("token") or "").strip() or \
        (parse_qs(urlparse(self.path).query).get("token") or [""])[0]
    if not tok or given != tok:
        return self._send(403, json.dumps(
            {"error": "glance disabled or bad token"}))
    if not s.get("glance_decide"):
        return self._send(403, json.dumps(
            {"error": "deciding from the glasses is off "
                      "(set settings.glance_decide)"}))
    tid = (body.get("id") or "").strip()
    t = sessions.get_track(tid) if tid else None
    if not t or not t.get("question"):
        return self._send(409, json.dumps({"error": "no pending question"}))
    rid = (body.get("request_id") or "").strip()
    if rid != ((t["question"] or {}).get("id") or ""):
        return self._send(409, json.dumps(
            {"error": "this question was already answered or replaced"}))
    picks, err = ask.validate_answers(t["question"], body.get("answers") or {})
    if err:
        return self._send(400, json.dumps({"error": err}))
    if any(pick.get("custom") for pick in picks):
        return self._send(400, json.dumps(
            {"error": "the glasses may only pick offered options"}))
    answers = body.get("answers") or {}
    import server
    server._bg("track:answer:" + tid, lambda: sessions.answer_question(
        tid, answers, request_id=rid, actor="glasses"))
    return self._send(200, json.dumps({"started": tid, "answered": True}))


# GET_PREFIX_ROUTES: (prefix, handler) pairs checked BEFORE the exact-match
# dicts, since /glance/voice/<id>.mp3 has a variable tail. Order matters only
# in that a prefix must be checked before any exact match it could shadow -
# none here do.
GET_PREFIX_ROUTES = [
    ("/glance/voice/", glance_voice),
]
GET_ROUTES = {
    "/glance": glance_get,
}
POST_ROUTES = {
    "/glance/talk": glance_talk,
    "/glance/answer": glance_answer,
}
