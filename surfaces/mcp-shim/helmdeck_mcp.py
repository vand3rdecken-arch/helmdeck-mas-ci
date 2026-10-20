#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""helmdeck-mcp - an END-TO-END encrypted bridge from any MCP client to a
HelmDeck daemon.

    claude mcp add helmdeck -- python helmdeck_mcp.py "<the HelmDeck link>"

The link someone shared with you looks like
    https://<relay>/mcp/<alias>#c=hdc_...&k=<daemon key>
This program speaks MCP over stdio to your AI tool and forwards every message
to that URL SEALED to the daemon's key (NaCl box - the same scheme HelmDeck's
phone app uses). The relay in between sees only ciphertext; your token travels
inside the seal too. The daemon's key comes from the link itself (the fragment,
which no server ever saw), so the relay cannot substitute its own.

First run redeems the one-time code and stores the token in
~/.helmdeck/mcp/<alias>.json (readable by you only). Later runs reuse it.

Needs: Python 3.8+ and PyNaCl (pip install pynacl).
"""
import base64
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit, parse_qs

try:
    from nacl.public import Box, PrivateKey, PublicKey
except ImportError:                                           # pragma: no cover
    sys.stderr.write("helmdeck-mcp needs PyNaCl: pip install pynacl\n")
    sys.exit(2)

UA = "helmdeck-mcp/1"
TIMEOUT = 130


def parse_link(link):
    u = urlsplit(link.strip())
    frag = parse_qs(u.fragment)
    url = "%s://%s%s" % (u.scheme, u.netloc, u.path.rstrip("/"))
    alias = u.path.rstrip("/").rsplit("/", 1)[-1]
    if u.scheme not in ("https", "http") or "/mcp/" not in u.path:
        raise SystemExit("not a HelmDeck MCP link: %s" % link)
    return url, alias, (frag.get("c") or [""])[0], (frag.get("k") or [""])[0]


def state_path(alias):
    d = os.path.join(os.path.expanduser("~"), ".helmdeck", "mcp")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, alias + ".json")


class Sealed:
    def __init__(self, url, daemon_pub_b64):
        if not daemon_pub_b64:
            raise SystemExit("the link carries no daemon key (&k=...) - ask for a new link")
        self.url = url
        self.peer = PublicKey(base64.b64decode(daemon_pub_b64))
        self.sk = PrivateKey.generate()                 # fresh per run
        self.box = Box(self.sk, self.peer)
        self.pub = base64.b64encode(bytes(self.sk.public_key)).decode()

    def call(self, body, auth=""):
        inner = {"body": body, "auth": auth, "ts": time.time(), "n": secrets.token_hex(12)}
        cipher = base64.b64encode(bytes(self.box.encrypt(json.dumps(inner).encode("utf-8")))).decode()
        env = json.dumps({"sealed": 1, "pub": self.pub, "cipher": cipher}).encode("utf-8")
        req = urllib.request.Request(self.url, data=env, method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                outer = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return {"status": e.code, "body": e.read().decode("utf-8", "replace")}
        res = self.box.decrypt(base64.b64decode(outer["cipher"]))   # raises on tamper
        return json.loads(res.decode("utf-8"))


def ensure_token(sealed, alias, code):
    p = state_path(alias)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            tok = json.load(f).get("token")
        if tok:
            return tok
    if not code:
        raise SystemExit("no stored access and the link has no code (#c=...)")
    r = sealed.call(json.dumps({"claim": code}))
    if r.get("status") != 200:
        raise SystemExit("could not redeem the link: %s" % (r.get("body") or r.get("status")))
    tok = json.loads(r["body"])["token"]
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"token": tok, "url": sealed.url}, f)
    return tok


def main():
    if len(sys.argv) != 2:
        sys.stderr.write(__doc__)
        return 2
    url, alias, code, k = parse_link(sys.argv[1])
    sealed = Sealed(url, k)
    token = ensure_token(sealed, alias, code)
    auth = "Bearer " + token
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        r = sealed.call(line, auth)
        st = r.get("status")
        if st == 200 and r.get("body"):
            sys.stdout.write(r["body"].strip() + "\n")
            sys.stdout.flush()
        elif st not in (200, 202) and isinstance(msg, dict) and msg.get("id") is not None:
            err = {"jsonrpc": "2.0", "id": msg["id"],
                   "error": {"code": -32000, "message": "HelmDeck: HTTP %s %s" % (st, (r.get("body") or "")[:200])}}
            sys.stdout.write(json.dumps(err) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
