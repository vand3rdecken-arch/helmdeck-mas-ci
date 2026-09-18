# -*- coding: utf-8 -*-
"""Create the next editable iOS appStoreVersion and write ONLY its
description (de-DE/en-US) - the one write `eas metadata:push` cannot make
safely right now.

Why this exists instead of just running `eas metadata:push`: that command
pushes the WHOLE `surfaces/app/store.config.json` in one batch, including
`apple.info.*.subtitle`. Subtitle lives on `appInfoLocalizations` ("App
Information"), a resource shared across every platform of the app - and as
of 2026-09-18 it is locked read-only because the macOS 0.2.18 version is
IN_REVIEW (ASC's own banner: "App information is currently in review").
The owner decided macOS stays in review and the subtitle waits; a metadata
push that also tries to PATCH the locked subtitle risks failing or
half-applying. The description lives on a completely different resource,
`appStoreVersionLocalizations` (per appStoreVersion, not shared across
platforms), so it can be written independently without touching appInfo.

    py -3.12 ops/deploy/asc_ios_description.py show
    py -3.12 ops/deploy/asc_ios_description.py apply --version 1.0.51

`apply` creates the appStoreVersion if it doesn't exist yet (idempotent -
reuses an existing editable one for the same versionString) and PATCHes/
POSTs the description for de-DE and en-US from `surfaces/app/store.config.json`.
It never touches appInfo/subtitle/keywords/promoText/etc.

Needs the same .env as asc_metadata_draft.py (ASC_KEY_ID / ASC_ISSUER_ID /
ASC_API_KEY_PATH), see DEPLOY.md 2b.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from asc_metadata_draft import APP_ID, _get, _req  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOCALES = ("de-DE", "en-US")

# "What's New in This Version" - Apple requires a non-empty value on every
# appStoreVersionLocalization before a version can be submitted (a submit
# attempt without it 409s with ENTITY_ERROR.ATTRIBUTE.REQUIRED on whatsNew).
# This is the owner-drafted text from ops/docs/store/APPSTORE_LISTING.md
# "Team-Harness-Entwurf v1" section, verified against real commit history
# for the changes since 1.0.48 - written for exactly this moment ("sobald
# der TestFlight-Only-Stand endet").
WHATS_NEW = {
    "de-DE": (
        "Antworten kommen jetzt zuverlässig an, auch nachdem Handy, Desktop "
        "oder Uhr aufgewacht sind. Henry zeigt jetzt an, wenn er im "
        "Hintergrund weiterarbeitet, und liefert Ergebnisse aus dem "
        "Hintergrund klar aufbereitet zurück statt als Rohtext. Kleinere "
        "Verbesserungen an der Wear-OS-Uhr-App (Ambient-Modus, Kopplung)."
    ),
    "en-US": (
        "Replies now arrive reliably, even after your phone, desktop or "
        "watch wakes up. Henry now shows when it keeps working in the "
        "background, and hands results come back as a clear summary "
        "instead of raw text. Small fixes to the Wear OS watch app "
        "(ambient mode, pairing)."
    ),
}

EDITABLE_STATES = (
    "PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED",
    "METADATA_REJECTED", "WAITING_FOR_REVIEW", "INVALID_BINARY",
)


def _store_config():
    with open(os.path.join(ROOT, "surfaces", "app", "store.config.json"), encoding="utf-8") as f:
        return json.load(f)


def _versions():
    return _get("/v1/apps/%s/appStoreVersions?limit=50&filter[platform]=IOS" % APP_ID).get("data", [])


def _find_version(version_string):
    for v in _versions():
        if v["attributes"].get("versionString") == version_string:
            return v
    return None


def _localizations(version_id):
    return _get("/v1/appStoreVersions/%s/appStoreVersionLocalizations" % version_id).get("data", [])


def cmd_show(argv):
    for v in _versions():
        a = v["attributes"]
        print("appStoreVersion id=%s version=%s state=%s" % (v["id"], a.get("versionString"), a.get("appStoreState")))
        for loc in _localizations(v["id"]):
            la = loc["attributes"]
            desc = (la.get("description") or "")
            print("  %s: %d chars: %r..." % (loc["attributes"].get("locale"), len(desc), desc[:60]))


def cmd_apply(argv):
    if "--version" not in argv:
        print("usage: apply --version 1.0.51")
        sys.exit(2)
    version_string = argv[argv.index("--version") + 1]
    cfg = _store_config()["apple"]["info"]

    v = _find_version(version_string)
    if v is None:
        v = _req("POST", "/v1/appStoreVersions", {
            "data": {
                "type": "appStoreVersions",
                "attributes": {"platform": "IOS", "versionString": version_string},
                "relationships": {"app": {"data": {"type": "apps", "id": APP_ID}}},
            }
        })["data"]
        print("created appStoreVersion %s (%s)" % (v["id"], version_string))
    else:
        state = v["attributes"].get("appStoreState")
        if state not in EDITABLE_STATES:
            raise RuntimeError("appStoreVersion %s is in state %s, not editable" % (version_string, state))
        print("reusing appStoreVersion %s (%s, state=%s)" % (v["id"], version_string, state))

    existing = {loc["attributes"]["locale"]: loc for loc in _localizations(v["id"])}
    for locale in LOCALES:
        description = cfg[locale]["description"]
        attrs = {"description": description, "whatsNew": WHATS_NEW[locale]}
        if locale in existing:
            _req("PATCH", "/v1/appStoreVersionLocalizations/%s" % existing[locale]["id"], {
                "data": {"type": "appStoreVersionLocalizations", "id": existing[locale]["id"],
                         "attributes": attrs},
            })
            print("updated description+whatsNew for %s (%d chars)" % (locale, len(description)))
        else:
            _req("POST", "/v1/appStoreVersionLocalizations", {
                "data": {
                    "type": "appStoreVersionLocalizations",
                    "attributes": dict(attrs, locale=locale),
                    "relationships": {"appStoreVersion": {"data": {"type": "appStoreVersions", "id": v["id"]}}},
                },
            })
            print("created description+whatsNew for %s (%d chars)" % (locale, len(description)))


CMDS = {"show": cmd_show, "apply": cmd_apply}

if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "show"
    if c not in CMDS:
        print(__doc__)
        sys.exit(2)
    CMDS[c](sys.argv[2:])
