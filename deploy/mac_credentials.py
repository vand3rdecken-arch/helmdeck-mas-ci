# -*- coding: utf-8 -*-
"""Mint a macOS Developer ID Application certificate via the App Store
Connect API, then hand it to the desktop-mac.yml workflow as a CI secret.

There is no Xcode/Keychain on this box (same constraint as
deploy/ios_credentials.sh), but Developer ID certs never needed Keychain in
the first place: a CSR is a standard PKCS#10 request, openssl builds one on
any OS, and the App Store Connect API signs it - the SAME Admin-role .p8 key
deploy/ios_credentials.sh already uses (DEPLOY.md 2b), since ASC API key
scopes are account-wide, not per-platform.

  py -3.12 deploy/mac_credentials.py --check
      Read-only. Mints a JWT, lists existing DEVELOPER_ID_APPLICATION certs
      and their expiry. Safe to run any time - creates nothing, costs no
      quota. Run this FIRST: Apple caps how many Developer ID certs an
      account may hold, so re-minting one that already exists just burns it.

  py -3.12 deploy/mac_credentials.py --create [--out DIR] [--password PW]
      Generates a private key + CSR locally (openssl, never touches the
      account), POSTs the CSR to Apple, and bundles the signed cert + key
      into a password-protected .p12. This DOES consume account quota - a
      real certificate is minted. --out defaults to a folder OUTSIDE the
      repo (mirrors ios_credentials.sh's refusal to let the .p8 sit inside
      one); --password defaults to a fresh random one, printed once since
      Apple-style secrets are not re-servable.

  py -3.12 deploy/mac_credentials.py --secrets FILE.p12 --password PW
      Separate, deliberate step: base64s the .p12 and runs
      `gh secret set MAC_CSC_LINK` / `MAC_CSC_KEY_PASSWORD` against the
      release repo (DEPLOY.md 1c - the two secrets desktop-mac.yml reads to
      switch from an unsigned build to a signed one). Requires `gh auth
      status` to already be logged in; never printed, never guessed.

Reads ASC_* from .env exactly like deploy/asc_build_state.py and
deploy/ios_credentials.sh do - same three values, same file, same key.
"""
import base64
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

import jwt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GH_REPO = os.environ.get("HELMDECK_GH_REPO", "Tienduyvo/helmdeck")


def _env():
    path = os.path.join(ROOT, ".env")
    env = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8-sig"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    for k in ("ASC_KEY_ID", "ASC_ISSUER_ID", "ASC_API_KEY_PATH"):
        env.setdefault(k, os.environ.get(k, ""))
    missing = [k for k in ("ASC_KEY_ID", "ASC_ISSUER_ID", "ASC_API_KEY_PATH") if not env.get(k)]
    if missing:
        fail("missing %s - see .env (DEPLOY.md 2b); this script reads the "
             "SAME three values as deploy/ios_credentials.sh" % ", ".join(missing))
    if not os.path.exists(env["ASC_API_KEY_PATH"]):
        fail("no .p8 at %s" % env["ASC_API_KEY_PATH"])
    return env


def fail(msg):
    print("!!! %s" % msg, file=sys.stderr)
    sys.exit(1)


def _token(env):
    now = int(time.time())
    return jwt.encode(
        {"iss": env["ASC_ISSUER_ID"], "iat": now, "exp": now + 600,
         "aud": "appstoreconnect-v1"},
        open(env["ASC_API_KEY_PATH"]).read(),
        algorithm="ES256", headers={"kid": env["ASC_KEY_ID"], "typ": "JWT"})


