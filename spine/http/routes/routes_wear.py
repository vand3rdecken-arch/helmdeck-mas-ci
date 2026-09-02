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

POST /wear/talk mirrors routes_glance.py's glance_talk for the RENDERING
half (the same ask.parse() extraction so the CLIENT never has to parse a
<helmdeck-ask> block itself) but NOT for authority. Owner decree 2026-08-29
("one single source of truth, watch or phone") supersedes the §4.7
advisory-only rule for the WATCH: the watch authenticates as a real
per-device client, exactly like the phone, so a board action Henry emits
here runs on the same rails as the phone's /chat - the same copilot.chat
allow_actions=True path, the same chat_dedupe idempotency claim. The
§4.7 rule stays TRUE where it came from: routes_glance.py keeps
allow_actions=False, because the glasses authenticate with one shared
glance_token, not a user session - that boundary was the reason for the
rule, and the watch was never on the wrong side of it.

GET /wear/voice is the SPOKEN half of the transcript, and it exists because
POST /wear/talk's inline clip only ever covered ONE of the ways a Henry answer
reaches the wrist (owner, 2026-09-02: "Stimme aktivieren ist ziemlich broken").
An answer that outlives talk()'s HTTP request, an answer to a turn started on
the PHONE or the GLASSES, an answer that lands while the display is off - all
three arrive over /wear/chat, which carried no audio at all. See
ops/docs/backlog/wear-voice-stream-playback/README.md.

