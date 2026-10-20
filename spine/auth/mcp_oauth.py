# -*- coding: utf-8 -*-
"""OAuth 2.1 for the MCP door (MCP spec "Authorization", 2025-06-18).

A standard MCP client (Claude Code, Cursor, ...) is given ONLY the server URL.
On 401 it reads the protected-resource metadata (RFC 9728), finds this
authorization server (RFC 8414), registers itself (RFC 7591, public client)
and runs authorization code + PKCE (S256) in the browser. The consent step is
HelmDeck's own share link: /authorize asks for the link (or its hdc_ code) the
member sent, redeems it ONCE (access_grants.claim) and hands the resulting
grant token back through the code exchange. So OAuth adds no new way in - it
is a standard wrapper around the same one-time claim.

`base` is the resource URL as the CLIENT sees it: https://<relay>/mcp/<alias>
through the door, http://<host>/mcp on the LAN. Everything is addressed under
it; the token is only valid at this resource (it is a grant token, which only
/mcp accepts) - the audience binding the spec asks for.

Pending authorization codes live in memory for CODE_TTL seconds: a daemon
restart in the middle of a login costs that login, nothing more.
"""
import base64
import hashlib
import html
import json
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlsplit

from spine.auth import access_grants
from spine.storage import db

CODE_TTL = 120
NAME_MAX = 100
URIS_MAX = 5
_codes = {}       # code -> {client_id, redirect_uri, challenge, token, expires, at}


def _json(code, obj, extra=None):
    return code, "application/json", json.dumps(obj), dict(extra or {}, **{"Cache-Control": "no-store"})


def _err(code, error, desc=""):
    return _json(code, {"error": error, "error_description": desc} if desc else {"error": error})


def prm_url(base):
    """Where the protected-resource metadata of `base` lives (RFC 9728 3.1):
    the well-known segment goes between host and path."""
    u = urlsplit(base)
    return "%s://%s/.well-known/oauth-protected-resource%s" % (u.scheme, u.netloc, u.path)


def www_authenticate(base):
    return 'Bearer realm="helmdeck", resource_metadata="%s"' % prm_url(base)


def protected_resource(base):
    return {"resource": base, "authorization_servers": [base],
            "bearer_methods_supported": ["header"], "resource_name": "HelmDeck"}


def server_metadata(base):
    return {"issuer": base,
            "authorization_endpoint": base + "/authorize",
            "token_endpoint": base + "/token",
            "registration_endpoint": base + "/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"]}


def _redirect_ok(uri):
    """https anywhere, or http on loopback (native/CLI clients) - RFC 8252."""
    try:
        u = urlsplit(uri)
    except ValueError:
        return False
    if u.fragment or not u.netloc:
        return False
    if u.scheme == "https":
        return True
    return u.scheme == "http" and (u.hostname or "") in ("127.0.0.1", "localhost", "::1")


def register(body):
    try:
        req = json.loads(body or "{}")
    except ValueError:
        return _err(400, "invalid_client_metadata", "body must be JSON")
    uris = req.get("redirect_uris")
    if (not isinstance(uris, list) or not uris or len(uris) > URIS_MAX
            or not all(isinstance(u, str) and len(u) < 500 and _redirect_ok(u) for u in uris)):
        return _err(400, "invalid_redirect_uri", "https or loopback http redirect URIs only")
    name = str(req.get("client_name") or "MCP client")[:NAME_MAX]
    cid = "mcpc_" + secrets.token_urlsafe(12)
    db.mcp_client_put(cid, name, uris)
    return _json(201, {"client_id": cid, "client_name": name, "redirect_uris": uris,
                       "token_endpoint_auth_method": "none",
                       "grant_types": ["authorization_code"], "response_types": ["code"],
                       "client_id_issued_at": int(time.time())})


