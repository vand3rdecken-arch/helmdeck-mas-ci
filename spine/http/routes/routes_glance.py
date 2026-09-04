# -*- coding: utf-8 -*-
"""Glasses (Meta Ray-Ban Display) routes - fourth slice of server.py's
dispatch-table split (see routes_auth.py for the pattern/rationale). All five
are token-gated (settings.glance_token), not session-cookie-coupled - the lens
authenticates with a single shared secret, not a login. GET /glance (the
board-state read, via glances.glance_payload), GET /glance/voice/<id>.mp3 (the
agent's answer as speech), GET /glance/banner (a fresh-blocker count as
speech, for the on-lens mute/repeat controls - see glance_banner_voice), POST
/glance/talk (ADVISORY chat with the board copilot - allow_actions=False,
never touches the board), POST /glance/answer (picks among options the worker
itself offered), POST /glance/photo (a DAT camera frame attached to a named
card - its own switch, see there). Bodies are byte-identical to the inline
blocks they replace. `_glance_question` comes from glances.py (already
a real module); `_bg` (background-job runner) stays in server.py since it
shares _ctl_lock/_ctl state with many other routes - reached via a lazy
`import server` (no cycle: resolved at call time).
"""
import json
from urllib.parse import parse_qs, quote, urlparse

from spine.ops.glances import glance_payload, _glance_question

# The text moved to ops/harness/agents/glass-brief.md (harness-config-ui phase
# 2) - policy, not mechanism, and until now one of the seven prose sources the
# owner could not see. The lens facts and the ADVISORY clause stay verbatim;
# only the length law became a slot.
def glass_brief(project=""):
    from spine.registry import harness
    return harness.brief("glass-brief", project=project)


def glance_voice(self, user):
    # The agent's answer as SPEECH. Same token as /glance; serving a
    # rendered mp3 is strictly less than what /glance already hands
    # out (it IS the same sentence, spoken), so it needs no extra
    # switch. The id is a content hash minted by voice.render, and
    # voice.path_for refuses anything that is not exactly that shape
    # - the URL must never become a file-read primitive.
    from spine.storage import events
    from spine.media import voice
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


def glance_banner_voice(self, user):
    # A fresh-blocker COUNT as speech, for the lens's proactive banner
    # (app.js notifyBanner/speakBanner) - the in-app half of "Blocker werden
    # vorgelesen" (ops/docs/glasses-reference.md SS4.6/SS11.6: the webview has no
    # speechSynthesis but plays audio, so the daemon renders and the lens
    # plays a clip URL, exactly the shape /glance/talk already returns).
    #
    # GLANCE-SAFE BY CONSTRUCTION (SS4.4/SS11.3): this endpoint only ever
    # speaks a NUMBER, never a task name or client - a bystander overhearing
    # the lens learns nothing. `n` is supplied by the caller (app.js already
    # computes "how many are new since I last looked"; the daemon has no way
    # to know that without per-client state) and is clamped hard so a bad
    # value can only ever change which small integer gets read aloud, never
    # inject arbitrary text into edge-tts.
    #
    # Same token as /glance, no extra switch - identical rationale to
    # glance_voice: speaking a count is strictly less than /glance's
    # needs_you list already hands out in plain JSON.
    from spine.storage import events
    from spine.media import voice
    tok = events.settings().get("glance_token") or ""
    q = parse_qs(urlparse(self.path).query)
    given = (q.get("token") or [""])[0]
    if not tok or given != tok:
        return self._send(403, json.dumps({"error": "glance disabled or bad token"}))
    try:
        n = int((q.get("n") or ["1"])[0])
    except ValueError:
        n = 1
    n = max(1, min(99, n))
    phrase = "1 new card needs you." if n == 1 else ("%d new cards need you." % n)
    vid = voice.render(phrase)
    return self._send(200, json.dumps({
        # None when speech is unavailable (offline, no edge-tts) - the lens
        # then simply keeps its silent visual banner, never an error
        "voice": ("/glance/voice/%s.mp3?token=%s" % (vid, quote(given)))
                 if vid else None}))


