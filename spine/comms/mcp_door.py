# -*- coding: utf-8 -*-
"""The PUBLIC door to /mcp: external MCP clients reach this daemon at
<relay>/mcp/<alias> without any HelmDeck pairing.

Why not the phone's relay room: MCP clients cannot seal frames, and the room
id must stay private (whoever holds it can dial /tunnel/ws and displace the
daemon). So the door is its OWN relay room, named by an alias that is
DERIVED by the worker from a secret only this daemon holds:

    alias = b64url(sha256(key))[:32]          (worker: /tunnel/mcpd?key=...)

The alias is public (it is in the shared URL); the key never leaves this
machine and the relay. Knowing the alias lets you SEND to the door, never BE
the daemon behind it.

home: settings.relay.mcp_key, because it is the same class as the relay's own
`sk`/`room` beside it - a machine-level transport credential of THIS daemon's
relay identity, rotated with it. Not access_grants (per account, per grant),
not user_secret (per account provider keys).

TWO MODES through the same door:
  - SEALED (the shim, surfaces/mcp-shim): the client encrypts every request to
    this daemon's key (NaCl box, e2ee.py, the phone's scheme); the relay sees
    ciphertext only. This is the end-to-end path.
  - DIRECT (any MCP client, OAuth or Bearer): TLS ends at Cloudflare, so the
    relay CAN read it. Offered for clients that cannot run the shim, and
    labelled so on the setup page.
Only POST /mcp and the OAuth surface (spine/auth/mcp_oauth.py) are
reachable through this socket - whatever the frame says.
"""
import base64
import hashlib
import json
import os
import threading
import time

_thread = None
_stop = False
_state = {"up": False, "since": 0.0, "err": ""}

PING_EVERY = 20.0
PING_TIMEOUT = 10.0
MAX_BODY = 1024 * 1024


def _key(create=False):
    from spine.storage import events
    rel = dict(events.settings().get("relay") or {})
    k = rel.get("mcp_key") or ""
    if not k and create:
        k = base64.urlsafe_b64encode(os.urandom(24)).decode().rstrip("=")
        rel["mcp_key"] = k
        events.save_settings({"relay": rel})
    return k, (rel.get("url") or "").rstrip("/")


def alias_of(key):
    """Must match surfaces/relay/worker/src/index.js mcpAlias()."""
    d = base64.urlsafe_b64encode(hashlib.sha256(key.encode("utf-8")).digest()).decode()
    return d.rstrip("=")[:32]


def _usable(relay):
    """https, or http to this machine's loopback (local testing) - the same
    rule relay_client applies to pairing links, since the token rides along."""
    from spine.comms import relay_client
    return relay.startswith(("https://", "http://")) and not relay_client.insecure_url(relay)


def public_url():
    """The URL an external MCP client uses, or "" when no usable relay is set."""
    k, relay = _key(create=True)
    if not _usable(relay):
        return ""
    return "%s/mcp/%s" % (relay, alias_of(k))


def state():
    return dict(_state, url=public_url())


_seen = {}         # sealed request nonce -> ts: a replayed frame is refused
SEAL_SKEW_S = 120


def _door_sk():
    from spine.comms import e2ee
    from spine.storage import events
    sk = (events.settings().get("relay") or {}).get("sk")
    return e2ee.import_sec(sk) if sk else None


def door_pub():
    """The daemon key a sealed client (the shim) encrypts to - the relay's own
    identity key, published in the share link's fragment (&k=)."""
    from spine.comms import e2ee
    sk = _door_sk()
    return e2ee.export_pub(sk.public_key) if sk else ""


def shim_sha():
    """sha256 of the end-to-end bridge as THIS daemon ships it
    (surfaces/mcp-shim/helmdeck_mcp.py). The app puts it into the share link's
    fragment (&s=), so the recipient checks the relay-served download against
    a value the relay never touched. Same bytes the worker embeds
    (gen_static.py reads this file as UTF-8 text)."""
    import hashlib, io as _io, os as _os
    from daemon.paths import REPO_ROOT
    try:
        txt = _io.open(_os.path.join(REPO_ROOT, "surfaces", "mcp-shim", "helmdeck_mcp.py"), encoding="utf-8").read()
    except OSError:
        return ""
    return hashlib.sha256(txt.encode("utf-8")).hexdigest()


def _mcp_call(body, auth, origin, base):
    from spine.comms import relay_client
    headers = {"Content-Type": "application/json", "X-Helmdeck-Base": base}
    if auth:
        headers["Authorization"] = auth
    if origin:
        headers["Origin"] = origin      # mcp._origin_ok judges it like a direct call
    r = relay_client._inproc({"method": "POST", "path": "/mcp", "body": body, "headers": headers})
    out = {"status": int(r.get("status") or 500), "body": r.get("body") or "",
           "ctype": (r.get("headers") or {}).get("Content-Type", "application/json")}
    if out["status"] == 401:
        from spine.auth import mcp_oauth
        out["headers"] = {"WWW-Authenticate": mcp_oauth.www_authenticate(base)}
    return out


