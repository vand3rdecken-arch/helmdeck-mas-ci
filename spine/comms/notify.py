# -*- coding: utf-8 -*-
"""Instant push when a card needs the owner - event-driven, zero polling.

Fires exactly at the status transitions where waiting costs real time
(needs_you, bounced). Single channel: FCM data messages whose payload is
NaCl-sealed with the pairing keys - Google delivers, the app decrypts.
Tokens arrive via POST /push/register (through the E2EE relay).

TWO DEVICE SLOTS, both fed by the same call (W2d, 2026-08-28):
  * the phone keeps the original settings.push.fcm_token, sealed to
    relay.phone_pub - unchanged, no migration;
  * every OTHER device (the watch) registers under its own pubkey in
    settings.push.devices and is sealed to THAT key.
recipients() re-checks both against the pinned set at send time, so unpairing
a device silences it without a second bookkeeping step.
"""
import re as _re
import json, urllib.request

# -- FCM, Signal-style: Google transports only ciphertext ------------------
#
# The payload is NaCl-box sealed with the SAME pairing keys that protect the
# relay (daemon sk + pinned phone pub), sent as an FCM data message. Google
# learns "app got a ping of size N at time T" - never the content. The app
# opens the box locally and shows the notification.

import base64, json as _json, os, threading, time as _time

from daemon.paths import DAEMON_ROOT as _DAEMON_ROOT
_SA = os.path.join(_DAEMON_ROOT, "fcm_service_account.json")
_tok = {"val": None, "exp": 0}
_tok_lock = threading.Lock()


