# -*- coding: utf-8 -*-
"""Daemon side of the ZERO-KNOWLEDGE relay (see relay/relay.py + e2ee.py). When
paired (settings.relay = {url, room, sk, phone_pub?}), this dials OUT to the
relay, pulls end-to-end-ENCRYPTED phone frames, decrypts them, runs the inner
request against the local daemon, and pushes an encrypted response. The relay
never sees plaintext; no inbound port is opened on the daemon.

Trust model: the phone's public key is pinned on first contact per room (TOFU)
and a later mismatch is refused, so a leaked room id can't be hijacked to talk
to your daemon."""
import json, threading, time, urllib.request, urllib.error

_thread = None
_stop = False
_pin_lock = threading.Lock()


def _cfg():
    import events
    r = events.settings().get("relay") or {}
    return ((r.get("url", "") or "").rstrip("/"), r.get("room", "") or "",
            r.get("sk", "") or "", r.get("phone_pub", "") or "")


def _pin_phone(pub):
    """Store the phone's public key on first contact; return the pinned key."""
    with _pin_lock:
        import events
        cur = (events.settings().get("relay") or {}).get("phone_pub", "") or ""
        if not cur:
            rel = dict(events.settings().get("relay") or {})
            rel["phone_pub"] = pub
            events.save_settings({"relay": rel})
            return pub
        return cur


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
    import e2ee
    fid = frame.get("id")
    pub = frame.get("pub", "")
    pinned = _pin_phone(pub)
    if pub != pinned:
        # Another device already owns this room (trust-on-first-use). Say so
        # instead of dropping the frame: silence looks exactly like "daemon
        # offline" and the caller just hangs until its timeout. The reply is
        # sealed to the caller's own key, so it leaks nothing to anyone else.
        try:
            import e2ee
            sk = e2ee.import_sec(sk_b64)
            body = json.dumps({"error": "another phone is paired with this "
                                        "workspace - unpair it first "
                                        "(Settings -> Mobile app -> Unpair)"})
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
    while not _stop:
        relay, room, sk, _ = _cfg()
        if not (relay and room and sk):
            time.sleep(5)
            continue
        try:
            frame = _pull(relay, room)
            if frame:
                threading.Thread(target=_serve_one, args=(relay, room, sk, port, frame),
                                 daemon=True).start()
        except Exception:
            time.sleep(3)


def start(port=8140):
    global _thread
    if _thread and _thread.is_alive():
        return
    _thread = threading.Thread(target=_loop, args=(port,), daemon=True)
    _thread.start()


def pairing_payload():
    """Ensure this daemon has a relay keypair + room id, and return the payload
    the phone needs to pair: relay url, room id, and the daemon's public key.
    (The phone also needs a device token for daemon auth - added by the caller.)"""
    import os, base64, events, e2ee
    rel = dict(events.settings().get("relay") or {})
    changed = False
    if not rel.get("sk"):
        sk, _ = e2ee.generate_keypair()
        rel["sk"] = e2ee.export_sec(sk)
        changed = True
    if not rel.get("room"):
        rel["room"] = base64.urlsafe_b64encode(os.urandom(12)).decode().rstrip("=")
        changed = True
    # Issuing a new pairing code means "let a phone in" - keeping the previously
    # pinned device would silently refuse the very phone the owner is pairing.
    if rel.get("phone_pub"):
        rel["phone_pub"] = ""
        changed = True
    if changed:
        events.save_settings({"relay": rel})
    sk = e2ee.import_sec(rel["sk"])
    return {"url": rel.get("url", ""), "room": rel["room"],
            "daemon_pub": e2ee.export_pub(sk.public_key)}


def unpair():
    """Forget the paired phone (its pinned key), so a new phone can pair."""
    import events
    rel = dict(events.settings().get("relay") or {})
    rel["phone_pub"] = ""
    events.save_settings({"relay": rel})
    return {"ok": True}
