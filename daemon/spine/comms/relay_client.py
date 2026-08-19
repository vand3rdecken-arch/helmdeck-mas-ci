# -*- coding: utf-8 -*-
"""Daemon side of the ZERO-KNOWLEDGE relay (see relay/relay.py + e2ee.py). When
paired (settings.relay = {url, room, sk, phone_pubs?}), this dials OUT to the
relay, pulls end-to-end-ENCRYPTED phone frames, decrypts them, runs the inner
request against the local daemon, and pushes an encrypted response. The relay
never sees plaintext; no inbound port is opened on the daemon.

Trust model - DETERMINISTIC pairing lifecycle (not blind TOFU): a device key is
served only if it is already pinned, or if it arrives inside the single-use
window opened by issuing a pairing code (PAIR_TTL). Outside that window an
unknown key gets a sealed, explicit refusal - so a leaked room id can't be
hijacked, and a failed pairing is VISIBLE on the phone instead of looking like
"daemon offline". Unpair rotates room + keypair, killing every code ever
issued."""
import json, threading, time, urllib.request, urllib.error

_thread = None
_stop = False
_pin_lock = threading.Lock()

# One pairing code admits ONE new device, and only this many seconds after the
# owner issued it. Both bounds make the code lifecycle deterministic: the
# newest code works once, old codes/windows are dead, nothing pins by accident.
# No cap on TOTAL paired devices: the security boundary is the single-use,
# owner-only code (POST /relay/pair requires role=="owner" - server.py), not a
# device count. An arbitrary "8" only capped legitimate multi-device owners
# (a tester recruitment run, a family, several test phones) while doing
# nothing for security - a device still needs a fresh owner-issued code either
# way, at any count.
PAIR_TTL = 900


def insecure_url(url):
    """True when this url would carry secrets in CLEARTEXT across a network:
    plain http:// to any host that is not this machine's own loopback. The
    relay frames themselves are E2EE-sealed, but the pairing link/QR puts a
    live bearer token into a URL - that must never travel unencrypted."""
    from urllib.parse import urlsplit
    try:
        u = urlsplit((url or "").strip())
    except ValueError:
        return True
    if u.scheme != "http":
        return False
    host = (u.hostname or "").lower()
    return not (host in ("localhost", "::1") or host.startswith("127."))


def _pubs_of(rel):
    """Pinned device keys; merges the legacy single phone_pub field (older
    installs) so an existing pairing survives the upgrade. Index 0 stays the
    push target (notify.py seals FCM payloads to phone_pub)."""
    legacy = rel.get("phone_pub", "") or ""
    pubs = [p for p in (rel.get("phone_pubs") or []) if p]
    if legacy and legacy not in pubs:
        pubs.insert(0, legacy)
    return pubs


def _cfg():
    from daemon.spine.storage import events
    r = events.settings().get("relay") or {}
    return ((r.get("url", "") or "").rstrip("/"), r.get("room", "") or "",
            r.get("sk", "") or "", _pubs_of(r))