def glance_get(self, user):
    # glance surface for the Meta Ray-Ban Display webapp (surfaces/glasses/).
    # Token-gated, cross-origin (CORS on via _send), no session-
    # cookie coupling. Off unless settings.glance_token is set.
    # READS here; the one write is POST /glance/answer, which is
    # separately gated by settings.glance_decide - see there.
    from spine.storage import events
    from cells.engineer.cards import sessions
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
    from spine.ops import ask
    from spine.storage import events
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
    from cells.copilot.chat import copilot
    from spine.ops import glassturn
    # THE TRANSCRIPT REACHES THE LENS HERE, at event time, from the one place
    # that observes it: the arrival of the words themselves.
    #
    # This is what makes the owner's own sentence visible on the display before
    # the answer exists - and it needs no support from the device, which matters
    # because the mic lives in a native service that ships on its own APK cycle.
    # Whatever spoke these words (the glasses mic, the phone mic, a D-pad tap on
    # the lens), they arrived, and that is a fact this process holds.
    #
    # `msg` AFTER the cap, not before: the lens must show what was actually sent
    # to Henry, not what the client offered. A transcript that disagreed with the
    # message would be a display lying about the thing it exists to show.
    glassturn.heard(msg)
    glassturn.thinking()
    try:
        out = copilot.chat("owner", msg, role="owner",
                           allow_actions=False, extra_system=glass_brief(),
                           # This response IS the delivery - the lens shows the
                           # reply and plays it aloud (below). Buzzing the phone
                           # about an answer already in the owner's ear is the
                           # noise that teaches him to mute the channel.
                           announce=False)
    except Exception as e:                       # noqa: BLE001
        # Never leave the lens on "thinking" after a turn that will not arrive -
        # a silent wait is the one thing the on-device UX laws forbid outright,
        # and "idle" would tell him his sentence was never heard when it was.
        glassturn.failed()
        return self._send(502, json.dumps({"error": str(e)[:200]}))
    reply = out.get("reply") or ""
    # copilot.chat parses the block at EVENT TIME and returns both halves, so
    # `reply` is already prose here; re-parsing it would find no question and
    # leave the lens with a dead end. Prefer the typed one, parse as a fallback.
    q, prose = out.get("question"), reply
    if not q:
        q, prose = ask.parse(reply)
    spoken = (prose or reply)[:600]
    # SPEAK it. The lens has no speechSynthesis but plays audio, so
    # the answer is rendered here and played there (voice.py). Only
    # the prose is spoken - reading six option labels aloud is
    # slower than glancing at them, and the options are the one part
    # the display is genuinely good at.
    from spine.media import voice
    vid = voice.render(spoken)
    # TERMINAL, and named for what was actually observed. Not "speaking": whether
    # the clip ever reached the owner's ear is something only the device learns,
    # and this process never does - see glassturn's module docstring. A
    # conversation that continues simply overwrites this with the next
    # `listening` the mic owner reports.
    #
    # The OPTIONS go with it, and that is not a convenience. On a spoken turn
    # this POST comes from GlassVoiceService on the PHONE, so the lens never sees
    # the response below - publishing the tappable half only there would leave
    # every voice turn optionless on the one surface that cannot type. Same
    # object as the response carries, computed once.
    lens_q = _glance_question({"question": q}) if q else None
    glassturn.answered(question=lens_q)
    return self._send(200, json.dumps({
        # the prose WITHOUT the block - ask.parse already strips it
        "reply": spoken,
        # the tappable half; None when the agent ignored the brief,
        # which the lens must show as a dead end rather than hide
        "question": lens_q,
        "refused": out.get("refused") or [],
        # None when speech is unavailable (offline, no edge-tts) -
        # the lens then simply shows the text, never an error
        "voice": ("/glance/voice/%s.mp3?token=%s" % (vid, quote(given)))
                 if vid else None}))


