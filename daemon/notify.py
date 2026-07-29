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


def card_event(track, status):
    """One line per transition the owner must act on."""
    titles = {
        "needs_you": ("Karte fertig - dein Urteil", "hourglass"),
        "bounced":   ("Karte gescheitert", "warning"),
        "done":      ("Karte akzeptiert", "white_check_mark"),
    }
    if status not in titles:
        return
    title, _ = titles[status]
    body = "%s  [%s]" % (track.get("task", "")[:80], track.get("id", ""))
    push_fcm(title, body, track.get("id", ""))
