# -*- coding: utf-8 -*-
"""Mint macOS signing certificates via the App Store Connect API, then hand
them to a CI workflow as a secret. Covers THREE cert types that only differ
in Apple's certificateType string and what they're for:

  developer-id    DEVELOPER_ID_APPLICATION    direct-download build (desktop-mac.yml)
  mas-app         MAC_APP_DISTRIBUTION        Mac App Store .app signing
  mas-installer   MAC_INSTALLER_DISTRIBUTION  Mac App Store .pkg signing

There is no Xcode/Keychain on this box (same constraint as
ops/deploy/ios_credentials.sh), but none of these ever needed Keychain in the
first place: a CSR is a standard PKCS#10 request, openssl builds one on any
OS, and the App Store Connect API signs it - the SAME Admin-role .p8 key
ops/deploy/ios_credentials.sh already uses (DEPLOY.md 2b), since ASC API key
scopes are account-wide, not per-platform.

  py -3.12 ops/deploy/mac_credentials.py --check [--type TYPE]
      Read-only. Mints a JWT, lists existing certs of TYPE (default
      developer-id) and their expiry. Safe to run any time - creates
      nothing, costs no quota. Run this FIRST: Apple caps how many certs of
      a given type an account may hold, so re-minting one that already
      exists just burns it.

  py -3.12 ops/deploy/mac_credentials.py --create [--type TYPE] [--out DIR] [--password PW]
      Generates a private key + CSR locally (openssl, never touches the
      account) and tries to POST the CSR to Apple. --out defaults to a
      folder OUTSIDE the repo (mirrors ios_credentials.sh's refusal to let
      the .p8 sit inside one).

      VERIFIED 2026-08-15 for developer-id against the real account: the
      POST comes back HTTP 403 "This operation can only be performed by the
      Account Holder" - EVERY API key hits this, regardless of role (Admin
      included), because Apple treats Developer ID Application certificate
      creation the same as ASC-key management and push keys
      (ops/deploy/ios_credentials.sh's own "still demand a human Apple ID"
      section) - it is walled off from ALL API-key auth, not just this
      key's role. mas-app/mas-installer are UNVERIFIED against this same
      wall until a real --create run reports back - iOS distribution certs
      (a comparable "goes through App Review" cert) mint fine via this same
      key (ops/deploy/ios_credentials.sh), so the wall may be Developer-ID-
      specific rather than blanket. --create still attempts the POST (in
      case Apple blocks it too or ever lifts the developer-id wall), but on
      that specific 403 it stops and prints the manual step instead of
      failing blind: upload the CSR it already wrote at
      <out>/mac_<type>.csr.pem to
      https://developer.apple.com/account/resources/certificates/add
      in a real, 2FA'd Account Holder browser session (pick the matching
      cert kind - "Developer ID Application", "Mac App Distribution" or
      "Mac Installer Distribution"), download the resulting .cer, then
      run --finish.

  py -3.12 ops/deploy/mac_credentials.py --finish CERT_PATH [--type TYPE] [--key KEY_PATH]
                                      [--out DIR] [--password PW]
      Second half of --create once a human has done the one step no API
      key can: bundles the manually-downloaded .cer with the private key
      --create already generated (--key defaults to
      <out>/mac_<type>.key.pem) into a password-protected .p12.
      --password defaults to a fresh random one, printed once since
      Apple-style secrets are not re-servable.

  py -3.12 ops/deploy/mac_credentials.py --secrets FILE.p12 --password PW [--type TYPE]
      Separate, deliberate step: base64s the .p12 and runs `gh secret set`
      against the release repo. developer-id writes MAC_CSC_LINK /
      MAC_CSC_KEY_PASSWORD (DEPLOY.md 1c); mas-app writes MAC_MAS_CSC_LINK /
      MAC_MAS_CSC_KEY_PASSWORD; mas-installer writes
      MAC_MAS_INSTALLER_CSC_LINK / MAC_MAS_INSTALLER_CSC_KEY_PASSWORD.
      Requires `gh auth status` to already be logged in; never printed,
      never guessed.

  py -3.12 ops/deploy/mac_credentials.py --bundleids
      Read-only. Lists every registered Bundle ID (App ID) and its
      platform, straight from the API - used to confirm app.helmdeck is
      registered UNIVERSAL (covers macOS, not just iOS) before trying to
      add a macOS platform to the existing App Store Connect app record.

  py -3.12 ops/deploy/mac_credentials.py --profiles
      Read-only. Lists every provisioning profile (any platform) with its
      type, state and expiry.

  py -3.12 ops/deploy/mac_credentials.py --profile-create --name NAME --bundle-id-resource ID --cert-id ID
      Creates a MAC_APP_STORE provisioning profile binding a Bundle ID
      resource id (from --bundleids) to a mas-app certificate id (from
      --check --type mas-app). Mac App Store profiles need no devices,
      same as iOS App Store profiles. Writes the downloaded
      .provisionprofile next to --out.

Reads ASC_* from .env exactly like ops/deploy/asc_build_state.py and
ops/deploy/ios_credentials.sh do - same three values, same file, same key.
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

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GH_REPO = os.environ.get("HELMDECK_GH_REPO", "Tienduyvo/helmdeck")

# short CLI name -> (Apple certificateType, file basename, GH secret pair)
CERT_TYPES = {
    "developer-id": ("DEVELOPER_ID_APPLICATION", "mac_developer_id",
                      ("MAC_CSC_LINK", "MAC_CSC_KEY_PASSWORD")),
    "mas-app": ("MAC_APP_DISTRIBUTION", "mac_app_distribution",
                 ("MAC_MAS_CSC_LINK", "MAC_MAS_CSC_KEY_PASSWORD")),
    "mas-installer": ("MAC_INSTALLER_DISTRIBUTION", "mac_installer_distribution",
                        ("MAC_MAS_INSTALLER_CSC_LINK", "MAC_MAS_INSTALLER_CSC_KEY_PASSWORD")),
}


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
             "SAME three values as ops/deploy/ios_credentials.sh" % ", ".join(missing))
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


class AccountHolderOnly(Exception):
    """Apple rejected the call with the 403 that means no API key - any
    role - can do this; only the human Account Holder can, in a 2FA'd
    browser session."""


class InvalidCertificateRequest(Exception):
    """VERIFIED 2026-09-10: MAC_APP_DISTRIBUTION and MAC_INSTALLER_DISTRIBUTION
    both 409 'Invalid Certificate' (ENTITY_ERROR.ATTRIBUTE.INVALID) from this
    same Admin-role key that mints iOS distribution certs fine - a DIFFERENT
    failure than developer-id's 403 Account-Holder wall, so it is not
    obviously the same block. Apple's message gives no more detail than
    that; whether it's a CSR-shape issue or an account-state gate (e.g. Mac
    software distribution not yet enabled for this team) can't be told apart
    from here without a from-Apple response. Same mitigation either way: a
    human, in the browser, can create the cert directly (no CSR upload
    needed) and hand the .cer to --finish."""


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
        raw = ex.read().decode(errors="replace")
        if ex.code == 403 and "Account Holder" in raw:
            raise AccountHolderOnly(raw)
        if ex.code == 409 and "Invalid Certificate" in raw:
            raise InvalidCertificateRequest(raw)
        fail("ASC API %s %s -> HTTP %s: %s" % (method, path, ex.code, raw[:500]))


def _run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        fail("command failed: %s\n%s" % (" ".join(cmd), r.stderr))
    return r.stdout


# --- --check -----------------------------------------------------------
def cmd_check(cert_type):
    env = _env()
    apple_type, _, _ = CERT_TYPES[cert_type]
    print("==> ASC key %s (issuer %s) from %s" % (env["ASC_KEY_ID"], env["ASC_ISSUER_ID"], env["ASC_API_KEY_PATH"]))
    d = _api(env, "GET", "/v1/certificates?filter[certificateType]=%s&limit=50" % apple_type)
    rows = d.get("data", [])
    if not rows:
        print("==> no existing %s certificate - --create is safe" % apple_type)
        return
    print("==> %d existing %s certificate(s):" % (len(rows), apple_type))
    for c in rows:
        a = c["attributes"]
        print("    id=%s  serial=%s  expires=%s  name=%s"
              % (c["id"], a.get("serialNumber"), a.get("expirationDate"), a.get("displayName")))
    print("==> re-running --create mints ANOTHER one against the account's quota - "
          "reuse an existing cert's .p12 if you already have it saved, don't re-mint blindly")


def _guard_out_dir(out_dir):
    out_dir = os.path.abspath(out_dir)
    if out_dir == ROOT or out_dir.startswith(ROOT + os.sep):
        fail("--out sits INSIDE the repo (%s) - a private key + .p12 must never be "
             "committable, point --out somewhere outside the repo, e.g. C:/hd/secrets" % out_dir)
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


def _normalize_cert(cert_bytes, cert_path):
    """Apple's certificateContent / a downloaded .cer can be DER or PEM -
    write whichever openssl actually accepts as PEM."""
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tf.write(cert_bytes)
        raw_path = tf.name
    try:
        der = subprocess.run(["openssl", "x509", "-inform", "DER", "-in", raw_path, "-out", cert_path],
                              capture_output=True, text=True)
        if der.returncode != 0:
            pem = subprocess.run(["openssl", "x509", "-inform", "PEM", "-in", raw_path, "-out", cert_path],
                                  capture_output=True, text=True)
            if pem.returncode != 0:
                fail("certificate parsed as neither DER nor PEM:\nDER: %s\nPEM: %s"
                     % (der.stderr, pem.stderr))
    finally:
        os.unlink(raw_path)


def _bundle_p12(key_path, cert_path, p12_path, password, label):
    pw = password or secrets.token_urlsafe(24)
    _run(["openssl", "pkcs12", "-export", "-inkey", key_path, "-in", cert_path,
          "-out", p12_path, "-passout", "pass:%s" % pw, "-name", label])
    print("==> wrote %s" % p12_path)
    print("==> p12 password (save this now, shown once): %s" % pw)
    print("==> next: py -3.12 ops/deploy/mac_credentials.py --secrets %s --password <the password above>" % p12_path)


# --- --create ------------------------------------------------------------
def cmd_create(cert_type, out_dir, password):
    env = _env()
    out_dir = _guard_out_dir(out_dir)
    apple_type, basename, _ = CERT_TYPES[cert_type]

    key_path = os.path.join(out_dir, basename + ".key.pem")
    csr_path = os.path.join(out_dir, basename + ".csr.pem")
    cert_path = os.path.join(out_dir, basename + ".cert.pem")
    p12_path = os.path.join(out_dir, basename + ".p12")

    print("==> generating private key + CSR (openssl, local only, no account contact yet)")
    _run(["openssl", "genrsa", "-out", key_path, "2048"])
    _run(["openssl", "req", "-new", "-key", key_path, "-out", csr_path,
          "-subj", "/CN=HelmDeck %s/O=HelmDeck" % apple_type])

    csr_b64 = base64.b64encode(open(csr_path, "rb").read()).decode()
    print("==> POSTing CSR to App Store Connect (certificateType=%s)" % apple_type)
    try:
        d = _api(env, "POST", "/v1/certificates", {
            "data": {
                "type": "certificates",
                "attributes": {"certificateType": apple_type, "csrContent": csr_b64},
            }
        })
    except AccountHolderOnly:
        print("==> Apple: 403 'This operation can only be performed by the Account Holder' -")
        print("    same wall confirmed for developer-id on 2026-08-15; if you're seeing this")
        print("    for %s that wall covers this type too. Manual step:" % apple_type)
        print("    1. As the Account Holder, in a real browser (Apple ID + 2FA):")
        print("       https://developer.apple.com/account/resources/certificates/add")
        print("       -> pick the certificate kind matching %s" % apple_type)
        print("    2. Upload the CSR already sitting at: %s" % csr_path)
        print("    3. Download the resulting certificate (.cer)")
        print("    4. py -3.12 ops/deploy/mac_credentials.py --finish <downloaded>.cer --type %s" % cert_type)
        return
    except InvalidCertificateRequest:
        print("==> Apple: 409 'Invalid Certificate' - NOT the Account-Holder wall (that's a 403),")
        print("    a different rejection this key hits for %s. See InvalidCertificateRequest's" % apple_type)
        print("    docstring for what is/isn't known about the cause. Manual step (same fallback):")
        print("    1. As the Account Holder, in a real browser (Apple ID + 2FA):")
        print("       https://developer.apple.com/account/resources/certificates/add")
        print("       -> pick the certificate kind matching %s" % apple_type)
        print("       (create it there directly - no need to upload the CSR this wrote,")
        print("        though %s works fine as one if the browser flow asks for it)" % csr_path)
        print("    2. Download the resulting certificate (.cer)")
        print("    3. py -3.12 ops/deploy/mac_credentials.py --finish <downloaded>.cer --type %s" % cert_type)
        return

    cert = d["data"]
    a = cert["attributes"]
    _normalize_cert(base64.b64decode(a["certificateContent"]), cert_path)
    print("==> minted: id=%s serial=%s expires=%s" % (cert["id"], a.get("serialNumber"), a.get("expirationDate")))
    _bundle_p12(key_path, cert_path, p12_path, password, "HelmDeck " + apple_type)


# --- --finish --------------------------------------------------------------
def cmd_finish(cert_arg, cert_type, key_path, out_dir, password):
    out_dir = _guard_out_dir(out_dir)
    apple_type, basename, _ = CERT_TYPES[cert_type]
    key_path = key_path or os.path.join(out_dir, basename + ".key.pem")
    if not os.path.exists(key_path):
        fail("no private key at %s - pass --key, or re-run --create --type %s first "
             "(it writes the key before it ever contacts Apple)" % (key_path, cert_type))
    if not os.path.exists(cert_arg):
        fail("no certificate at %s" % cert_arg)

    cert_path = os.path.join(out_dir, basename + ".cert.pem")
    p12_path = os.path.join(out_dir, basename + ".p12")
    _normalize_cert(open(cert_arg, "rb").read(), cert_path)
    print("==> bundling %s + %s" % (key_path, cert_path))
    _bundle_p12(key_path, cert_path, p12_path, password, "HelmDeck " + apple_type)


# --- --secrets -----------------------------------------------------------
def cmd_secrets(p12_path, password, cert_type):
    if not password:
        fail("--password required (the one --create printed)")
    if not os.path.exists(p12_path):
        fail("no .p12 at %s" % p12_path)
    _, _, (link_key, pw_key) = CERT_TYPES[cert_type]
    who = _run(["gh", "auth", "status"])
    print(who.strip() if who.strip() else "==> gh authenticated")
    b64 = base64.b64encode(open(p12_path, "rb").read()).decode()
    print("==> gh secret set %s --repo %s" % (link_key, GH_REPO))
    subprocess.run(["gh", "secret", "set", link_key, "--repo", GH_REPO, "--body", b64], check=True)
    print("==> gh secret set %s --repo %s" % (pw_key, GH_REPO))
    subprocess.run(["gh", "secret", "set", pw_key, "--repo", GH_REPO, "--body", password], check=True)
    print("==> done - %s / %s are live" % (link_key, pw_key))


# --- --bundleids -----------------------------------------------------------
def cmd_bundleids():
    """Read-only. Confirms which platform each registered Bundle ID covers -
    UNIVERSAL means it already works for macOS, not just whatever platform it
    was first used on, so a matching app record can add a macOS platform
    without registering a new identifier."""
    env = _env()
    d = _api(env, "GET", "/v1/bundleIds?limit=100")
    rows = d.get("data", [])
    print("==> %d registered bundle id(s):" % len(rows))
    for row in rows:
        a = row["attributes"]
        print("    id=%s  identifier=%s  name=%s  platform=%s"
              % (row["id"], a.get("identifier"), a.get("name"), a.get("platform")))


# --- --profiles --------------------------------------------------------------
def cmd_profiles():
    env = _env()
    d = _api(env, "GET", "/v1/profiles?limit=100")
    rows = d.get("data", [])
    print("==> %d provisioning profile(s):" % len(rows))
    for row in rows:
        a = row["attributes"]
        print("    id=%s  name=%s  type=%s  state=%s  expires=%s"
              % (row["id"], a.get("name"), a.get("profileType"), a.get("profileState"), a.get("expirationDate")))


# --- --profile-create --------------------------------------------------------
def cmd_profile_create(name, bundle_id_resource, cert_id, out_dir):
    """MAC_APP_STORE profiles need no device list, same as iOS App Store
    profiles - just the bundle id resource and a mas-app certificate id."""
    env = _env()
    out_dir = _guard_out_dir(out_dir)
    d = _api(env, "POST", "/v1/profiles", {
        "data": {
            "type": "profiles",
            "attributes": {"name": name, "profileType": "MAC_APP_STORE"},
            "relationships": {
                "bundleId": {"data": {"type": "bundleIds", "id": bundle_id_resource}},
                "certificates": {"data": [{"type": "certificates", "id": cert_id}]},
            },
        }
    })
    prof = d["data"]
    a = prof["attributes"]
    content = base64.b64decode(a["profileContent"])
    out_path = os.path.join(out_dir, "mac_app_store.provisionprofile")
    open(out_path, "wb").write(content)
    print("==> created profile id=%s name=%s expires=%s" % (prof["id"], a.get("name"), a.get("expirationDate")))
    print("==> wrote %s" % out_path)


if __name__ == "__main__":
    args = sys.argv[1:]
    cert_type = args[args.index("--type") + 1] if "--type" in args else "developer-id"
    if cert_type not in CERT_TYPES:
        fail("--type must be one of %s" % ", ".join(CERT_TYPES))

    if "--check" in args:
        cmd_check(cert_type)
    elif "--create" in args:
        out_dir = args[args.index("--out") + 1] if "--out" in args else "C:/hd/secrets"
        pw = args[args.index("--password") + 1] if "--password" in args else None
        cmd_create(cert_type, out_dir, pw)
    elif "--finish" in args:
        cert_arg = args[args.index("--finish") + 1]
        out_dir = args[args.index("--out") + 1] if "--out" in args else "C:/hd/secrets"
        key_path = args[args.index("--key") + 1] if "--key" in args else None
        pw = args[args.index("--password") + 1] if "--password" in args else None
        cmd_finish(cert_arg, cert_type, key_path, out_dir, pw)
    elif "--secrets" in args:
        p12 = args[args.index("--secrets") + 1]
        pw = args[args.index("--password") + 1] if "--password" in args else None
        cmd_secrets(p12, pw, cert_type)
    elif "--bundleids" in args:
        cmd_bundleids()
    elif "--profiles" in args:
        cmd_profiles()
    elif "--profile-create" in args:
        name = args[args.index("--name") + 1]
        bundle_id_resource = args[args.index("--bundle-id-resource") + 1]
        cert_id = args[args.index("--cert-id") + 1]
        out_dir = args[args.index("--out") + 1] if "--out" in args else "C:/hd/secrets"
        cmd_profile_create(name, bundle_id_resource, cert_id, out_dir)
    else:
        print(__doc__)
        sys.exit(2)