# How much of the ONE Henry conversation the lens may pull, and how much of any
# single line. The wrist dropped its per-line cap by owner decree ("kein Zeichen
# cap") because a watch scrolls freely; the lens is a 600x600 additive display
# where a long paragraph pushes the live turn state off the screen, and the state
# is the thing this surface exists to show. GLASS_BRIEF already holds Henry to
# two sentences, so this only ever bites on a MIRRORED card line, which the lens
# shows as context rather than as something to read in full - the card's own text
# is one tap away on the needs list.
GLASS_CHAT_MAX = 12
GLASS_CHAT_LINE = 400

# How long the lens's hanging read may block before answering with "nothing
# moved". Comfortably inside the Cloudflare Worker's patience in front of it,
# and matched by db.wait_glass's own default.
GLASS_WAIT_S = 20


def glance_chat(self, user):
    """THE ONE CONVERSATION, as the lens reads it - plus the live state of the
    turn happening right now.

    WHY THIS EXISTS. The glasses voice loop already worked and already went to
    Henry: GlassVoiceService opens the glasses mic, hands the recognised words to
    POST /glance/talk, and that calls the SAME copilot.chat session the phone and
    the watch use. What was missing was the lens's half - it never saw any of it.
    It could not show that a mic was open, it never showed the words about to be
    sent in the owner's name, and its own talk screen held exactly one reply with
    no memory of the exchange it belonged to.

    So this is deliberately NOT a new channel. It is the read side of the
    conversation that already exists, shaped for the lens - the same thing
    wear_chat_get is for the watch, and it reads the same copilot.history() for
    the same reason: one Henry, many windows onto him, never a per-surface
    transcript that can drift.

    A HANGING GET, not a poll. The platform guidance the glasses app already
    follows is emphatic about idle timers ("start them on demand, stop them when
    not visible"), and the reference doc's factory rule from the owner's earlier
    glasses project is blunter still: never ship a fast poll. A conversation
    needs sub-second feedback, and a poll fast enough to feel live would be a
    battery fire on a headset. So the lens holds ONE request that transmits
    nothing until the transcript or the turn state actually moves - exactly the
    shape the watch was moved to on 2026-08-30 ("einheitlich wie Paseo, kein
    Polling").

    Both cursors ride in and out. A client that sends neither (or 0) is answered
    immediately, which is what makes the first load fast and what lets a
    reconnect catch up without a special case: it always compares the numbers it
    gets back against the ones it sent.
    """
    from spine.storage import events, db
    from spine.ops import glassturn
    tok = events.settings().get("glance_token") or ""
    q = parse_qs(urlparse(self.path).query)
    given = (q.get("token") or [""])[0]
    if not tok or given != tok:
        return self._send(403, json.dumps({"error": "glance disabled or bad token"}))

    def _cursor(name):
        # None means "I have nothing" - ABSENT and ZERO are deliberately not the
        # same thing, and conflating them is a real bug this test caught on its
        # first run. On a freshly started daemon both counters ARE zero, so a
        # client sending c=0&g=0 is genuinely up to date and would correctly
        # block - leaving a first-time lens staring at an empty conversation for
        # the full wait, which is the silent wait the on-device UX laws forbid
        # outright. A client with no cursors yet says so by omitting them.
        #
        # A malformed value takes the same path rather than erroring: a lens
        # stuck retrying a 400 is worse than one that simply resynchronises, and
        # resynchronising is free.
        raw = (q.get(name) or [None])[0]
        if raw is None or raw == "":
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    c_last, g_last = _cursor("c"), _cursor("g")
    if c_last is None or g_last is None:
        c_now, g_now = db.current_chat_version(), db.current_glass_version()
    else:
        # Blocks only when the client is already up to date. wait_glass returns
        # the CURRENT pair either way, so a spurious or timed-out wake costs one
        # round trip and cannot lose an event.
        c_now, g_now = db.wait_glass(c_last, g_last, timeout=GLASS_WAIT_S)
    return self._send(200, json.dumps({
        "c": c_now, "g": g_now,
        # what is happening RIGHT NOW - the half the lens cannot derive
        "turn": glassturn.snapshot(),
        # ...and what has been said, which is durable and shared
        "messages": _glance_messages()}))


