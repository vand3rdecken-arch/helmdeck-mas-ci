# -*- coding: utf-8 -*-
"""Daemon side of the ZERO-KNOWLEDGE relay (see surfaces/relay/relay.py + e2ee.py). When
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
import http.client, json, socket, threading, time, urllib.request, urllib.error

_thread = None
_stop = False
_pin_lock = threading.Lock()

# -- push retry bookkeeping (relay-push-resilience Phase B) -----------------
# A push (daemon -> relay -> phone) crosses whatever network sits between
# this daemon and the relay - often a Cloudflare tunnel even when both
# processes share one machine (memory helmdeck-relay-local-fallback). A
# reset there used to be silent and final (bare `except Exception: pass`):
# the relay's waiting slot stays open for REPLY_TIMEOUT (120s), so a retry a
# few seconds later still delivers, but nothing ever retried. _push_fails
# counts GIVE-UPs only (rejections + exhausted retries) and is process-wide
# (both call sites in _serve_one share it), so a burst of concurrent frame
# failures during one outage logs at the SAME first-then-every-10th cadence
# as a sustained one, instead of each frame's thread emitting its own
# "first failure" line.
_push_lock = threading.Lock()
_push_fails = 0

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
    from spine.storage import events
    r = events.settings().get("relay") or {}
    return ((r.get("url", "") or "").rstrip("/"), r.get("room", "") or "",
            r.get("sk", "") or "", _pubs_of(r))


def _admit(pub):
    """Decide whether to serve this device key. Returns (True, "") for a pinned
    key; pins a NEW key only inside the open pairing window (consuming it);
    otherwise returns (False, reason) - the reason is sealed back to the caller
    so pairing failures surface in the app instead of hanging."""
    with _pin_lock:
        from spine.storage import events
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


def _push(relay, room, fid, cipher):
    """POST one reply frame to the relay, retrying transport-level failures
    (a reset/timeout on the tunnel leg) up to 3 attempts total. NEVER retries
    a 4xx from the relay itself - that is our bug (bad room, bad payload),
    and retrying would hide it instead of surfacing it. Idempotent by
    construction: the relay keys pushes by frame id (relay.py's `waiting`
    dict), so a duplicate delivery lands on an already-served or expired
    slot and is a harmless 200 (relay.py's push handler has no side effect
    beyond setting that one slot). Returns True iff the relay accepted the
    push (200) at any attempt."""
    body = json.dumps({"id": fid, "cipher": cipher}).encode("utf-8")
    req_kwargs = dict(data=body, headers={"Content-Type": "application/json"})
    last_err = None
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(urllib.request.Request(
                    relay + "/tunnel/push?room=" + room, **req_kwargs), timeout=15) as resp:
                status = getattr(resp, "status", 200)
        except urllib.error.HTTPError as e:
            if e.code < 500:
                _push_giveup("push rejected frame=%s: HTTP %d" % (fid[:8], e.code))
                return False
            last_err = e   # 5xx: Cloudflare/relay-side error, treat as transport
        except (urllib.error.URLError, socket.timeout, ConnectionResetError,
                http.client.RemoteDisconnected) as e:
            last_err = e
        else:
            if status == 200:
                _push_recovered(attempt)
                return True
            last_err = Exception("relay returned HTTP %d" % status)
        if attempt < 3:
            time.sleep(1 if attempt == 1 else 3)
    _push_giveup("push lost frame=%s after 3 attempts: %s" % (fid[:8], str(last_err)[:200]))
    return False


def _push_recovered(attempt):
    # Per-call visibility: THIS push needed retries and still got through -
    # log it immediately, independent of any other frame's failures. A push
    # that succeeds on its first try (the common case) logs nothing.
    # Resets the give-up cadence counter so the NEXT outage starts counting
    # from "first failure" again, same as the pull loop resetting `errs` on
    # any successful pull.
    global _push_fails
    with _push_lock:
        _push_fails = 0
    if attempt > 1:
        try:
            from spine.storage import events
            events.log("relay", "push delivered after %d retry(s)" % (attempt - 1))
        except Exception:
            pass


def _push_giveup(msg):
    # A push that never got through this call (rejected outright, or
    # exhausted all 3 attempts). Capped at first-then-every-10th (same
    # cadence as the pull loop's `bridge unreachable`) so a sustained
    # relay/tunnel outage - many frames, each giving up - logs as ONE
    # readable trend instead of one line per lost frame.
    global _push_fails
    with _push_lock:
        _push_fails += 1
        n = _push_fails
    if n == 1 or n % 10 == 0:
        try:
            from spine.storage import events
            events.log("relay", msg)
        except Exception:
            pass


def _serve_one(relay, room, sk_b64, port, frame):
    from spine.comms import e2ee
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
            _push(relay, room, fid, resp["cipher"])
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
    _push(relay, room, fid, cipher)


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
                    from spine.storage import events
                    events.log("relay", "relay url is plain http:// - frames are "
                               "still E2EE-sealed, but pairing is refused until "
                               "the relay URL is https (Settings -> Mobile app)")
                except Exception:
                    pass
            frame = _pull(relay, room)
            if errs:
                try:
                    from spine.storage import events
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
                    from spine.storage import events
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
    from spine.storage import events
    from spine.comms import e2ee
    rel = dict(events.settings().get("relay") or {})
    if insecure_url(rel.get("url", "")):
        # Refuse BEFORE opening the window or minting anything: the code this
        # payload becomes embeds a live device token in a plain-http URL.
        raise ValueError("relay url is plain http:// - the pairing link would "
                         "carry a live device token unencrypted. Use the HTTPS "
                         "relay URL (ops/deploy/README.md), or http://localhost "
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



# -- Claim codes: pairing for a device with no camera and no keyboard -------
#
# The existing pairing_payload() -> QR flow assumes the new device can SCAN
# (a camera) and, per applyPairing() in config.ts, decode a base64 JSON blob
# from a link. A Wear OS watch commonly has NEITHER: most models ship no
# camera at all, and WO-P6 (Play's own quality bar) forbids a password/text
# prompt on the wrist anyway. What it DOES have, established and cited
# elsewhere in this card (ops/docs/backlog/wear-os-integration/README.md
# §5): a microphone, via ACTION_RECOGNIZE_SPEECH.
#
# So this is glasses-reference.md §2.1/§2.2's device-code pattern, imported
# for real this time (the doc's own words: "the confusable-free alphabet and
# the single-use hand-over are the details worth importing" - never actually
# built until now). The owner reads a short SPOKEN code off the phone/desktop
# and dictates it to the watch; GET /relay/pair/claim (routes_relay.py,
# deliberately UNAUTHENTICATED - the claiming device has no session yet,
# same as pair_pending already accepts for the QR path) trades it in exactly
# once for the SAME payload shape /relay/pair already returns.
#
# In-memory only, never settings.json: the stashed payload carries a LIVE
# bearer token (auth.issue_token's plaintext, same one the QR embeds), and
# unlike rel.sk this has no reason to survive a daemon restart - an
# unclaimed code just expires, the same degradation PAIR_TTL already accepts
# for the QR flow.
CLAIM_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no I/O/0/1/L - a spoken
# or misheard code must never resolve to a DIFFERENT valid one, only to no
# code at all (glasses-reference.md §2.2, quoted verbatim in this repo).
CLAIM_CODE_LEN = 6
CLAIM_TTL = PAIR_TTL  # same 15-minute window as the QR path - one policy

_claim_lock = threading.Lock()
_claims = {}  # code -> {"payload": {...}, "expires": ts}


def mint_claim_code(payload):
    """Stash a full pairing payload behind a short, speakable code. Returns
    (code, ttl_seconds). The caller (routes_relay.py) builds `payload` -
    this function does not know or care that it contains a device token,
    exactly like relay_client otherwise knows nothing about auth.py."""
    import random
    with _claim_lock:
        now = time.time()
        for c in [c for c, v in _claims.items() if v["expires"] < now]:
            del _claims[c]  # opportunistic sweep; this map is never large
        code = "".join(random.SystemRandom().choice(CLAIM_ALPHABET)
                       for _ in range(CLAIM_CODE_LEN))
        _claims[code] = {"payload": payload, "expires": now + CLAIM_TTL}
        return code, CLAIM_TTL


def claim_code(code):
    """Single-use: the payload comes back exactly once, then the code is
    gone - same hand-over discipline _admit() already applies to
    pair_pending. Unknown, expired, and already-claimed all return None
    INDISTINGUISHABLY on purpose: unlike the QR path (where a device has
    already proven it holds a pinned key before it sees a detailed reason),
    this route is reachable by anyone who can guess a 6-character code, so it
    must not become an oracle that confirms which codes ever existed."""
    code = (code or "").strip().upper()
    with _claim_lock:
        rec = _claims.pop(code, None)
    if not rec or rec["expires"] < time.time():
        return None
    return rec["payload"]


def unpair():
    """Revoke mobile access outright: forget every pinned device AND rotate
    room + keypair, so every pairing code/QR/link ever issued is dead - a
    deterministic kill-switch, not just "let the next phone pin itself". The
    push token goes too (it belongs to the unpaired phone)."""
    import os, base64
    from spine.storage import events
    from spine.comms import e2ee
    rel = dict(events.settings().get("relay") or {})
    sk, _ = e2ee.generate_keypair()
    rel.update({"sk": e2ee.export_sec(sk),
                "room": base64.urlsafe_b64encode(os.urandom(12)).decode().rstrip("="),
                "phone_pub": "", "phone_pubs": [], "pair_pending": None})
    push = dict(events.settings().get("push") or {})
    push["fcm_token"] = ""
    # W2d: the watch (and any further device) registers its own push slot under
    # its pubkey. Unpairing rotates the keys and empties phone_pubs, so
    # notify.recipients() would already drop them - this clears the now-dead
    # entries too, so settings.json does not keep stale FCM tokens around.
    push["devices"] = {}
    events.save_settings({"relay": rel, "push": push})
    try:
        events.log("relay", "unpaired - room + keys rotated, all issued codes revoked")
    except Exception:
        pass
    return {"ok": True}