PULL, not push, and that was measured rather than preferred: the alternative
was carrying the clip on the /stream/wait event, but that cursor is SHARED with
the phone, the desktop and the glasses (one hanging GET for the whole fleet), so
a clip on it would ship a base64 mp3 to every client on every chat event and
force a TTS render - a network round trip to Microsoft's voice service, per
reply - even when nothing on the owner's wrist is listening. Pulling renders
exactly when a watch has voice switched ON and exactly once per answer.
"""
import hashlib
import json

# Wear OS quality bar (README.md §7.2): fits a 192dp circle, no keyboard,
# tap-to-answer or dictation only - the same CLASS of constraint GLASS_BRIEF
# encodes for the glasses, but this is a DIFFERENT device (no
# speechSynthesis-less-webview quirks, no lens-specific facts), so it gets
# its own text rather than reusing GLASS_BRIEF's glasses-specific claims
# verbatim.
# The text moved to ops/harness/agents/wear-brief.md (harness-config-ui phase
# 2): it is policy, not mechanism, and as a constant it was invisible to the
# owner and unreachable by the /harness editor. The length law is a rendered
# slot there, so the watch can be terser than the chat without either number
# being buried in Python.
def wear_brief(project=""):
    from spine.registry import harness
    return harness.brief("wear-brief", project=project)


# Per-section cap. The wrist is a triage surface, not a backlog reader; the
# totals ride alongside so "3 von 12" stays honest without sending 12 rows.
WEAR_LIST_MAX = 5

# NO body cap (owner decree 2026-08-29, second half of "one single source of
# truth": "kein Zeichen cap"). This walked 700 -> 1200 -> gone, each step after
# the owner read a real turn report on the watch and found it cut ("Message
# abgeschnitten"): a DELIVERED summary is the thing he opens a card to read,
# and any bound loses it mid-thought eventually. The CARD SCREEN scrolls
# (TransformingLazyColumn); scrolling costs him a flick, a missing half costs
# him the answer. The payload stays bounded upstream anyway - `last_reply` is
# storage-capped and the board lists at most WEAR_LIST_MAX rows per section.
WEAR_BODY_MAX = None

# The `detail` line the watch shows above the body. Same number glance_payload
# already caps it at, so this only ever re-cuts text that arrived at the wall.
WEAR_DETAIL_MAX = 160

# THE WRIST-TEXT POLICY NOW LIVES IN spine/ops/glances.py, and these three names
# are thin aliases onto it.
#
# It moved when the GLASSES gained a transcript of their own (routes_glance
# glance_chat). The comment further down this file - "One wrist-text policy, one
# function" - was written after /wear/board and /wear/chat had drifted into two
# clip rules and the weaker one shipped markdown to the watch. Letting the lens
# grow a third copy would have been that same defect one surface wider, and the
# failure mode is silent: the watch renders a reply cleanly, the glasses render
# the SAME reply with literal '**' on it, and nothing errors.
#
# Aliased rather than renamed at the call sites so this file's behaviour and its
# spelling are unchanged - ops/tests/test_wear_card_body.py drives W._wear_text
# and W._wear_clip directly and still does.
from spine.ops.glances import clip_text as _wear_clip
from spine.ops.glances import readable as _glances_readable
from spine.ops.glances import _MD_MARKS as _WEAR_MD          # noqa: F401  (kept for callers/tests)


def _wear_text(raw, cap=WEAR_BODY_MAX):
    """A card's own prose, made readable on a wrist.

    The wrist's default cap is WEAR_BODY_MAX; the shared implementation defaults
    to None. That difference is the whole reason this wrapper still exists -
    every existing caller here relies on the wrist default being applied when it
    passes no cap at all."""
    return _glances_readable(raw, cap)


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
# Per-line cap for the scrollback: NONE (same decree as WEAR_BODY_MAX). The
# old 240 meant a watch-read conversation and a phone-read one disagreed about
# what was said - the exact discrepancy the one-source-of-truth decree closes.
# _wear_text still strips ask-blocks, fences and markdown; only the CUT is gone.
WEAR_CHAT_LINE_MAX = None

# WHICH transcript lines the watch may SPEAK. Henry's own voice only: "bot" is
# his answer to a question and "pm" is his proactive half (lane outcomes, broker
# decisions, alerts) - both are him talking to the owner.
#
# Deliberately NOT "card": a mirrored card event is a whole brief with tappable
# options, and reading one aloud is exactly the podcast WEAR_VOICE_MAX exists to
# prevent - it is news to LOOK at, and it already buzzes the wrist as a push.
# Not "act" either (an action receipt is chrome), and not "error" (the text is
# on the screen he is holding up).
WEAR_SPEAK_CLS = ("bot", "pm")

# The spoken bound, ONE owner for both voice paths. ~45s of TTS; past that a
# clip is a podcast, and the full text is on the screen he is looking at.
WEAR_VOICE_MAX = 600


def _wear_msg_key(m):
    """A transcript line's IDENTITY - the one question the watch has to answer
    before speaking: "have I already played this?"

    DERIVED FROM THE LINE, because there is nothing else to derive it from: the
    chat log carries no message id for a Henry line (copilot._append_log writes
    cls/text/ts/date, and client_msg_id lands only on the OWNER's entry - see
    ops/tests/test_chat_msg_identity.py). And an INDEX is not an identity here:
    _append_log trims to the last 80 entries on every write, so the same message
    changes index over its life and a client holding "index 7" would silently
    start comparing itself against a different line.

    Hashed over the STORED text, before any wrist rendering. /wear/chat strips
    markdown and ask-blocks out of it and /wear/voice speaks it; if the key were
    taken from either rendering, the two routes could disagree about the same
    line and the watch would speak an answer twice or never.

    Two byte-identical messages in the same MINUTE collapse to one key. That is
    honest rather than lossy: nothing on the wrist could tell them apart either.
    """
    m = m or {}
    raw = "%s|%s|%s|%s" % (m.get("cls") or "", m.get("date") or "",
                           m.get("ts") or "", m.get("text") or "")
    return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:16]


def _wear_newest_speakable(user, only=WEAR_SPEAK_CLS):
    """The newest line the watch could still be owed OUT LOUD, or None.

    NEWEST-ONLY is enforced HERE, on the server, and that is the point: the
    guardrail "never read the history back at him" is then a property of the
    route rather than a promise the watch makes. No reconnect, no retry and no
    client bug can turn this into a machine reciting yesterday's conversation,
    because there is no request that would render an older line.
    """
    from cells.copilot import copilot
    msgs = (copilot.history(user) or {}).get("messages") or []
    for m in reversed(msgs):
        # Same defensive read as wear_chat_get: the log is a FILE, and a
        # truncated write or a hand-edit can leave a non-dict in the array.
        if not isinstance(m, dict):
            continue
        if (m.get("cls") or "") not in only:
            continue
        if not (m.get("text") or "").strip():
            continue
        return m
    return None


# How much of a mirrored card's task line may become its TITLE on the wrist.
# Not None like the two above: those bound a message BODY, which scrolls, and
# this bounds a heading that sits in front of every card line. 42 (the push
# notification's notice.label) was too short to tell two cards apart - the
# owner photographed "Frage · UX-FIX (Owner-Besc hwerde 2026-08-30): Die…" and
# could not - and the raw task is a whole brief. See _wear_card_name.
WEAR_NAME_MAX = 90


def _wear_card_name(card_id, stored, cache):
    """A mirrored card's name for the wrist - its own task line, whole.

    `stored` is what card_mirror froze into the log entry (a 42-char
    notice.label with an "…"); it stays the fallback for a card that has since
    been deleted, because a line labelled with a short name still tells the
    owner WHICH card spoke, and a blank one does not.

    `cache` is a caller-owned dict so the track list is read at most ONCE per
    response no matter how many card lines the transcript carries - this route
    is called on every stream wake, and a per-line storage read would put the
    board's whole track list behind each one.
    """
    if not card_id:
        return stored
    if "by_id" not in cache:
        try:
            from cells.engineer import sessions
            cache["by_id"] = {t.get("id"): t for t in sessions.list_tracks() or ()}
        except Exception:                                   # noqa: BLE001
            cache["by_id"] = {}
    t = cache["by_id"].get(card_id) or {}
    task = (t.get("task") or "").replace("\r", "\n").split("\n")[0].strip()
    if not task:
        return stored
    # WIDER THAN THE NOTIFICATION, NOT UNBOUNDED. Measured on the owner's own
    # watch (Xiaomi Watch 5, 480x480 @320dpi = 240dp): the title renders about
    # ten characters per line, so notice.label's 42 already cost five lines -
    # and the cards in this repo carry whole briefs as their task text, one of
    # them 1500 characters. Sending the task WHOLE would have put a sixty-line
    # bold title in front of every mirrored question, which is a worse defect
    # than the one being fixed.
    #
    # No sentence heuristic: tried and rejected against the real transcript,
    # where "BUG: /compact bzw." named a card after an abbreviation.
    if len(task) <= WEAR_NAME_MAX:
        return task
    cut = task[:WEAR_NAME_MAX]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > WEAR_NAME_MAX // 2 else cut).rstrip(" ,.;:-") + "…"


def wear_chat_get(self, user):
    """The owner's REAL Henry transcript - the same copilot session the phone
    renders, not a watch-local one.

    Owner, 2026-08-29: "Ich will den Chat Verlauf mit Henry sehen und
    Nachrichten verschicken." The sending half already worked: wear_talk_post
    below calls copilot.chat() with the SAME user, so a watch message has
    always landed in the same Claude session (copilot_sessions.json) the phone
    resumes. Only the READING half was missing, which is why the watch looked
    like a separate, amnesiac chat.

    Trimmed to the shape a round screen can use: `cls` collapses to who spoke;
    unknown internal classes are dropped rather than shown as if Henry had
    said them.
    """
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    from cells.copilot import copilot
    from spine.ops import ask
    from spine.ops.glances import _glance_question
    msgs = (copilot.history(user["name"]) or {}).get("messages") or []
    out = []
    # Filled on the FIRST card line only, and only if there is one - a
    # transcript with no mirrored card never touches the track list at all.
    _names = {}
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
        # "act" joined when /wear/talk gained allow_actions=True (owner decree
        # 2026-08-29, one source of truth): an action receipt is the only proof
        # a watch-issued move actually ran - and "action failed: ..." lands in
        # the same class. Filtering it out here would recreate the exact defect
        # this decree closed: the owner commands from the wrist and the outcome
        # is only visible on the phone.
        if cls not in ("you", "bot", "error", "card", "pm", "act"):
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
        # The FULL text, not a teaser (owner decree 2026-08-29: "kein Zeichen
        # cap") - "one tap away on the phone" was the discrepancy, not a
        # feature. The transcript stays bounded by WEAR_CHAT_MAX lines.
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
        # `key` IS the "this line can be spoken" marker, not a second flag: it
        # is emitted on exactly the classes /wear/voice will render, so the
        # watch's whole rule is "the last row that carries a key". A class the
        # server will not speak has no key, so a client cannot ask for one.
        #
        # Sent on EVERY speakable line rather than only the newest, because the
        # watch replaces its list wholesale on every refresh: it needs to name
        # the line it is looking at, and "the last one" is a position, which is
        # precisely what a wholesale replacement makes untrustworthy.
        if cls in WEAR_SPEAK_CLS:
            row["key"] = _wear_msg_key(m)
        if cls == "card":
            # The LABEL the watch draws instead of a sender name ("Frage ·
            # Kartenname"). Sent as its parts, not as a rendered string: the
            # wrist composes it into a TitleCard title, and a pre-rendered label
            # would have to guess that layout from the server.
            row["kind"] = (m or {}).get("kind") or ""
            row["card"] = (m or {}).get("card") or ""
            # The NAME is DERIVED from the live card, not read back from the
            # frozen copy card_mirror stamped into the log entry.
            #
            # That copy is a notice.label(), capped at 42 chars with an "…"
            # glued on - the right length for the PUSH NOTIFICATION it was
            # built for, and the wrong one for a screen that scrolls. The
            # owner photographed the result on his watch (2026-08-30): a
            # title that wraps over five lines AND still ends in "Die…",
            # which is the worst of both. Same decree the message bodies on
            # this route already follow (WEAR_CHAT_LINE_MAX = None): no
            # character cap on the wrist.
            #
            # Deriving it repairs every line ALREADY in the log, which no
            # wider cap at write time could do - and it leaves notice.label
            # alone for the PM notification that genuinely needs 42 chars.
            row["cardName"] = _wear_card_name(
                row["card"], (m or {}).get("cardName") or "", _names)
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
    # SAME IDEMPOTENCY as the phone's /chat (chat_dedupe). Advisory turns could
    # afford a relay retry running twice - the worst case was a duplicate
    # sentence. With allow_actions=True (owner decree 2026-08-29, one source of
    # truth) a replayed POST would replay a MOVE, so the claim moves in front of
    # the turn here exactly as routes_copilot.chat_post does. The watch sends no
    # mid; claim() falls back to the content key + time window for id-less
    # clients, which is precisely the relay-retry shape.
    from cells.copilot import chat_dedupe
    mine, original = chat_dedupe.claim(user["name"], msg, body.get("card"), None)
    if original is not None:
        # The watch RETRIES on this (RelayClient.talk): its first POST died on
        # a timeout layer (client 20s, relay REPLY_TIMEOUT 120s) while the turn
        # kept running, and the replay is how it collects the answer. So the
        # replay must carry the SAME shape as a live reply - question included,
        # or the retry that finally lands would show prose with the buttons
        # missing. reply=""+duplicate=true means "still running, ask again";
        # the client keys its retry loop on exactly that pair. No voice on a
        # replay: settle() ran before render_b64, and the text is on screen.
        from spine.ops import ask as _ask
        from spine.ops.glances import _glance_question as _gq
        done = chat_dedupe.await_result(original)
        out = dict(done or {"reply": ""})
        q = out.get("question")
        if not q:
            q, _prose = _ask.parse(out.get("reply") or "")
        return self._send(200, json.dumps(
            {"reply": out.get("reply") or "",
             "question": _gq({"question": q}) if q else None,
             "refused": out.get("refused") or [], "duplicate": True}))
    try:
        out = copilot.chat(user["name"], msg, role=user["role"],
                           allow_actions=True, extra_system=wear_brief(),
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
        chat_dedupe.fail(mine)
        return self._send(502, json.dumps({"error": str(e)[:200]}))
    chat_dedupe.settle(mine, out)
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
    # The TEXT goes out whole (kein-Zeichen-cap decree); only the VOICE keeps a
    # bound - WEAR_VOICE_MAX, the same one /wear/voice applies.
    #
    # _wear_text, not a bare slice, and that is not cosmetic: it is the SAME
    # rendering /wear/voice runs over the stored line, so both doors hand
    # voice.render() a byte-identical string and its content-hash cache actually
    # hits. A raw slice here would mint a second cache entry for the same
    # sentence and pay a second round trip to the speech service.
    full = prose or reply
    spoken = _wear_text(full, WEAR_VOICE_MAX)
    resp = {
        # the prose WITHOUT the block - ask.parse already strips it, so the
        # watch renders `reply` as plain text and never sees raw JSON
        "reply": full,
        # the tappable half; None when the agent ignored the brief, which the
        # watch must show as a dead end rather than hide (same rule
        # glance_talk already applies for the glasses)
        "question": _glance_question({"question": q}) if q else None,
        "refused": out.get("refused") or [],
    }
    # WHICH LINE THIS REPLY BECAME IN THE LOG. The watch plays the clip below
    # and then, a heartbeat later, sees the same answer arrive over /wear/chat
    # with a key on it - without this handle it would have no way to know the
    # two are the same sentence and would say it twice. Claimed from the log
    # rather than from `reply`, so it is the same derivation /wear/chat runs.
    #
    # only=("bot",) rather than WEAR_SPEAK_CLS: what we are naming is the turn
    # that just finished. A "pm" line that landed in the same instant is a
    # DIFFERENT thing Henry said and must stay unclaimed, or the watch would
    # swallow it unspoken.
    _mine = _wear_newest_speakable(user["name"], only=("bot",))
    if _mine is not None:
        resp["voiceKey"] = _wear_msg_key(_mine)
    # Voice on this door is now the CLIENT's call, and defaults to on.
    #
    # It used to be unconditional, with the reasoning that a small round screen
    # with no keyboard should always be heard rather than read. That reasoning
    # still holds for a watch that is LISTENING - but the watch has had a
    # "Stimme aktivieren" toggle since 2026-08-29 that defaults to OFF, so the
    # unconditional render was paying a speech round trip per turn to produce a
    # clip the wrist threw away. A client that says nothing (an older build)
    # keeps exactly the old behaviour.
    #
    # render_b64, NOT render()+a URL: the watch talks through the SEALED
    # RELAY (RelayClient.kt's authedCall), exactly like the phone's own
    # /chat - one JSON request/response, no second channel for a client to
    # fetch a binary from, and a URL pointing at localhost means nothing
    # across the internet anyway. voice.py's own docstring says this
    # explicitly for the phone; it applies to the watch for the identical
    # reason, not a new one.
    if body.get("voice", True):
        from spine.media import voice as _voice
        clip = _voice.render_b64(spoken)
        if clip:
            resp["voice"] = clip
    return self._send(200, json.dumps(resp))


def wear_voice_get(self, user):
    """The clip for ONE transcript line - the wrist's catch-up voice path.

    The watch asks for the line it just saw arrive (`?key=`), and gets audio
    back only if that line is still the newest speakable one. Two properties
    fall out of that, and both are the reason this is not simply "render the
    latest":

     1. NO HISTORY. There is no request shape that renders an older line, so
        "only the newest unplayed answer is spoken" is enforced here rather than
        trusted to the client (backlog card, Leitplanke 2).
     2. NO WASTED RENDER. A key that no longer matches costs a log read and
        nothing else - a watch that woke up late is answered with the current
        key and speaks that instead, one clip, not a queue of missed ones.

    Voice stays SERVER-rendered (ops/docs/glasses-reference.md §4) - this route
    is the whole of it; nothing on the watch synthesises anything.
    """
    if user["role"] == "client":
        return self._send(403, json.dumps({"error": "owner/operator only"}))
    from urllib.parse import parse_qs, urlparse
    want = (parse_qs(urlparse(self.path).query).get("key") or [""])[0].strip()
    if not want:
        return self._send(400, json.dumps({"error": "key required"}))
    m = _wear_newest_speakable(user["name"])
    key = _wear_msg_key(m) if m is not None else ""
    # The current key rides back even on a miss, so a client that raced a newer
    # answer learns what to ask for instead of retrying the stale one.
    resp = {"key": key}
    if m is not None and key == want:
        from spine.media import voice as _voice
        clip = _voice.render_b64(_wear_text(m.get("text") or "", WEAR_VOICE_MAX))
        # An absent clip is SILENCE, never an error: the text is already on the
        # watch, and voice.py fails soft by contract (no network, no edge-tts,
        # a rate limit). Same rule wear_talk_post's own clip follows.
        if clip:
            resp["voice"] = clip
    return self._send(200, json.dumps(resp))


GET_ROUTES = {"/wear/board": wear_board_get, "/wear/chat": wear_chat_get,
              "/wear/voice": wear_voice_get}
POST_ROUTES = {"/wear/talk": wear_talk_post}