# The transcript classes the lens shows. Identical to the watch's allowlist
# (routes_wear.wear_chat_get) and for the identical reasons - "card" is the
# mirrored inbox, "pm" is Henry's proactive voice, "act" is the receipt proving a
# move ran. Dropping any of them here would give the glasses a conversation with
# a piece missing that every other surface can see, which is precisely the
# per-surface drift reading copilot.history() is meant to prevent.
_GLANCE_CLASSES = ("you", "bot", "error", "card", "pm", "act")

# What the lens calls a mirrored card event. The watch's own KIND_LABEL, in
# English because this surface is (GLASS_BRIEF, the nav bar and every other
# string here are too).
_GLANCE_KIND = {"question": "Question", "result": "Result", "blocker": "Blocker"}


def _glance_messages():
    """The tail of the owner's Henry transcript, trimmed for a 600x600 lens.

    Shared shaping (glances.readable) with the watch, so a reply that renders
    cleanly on the wrist cannot arrive here with literal '**' on it.

    A mirrored card line keeps its label ("Question - card name") and is shown as
    CONTEXT only: no options are rendered from here. Answering a card already has
    exactly one path on this surface - the decide screen, reached from the needs
    list and gated by settings.glance_decide - and offering a second one from the
    chat would be the drift /glance/answer's docstring exists to forbid.
    """
    from cells.copilot.chat import copilot
    from spine.ops.glances import readable
    msgs = (copilot.history("owner") or {}).get("messages") or []
    out = []
    for m in msgs:
        # The log is a FILE this only reads; a truncated write or a hand-edit can
        # leave anything in the array. Same guard wear_chat_get carries after a
        # string entry there cost the watch its whole transcript for one bad line.
        if not isinstance(m, dict):
            continue
        cls = m.get("cls") or ""
        if cls not in _GLANCE_CLASSES:
            continue
        text = readable(m.get("text") or "", GLASS_CHAT_LINE)
        if not text:
            continue
        row = {"mine": cls == "you", "text": text, "ts": m.get("ts") or ""}
        if cls == "card":
            kind = m.get("kind") or ""
            row["label"] = (_GLANCE_KIND.get(kind) or "Card") + " - " + \
                ((m.get("cardName") or m.get("card") or "")[:40])
        out.append(row)
    return out[-GLASS_CHAT_MAX:]


# What a client holding the SHARED glance token may assert about the turn.
#
# Deliberately just the two states that party actually OBSERVES: it owns the
# microphone, so it alone knows the mic opened and alone knows it closed without
# words. Everything else - heard, thinking, answered, failed - is set by the
# daemon from its own request handling and can never be claimed from outside. A
# token that could assert "answered" could paint a reply state the owner never
# got, which is the one lie this whole surface is being built to remove.
_CLIENT_STATES = ("listening", "idle", "draft")