def _api(env, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        "https://api.appstoreconnect.apple.com" + path, data=data, method=method,
        headers={"Authorization": "Bearer " + _token(env),
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as ex:
        body = ex.read().decode(errors="replace")
        fail("ASC API %s %s -> HTTP %s: %s" % (method, path, ex.code, body[:500]))


def _run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        fail("command failed: %s\n%s" % (" ".join(cmd), r.stderr))
    return r.stdout


# --- --check -----------------------------------------------------------
def cmd_check():
    env = _env()
    print("==> ASC key %s (issuer %s) from %s" % (env["ASC_KEY_ID"], env["ASC_ISSUER_ID"], env["ASC_API_KEY_PATH"]))
    d = _api(env, "GET", "/v1/certificates?filter[certificateType]=DEVELOPER_ID_APPLICATION&limit=50")
    rows = d.get("data", [])
    if not rows:
        print("==> no existing Developer ID Application certificate - --create is safe")
        return
    print("==> %d existing Developer ID Application certificate(s):" % len(rows))
    for c in rows:
        a = c["attributes"]
        print("    id=%s  serial=%s  expires=%s  name=%s"
              % (c["id"], a.get("serialNumber"), a.get("expirationDate"), a.get("displayName")))
    print("==> re-running --create mints ANOTHER one against the account's quota - "
          "reuse an existing cert's .p12 if you already have it saved, don't re-mint blindly")


# --- --create ------------------------------------------------------------
def cmd_create(out_dir, password):
    env = _env()
    out_dir = os.path.abspath(out_dir)
    if out_dir == ROOT or out_dir.startswith(ROOT + os.sep):
        fail("--out sits INSIDE the repo (%s) - a private key + .p12 must never be "
             "committable, point --out somewhere outside the repo, e.g. C:/hd/secrets" % out_dir)
    os.makedirs(out_dir, exist_ok=True)

    key_path = os.path.join(out_dir, "mac_developer_id.key.pem")
    csr_path = os.path.join(out_dir, "mac_developer_id.csr.pem")
    cert_path = os.path.join(out_dir, "mac_developer_id.cert.pem")
    p12_path = os.path.join(out_dir, "mac_developer_id.p12")

    print("==> generating private key + CSR (openssl, local only, no account contact yet)")
    _run(["openssl", "genrsa", "-out", key_path, "2048"])
    _run(["openssl", "req", "-new", "-key", key_path, "-out", csr_path,
          "-subj", "/CN=HelmDeck Developer ID Application/O=HelmDeck"])

    csr_b64 = base64.b64encode(open(csr_path, "rb").read()).decode()
    print("==> POSTing CSR to App Store Connect (certificateType=DEVELOPER_ID_APPLICATION) - "
          "this MINTS a real certificate against the account's quota")
    d = _api(env, "POST", "/v1/certificates", {
        "data": {
            "type": "certificates",
            "attributes": {"certificateType": "DEVELOPER_ID_APPLICATION", "csrContent": csr_b64},
        }
    })
    cert = d["data"]
    a = cert["attributes"]
    raw = base64.b64decode(a["certificateContent"])
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tf.write(raw)
        raw_path = tf.name
    try:
        der = subprocess.run(["openssl", "x509", "-inform", "DER", "-in", raw_path, "-out", cert_path],
                              capture_output=True, text=True)
        if der.returncode != 0:
            pem = subprocess.run(["openssl", "x509", "-inform", "PEM", "-in", raw_path, "-out", cert_path],
                                  capture_output=True, text=True)
            if pem.returncode != 0:
                fail("certificateContent from Apple parsed as neither DER nor PEM:\nDER: %s\nPEM: %s"
                     % (der.stderr, pem.stderr))
    finally:
        os.unlink(raw_path)

    pw = password or secrets.token_urlsafe(24)
    _run(["openssl", "pkcs12", "-export", "-inkey", key_path, "-in", cert_path,
          "-out", p12_path, "-passout", "pass:%s" % pw, "-name", "HelmDeck Developer ID Application"])

    print("==> minted: id=%s serial=%s expires=%s" % (cert["id"], a.get("serialNumber"), a.get("expirationDate")))
    print("==> wrote %s" % p12_path)
    print("==> p12 password (save this now, shown once): %s" % pw)
    print("==> next: py -3.12 deploy/mac_credentials.py --secrets %s --password <the password above>" % p12_path)


# --- --secrets -----------------------------------------------------------
def cmd_secrets(p12_path, password):
    if not password:
        fail("--password required (the one --create printed)")
    if not os.path.exists(p12_path):
        fail("no .p12 at %s" % p12_path)
    who = _run(["gh", "auth", "status"])
    print(who.strip() if who.strip() else "==> gh authenticated")
    b64 = base64.b64encode(open(p12_path, "rb").read()).decode()
    print("==> gh secret set MAC_CSC_LINK --repo %s" % GH_REPO)
    subprocess.run(["gh", "secret", "set", "MAC_CSC_LINK", "--repo", GH_REPO, "--body", b64], check=True)
    print("==> gh secret set MAC_CSC_KEY_PASSWORD --repo %s" % GH_REPO)
    subprocess.run(["gh", "secret", "set", "MAC_CSC_KEY_PASSWORD", "--repo", GH_REPO, "--body", password], check=True)
    print("==> done - re-run .github/workflows/desktop-mac.yml, it will now sign the build")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--check" in args:
        cmd_check()
    elif "--create" in args:
        out_dir = args[args.index("--out") + 1] if "--out" in args else "C:/hd/secrets"
        pw = args[args.index("--password") + 1] if "--password" in args else None
        cmd_create(out_dir, pw)
    elif "--secrets" in args:
        p12 = args[args.index("--secrets") + 1]
        pw = args[args.index("--password") + 1] if "--password" in args else None
        cmd_secrets(p12, pw)
    else:
        print(__doc__)
        sys.exit(2)
