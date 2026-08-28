# -*- coding: utf-8 -*-
"""Instant push when a card needs the owner - event-driven, zero polling.

Fires exactly at the status transitions where waiting costs real time
(needs_you, bounced). Single channel: FCM data messages whose payload is
NaCl-sealed with the pairing keys - Google delivers, the app decrypts.
The phone's token arrives via POST /push/register (through the E2EE relay)
and lands in settings.json as push.fcm_token.
"""
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
    from spine.storage import events
    return (os.path.exists(_SA)
            and bool((events.settings().get("push") or {}).get("fcm_token")))


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


def push_fcm(title, body, track_id="", urgent=False, kind="", ask=None):
    """Sealed data message to the paired phone. Best-effort like push().

    `ask` is the optional ask_payload() block: it turns the phone's (and the
    bridged watch's) notification buttons into the worker's OWN options. It
    rides INSIDE the sealed box like everything else, so Google still learns
    nothing, and it is optional on both ends - an older app JSON-parses the
    payload and simply ignores a key it does not know."""
    from spine.storage import events
    from spine.comms import e2ee
    s = events.settings()
    if not urgent and _quiet_now(s):
        print("notify: fcm held (quiet hours) -", title)
        return False
    device = (s.get("push") or {}).get("fcm_token", "")
    rel = s.get("relay") or {}
    if not (device and os.path.exists(_SA) and rel.get("sk") and rel.get("phone_pub")):
        # Say WHICH leg is missing. This used to be a bare False - release.sh's
        # "notify" step then looked identical whether the push was sent, skipped
        # or impossible, and an unnotified phone read as "shipped fine".
        missing = [n for n, ok in (("fcm_token", device), ("service_account", os.path.exists(_SA)),
                                   ("relay.sk", rel.get("sk")), ("relay.phone_pub", rel.get("phone_pub"))) if not ok]
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
        cipher = e2ee.seal_b64(
            raw, e2ee.import_sec(rel["sk"]), e2ee.import_pub(rel["phone_pub"]))
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
        msg = {"message": {"token": device,
                           "data": {"cipher": cipher},
                           "android": {"priority": "high"}}}
        req = urllib.request.Request(
            "https://fcm.googleapis.com/v1/projects/%s/messages:send" % sa["project_id"],
            data=_json.dumps(msg).encode(), method="POST")
        req.add_header("Authorization", "Bearer " + _access_token())
        req.add_header("Content-Type", "application/json")
        urllib.request.urlopen(req, timeout=15).read()
        return True
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


def card_event(track, status):
    """One line per transition the owner must act on. The title follows the
    workspace language (policy.lang); the body is the card's own title, which
    is the owner's text and never translated.

    `status` is the notify REASON, not the card's status field: a turn that
    ended on a typed question reports "question" so the owner learns there is a
    decision waiting (with the question itself as the body) instead of the
    generic "card finished"."""
    from spine.registry import i18n
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