def glance_state(self, user, body):
    """The microphone's own report - the ONE signal the daemon cannot observe.

    GlassVoiceService is the only party that knows a mic is open: it opens it.
    Everything else about a glasses turn happens inside this process (the words
    arrive at /glance/talk, Henry is called here, the answer is rendered here),
    so this endpoint is small on purpose - it carries exactly the fact that has
    no other route into the daemon, and nothing else.

    Gated by settings.glance_talk, the same switch the conversation itself is
    behind: if the lens may not talk to Henry, a listening indicator for a
    conversation that cannot happen is noise. No NEW consent is asked for, and
    none is bypassed.
    """
    from spine.storage import events
    from spine.ops import glassturn
    s = events.settings()
    tok = s.get("glance_token") or ""
    given = (body.get("token") or "").strip() or \
        (parse_qs(urlparse(self.path).query).get("token") or [""])[0]
    if not tok or given != tok:
        return self._send(403, json.dumps({"error": "glance disabled or bad token"}))
    if not s.get("glance_talk"):
        return self._send(403, json.dumps(
            {"error": "talking to the board agent from the glasses is "
                      "off (set settings.glance_talk)"}))
    state = (body.get("state") or "").strip()
    if state not in _CLIENT_STATES:
        # Name what IS allowed. A native client debugging a typo against a bare
        # 400 learns nothing, and this one cannot be stepped through easily.
        return self._send(400, json.dumps(
            {"error": "state must be one of %s" % (", ".join(_CLIENT_STATES),)}))
    mic = (body.get("mic") or "").strip()
    if state == "listening":
        glassturn.listening(mic=mic, text=body.get("text") or "")
    elif state == "draft":
        # WORDS, not yet sent. The seq goes back in the response because the
        # caller's next move is to wait on THIS draft (GET /glance/decision) and
        # a wait addressed to "whatever is current" is the stale-tap bug in
        # another costume.
        text = (body.get("text") or "").strip()
        if not text:
            return self._send(400, json.dumps({"error": "draft needs text"}))
        return self._send(200, json.dumps(
            {"ok": True, "seq": glassturn.draft(text, mic=mic)}))
    else:
        glassturn.idle(mic=mic)
    return self._send(200, json.dumps({"ok": True}))


def glance_decide(self, user, body):
    """The owner ruled on the draft, from the lens.

    Separate from /glance/state because the DIRECTION is the opposite one: state
    is the device telling the daemon what it observed, this is the owner telling
    the device what to do. Collapsing them would put "what happened" and "what
    should happen" behind one verb, and the lens would be able to fake a
    microphone report.

    A stale or unaddressed verdict is answered 409 rather than 200, so the lens
    can say "das war ein alter Entwurf" instead of leaving the owner to wonder
    why his tap did nothing.
    """
    from spine.storage import events
    from spine.ops import glassturn
    s = events.settings()
    tok = s.get("glance_token") or ""
    given = (body.get("token") or "").strip() or \
        (parse_qs(urlparse(self.path).query).get("token") or [""])[0]
    if not tok or given != tok:
        return self._send(403, json.dumps({"error": "glance disabled or bad token"}))
    if not s.get("glance_talk"):
        return self._send(403, json.dumps(
            {"error": "talking to the board agent from the glasses is "
                      "off (set settings.glance_talk)"}))
    value = (body.get("decision") or "").strip()
    if value not in glassturn.DECISIONS:
        return self._send(400, json.dumps(
            {"error": "decision must be one of %s" % (", ".join(glassturn.DECISIONS),)}))
    try:
        seq = int(body.get("seq") or 0)
    except (TypeError, ValueError):
        seq = 0
    if not glassturn.decide(value, seq=seq):
        return self._send(409, json.dumps(
            {"error": "no live draft for that seq"}))
    return self._send(200, json.dumps({"ok": True, "decision": value}))


def glance_decision(self, user):
    """The mic owner waits here for the verdict on its draft. LONG-POLL.

    Held open rather than polled for the reason glassturn.await_decision states:
    the waiting party is a foreground service on a phone and the daemon already
    owns the event that ends the wait. Bounded by glassturn.DECIDE_WAIT_S, and
    the timeout answer is an empty decision - never a send. Nothing is ever
    spoken in the owner's name because a request expired.
    """
    from spine.storage import events
    from spine.ops import glassturn
    s = events.settings()
    q = parse_qs(urlparse(self.path).query)
    tok = s.get("glance_token") or ""
    given = (q.get("token") or [""])[0]
    if not tok or given != tok:
        return self._send(403, json.dumps({"error": "glance disabled or bad token"}))
    if not s.get("glance_talk"):
        return self._send(403, json.dumps(
            {"error": "talking to the board agent from the glasses is "
                      "off (set settings.glance_talk)"}))
    try:
        seq = int((q.get("seq") or ["0"])[0])
    except (TypeError, ValueError):
        seq = 0
    if seq <= 0:
        return self._send(400, json.dumps({"error": "seq required"}))
    return self._send(200, json.dumps(
        {"decision": glassturn.await_decision(seq)}))


