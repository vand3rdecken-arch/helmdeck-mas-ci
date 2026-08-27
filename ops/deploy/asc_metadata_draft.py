# -*- coding: utf-8 -*-
"""Fill the TestFlight metadata that App Store Connect actually has fields for
- Beta App Review Detail, Beta App Localization (DE/EN), Beta Build
Localization ("What to Test") - as DRAFT values a human reviews before the
next `eas submit` / before ever flipping the app to external testing.

The content itself lives in `ops/docs/store/ASC_METADATA.md`, not here - this
script only pushes what that file documents, so the two can never silently
drift without a diff showing it. Read that file first, in particular
section 1 (export compliance is a legal question, deliberately left to the
owner) and the `contactPhone` gap (no phone number invented).

Internal TestFlight testing (this app's fixed scope, ops/docs/ios-requirements.md
SS1/SS7) needs NONE of this to distribute a build - it exists so a later
switch to external testing, or a Store release, has no empty fields left.
`apply` never submits anything for review; it only writes metadata fields,
same as typing them into the App Store Connect web UI and clicking Save.

  py -3.12 ops/deploy/asc_metadata_draft.py show          # read-only, current ASC state
  py -3.12 ops/deploy/asc_metadata_draft.py apply --yes   # write the draft (PATCH/POST only)

Needs `.env` (ASC_KEY_ID / ASC_ISSUER_ID / ASC_API_KEY_PATH) - same as
ops/deploy/asc_build_state.py and ops/deploy/asc_guide.py. That file is git-ignored
and does not exist in an isolated card worktree by design; run this from the
main box.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

import jwt

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ID = "6801637667"
BUNDLE = "app.helmdeck"

# --- the draft content itself (mirrors ops/docs/store/ASC_METADATA.md) --------

REVIEW_DETAIL = {
    "contactFirstName": "Tien Duy",
    "contactLastName": "Vo",
    "contactEmail": "tienduyvo@googlemail.com",
    # contactPhone deliberately absent - no number in the repo, not invented
    "demoAccountRequired": False,
    "notes": (
        "HelmDeck ist eine Begleit-App: Sie funktioniert nur zusammen mit "
        "einer eigenen laufenden HelmDeck-Installation (Desktop/Server). Es "
        "gibt kein zentrales Entwickler-Konto und keinen Demo-Login - "
        "Pairing erfolgt per QR-Code, den die Installation selbst anzeigt. "
        "Fuer einen reinen UI-Rundgang ohne eigene Installation bitte den "
        "Owner kontaktieren."
    ),
}

LOCALIZATIONS = {
    "de-DE": {
        "description": (
            "HelmDeck ist die Begleit-App fuer deine eigene HelmDeck-"
            "Installation: ein Board, auf dem KI-Agenten an echten Aufgaben "
            "arbeiten, waehrend du steuerst, Rueckfragen beantwortest und "
            "Ergebnisse abnimmst - vom Telefon aus. Die App verbindet sich "
            "ausschliesslich mit deinem eigenen Rechner/Server, Inhalte sind "
            "Ende-zu-Ende-verschluesselt (Curve25519/XSalsa20-Poly1305). "
            "Diese Beta ist der interne Testkanal vor einem moeglichen "
            "Store-Release."
        ),
        "feedbackEmail": "tienduyvo@googlemail.com",
        "marketingUrl": "https://helmdeck.de",
        "privacyPolicyUrl": "https://141.144.227.105.sslip.io/privacy",
    },
    "en-US": {
        "description": (
            "HelmDeck is the companion app for your own HelmDeck "
            "installation: a board where AI agents work on real tasks while "
            "you steer, answer questions and approve results - from your "
            "phone. The app talks only to your own machine/server; content "
            "is end-to-end encrypted (Curve25519/XSalsa20-Poly1305). This "
            "beta is the internal test channel ahead of a possible App "
            "Store release."
        ),
        "feedbackEmail": "tienduyvo@googlemail.com",
        "marketingUrl": "https://helmdeck.de",
        "privacyPolicyUrl": "https://141.144.227.105.sslip.io/privacy",
    },
}

BUILD_WHATS_NEW = {
    "de-DE": (
        "Erster interner Testbuild. Bitte pruefen: Pairing per QR-Code vom "
        "Desktop, Board ansehen, eine Karte mit Foto-Anhang anlegen, Push-"
        "Benachrichtigung bei einer Agenten-Rueckfrage."
    ),
    "en-US": (
        "First internal test build. Please check: QR-code pairing from the "
        "desktop, viewing the board, creating a card with a photo "
        "attachment, receiving a push notification for an agent question."
    ),
}

API = "https://api.appstoreconnect.apple.com"


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


def _token():
    e = _env()
    if not (e["ASC_KEY_ID"] and e["ASC_ISSUER_ID"] and e["ASC_API_KEY_PATH"]):
        raise RuntimeError("ASC_* not configured in .env (see DEPLOY.md 2b)")
    now = int(time.time())
    return jwt.encode(
        {"iss": e["ASC_ISSUER_ID"], "iat": now, "exp": now + 600,
         "aud": "appstoreconnect-v1"},
        open(e["ASC_API_KEY_PATH"]).read(),
        algorithm="ES256", headers={"kid": e["ASC_KEY_ID"], "typ": "JWT"})


def _req(method, path, body=None):
    """One authenticated JSON:API call. A fresh token per call - simplest way
    to stay valid across a whole `apply` run."""
    headers = {"Authorization": "Bearer " + _token()}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(API + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as ex:
        detail = ex.read().decode("utf-8", "replace")[:800]
        raise RuntimeError("%s %s -> HTTP %s: %s" % (method, path, ex.code, detail))


def _get(path):
    return _req("GET", path)


def _latest_build():
    d = _get("/v1/builds?filter[app]=%s&sort=-uploadedDate&limit=1" % APP_ID)
    rows = d.get("data", [])
    if not rows:
        raise RuntimeError("no builds found for app %s yet" % APP_ID)
    return rows[0]


def _review_detail_id():
    d = _get("/v1/apps/%s/betaAppReviewDetail" % APP_ID)
    data = d.get("data")
    if not data:
        raise RuntimeError("no betaAppReviewDetail on this app record")
    return data["id"], data.get("attributes", {})


def _existing_localizations():
    d = _get("/v1/apps/%s/betaAppLocalizations?limit=50" % APP_ID)
    return {row["attributes"]["locale"]: row for row in d.get("data", [])}


def _existing_build_localizations(build_id):
    d = _get("/v1/builds/%s/betaBuildLocalizations?limit=50" % build_id)
    return {row["attributes"]["locale"]: row for row in d.get("data", [])}


def cmd_show():
    build = _latest_build()
    print("build id=%s version=%s state=%s" % (
        build["id"], build["attributes"].get("version"),
        build["attributes"].get("processingState")))

    rid, attrs = _review_detail_id()
    print("--- betaAppReviewDetail (id=%s) ---" % rid)
    for k in ("contactFirstName", "contactLastName", "contactEmail",
              "contactPhone", "demoAccountRequired", "demoAccountName", "notes"):
        print("  %s = %r" % (k, attrs.get(k)))

    print("--- betaAppLocalizations ---")
    existing = _existing_localizations()
    for locale in LOCALIZATIONS:
        row = existing.get(locale)
        if row:
            a = row["attributes"]
            print("  [%s] id=%s description=%r feedbackEmail=%r marketingUrl=%r privacyPolicyUrl=%r"
                  % (locale, row["id"], (a.get("description") or "")[:60],
                     a.get("feedbackEmail"), a.get("marketingUrl"), a.get("privacyPolicyUrl")))
        else:
            print("  [%s] MISSING - would be created by apply" % locale)

    print("--- betaBuildLocalizations (build %s) ---" % build["id"])
    existing_b = _existing_build_localizations(build["id"])
    for locale in BUILD_WHATS_NEW:
        row = existing_b.get(locale)
        if row:
            print("  [%s] id=%s whatsNew=%r" % (
                locale, row["id"], (row["attributes"].get("whatsNew") or "")[:60]))
        else:
            print("  [%s] MISSING - would be created by apply" % locale)


def cmd_apply(argv):
    if "--yes" not in argv:
        print("refusing to write without --yes (this PATCHes/POSTs live App "
              "Store Connect data - review ops/docs/store/ASC_METADATA.md first)")
        sys.exit(2)

    rid, _ = _review_detail_id()
    _req("PATCH", "/v1/betaAppReviewDetails/%s" % rid, {
        "data": {"type": "betaAppReviewDetails", "id": rid, "attributes": REVIEW_DETAIL}})
    print("betaAppReviewDetail updated")

    existing = _existing_localizations()
    for locale, attrs in LOCALIZATIONS.items():
        row = existing.get(locale)
        if row:
            _req("PATCH", "/v1/betaAppLocalizations/%s" % row["id"], {
                "data": {"type": "betaAppLocalizations", "id": row["id"], "attributes": attrs}})
            print("betaAppLocalization[%s] updated (id=%s)" % (locale, row["id"]))
        else:
            body = dict(attrs, locale=locale)
            _req("POST", "/v1/betaAppLocalizations", {
                "data": {"type": "betaAppLocalizations", "attributes": body,
                          "relationships": {"app": {"data": {"type": "apps", "id": APP_ID}}}}})
            print("betaAppLocalization[%s] created" % locale)

    build = _latest_build()
    existing_b = _existing_build_localizations(build["id"])
    for locale, whats_new in BUILD_WHATS_NEW.items():
        row = existing_b.get(locale)
        if row:
            _req("PATCH", "/v1/betaBuildLocalizations/%s" % row["id"], {
                "data": {"type": "betaBuildLocalizations", "id": row["id"],
                          "attributes": {"whatsNew": whats_new}}})
            print("betaBuildLocalization[%s] updated (id=%s)" % (locale, row["id"]))
        else:
            _req("POST", "/v1/betaBuildLocalizations", {
                "data": {"type": "betaBuildLocalizations",
                          "attributes": {"locale": locale, "whatsNew": whats_new},
                          "relationships": {"build": {"data": {"type": "builds", "id": build["id"]}}}}})
            print("betaBuildLocalization[%s] created" % locale)

    print("done - nothing was submitted for review, only metadata fields were written")


CMDS = {"show": lambda argv: cmd_show(), "apply": cmd_apply}

if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "show"
    if c not in CMDS:
        print(__doc__)
        sys.exit(2)
    CMDS[c](sys.argv[2:])
