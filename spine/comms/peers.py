# -*- coding: utf-8 -*-
"""Connections to OTHER HelmDeck instances - the client side of the MCP door.

Another instance (another PC, another person) issues a share link for some of
its rooms/cards (spine/auth/access_grants.py there). An account here pastes it:
add() redeems the one-time code END-TO-END (sealed to the other daemon's key
from the link fragment, the shim's protocol - surfaces/mcp-shim), stores the
token encrypted for THIS account (peer_links, DPAPI), and caches the remote
scope. From then on:
  - the app shows those rooms next to its own (routes_peers -> call());
  - Henry's chat for that account gets each connection as an MCP server
    (peer_mcp.py, a stdio proxy that reads the token itself - it never rides
    in a file, an argv or an env var).

ONE OWNER: every remote call goes through call()/raw(), every write of a
connection through add()/remove()/_save(). The token is decrypted only inside
_token() and never leaves this module except into the sealed envelope.
"""
import base64
import json
import secrets
import time
import urllib.error
import urllib.request
from urllib.parse import parse_qs, unquote, urlsplit

from spine.storage import db

TIMEOUT = 60
LABEL_MAX = 60
MAX_PER_ACCOUNT = 20


class PeerError(Exception):
    pass


def parse_link(link):
    """<https://relay>/mcp/<alias>#c=<code>&k=<daemon key> -> (url, code, key)."""
    try:
        u = urlsplit((link or "").strip())
    except ValueError:
        raise PeerError("not a HelmDeck link")
    frag = parse_qs(u.fragment)
    path = u.path.rstrip("/")
    if u.scheme not in ("https", "http") or "/mcp/" not in path or not u.netloc:
        raise PeerError("not a HelmDeck link")
    from spine.comms import relay_client
    if relay_client.insecure_url(link):
        raise PeerError("the link is plain http to another machine - refused")
    code, key = (frag.get("c") or [""])[0], (frag.get("k") or [""])[0]
    if not code or not key:
        raise PeerError("the link has no code or no key (#c=...&k=...) - ask for a new one")
    return "%s://%s%s" % (u.scheme, u.netloc, path), code, unquote(key)