def _sealed(env, base):
    """END-TO-END mode (the shim, surfaces/mcp-shim): the relay forwarded only
    {sealed, pub, cipher}; the request inside - token included - is readable
    here and nowhere on the way. Reply sealed back to the same client key."""
    from spine.comms import e2ee
    sk = _door_sk()
    if not sk:
        return {"status": 503, "body": json.dumps({"error": "no door key"})}
    try:
        peer = e2ee.import_pub(str(env.get("pub") or ""))
        inner = json.loads(e2ee.open_b64(str(env.get("cipher") or ""), sk, peer))
    except Exception:                                        # noqa: BLE001
        return {"status": 400, "body": json.dumps({"error": "cannot open sealed request"})}
    now = time.time()
    n = str(inner.get("n") or "")
    try:
        fresh = abs(now - float(inner.get("ts"))) <= SEAL_SKEW_S
    except (TypeError, ValueError):
        fresh = False
    for k in [k for k, t in _seen.items() if now - t > SEAL_SKEW_S * 2]:
        _seen.pop(k, None)
    if not n or not fresh or n in _seen:
        res = {"status": 409, "body": json.dumps({"error": "stale or replayed request"})}
    else:
        _seen[n] = now
        from spine.http import mcp as _mcp
        _mcp.SEALED.on = True          # the one proof a request came end-to-end
        try:
            res = _mcp_call(str(inner.get("body") or ""), str(inner.get("auth") or ""), "", base)
        finally:
            _mcp.SEALED.on = False
    cipher = e2ee.seal_b64(json.dumps(res).encode("utf-8"), sk, peer)
    return {"status": 200, "body": json.dumps({"cipher": cipher})}


def _answer(frame):
    """One forwarded request -> {status, body, ctype?, headers?}. Only the MCP
    resource and its OAuth surface are reachable - whatever the frame says."""
    body = frame.get("body") or ""
    if not isinstance(body, str) or len(body) > MAX_BODY:
        return {"status": 413, "body": json.dumps({"error": "body too large"})}
    # ONE canonical resource URL (OAuth issuer + audience): this daemon's own
    # configured relay, never the host a request happened to arrive on (the
    # worker answers on its custom domain AND workers.dev; wrangler dev
    # rewrites the host) - so metadata, 401 hints and tokens always agree
    base = public_url() or str(frame.get("base") or "")
    sub = str(frame.get("sub") or "")
    method = str(frame.get("method") or "POST").upper()
    if sub:
        from spine.auth import mcp_oauth
        out = mcp_oauth.route(method, sub, str(frame.get("query") or ""), body, base)
        if out is None:
            return {"status": 404, "body": json.dumps({"error": "not found"})}
        code, ctype, text, headers = out
        return {"status": code, "ctype": ctype, "body": text, "headers": headers}
    try:
        env = json.loads(body) if body.startswith("{") else None
    except ValueError:
        env = None
    if isinstance(env, dict) and env.get("sealed"):
        return _sealed(env, base)
    return _mcp_call(body, str(frame.get("auth") or ""), str(frame.get("origin") or ""), base)


def _session(relay, key):
    from websockets.sync.client import connect
    from urllib.parse import quote
    scheme, rest = relay.split("://", 1)
    url = ("wss" if scheme == "https" else "ws") + "://" + rest + "/tunnel/mcpd?key=" + quote(key, safe="")
    ws = connect(url, open_timeout=15, close_timeout=5, ping_interval=PING_EVERY,
                 ping_timeout=PING_TIMEOUT, max_size=MAX_BODY * 2)
    lock = threading.Lock()

    def reply(fid, out):
        with lock:
            ws.send(json.dumps({"kind": "reply", "id": fid, **out}))

    def serve(frame):
        try:
            out = _answer(frame)
        except Exception as e:                               # noqa: BLE001
            out = {"status": 500, "body": json.dumps({"error": str(e)[:200]})}
        try:
            reply(frame["id"], out)
        except Exception:                                    # noqa: BLE001
            pass       # the socket died; the caller gets the relay's 504

    _state.update(up=True, since=time.time(), err="")
    try:
        while not _stop:
            try:
                msg = ws.recv(timeout=5)
            except TimeoutError:
                continue
            try:
                data = json.loads(msg) if isinstance(msg, str) else None
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            if data.get("kind") == "mcp" and isinstance(data.get("id"), str):
                threading.Thread(target=serve, args=(data,), daemon=True).start()
            elif data.get("kind") == "probe":
                with lock:
                    ws.send(json.dumps({"kind": "alive"}))
    finally:
        _state["up"] = False
        try:
            ws.close()
        except Exception:                                    # noqa: BLE001
            pass


def _wanted():
    """Open the door only while a grant could use it: at least one ACTIVE
    access grant exists. No grant -> no socket, no billed relay connection."""
    from spine.storage import db
    try:
        return db.conn().execute(
            "SELECT 1 FROM access_grants WHERE revoked IS NULL AND expires>? LIMIT 1",
            (time.time(),)).fetchone() is not None
    except Exception:                                        # noqa: BLE001
        return False


def _loop():
    delay = 3
    while not _stop:
        try:
            key, relay = _key()
            if not (key and _usable(relay)) or not _wanted():
                time.sleep(10)
                continue
            _session(relay, key)
            delay = 3
            time.sleep(0.5)
        except Exception as e:                               # noqa: BLE001
            _state.update(up=False, err=str(e)[:200])
            time.sleep(delay)
            delay = min(delay * 2, 60)


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _thread = threading.Thread(target=_loop, name="mcp-door", daemon=True)
    _thread.start()
