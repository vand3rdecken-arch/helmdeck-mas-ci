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

_SA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fcm_service_account.json")
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
    import events
    return (os.path.exists(_SA)
            and bool((events.settings().get("push") or {}).get("fcm_token")))


def push_fcm(title, body, track_id=""):
    """Sealed data message to the paired phone. Best-effort like push()."""
    import events, e2ee
    s = events.settings()
    device = (s.get("push") or {}).get("fcm_token", "")
    rel = s.get("relay") or {}
    if not (device and os.path.exists(_SA) and rel.get("sk") and rel.get("phone_pub")):
        return False
    try:
        sa = _json.load(open(_SA, encoding="utf-8"))
        cipher = e2ee.seal_b64(
            _json.dumps({"title": title, "body": body, "track": track_id}).encode("utf-8"),
            e2ee.import_sec(rel["sk"]), e2ee.import_pub(rel["phone_pub"]))
        # A GENERIC notification block so Android displays the push automatically
        # even when the app is backgrounded/killed (a data-only message needs an
        # in-app background handler, which we don't ship). Zero-knowledge is kept:
        # the block carries NO card content - just "you have a message" - while the
        # real title/body stay in the sealed `cipher`, which the app decrypts and
        # re-presents in full when it's open.
        msg = {"message": {"token": device,
                           "data": {"cipher": cipher},
                           "notification": {"title": "HelmDeck",
                                            "body": "Neue Meldung – zum Ansehen tippen"},
                           "android": {"priority": "high", "notification": {"channel_id": "default"}}}}
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
    import presence
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


def card_event(track, status):
    """One line per transition the owner must act on. The title follows the
    workspace language (policy.lang); the body is the card's own title, which
    is the owner's text and never translated.

    `status` is the notify REASON, not the card's status field: a turn that
    ended on a typed question reports "question" so the owner learns there is a
    decision waiting (with the question itself as the body) instead of the
    generic "card finished"."""
    import i18n
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
    if status == "question":
        import ask
        q = ask.summary(track.get("question"))
        if q:
            body = "%s\n%s" % (q[:120], track.get("task", "")[:60])
    push_fcm(i18n.t(keys[status]), body, track.get("id", ""))
