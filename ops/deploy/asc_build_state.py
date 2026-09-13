# -*- coding: utf-8 -*-
"""Ask App Store Connect what it actually did with our upload.

`eas submit` finishing only proves the .ipa reached Apple. Apple then PROCESSES
it, and that step is a real gate: a binary with a broken slice, a bad
entitlement or a missing Info.plist key comes back INVALID instead of VALID.
Since there is no macOS/Xcode on this box (ops/docs/ios-watch-feasibility.md R2),
this processing verdict is the strongest automated statement available about
the artifact - so read it from Apple rather than declaring success at upload.

  py -3.12 ops/deploy/asc_build_state.py            # one look
  py -3.12 ops/deploy/asc_build_state.py --wait     # poll until Apple stops PROCESSING

Reads ASC_* from .env, mints a fresh ES256 JWT per request (they expire in
minutes), and prints the processing state per build. Exit 0 = VALID,
2 = still processing when the deadline hit, 1 = anything Apple calls bad.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

import jwt

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ID = "6801637667"


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
    return env


def _get(path):
    """One authenticated GET. The token is minted per call on purpose - a long
    poll outlives any single JWT."""
    e = _env()
    now = int(time.time())
    tok = jwt.encode(
        {"iss": e["ASC_ISSUER_ID"], "iat": now, "exp": now + 600,
         "aud": "appstoreconnect-v1"},
        open(e["ASC_API_KEY_PATH"]).read(),
        algorithm="ES256", headers={"kid": e["ASC_KEY_ID"], "typ": "JWT"})
    req = urllib.request.Request("https://api.appstoreconnect.apple.com" + path,
                                 headers={"Authorization": "Bearer " + tok})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def builds():
    d = _get("/v1/builds?filter[app]=%s&limit=10" % APP_ID)
    out = []
    for b in d.get("data", []):
        a = b["attributes"]
        out.append({
            "id": b["id"],
            "version": a.get("version"),
            "state": a.get("processingState"),
            "expired": a.get("expired"),
            "uploaded": a.get("uploadedDate"),
        })
    return out


def failed_uploads():
    """Uploads Apple refused before they ever became a build (e.g. 90683, a
    missing Info.plist purpose string). Those never show up in /v1/builds, so
    polling builds alone waits blind for something that will never appear."""
    d = _get("/v1/apps/%s/buildUploads?limit=5" % APP_ID)
    out = []
    for u in d.get("data", []):
        a = u["attributes"]
        st = a.get("state") or {}
        if st.get("state") == "FAILED":
            out.append((a.get("cfBundleShortVersionString"), a.get("cfBundleVersion"),
                        [e.get("code", "") + " " + " ".join(re.findall(r"NS\w+UsageDescription", e.get("description") or ""))
                         + " " + (e.get("description") or "")[:160]
                         for e in st.get("errors", [])]))
    return out


def show(rows):
    if not rows:
        print("builds=0  (Apple has not surfaced the upload yet)")
    for r in rows:
        print("build %s  version=%s  state=%s  expired=%s  uploaded=%s"
              % (r["id"][:8], r["version"], r["state"], r["expired"], r["uploaded"]))
    return rows


if __name__ == "__main__":
    wait = "--wait" in sys.argv
    deadline = time.time() + 1500        # ~25 min; Apple quotes 5-10
    while True:
        try:
            rows = builds()
        except urllib.error.HTTPError as ex:
            print("http %s: %s" % (ex.code, ex.read()[:200]))
            rows = []
        except Exception as ex:                       # transient DNS/TLS
            print("err: %s" % ex)
            rows = []
        show(rows)
        try:
            bad_up = failed_uploads()
        except Exception as ex:
            print("buildUploads err: %s" % ex)
            bad_up = []
        newest = max((int(r["version"]) for r in rows if (r["version"] or "").isdigit()), default=0)
        bad_up = [u for u in bad_up if (u[1] or "").isdigit() and int(u[1]) > newest]
        if bad_up:
            for ver, num, errs in bad_up:
                print("UPLOAD FAILED %s (%s):" % (ver, num))
                for e in errs:
                    print("  " + e)
            print("RESULT=UPLOAD_FAILED")
            sys.exit(1)
        states = [r["state"] for r in rows]
        if not wait:
            break
        if states and "PROCESSING" not in states:
            break
        if time.time() > deadline:
            print("RESULT=TIMEOUT (still PROCESSING at the deadline)")
            sys.exit(2)
        time.sleep(30)
    if wait:
        bad = [s for s in states if s not in ("VALID",)]
        print("RESULT=%s" % ("VALID" if states and not bad else ",".join(states) or "NONE"))
        sys.exit(0 if states and not bad else 1)