def glance_photo(self, user, body):
    # THE GLASSES CAMERA's landing point - the daemon half of
    # app/plugins/metadat/GlassCameraService.kt, which captures one frame over
    # DAT and POSTs it here as base64. Until this existed the Kotlin's contract
    # was named but unserved, so a successful capture ended in a 404.
    #
    # ITS OWN SWITCH, default OFF, and this is the least negotiable one in the
    # file. glance_token gates READING the board; glance_talk gates SPENDING
    # QUOTA; this gates A CAMERA ON THE OWNER'S FACE uploading what he is
    # looking at. Reusing an existing switch would mean a token minted to read
    # a blocker list silently became one that can pull frames from a room. It
    # is a different thing to consent to, so it is a different flag.
    #
    # THE CARD ID IS REQUIRED, not guessed. The tempting default - "attach it
    # to whatever the owner is focused on" - is exactly the assumed,
    # reconstructed state CLAUDE.md's no-monkey-patches law forbids: presence
    # is a heuristic, and silently attaching a photo of the owner's room to the
    # WRONG card is unrecoverable in a way a 400 is not. The lens knows which
    # card is on screen; it says so.
    from spine.storage import events
    from cells.engineer.cards import sessions
    s = events.settings()
    tok = s.get("glance_token") or ""
    given = (body.get("token") or "").strip() or \
        (parse_qs(urlparse(self.path).query).get("token") or [""])[0]
    if not tok or given != tok:
        return self._send(403, json.dumps(
            {"error": "glance disabled or bad token"}))
    if not s.get("glance_photo"):
        return self._send(403, json.dumps(
            {"error": "sending photos from the glasses is off "
                      "(set settings.glance_photo)"}))
    # REQUEST SHAPE FIRST, STORAGE SECOND. Every check below is a string test
    # on data already in hand; the card lookup touches the track store. Doing
    # the cheap ones first means a malformed or oversized upload is rejected
    # without a read, and - the reason that matters - a 12 MB payload never
    # gets as far as a lookup it was always going to fail.
    tid = (body.get("id") or "").strip()
    if not tid:
        return self._send(400, json.dumps({"error": "card id required"}))
    b64 = (body.get("b64") or "").strip()
    if not b64:
        return self._send(400, json.dumps({"error": "b64 required"}))
    # Cheap pre-check on the ENCODED length before decoding: base64 is 4/3 of
    # the payload, and refusing early means a runaway upload never becomes a
    # decoded blob in memory. save_attachments caps the decoded size too.
    if len(b64) > 12_000_000:
        return self._send(413, json.dumps({"error": "photo too large"}))
    t = sessions.get_track(tid)
    if not t:
        return self._send(409, json.dumps({"error": "no such card"}))
    mime = (body.get("mime") or "image/jpeg").strip().lower()
    ext = "heic" if "heic" in mime else "jpg"
    # A capture is identified by WHEN it was taken, which is the only thing the
    # owner can correlate it to later. Sub-second so a burst cannot collide.
    import time as _t
    name = _t.strftime("glasses-%Y%m%d-%H%M%S", _t.localtime()) + ".%s" % ext
    try:
        from cells.engineer.cards import cardadmin
        cardadmin.add_attachments(
            tid, [{"name": name, "data": b64, "mime": mime}], actor="glasses")
    except Exception as e:                       # noqa: BLE001
        return self._send(500, json.dumps({"error": str(e)[:200]}))
    return self._send(200, json.dumps({"attached": name, "id": tid}))


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
    from spine.ops import ask
    from spine.storage import events
    from cells.engineer.cards import sessions
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
    from spine.http import server
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
    "/glance/banner": glance_banner_voice,
    "/glance/chat": glance_chat,
    "/glance/decision": glance_decision,
}
POST_ROUTES = {
    "/glance/talk": glance_talk,
    "/glance/answer": glance_answer,
    "/glance/photo": glance_photo,
    "/glance/state": glance_state,
    "/glance/decide": glance_decide,
}