def _sealed_call(url, door_pub, inner_body, auth=""):
    """POST one request sealed to the remote daemon; return its {status, body}."""
    from spine.comms import e2ee
    try:
        peer = e2ee.import_pub(door_pub)
    except Exception:                                        # noqa: BLE001
        raise PeerError("the link's key is not valid")
    sk, pk = e2ee.generate_keypair()
    inner = {"body": inner_body, "auth": auth, "ts": time.time(), "n": secrets.token_hex(12)}
    env = json.dumps({"sealed": 1, "pub": e2ee.export_pub(pk),
                      "cipher": e2ee.seal_b64(json.dumps(inner).encode("utf-8"), sk, peer)}).encode("utf-8")
    req = urllib.request.Request(url, data=env, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "helmdeck-peer/1"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            outer = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise PeerError("the other HelmDeck answered HTTP %s" % e.code)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise PeerError("the other HelmDeck is not reachable: %s" % str(e)[:120])
    try:
        return json.loads(e2ee.open_b64(outer["cipher"], sk, peer))
    except Exception:                                        # noqa: BLE001
        raise PeerError("the answer was not sealed by the other HelmDeck")


def _token(p):
    from spine.storage import usersecrets
    return usersecrets.decrypt(p["account"], "peer:" + p["id"], p["token_enc"])


def raw(account, pid, body):
    """Forward ONE JSON-RPC message (text) to the remote MCP door; return the
    reply text ('' for a notification). The stdio proxy's whole job."""
    p = db.peer_get(account, pid)
    if not p:
        raise PeerError("no such connection")
    res = _sealed_call(p["url"], p["door_pub"], body, "Bearer " + _token(p))
    st = res.get("status")
    if st == 401:
        _save(p, err="the other side revoked or expired this access")
        raise PeerError("access revoked or expired")
    if st not in (200, 202):
        raise PeerError("the other HelmDeck answered %s" % st)
    return res.get("body") or ""


def call(account, pid, tool, args=None):
    """tools/call on the remote; returns the tool's structured result (dict).
    Raises PeerError with the remote's message when the tool refused."""
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": tool, "arguments": args or {}}})
    reply = json.loads(raw(account, pid, body) or "{}")
    if "error" in reply:
        raise PeerError(reply["error"].get("message") or "remote error")
    res = reply.get("result") or {}
    text = ((res.get("content") or [{}])[0]).get("text", "")
    if res.get("isError"):
        raise PeerError(text or "refused")
    if isinstance(res.get("structuredContent"), dict):
        return res["structuredContent"]
    try:
        return json.loads(text)
    except ValueError:
        return {"text": text}


def _save(p, **changes):
    p = dict(p, **changes)
    db.peer_put(p)
    return p


def public(p):
    """What the account sees of a connection - never the token."""
    return {"id": p["id"], "label": p["label"], "url": p["url"], "hint": p["hint"],
            "info": p["info"], "created": p["created"], "checked": p.get("checked"),
            "err": p.get("err") or ""}


def refresh(account, pid):
    """Re-read the remote scope (rooms/cards + names) into the cached info."""
    p = db.peer_get(account, pid)
    if not p:
        raise PeerError("no such connection")
    try:
        sc = call(account, pid, "helmdeck_scope")
    except PeerError as e:
        return public(_save(db.peer_get(account, pid) or p, checked=time.time(), err=str(e)))
    info = {"as": sc.get("you_are", ""), "for": sc.get("on_behalf_of", ""),
            "expires": sc.get("expires"), "scope": sc.get("scope") or []}
    return public(_save(p, info=info, checked=time.time(), err=""))


def add(account, link, label=""):
    from spine.storage import usersecrets
    if not usersecrets.available():
        raise PeerError("no at-rest encryption on this machine - connections need Windows DPAPI")
    if len(db.peers_of(account)) >= MAX_PER_ACCOUNT:
        raise PeerError("at most %d connections per account" % MAX_PER_ACCOUNT)
    url, code, key = parse_link(link)
    res = _sealed_call(url, key, json.dumps({"claim": code}))
    if res.get("status") != 200:
        try:
            msg = json.loads(res.get("body") or "{}").get("error")
        except ValueError:
            msg = None
        raise PeerError(msg or "the link could not be redeemed")
    got = json.loads(res["body"])
    pid = "pl" + secrets.token_hex(5)
    token = got["token"]
    label = (label or "").strip()[:LABEL_MAX] or "%s (%s)" % (got.get("issuer") or "HelmDeck", got.get("label") or "")
    p = {"id": pid, "account": account, "label": label, "url": url, "door_pub": key,
         "token_enc": usersecrets.encrypt(account, "peer:" + pid, token), "hint": token[-4:],
         "info": {}, "created": time.time(), "checked": None, "err": ""}
    db.peer_put(p)
    _emit("add", account, peer=pid, url=url)
    return refresh(account, pid)


def remove(account, pid):
    n = db.peer_delete(account, pid)
    if n:
        _emit("remove", account, peer=pid)
    return bool(n)


def mine(account):
    return [public(p) for p in db.peers_of(account)]


def drop_user(account):
    return db.peers_drop_user(account)


def mcp_servers(account):
    """{server name: stdio config} - one per connection of `account`, for any
    claude spawn that acts for that account (Henry's chat, its cards). The
    entry carries NO secret: spine/comms/peer_mcp.py decrypts the token itself.
    PYTHONPATH, not "cwd": the CLI does not honour cwd for stdio servers
    (measured: CONNECTION_CLOSED, module not found from the turn's cwd)."""
    import os, re, sys
    from daemon.paths import REPO_ROOT
    out = {}
    for c in (db.peers_of(account) if account else []):
        slug = re.sub(r"[^a-z0-9]+", "_", (c.get("label") or "").lower()).strip("_")[:24] or "peer"
        env = {"PYTHONPATH": REPO_ROOT}
        if os.environ.get("HELMDECK_DATA_ROOT"):
            env["HELMDECK_DATA_ROOT"] = os.environ["HELMDECK_DATA_ROOT"]
        out["helmdeck_%s_%s" % (slug, c["id"][-4:])] = {
            "type": "stdio", "command": sys.executable,
            "args": ["-m", "spine.comms.peer_mcp", account, c["id"]], "env": env}
    return out


def fingerprint(account):
    """Changes whenever the account's connections do - Henry's warm process
    is re-spawned on a change so its MCP servers match (copilot._persist_get)."""
    return ",".join(sorted(p["id"] for p in db.peers_of(account)))


def _emit(op, actor, **fields):
    try:
        from spine.storage import events
        events.emit("peer_link", "-", op=op, actor=actor, **fields)
    except Exception:                                        # noqa: BLE001
        pass