def _access_token():
    """OAuth2 access token for FCM v1, cached until shortly before expiry."""
    with _tok_lock:
        if _tok["val"] and _time.time() < _tok["exp"] - 120:
            return _tok["val"]
        import jwt as _jwt
        sa = _json.load(open(_SA, encoding="utf-8"))
        now = int(_time.time())
        assertion = _jwt.encode(
            {"iss": sa["client_email"], "scope": "https://www.googleapis.com/auth/firebase.messaging",
             "aud": sa["token_uri"], "iat": now, "exp": now + 3600},
            sa["private_key"], algorithm="RS256")
        import urllib.parse
        body = urllib.parse.urlencode({
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion}).encode()
        req = urllib.request.Request(sa["token_uri"], data=body, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        r = _json.loads(urllib.request.urlopen(req, timeout=15).read())
        _tok["val"] = r["access_token"]
        _tok["exp"] = _time.time() + int(r.get("expires_in", 3600))
        return _tok["val"]


def fcm_ready():
    """True when a push could actually land somewhere. Asks recipients() rather
    than looking at push.fcm_token, so a workspace whose only paired device is
    the WATCH reads as ready instead of as 'push not set up'."""
    from spine.storage import events
    return os.path.exists(_SA) and bool(recipients(events.settings()))


def _quiet_now(s):
    """Quiet hours (owner 2026-08-22): at night only URGENT pushes buzz the
    phone - everything else stays an in-app chat line until morning. Policy is
    data: settings push.quiet = {"from":"22:00","to":"07:00"} (defaults) or
    {"off": true} to disable."""
    q = (s.get("push") or {}).get("quiet") or {}
    if q.get("off"):
        return False
    a, b = str(q.get("from") or "22:00"), str(q.get("to") or "07:00")
    now = _time.strftime("%H:%M")
    return (now >= a or now < b) if a > b else (a <= now < b)


# Android renders at most THREE notification action buttons ("A notification can
# offer up to three action buttons", developer.android.com build-notification), so
# sealing more than three option labels would spend payload bytes on buttons
# nobody can tap. Wear OS bridges whatever the phone posts, so three is also what
# reaches the wrist.
PUSH_MAX_OPTIONS = 3
# FCM rejects a data message larger than 4 KB. The sealed cipher is base64 of
# (nonce + box), i.e. ~4/3 of the plaintext plus overhead, so this keeps the ask
# well inside the budget - and it is CHECKED below, not assumed.
PUSH_MAX_PAYLOAD = 3000


def ask_payload(track):
    """The card's pending question reduced to what a NOTIFICATION can act on,
    or None when a single tap could not settle it.

    Deliberately narrow - a wrist button may only be offered when one tap is a
    COMPLETE, valid answer:
      * exactly one question: ask.validate_answers demands an answer for EVERY
        question, so a two-question ask can never be settled by one button;
      * not multiSelect: one tap cannot express "these two".
    In both excluded cases the push keeps the 3 generic actions and the owner
    opens the app, which is the same floor as before this function existed.

    Option labels ride VERBATIM and are never clipped: validate_answers matches
    a label by EQUALITY, so a truncated label would silently stop being a preset
    pick and arrive as `custom` free text - the worker would then read a
    button press as the owner's own typed words. Clipping for display is the
    notification UI's job, not the payload's.
    """
    q_all = track.get("question") or {}
    qs = q_all.get("questions") or []
    if len(qs) != 1:
        return None
    q = qs[0]
    if q.get("multiSelect"):
        return None
    labels = [o.get("label") for o in (q.get("options") or []) if o.get("label")]
    if len(labels) < 2:
        return None
    # Everything fits, or we keep the last slot for dictation - ask.py accepts
    # free text as the owner's own answer, so a truncated list is never a dead
    # end at the wrist.
    opts = labels if len(labels) <= PUSH_MAX_OPTIONS else labels[:PUSH_MAX_OPTIONS - 1]
    return {"id": q_all.get("id") or "", "header": q.get("header") or "",
            "options": opts, "more": len(labels) > len(opts)}


def recipients(s):
    """Every device this push must reach, as a list of (label, token, pub).

    DERIVED AND VERIFIED AT SEND TIME, never trusted from the stored blob (the
    Paseo principle, CLAUDE.md): a registered device only stays a recipient
    while its key is STILL PINNED in relay.phone_pubs. Unpairing therefore
    silences a device immediately, with no second bookkeeping step that could
    drift out of sync with the pinned set - the same reason _admit() is the one
    owner of pinning.

    relay_client._pubs_of is the single source of truth for "what is pinned"
    (it merges the legacy phone_pub mirror); replicating that merge here would
    be exactly the kind of drift this repo keeps out.
    """
    from spine.comms import relay_client
    rel = s.get("relay") or {}
    pinned = set(relay_client._pubs_of(rel))
    push = s.get("push") or {}
    out = []
    # The phone keeps its legacy slot: settings.push.fcm_token + relay.phone_pub
    # (= phone_pubs[0]). Untouched so an existing install keeps working with no
    # migration step and no re-registration.
    phone_pub = rel.get("phone_pub", "") or ""
    phone_tok = push.get("fcm_token", "") or ""
    # ...but only when no device registered that SAME token together with its
    # own key. relay.phone_pub is _admit's pubs[0] - the OLDEST pinned key,
    # not necessarily the key the phone holds today (8 pinned keys on the
    # owner box 2026-09-13, six re-pairings that day never moved it). A push
    # sealed to the wrong key decrypts to nothing and the phone shows the
    # generic "Neue Meldung" placeholder - the owner's report. An explicit
    # (pub, token) registration is the truth for that token; see below.
    explicit_tokens = {((d or {}).get("token") or "").strip()
                       for _p, d in (push.get("devices") or {}).items()
                       if _p in pinned}
    # An FCM registration token is 140+ chars. A 64-hex value here is an APNs
    # device token (the iOS build registers through the same legacy path,
    # 2026-09-14 13:08) - FCM answers 400 Bad Request to it on every push.
    # iOS needs its own APNs leg; until then it is skipped, not spammed.
    if phone_tok and _re.fullmatch(r"[0-9a-fA-F]{64}", phone_tok):
        print("notify: legacy push token is an APNs device token (64 hex) - FCM would 400 it, skipped")
        phone_tok = ""
    if phone_tok and phone_pub and phone_pub in pinned and phone_tok not in explicit_tokens:
        out.append(("phone", phone_tok, phone_pub))
    # Additional devices (the watch, W2d) register under their OWN pubkey and
    # are sealed to it - NOT to the phone's. A second device must never be able
    # to open the first device's notifications.
    for pub, d in (push.get("devices") or {}).items():
        tok = ((d or {}).get("token") or "").strip()
        if tok and pub in pinned and (pub != phone_pub or tok in explicit_tokens):
            out.append(((d or {}).get("label") or "device", tok, pub))
    return out


def push_fcm(title, body, track_id="", urgent=False, kind="", ask=None):
    """Sealed data message to EVERY paired device. Best-effort like push().

    Was phone-only until W2d; the watch is a second, independently sealed
    recipient. Returns True if at least one device took the message - a dead
    watch must never make a delivered phone push report as failure.

    `ask` is the optional ask_payload() block: it turns each device's
    notification buttons into the worker's OWN options. It rides INSIDE the
    sealed box like everything else, so Google still learns nothing, and it is
    optional on both ends - an older app JSON-parses the payload and simply
    ignores a key it does not know."""
    from spine.storage import events
    from spine.comms import e2ee
    s = events.settings()
    if not urgent and _quiet_now(s):
        print("notify: fcm held (quiet hours) -", title)
        return False
    rel = s.get("relay") or {}
    targets = recipients(s)
    if not (targets and os.path.exists(_SA) and rel.get("sk")):
        # Say WHICH leg is missing. This used to be a bare False - release.sh's
        # "notify" step then looked identical whether the push was sent, skipped
        # or impossible, and an unnotified phone read as "shipped fine".
        missing = [n for n, ok in (("a registered+pinned device", targets),
                                   ("service_account", os.path.exists(_SA)),
                                   ("relay.sk", rel.get("sk"))) if not ok]
        print("notify: fcm skipped - missing:", ", ".join(missing))
        return False
    try:
        sa = _json.load(open(_SA, encoding="utf-8"))
        payload = {"title": title, "body": body, "track": track_id, "kind": kind}
        if ask:
            payload["ask"] = ask
        raw = _json.dumps(payload).encode("utf-8")
        if ask and len(raw) > PUSH_MAX_PAYLOAD:
            # An oversized ask must never cost the owner the NOTIFICATION - drop
            # the buttons, keep the news. He can still open the card and pick.
            print("notify: ask dropped - payload %d B over the %d B budget"
                  % (len(raw), PUSH_MAX_PAYLOAD))
            payload.pop("ask")
            raw = _json.dumps(payload).encode("utf-8")
        sk = e2ee.import_sec(rel["sk"])
        # DATA-ONLY on purpose (no `notification` block). Android's FCM SDK only
        # invokes an in-app handler for messages shaped this way; a message that
        # ALSO carries a `notification` block auto-displays that block from the
        # system tray whenever the app is backgrounded/killed and never reaches
        # app code until tapped (measured behaviour, not an assumption - this is
        # why HelmDeck used to ship the generic "Neue Meldung" hybrid). The app
        # now ships that in-app handler (surfaces/app/src/data/push.ts,
        # BACKGROUND_NOTIFICATION_TASK via expo-task-manager), which decrypts
        # `cipher` and raises the real title/body as a local notification itself
        # - so zero-knowledge is unchanged (Google still transports only
        # ciphertext) and the phone now shows real content instead of a
        # generic "tap to see" placeholder in every app state.
        #
        # ROLLOUT ORDER: this is a native app change (new dependency), so an
        # old installed APK has no background handler and would show NOTHING
        # for a data-only push while backgrounded. Ship the new APK (and
        # confirm the background task fires) BEFORE restarting the daemon on
        # this code - see ops/docs/backlog/wear-os-integration/README.md §4.3.
        url = ("https://fcm.googleapis.com/v1/projects/%s/messages:send"
               % sa["project_id"])
        bearer = "Bearer " + _access_token()
        sent = 0
        for label, token, pub in targets:
            # Sealed PER DEVICE, to that device's own pinned key. One shared
            # ciphertext would mean the watch could open the phone's mail and
            # vice versa - the pairing keys exist precisely to prevent that.
            try:
                cipher = e2ee.seal_b64(raw, sk, e2ee.import_pub(pub))
                msg = {"message": {"token": token,
                                   "data": {"cipher": cipher},
                                   "android": {"priority": "high"}}}
                req = urllib.request.Request(
                    url, data=_json.dumps(msg).encode(), method="POST")
                req.add_header("Authorization", bearer)
                req.add_header("Content-Type", "application/json")
                urllib.request.urlopen(req, timeout=15).read()
                sent += 1
            except Exception as e:
                # One dead device must not silence the others - a stale watch
                # token (uninstalled app, revoked registration) is the normal
                # case, not an outage. Named per device so the log says WHICH.
                print("notify: fcm failed for %s: %s" % (label, e))
        return sent > 0
    except Exception as e:
        print("notify: fcm failed:", e)
        return False


# Reasons that may NEVER reach the phone, whatever presence says:
#   background - the card is waiting on its own task, not on the owner
#   error      - a runtime failure is not an instruction to the owner; it belongs
#                on the card and in the log. Paseo excludes it from push for the
#                same reason: being woken by a crash you cannot act on at 3am
#                teaches you to mute the channel.
NEVER_PUSH = ("background", "error")

_last_push = {}          # card id -> the dedup key already pushed
_dedup_lock = __import__("threading").Lock()


def _dedup_key(track, status):
    """What makes this notification DISTINCT. A pending question dedups on the
    question's id, so a card that asks once is pushed once no matter how many
    times the turn is re-settled ("first-only", Paseo's rule) - but a NEW
    question is a new key and does push."""
    if status == "question":
        return "question:" + ((track.get("question") or {}).get("id") or "?")
    return status


def should_push(track, status):
    """(ok, why) - the 3-tier presence policy, in one place so the reason is
    inspectable instead of buried in an if. `why` is for the log."""
    if status in NEVER_PUSH:
        return False, "reason is never pushed"
    tid = track.get("id", "")
    key = _dedup_key(track, status)
    with _dedup_lock:
        if _last_push.get(tid) == key:
            return False, "already pushed (dedup %s)" % key
    from spine.comms import presence
    decision = presence.plan(tid)
    if decision == "silent":
        return False, "owner is looking at this card"
    if decision == "inapp":
        return False, "owner is present elsewhere - in-app is enough"
    with _dedup_lock:
        _last_push[tid] = key
    return True, "owner is away"


def clear_dedup(track_id):
    """The card moved on, so the next notification about it is news again.
    Called when a turn STARTS (the owner steered / answered)."""
    with _dedup_lock:
        _last_push.pop(track_id, None)
    # Re-arm the chat mirror on the SAME signal. The two registries are
    # deliberately separate (different suppression policies) but they must
    # re-arm together: if only the push's cleared, a steered card would buzz
    # about a question the chat had decided was not news, and the owner would
    # tap that notification into a transcript that never mentioned it.
    try:
        from cells.copilot.chat import card_mirror
        card_mirror.clear_dedup(track_id)
    except Exception:
        pass


def escalate(title, body, track_id=""):
    """PM escalation delivery: the SAME 3-tier presence policy as card_event,
    for PM-authored alerts (cost watchdog, triangle tilt, quota pacing) whose
    chat line has already landed via pm._say. Dedup is the CALLER's job - the
    PM content-hashes / level-ladders its escalations - so this deliberately
    skips _last_push and only decides delivery:
      focused on that card -> silent (the alert is on his screen)
      present elsewhere    -> in-app (the chat line is enough)
      absent               -> sealed FCM push
    track_id may be "" for goal-level alerts: then no client can be 'focused'
    and only the present/absent split applies - absent still pushes, which is
    the safe direction to be wrong in."""
    from spine.comms import presence
    decision = presence.plan(track_id)
    if decision != "push":
        print("notify: escalation suppressed (%s) - %s" % (decision, title))
        return False
    return push_fcm(title, body, track_id)


# How much of a Henry answer becomes the notification body. ~100 chars is what a
# lockscreen line and a round watch face actually show; the full answer is one
# tap away in the chat. This budget exists because a lockscreen CANNOT SCROLL -
# it is not a house style to be copied inward. The chat-side counterpart of this
# constant (card_mirror.RESULT_MAX, 400) was removed on 2026-08-30: the chat
# scrolls and folds, so a cap there destroyed the very text this pointer points
# at. See spine/comms/notice.short's docstring for the full rule.
CHAT_BODY_MAX = 100


def chat_summary(text):
    """A Henry reply reduced to ONE notification line.

    Three strippers rather than a slice, and each has a scar behind it:
      * ask.parse drops a trailing <helmdeck-ask> block - the board agent may end
        a turn with one, and raw interaction JSON on a lockscreen is not news.
        The same parse /wear/talk and the voice path already apply to this exact
        text, so this is the established owner of that cleanup, not a new one;
      * voice.speakable drops markdown - the model writes '**fertig**' for a
        surface that renders it and a notification renders nothing (measured for
        speech 2026-08-21: 'Stern Stern Stern' read aloud; the same glyphs
        arrive literally in a notification body);
      * the trailing ' …' says the line was CUT. d243545's lesson on the wrist:
        a silent cut reads as the complete answer.
    """
    from spine.media import voice
    from spine.ops import ask
    _q, prose = ask.parse(text or "")
    # one line, never a layout: a notification collapses newlines anyway, and
    # the watch draws the body into a fixed box
    body = " ".join(voice.speakable(prose or "").split())
    if len(body) <= CHAT_BODY_MAX:
        return body
    cut = body[:CHAT_BODY_MAX]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > CHAT_BODY_MAX // 2 else cut).rstrip() + " …"


def chat_reply(text):
    """Henry ANSWERED - the reverse direction of the one-inbox decree.

    card_event carries the board's news INTO the Henry chat; this carries the
    chat's own news back OUT to the devices. Until now only worker cards could
    reach the owner at all: Henry finished a turn, wrote it to the transcript,
    and the owner learned about it by opening the app on the off chance (owner
    report 2026-08-29 18:09).

    PRESENCE decides, exactly as it does for a card - the same instrument, not a
    second policy. But it is asked about the CHAT, not about "somewhere":

      focused on the chat -> silent (he is reading this very transcript)
      anything else       -> sealed FCM push to every paired device

    The first version asked presence.plan("") and stayed quiet on BOTH 'silent'
    and 'inapp', on the theory that "a client with the app visible" means "the
    answer is already on his screen". That theory cost the whole feature: 'inapp'
    means an app is open SOMEWHERE - the desktop shell on the PC, the board tab
    on another device, the phone showing the card list - and none of those show a
    Henry answer. Measured 2026-08-30 in daemon.out.log: EVERY chat reply since
    the fix shipped logged "suppressed (inapp)", i.e. not one push was ever sent,
    which is the exact defect the reverse mirror was built to close.

    'focused' is not unavailable here - it just needed a name. presence.CHAT is
    that name: the chat screen reports it the same way a card screen reports its
    id (surfaces/app/src/app/chat.tsx), so the three-tier instrument is used as
    designed instead of being collapsed into a present/absent split that cannot
    tell reading-the-answer from having-a-window-open.

    An older app that never reports it simply never suppresses - the safe
    direction presence.py names: a missed push is worse than an extra one.

    urgent=True is NOT a priority claim - it is what tells push_fcm this is
    SOLICITED. Quiet hours exist so autonomous overnight work does not buzz the
    phone; an answer to a question the owner typed two minutes ago is precisely
    what he is demonstrably still awake for, and holding it until morning would
    silently recreate the defect this closes. He started this turn; nothing here
    fires on its own.

    No dedup registry: one turn produces one reply, and a replayed POST /chat is
    already answered from chat_dedupe's stored result WITHOUT re-running the
    turn - so there is no second event to swallow, and a registry would only be
    state nobody clears.
    """
    body = chat_summary(text)
    if not body:
        return False
    from spine.comms import presence
    from spine.registry import i18n
    decision = presence.plan(presence.CHAT)
    if decision == "silent":
        # Named, not counted: "why didn't my phone buzz?" must have a checkable
        # answer in the log itself. A bare decision word is what let this
        # suppress 100% of replies for a day without anyone being able to see
        # WHICH window was doing the suppressing.
        who = ", ".join("%s/%s" % (c.get("device"), c.get("focused"))
                        for c in presence.snapshot()["clients"]) or "?"
        print("notify: chat reply silent - owner is on the chat screen (%s)" % who)
        return False
    # kind="chat" with NO track: the app routes a trackless chat push into the
    # Henry chat instead of the dashboard its trackless branch falls back to
    # (surfaces/app/src/app/_layout.tsx). The watch needs no change at all -
    # PushService renders title/body from the same sealed payload and opens the
    # app; it never looked at `kind`.
    return push_fcm(i18n.t("push.henry"), body, "", urgent=True, kind="chat")


def card_event(track, status):
    """One line per transition the owner must act on. The title follows the
    workspace language (policy.lang); the body is the card's own title, which
    is the owner's text and never translated.

    `status` is the notify REASON, not the card's status field: a turn that
    ended on a typed question reports "question" so the owner learns there is a
    decision waiting (with the question itself as the body) instead of the
    generic "card finished"."""
    from spine.registry import i18n
    # THE EVENT MIRROR (owner decree 2026-08-29) runs FIRST and unconditionally.
    # Everything below this line decides whether to BUZZ; this decides whether
    # the owner can ever find out at all. The two must not share a gate: a push
    # is correctly suppressed while the owner is present, in quiet hours, and on
    # a repeat - and every one of those is a reason the chat line matters MORE,
    # not less. It is also why this sits above the `keys` check rather than
    # inside it: the mirror keeps its own reason table (card_mirror.REASONS) so
    # the inbox's editorial policy and the push's never silently drift into one.
    try:
        from cells.copilot.chat import card_mirror
        card_mirror.mirror(track, status)
    except Exception as _me:                                    # noqa: BLE001
        # Best-effort like every other write in this module, but never SILENT:
        # a mirror that stops working is invisible by construction (the owner
        # sees a chat with nothing in it, which is what a quiet board looks
        # like too), so the one place it can announce its own failure is here.
        print("notify: chat mirror failed -", str(_me)[:200])
    # NB "background" is deliberately absent: a card waiting on its own
    # background task is NOT the owner's move, so it must never buzz his phone.
    # It shows as an in-app cue and auto-continues when the task finishes.
    keys = {"needs_you": "push.needsYou", "bounced": "push.bounced",
            "done": "push.done", "question": "push.question"}
    if status not in keys:
        return
    ok, why = should_push(track, status)
    if not ok:
        print("notify: %s/%s suppressed - %s" % (track.get("id", "?"), status, why))
        return
    body = "%s  [%s]" % (track.get("task", "")[:80], track.get("id", ""))
    ask_block = None
    if status == "question":
        from spine.ops import ask
        q = ask.summary(track.get("question"))
        if q:
            body = "%s\n%s" % (q[:120], track.get("task", "")[:60])
        # The worker's own options become the notification's buttons (W1c), so
        # a single-question ask is answerable from the lockscreen or the watch
        # without opening the app. None when one tap could not settle it.
        ask_block = ask_payload(track)
    # an URGENT-priority card's ask may pierce quiet hours; the rest waits.
    # `kind` rides in the sealed payload so a tap on a DONE push can open the
    # voice mode and have Henry SPEAK the result (owner 2026-08-22) instead of
    # deep-linking into the card.
    push_fcm(i18n.t(keys[status]), body, track.get("id", ""),
             urgent=(track.get("priority") == "urgent"), kind=status,
             ask=ask_block)