_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>Connect to HelmDeck</title><style>
body{font:15px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;max-width:520px;margin:0 auto;padding:32px 18px;color:#1d1d1f;background:#fafafa}
h1{font-size:21px;margin:0 0 6px}.sub{color:#6e6e73}input{width:100%%;box-sizing:border-box;font:14px ui-monospace,Consolas,monospace;padding:10px;border:1px solid #d2d2d7;border-radius:10px;margin:14px 0}
button{border:0;border-radius:10px;padding:10px 18px;background:#0a66ff;color:#fff;font-size:14px;cursor:pointer}.err{color:#c0392b}
@media (prefers-color-scheme:dark){body{background:#111;color:#eee}.sub{color:#999}input{background:#1c1c1e;color:#eee;border-color:#333}}
</style></head><body><h1>Connect %(client)s to HelmDeck</h1>
<p class="sub">Paste the HelmDeck link someone shared with you. It works once: after this, %(client)s holds the access and the link opens nothing.</p>
%(error)s<form method="post" action="%(action)s">%(hidden)s
<input name="link" placeholder="https://.../mcp/...#c=hdc_..." autocomplete="off" autofocus required>
<button type="submit">Connect</button></form></body></html>"""


def _authorize_params(q):
    p = {k: (q.get(k) or [""])[0] for k in
         ("response_type", "client_id", "redirect_uri", "code_challenge",
          "code_challenge_method", "state", "resource")}
    c = db.mcp_client_get(p["client_id"])
    if not c or p["redirect_uri"] not in c["redirect_uris"]:
        return None, None, "unknown client or redirect_uri"
    return p, c, ""


def _redirect(uri, **params):
    sep = "&" if urlsplit(uri).query else "?"
    return 302, "text/plain", "", {"Location": uri + sep + urlencode(
        {k: v for k, v in params.items() if v})}


def authorize_get(query, base, error=""):
    p, c, why = _authorize_params(parse_qs(query))
    if not p:
        # never redirect to an unverified URI (open redirector) - say it here
        return 400, "text/html; charset=utf-8", "<p>%s</p>" % html.escape(why), {}
    if p["response_type"] != "code" or p["code_challenge_method"] != "S256" or not p["code_challenge"]:
        return _redirect(p["redirect_uri"], error="invalid_request",
                         error_description="authorization code with PKCE S256 required", state=p["state"])
    if p["resource"] and p["resource"].rstrip("/") != base.rstrip("/"):
        return _redirect(p["redirect_uri"], error="invalid_target", state=p["state"])
    hidden = "".join('<input type="hidden" name="%s" value="%s">' % (k, html.escape(v, quote=True))
                     for k, v in p.items())
    body = _PAGE % {"client": html.escape(c["name"]), "action": html.escape(base + "/authorize", quote=True),
                    "hidden": hidden, "error": '<p class="err">%s</p>' % html.escape(error) if error else ""}
    return 200, "text/html; charset=utf-8", body, {"Cache-Control": "no-store",
                                                    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'",
                                                    "X-Frame-Options": "DENY"}


def authorize_post(body, base):
    q = parse_qs(body or "")
    p, c, why = _authorize_params(q)
    if not p:
        return 400, "text/html; charset=utf-8", "<p>%s</p>" % html.escape(why), {}
    link = (q.get("link") or [""])[0].strip()
    code_in = link.split("c=", 1)[1].split("&")[0] if "c=" in link else link
    try:
        hit = access_grants.claim(code_in)
    except access_grants.SealedOnly:
        return authorize_get(urlencode(p), base, error="This link works only end-to-end. Use the "
                             "helmdeck-mcp bridge (option 1 on the link's page) instead of signing in here.")
    if not hit:
        return authorize_get(urlencode(p), base,
                             error="That link was already used, revoked or has expired. Ask for a new one.")
    token, g = hit
    code = secrets.token_urlsafe(24)
    now = time.time()
    for k in [k for k, v in _codes.items() if v["expires"] < now]:
        _codes.pop(k, None)
    _codes[code] = {"client_id": p["client_id"], "redirect_uri": p["redirect_uri"],
                    "challenge": p["code_challenge"], "token": token,
                    "token_expires": g["expires"], "expires": now + CODE_TTL}
    return _redirect(p["redirect_uri"], code=code, state=p["state"])


def token(body, base):
    q = {k: (v or [""])[0] for k, v in parse_qs(body or "").items()}
    if q.get("grant_type") != "authorization_code":
        return _err(400, "unsupported_grant_type")
    pend = _codes.pop(q.get("code", ""), None)       # single use, even on failure
    if not pend or pend["expires"] < time.time():
        return _err(400, "invalid_grant", "unknown or expired code")
    if q.get("client_id") != pend["client_id"] or q.get("redirect_uri") != pend["redirect_uri"]:
        return _err(400, "invalid_grant", "client or redirect_uri mismatch")
    if q.get("resource") and q["resource"].rstrip("/") != base.rstrip("/"):
        return _err(400, "invalid_target")
    verifier = q.get("code_verifier", "")
    digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii", "ignore")).digest()).decode().rstrip("=")
    if not verifier or not secrets.compare_digest(digest, pend["challenge"]):
        return _err(400, "invalid_grant", "PKCE verification failed")
    return _json(200, {"access_token": pend["token"], "token_type": "Bearer",
                       "expires_in": max(0, int(pend["token_expires"] - time.time()))})


def route(method, sub, query, body, base):
    """The OAuth surface under `base`. sub is the path below it ('authorize',
    'token', 'register', 'wk/prm', 'wk/as'). Returns (status, ctype, body,
    headers) or None when `sub` is not OAuth."""
    if sub == "wk/prm" and method == "GET":
        return _json(200, protected_resource(base))
    if sub == "wk/as" and method == "GET":
        return _json(200, server_metadata(base))
    if sub == "register" and method == "POST":
        return register(body)
    if sub == "authorize":
        return authorize_get(query, base) if method == "GET" else authorize_post(body, base)
    if sub == "token" and method == "POST":
        return token(body, base)
    return None


def split_path(path):
    """Direct (LAN) request path -> sub, or None. Accepts /mcp/<sub> and the
    root well-known forms for the resource /mcp."""
    p = path.split("?")[0]
    if p in ("/.well-known/oauth-protected-resource/mcp", "/.well-known/oauth-protected-resource",
             "/mcp/.well-known/oauth-protected-resource"):
        return "wk/prm"
    if p in ("/.well-known/oauth-authorization-server/mcp", "/.well-known/oauth-authorization-server",
             "/mcp/.well-known/oauth-authorization-server", "/.well-known/openid-configuration/mcp",
             "/mcp/.well-known/openid-configuration"):
        return "wk/as"
    if p in ("/mcp/authorize", "/mcp/token", "/mcp/register"):
        return p[5:]
    return None
