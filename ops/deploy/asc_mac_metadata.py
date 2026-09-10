# -*- coding: utf-8 -*-
"""Fill the App Store Connect metadata for the macOS platform's App Store
version (§1f in DEPLOY.md) — the `MAC_OS` appStoreVersion added to the
existing `app.helmdeck` app record on 2026-09-10. Same discipline as
ops/deploy/asc_metadata_draft.py (TestFlight metadata): the content is DRAFT,
`apply` only PATCHes fields a human could type into the App Store Connect
web UI, and nothing here ever submits anything for review.

  py -3.12 ops/deploy/asc_mac_metadata.py show          # read-only, current ASC state
  py -3.12 ops/deploy/asc_mac_metadata.py apply --yes   # writes the draft (PATCH only)

Needs `.env` (ASC_KEY_ID / ASC_ISSUER_ID / ASC_API_KEY_PATH), same as every
other ops/deploy/asc_*.py script.
"""
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mac_credentials as m  # noqa: E402 - reuses _env/_api/JWT, not a copy

APP_ID = "6801637667"
PLATFORM = "MAC_OS"

DESCRIPTION = {
    "de-DE": (
        "HelmDeck ist dein KI-Agenten-Board fuer den Mac: eine native App, "
        "die einen lokalen Daemon startet und KI-Agenten (Claude Code) an "
        "echten Aufgaben arbeiten laesst, waehrend du auf einem Kanban-"
        "Board steuerst, Rueckfragen beantwortest und Ergebnisse abnimmst "
        "- direkt auf deinem Mac, nicht in einer fremden Cloud.\n\n"
        "Optional verbindest du dein iPhone/iPad ueber eine Ende-zu-Ende-"
        "verschluesselte Pairing-Verbindung (Curve25519/XSalsa20-Poly1305) "
        "und behaeltst das Board auch unterwegs im Blick.\n\n"
        "HelmDeck ist noch jung und entwickelt sich staendig weiter. "
        "Feedback ist jederzeit willkommen an die Mail unten."
    ),
    "en-US": (
        "HelmDeck is your AI agent board for the Mac: a native app that "
        "runs a local daemon and lets AI agents (Claude Code) work on "
        "real tasks while you steer from a Kanban board, answer questions "
        "and approve results - right on your Mac, not in someone else's "
        "cloud.\n\n"
        "Optionally pair your iPhone/iPad over an end-to-end encrypted "
        "connection (Curve25519/XSalsa20-Poly1305) to keep an eye on the "
        "board on the go.\n\n"
        "HelmDeck is still young and evolving. Feedback is always welcome "
        "at the address below."
    ),
}
PROMOTIONAL_TEXT = {
    "de-DE": "KI-Agenten arbeiten fuer dich - du steuerst vom Board aus, auf deinem eigenen Mac.",
    "en-US": "AI agents do the work - you steer from the board, on your own Mac.",
}


def _get(path):
    return m._api(m._env(), "GET", path)


def _localizations():
    ver = _get("/v1/apps/%s/appStoreVersions?filter[platform]=%s&limit=10" % (APP_ID, PLATFORM))
    rows = ver.get("data", [])
    if not rows:
        raise RuntimeError("no %s appStoreVersion on app %s - see DEPLOY.md 1f" % (PLATFORM, APP_ID))
    version = rows[0]
    locs = _get("/v1/appStoreVersions/%s/appStoreVersionLocalizations?limit=50" % version["id"])
    return version, {row["attributes"]["locale"]: row for row in locs.get("data", [])}


def cmd_show():
    version, locs = _localizations()
    a = version["attributes"]
    print("appStoreVersion id=%s platform=%s version=%s state=%s"
          % (version["id"], a.get("platform"), a.get("versionString"), a.get("appStoreState")))
    for locale in DESCRIPTION:
        row = locs.get(locale)
        if not row:
            print("  [%s] MISSING localization" % locale)
            continue
        la = row["attributes"]
        print("  [%s] id=%s description=%r promotionalText=%r keywords=%r"
              % (locale, row["id"], (la.get("description") or "")[:60],
                 la.get("promotionalText"), la.get("keywords")))


def cmd_apply(argv):
    if "--yes" not in argv:
        print("refusing to write without --yes (this PATCHes live App Store "
              "Connect data)")
        sys.exit(2)
    _, locs = _localizations()
    for locale, description in DESCRIPTION.items():
        row = locs.get(locale)
        if not row:
            print("  [%s] MISSING localization - not created (Apple auto-creates "
                  "one per app default locale when the version is made; re-run "
                  "`show` after adding the locale in the ASC UI if this persists)" % locale)
            continue
        attrs = {"description": description, "promotionalText": PROMOTIONAL_TEXT[locale]}
        d = m._api(m._env(), "PATCH", "/v1/appStoreVersionLocalizations/%s" % row["id"], {
            "data": {"type": "appStoreVersionLocalizations", "id": row["id"], "attributes": attrs}
        })
        la = d["data"]["attributes"]
        print("  [%s] updated - description_len=%d promotionalText=%r"
              % (locale, len(la.get("description") or ""), la.get("promotionalText")))
    print("done - nothing was submitted for review, only metadata fields were written")


CMDS = {"show": lambda argv: cmd_show(), "apply": cmd_apply}

if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "show"
    if c not in CMDS:
        print(__doc__)
        sys.exit(2)
    CMDS[c](sys.argv[2:])