def _admit(pub):
    """Decide whether to serve this device key. Returns (True, "") for a pinned
    key; pins a NEW key only inside the open pairing window (consuming it);
    otherwise returns (False, reason) - the reason is sealed back to the caller
    so pairing failures surface in the app instead of hanging."""
    with _pin_lock:
        from daemon.spine.storage import events
        rel = dict(events.settings().get("relay") or {})
        pubs = _pubs_of(rel)
        if pub in pubs:
            return True, ""
        pend = rel.get("pair_pending") or {}
        try:
            expires = float(pend.get("expires") or 0)
        except (TypeError, ValueError):
            expires = 0
        if not expires:
            return False, ("this device is not paired with the workspace - "
                           "generate a pairing code on the desktop "
                           "(Settings -> Mobile app -> Pair phone)")
        if time.time() > expires:
            rel["pair_pending"] = None
            events.save_settings({"relay": rel})
            return False, ("pairing code expired (valid %d minutes, single "
                           "use) - generate a fresh one on the desktop"
                           % (PAIR_TTL // 60))
        pubs.append(pub)
        rel["phone_pubs"] = pubs
        rel["phone_pub"] = pubs[0]      # push target + legacy mirror
        rel["pair_pending"] = None      # single use: this code is spent
        events.save_settings({"relay": rel})
        try:
            events.log("relay", "device paired (%d device(s) pinned)" % len(pubs))
        except Exception:
            pass
        return True, ""


def _local(port, inner):
    url = "http://127.0.0.1:%d%s" % (port, inner.get("path", "/"))
    method = inner.get("method", "GET")
    raw = (inner.get("body") or "").encode("utf-8")
    data = raw if (method in ("POST", "PUT", "PATCH", "DELETE") and raw) else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers=inner.get("headers") or {})
    try:
        with urllib.request.urlopen(req, timeout=115) as resp:
            return {"status": getattr(resp, "status", 200),
                    "headers": {"Content-Type": resp.headers.get("Content-Type", "application/json")},
                    "body": resp.read().decode("utf-8", "replace")}
    except urllib.error.HTTPError as e:
        return {"status": e.code,
                "headers": {"Content-Type": e.headers.get("Content-Type", "application/json")},
                "body": e.read().decode("utf-8", "replace")}
    except Exception as e:
        return {"status": 502, "headers": {}, "body": json.dumps({"error": str(e)[:200]})}


def _serve_one(relay, room, sk_b64, port, frame):
    from daemon.spine.comms import e2ee
    fid = frame.get("id")
    pub = frame.get("pub", "")
    ok, reason = _admit(pub)
    if not ok:
        # Refused (not pinned, window closed/expired). Say so instead of
        # dropping the frame: silence looks exactly like "daemon offline" and
        # the caller just hangs until its timeout. The reply is sealed to the
        # caller's own key, so it leaks nothing to anyone else.
        try:
            sk = e2ee.import_sec(sk_b64)
            body = json.dumps({"error": reason})
            resp = {"status": 409, "headers": {"Content-Type": "application/json"},
                    "body": body, "id": fid}
            resp["cipher"] = e2ee.seal_b64(json.dumps(
                {k: resp[k] for k in ("status", "headers", "body")}).encode(),
                sk, e2ee.import_pub(pub))
            urllib.request.urlopen(urllib.request.Request(
                relay + "/tunnel/push?room=" + room,
                data=json.dumps({"id": fid, "cipher": resp["cipher"]}).encode("utf-8"),
                headers={"Content-Type": "application/json"}), timeout=15)
        except Exception:
            pass
        return
    try:
        sk = e2ee.import_sec(sk_b64)
        peer = e2ee.import_pub(pub)
        inner = json.loads(e2ee.open_b64(frame["cipher"], sk, peer))
    except Exception:
        return               # undecryptable / tampered - ignore
    resp = _local(port, inner)
    try:
        cipher = e2ee.seal_b64(json.dumps(resp).encode("utf-8"), sk, peer)
    except Exception:
        return
    try:
        urllib.request.urlopen(urllib.request.Request(
            relay + "/tunnel/push?room=" + room,
            data=json.dumps({"id": fid, "cipher": cipher}).encode("utf-8"),
            headers={"Content-Type": "application/json"}), timeout=15)
    except Exception:
        pass


def _pull(relay, room):
    req = urllib.request.Request(relay + "/tunnel/pull?room=" + room)
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            if getattr(resp, "status", 200) == 204:
                return None
            data = resp.read()
            return json.loads(data) if data else None
    except urllib.error.HTTPError as e:
        if e.code == 204:
            return None
        raise


def _loop(port):
    # The whole body is guarded: a single unhandled error (a hiccup in
    # events.settings(), a transient DNS/TLS failure, a relay restart) must
    # NEVER kill this thread - if it dies, the phone silently loses the daemon
    # while the desktop looks perfectly healthy ("no daemon connected for this
    # room"). Same rule as the night shift: the background worker outlives its
    # own errors. It only exits when the daemon is shutting down (_stop).
    # Reconnect with EXPONENTIAL backoff (3s..60s): a dead relay is retried
    # gently instead of hammered every 3s, and recovery resets the delay so a
    # blip costs one short pause. Logged on first failure, then sparsely
    # (every 10th) to keep the event log readable; recovery is logged once.
    delay, errs = 3, 0
    warned_http = False
    while not _stop:
        try:
            relay, room, sk, _ = _cfg()
            if not (relay and room and sk):
                time.sleep(5)
                continue
            if insecure_url(relay) and not warned_http:
                # Legacy config from before the https guard. Frames stay
                # E2EE-sealed either way, so keep bridging - but say it once:
                # new pairing links are refused until the URL is https.
                warned_http = True
                try:
                    from daemon.spine.storage import events
                    events.log("relay", "relay url is plain http:// - frames are "
                               "still E2EE-sealed, but pairing is refused until "
                               "the relay URL is https (Settings -> Mobile app)")
                except Exception:
                    pass
            frame = _pull(relay, room)
            if errs:
                try:
                    from daemon.spine.storage import events
                    events.log("relay", "bridge reconnected after %d failed attempt(s)" % errs)
                except Exception:
                    pass
            errs, delay = 0, 3
            if frame:
                threading.Thread(target=_serve_one, args=(relay, room, sk, port, frame),
                                 daemon=True).start()
        except Exception as e:
            errs += 1
            if errs == 1 or errs % 10 == 0:
                try:
                    from daemon.spine.storage import events
                    events.log("relay", "bridge unreachable (attempt %d, retry in %ds): %s"
                               % (errs, delay, str(e)[:200]))
                except Exception:
                    pass
            time.sleep(delay)
            delay = min(delay * 2, 60)


def start(port=8140):
    global _thread
    if _thread and _thread.is_alive():
        return
    _thread = threading.Thread(target=_loop, args=(port,), daemon=True)
    _thread.start()


def pairing_payload():
    """Ensure this daemon has a relay keypair + room id, open the single-use
    pairing window (PAIR_TTL), and return the payload the phone needs to pair:
    relay url, room id, the daemon's public key and the window length. Already
    pinned devices are untouched - the old behaviour (clearing the pin at
    issuance) silently unpaired the current phone the moment the owner
    GENERATED a code, then re-pinned whichever device spoke first.
    (The phone also needs a device token for daemon auth - added by the caller.)"""
    import os, base64
    from daemon.spine.storage import events
    from daemon.spine.comms import e2ee
    rel = dict(events.settings().get("relay") or {})
    if insecure_url(rel.get("url", "")):
        # Refuse BEFORE opening the window or minting anything: the code this
        # payload becomes embeds a live device token in a plain-http URL.
        raise ValueError("relay url is plain http:// - the pairing link would "
                         "carry a live device token unencrypted. Use the HTTPS "
                         "relay URL (deploy/README.md), or http://localhost "
                         "only for local testing.")
    if not rel.get("sk"):
        sk, _ = e2ee.generate_keypair()
        rel["sk"] = e2ee.export_sec(sk)
    if not rel.get("room"):
        rel["room"] = base64.urlsafe_b64encode(os.urandom(12)).decode().rstrip("=")
    rel["pair_pending"] = {"expires": time.time() + PAIR_TTL}
    events.save_settings({"relay": rel})
    sk = e2ee.import_sec(rel["sk"])
    return {"url": rel.get("url", ""), "room": rel["room"],
            "daemon_pub": e2ee.export_pub(sk.public_key),
            "expires_in": PAIR_TTL}


def unpair():
    """Revoke mobile access outright: forget every pinned device AND rotate
    room + keypair, so every pairing code/QR/link ever issued is dead - a
    deterministic kill-switch, not just "let the next phone pin itself". The
    push token goes too (it belongs to the unpaired phone)."""
    import os, base64
    from daemon.spine.storage import events
    from daemon.spine.comms import e2ee
    rel = dict(events.settings().get("relay") or {})
    sk, _ = e2ee.generate_keypair()
    rel.update({"sk": e2ee.export_sec(sk),
                "room": base64.urlsafe_b64encode(os.urandom(12)).decode().rstrip("="),
                "phone_pub": "", "phone_pubs": [], "pair_pending": None})
    push = dict(events.settings().get("push") or {})
    push["fcm_token"] = ""
    events.save_settings({"relay": rel, "push": push})
    try:
        events.log("relay", "unpaired - room + keys rotated, all issued codes revoked")
    except Exception:
        pass
    return {"ok": True}
