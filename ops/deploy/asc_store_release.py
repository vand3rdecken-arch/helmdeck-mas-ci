# -*- coding: utf-8 -*-
"""App Store Connect: the actual App Store release - version, listing text, submit.

Companion to asc_external_beta.py (TestFlight access) and asc_metadata_draft.py
(beta metadata). This one is the real Store release: creates an
appStoreVersion, writes App Store listing text (subtitle/description/keywords/
promotional text/support+marketing URL/copyright/whatsNew), attaches an
Apple-processed build, and submits for the actual App Review (not Beta App
Review). Auth/env/HTTP are reused from asc_metadata_draft so there stays
exactly one ASC client in the repo.

Owner decision 2026-09-05: submit directly to the App Store, the same way the
Play Store listing already went live (ops/docs/store/LISTING.md) - no staged
"draft only, wait for a later go-ahead" step. See ios-requirements.md 1 for
the scope change (previously "no App Store release in scope").

Content lives in ops/docs/store/APPSTORE_LISTING.md (the Apple-only fields:
subtitle/keywords/promotional text - LISTING.md is Play-only and doesn't have
them) plus the same underlying description as LISTING.md's full description.
This script mirrors that content into API payloads; if the two ever drift,
the docs file is the one to trust and this file needs a matching edit.

    show                    # read-only: appInfo, latest version, submission state
    create-version <ver>    # POST appStoreVersion (platform IOS, versionString)
    apply --yes             # write subtitle + listing text on the editable version
    attach <build-id>       # attach an Apple-processed build to that version
    submit --yes            # -> real App Review (not Beta App Review)

Each step is separate on purpose, same convention as asc_external_beta.py.
submit is the irreversible-ish one: it puts the actual Store listing in front
of an Apple reviewer. Both apply and submit refuse to run without --yes.

The field/endpoint mapping below is the best-known shape of the ASC API - it
HAS changed shape across versions before (see APPSTORE_LISTING.md's note on
why pricing has no script here). Run `show` first: if an endpoint 404s, that
mapping has drifted and needs a fix before `apply`, not a silent skip - this
script deliberately does not swallow HTTP errors.

Needs the same .env as asc_metadata_draft.py (ASC_KEY_ID / ASC_ISSUER_ID /
ASC_API_KEY_PATH), see DEPLOY.md 2b. Not present in an isolated card worktree
by design; run this from the main box.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from asc_metadata_draft import APP_ID, _get, _req  # noqa: E402

COPYRIGHT = "2026 Tien Duy Vo"  # from git config user.name, like ASC_METADATA.md's contact fields - please check

APP_INFO_LOCALIZATIONS = {
    "de-DE": {"subtitle": "KI-Agenten erledigen Arbeit"},
    "en-US": {"subtitle": "AI agents get the work done"},
}

# Same underlying copy as ops/docs/store/LISTING.md "Vollstaendige Beschreibung",
# transliterated (ae/oe/ue/ss) to keep this file plain-ASCII like the rest of
# the ASC scripts in this repo.
VERSION_LOCALIZATIONS = {
    "de-DE": {
        "description": (
            "HelmDeck ist die Fernbedienung fuer deine eigene HelmDeck-Installation: ein "
            "Board, auf dem Tickets sich nicht nur verwalten lassen, sondern sich selbst "
            "erledigen. KI-Agenten arbeiten auf deinem Rechner an echten Projekten - du "
            "steuerst, beantwortest Rueckfragen und nimmst Ergebnisse ab, vom Telefon aus.\n\n"
            "DEIN BOARD, UEBERALL\n"
            "- Auftraege anlegen - mit Prioritaet, Wert, Kunde und Anhaengen (Fotos, Dateien)\n"
            "- Live zusehen, wie der Agent arbeitet: jeder Schritt im Verlauf, Turn fuer Turn\n"
            "- \"Wartet auf dich\": Rueckfragen des Agenten direkt im Chat beantworten\n"
            "- Qualitaets-Gate vor jeder Abnahme: Pruefungen laufen automatisch, du siehst "
            "das Ergebnis, erst deine Freigabe merged und deployt\n"
            "- Push-Benachrichtigung, wenn eine Antwort da ist oder etwas zur Abnahme steht\n"
            "- Uebersicht mit echten Zahlen: gelieferter Wert, KI-Kosten, Marge pro Karte\n\n"
            "DEINE DATEN BLEIBEN DEINE\n"
            "- Die App verbindet sich ausschliesslich mit deinem eigenen HelmDeck-Daemon - "
            "direkt im LAN oder von unterwegs ueber ein Zero-Knowledge-Relay\n"
            "- Ende-zu-Ende-Verschluesselung (Curve25519/XSalsa20-Poly1305): das Relay "
            "sieht nur Chiffretext, niemals Inhalte\n"
            "- Auch Push-Nachrichten sind Ende-zu-Ende-verschluesselt\n"
            "- Keine Werbung, keine Analytics-Weitergabe an Dritte, kein Konto beim Entwickler\n\n"
            "WICHTIG\n"
            "HelmDeck ist eine Begleit-App: Sie benoetigt eine laufende HelmDeck-"
            "Installation auf deinem eigenen Rechner. Die Kopplung dauert eine Minute - "
            "QR-Code auf dem Desktop scannen, fertig. Ohne eigenen Rechner? Auf dem ersten "
            "Screen unten \"Ohne eigenen Rechner ausprobieren\" tippen und das Board mit "
            "Beispieldaten erkunden.\n\n"
            "Datenschutz: https://relay.helmdeck.de/privacy"
        ),
        "keywords": "KI,Agent,Automatisierung,Board,Produktivitaet,Tickets,Kanban,Projektmanagement,Team,Workflow",
        "promotionalText": (
            "HelmDeck verbindet sich mit deiner eigenen Installation: KI-Agenten arbeiten "
            "an echten Aufgaben, du steuerst und nimmst ab - Ende-zu-Ende-verschluesselt."
        ),
        "supportUrl": "https://helmdeck.de",
        "marketingUrl": "https://helmdeck.de",
        "whatsNew": "Erster App-Store-Release von HelmDeck.",
    },
    "en-US": {
        "description": (
            "HelmDeck is the remote control for your own HelmDeck installation: a board "
            "where tickets don't just get tracked - they get done. AI agents work on real "
            "projects on your machine; you steer, answer their questions and approve "
            "results from your phone.\n\n"
            "YOUR BOARD, ANYWHERE\n"
            "- File requests with priority, value, client and attachments (photos, files)\n"
            "- Watch the agent work live: every step in the timeline, turn by turn\n"
            "- \"Needs you\": answer the agent's questions right in the chat\n"
            "- Quality gate before every acceptance: checks run automatically, you see "
            "the report, and only your approval merges and deploys\n"
            "- Push notifications when a reply arrives or work is ready for review\n"
            "- A dashboard with real numbers: value delivered, AI cost, margin per card\n\n"
            "YOUR DATA STAYS YOURS\n"
            "- The app talks exclusively to your own HelmDeck daemon - directly on your "
            "LAN, or remotely through a zero-knowledge relay\n"
            "- End-to-end encryption (Curve25519/XSalsa20-Poly1305): the relay only ever "
            "sees ciphertext, never content\n"
            "- Push messages are end-to-end encrypted too\n"
            "- No ads, no third-party analytics sharing, no developer-hosted account\n\n"
            "NOTE\n"
            "HelmDeck is a companion app: it requires a running HelmDeck installation on "
            "your own computer. Pairing takes a minute - scan the QR code on your desktop "
            "and you're in. No computer handy? On the first screen, tap \"Try it without "
            "your own computer\" to explore the board with sample data.\n\n"
            "Privacy policy: https://relay.helmdeck.de/privacy"
        ),
        "keywords": "AI,agent,automation,board,productivity,tickets,kanban,project management,workflow,team",
        "promotionalText": (
            "HelmDeck connects to your own installation: AI agents work on real tasks "
            "while you steer and approve - all end-to-end encrypted."
        ),
        "supportUrl": "https://helmdeck.de",
        "marketingUrl": "https://helmdeck.de",
        "whatsNew": "Initial App Store release of HelmDeck.",
    },
}

# appStoreState values that mean "still ours to edit" rather than "in Apple's hands"
EDITABLE_APP_INFO_STATES = (
    None, "PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED", "METADATA_REJECTED",
)
EDITABLE_VERSION_STATES = (
    "PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED",
    "METADATA_REJECTED", "WAITING_FOR_REVIEW", "INVALID_BINARY",
)


def _app_infos():
    return _get("/v1/apps/%s/appInfos" % APP_ID).get("data", [])


def _editable_app_info():
    infos = _app_infos()
    for info in infos:
        if info["attributes"].get("appStoreState") in EDITABLE_APP_INFO_STATES:
            return info
    return infos[0] if infos else None


def _app_info_localizations(info_id):
    d = _get("/v1/appInfos/%s/appInfoLocalizations?limit=50" % info_id)
    return {row["attributes"]["locale"]: row for row in d.get("data", [])}


def _versions():
    return _get("/v1/apps/%s/appStoreVersions?limit=50&filter[platform]=IOS" % APP_ID).get("data", [])


def _editable_version():
    for v in _versions():
        if v["attributes"].get("appStoreState") in EDITABLE_VERSION_STATES:
            return v
    return None


def _version_localizations(version_id):
    d = _get("/v1/appStoreVersions/%s/appStoreVersionLocalizations?limit=50" % version_id)
    return {row["attributes"]["locale"]: row for row in d.get("data", [])}


def cmd_show(argv):
    info = _editable_app_info()
    print("--- appInfo ---")
    if info:
        print("  id=%s appStoreState=%s" % (info["id"], info["attributes"].get("appStoreState")))
        for locale, row in _app_info_localizations(info["id"]).items():
            print("  [%s] subtitle=%r name=%r" % (
                locale, row["attributes"].get("subtitle"), row["attributes"].get("name")))
    else:
        print("  none found")

    print("--- appStoreVersions (IOS) ---")
    for v in _versions():
        a = v["attributes"]
        print("  id=%s version=%s state=%s copyright=%r" % (
            v["id"], a.get("versionString"), a.get("appStoreState"), a.get("copyright")))

    ev = _editable_version()
    if not ev:
        print("no editable appStoreVersion yet - run create-version <version> first")
        return
    print("--- appStoreVersionLocalizations (editable version %s) ---" % ev["id"])
    for locale, row in _version_localizations(ev["id"]).items():
        a = row["attributes"]
        print("  [%s] keywords=%r supportUrl=%r whatsNew=%r description=%r"
              % (locale, a.get("keywords"), a.get("supportUrl"), a.get("whatsNew"),
                 (a.get("description") or "")[:60]))
    sub = _get("/v1/appStoreVersions/%s/appStoreVersionSubmission" % ev["id"]).get("data")
    print("submission: %s" % (sub["attributes"] if sub else "NOT SUBMITTED"))


def cmd_create_version(argv):
    if not argv:
        print("usage: create-version <version-string>  (e.g. 1.0.48)")
        sys.exit(2)
    if _editable_version():
        print("an editable appStoreVersion already exists - run show")
        return
    version = argv[0]
    d = _req("POST", "/v1/appStoreVersions", {
        "data": {
            "type": "appStoreVersions",
            "attributes": {
                "platform": "IOS",
                "versionString": version,
                "releaseType": "MANUAL",
                "copyright": COPYRIGHT,
                "usesIdfa": False,
            },
            "relationships": {"app": {"data": {"type": "apps", "id": APP_ID}}},
        }})
    print("created appStoreVersion %s (%s)" % (d["data"]["id"], version))


def cmd_apply(argv):
    if "--yes" not in argv:
        print("refusing to write without --yes (PATCHes/POSTs live App Store listing data - "
              "review ops/docs/store/APPSTORE_LISTING.md first)")
        sys.exit(2)

    info = _editable_app_info()
    if not info:
        print("no appInfo found - unexpected, check the app record in ASC")
        sys.exit(1)
    existing_info_loc = _app_info_localizations(info["id"])
    for locale, attrs in APP_INFO_LOCALIZATIONS.items():
        row = existing_info_loc.get(locale)
        if not row:
            print("SKIP appInfoLocalization[%s]: no existing row to PATCH (name is a required "
                  "field on that resource and not set here - not guessing the Store display "
                  "name); add it in the ASC UI once, then re-run apply" % locale)
            continue
        _req("PATCH", "/v1/appInfoLocalizations/%s" % row["id"], {
            "data": {"type": "appInfoLocalizations", "id": row["id"], "attributes": attrs}})
        print("appInfoLocalization[%s] subtitle updated" % locale)

    ev = _editable_version()
    if not ev:
        print("no editable appStoreVersion - run create-version <version> first")
        sys.exit(1)

    existing_v_loc = _version_localizations(ev["id"])
    for locale, attrs in VERSION_LOCALIZATIONS.items():
        row = existing_v_loc.get(locale)
        if row:
            _req("PATCH", "/v1/appStoreVersionLocalizations/%s" % row["id"], {
                "data": {"type": "appStoreVersionLocalizations", "id": row["id"], "attributes": attrs}})
            print("appStoreVersionLocalization[%s] updated (id=%s)" % (locale, row["id"]))
        else:
            body = dict(attrs, locale=locale)
            _req("POST", "/v1/appStoreVersionLocalizations", {
                "data": {"type": "appStoreVersionLocalizations", "attributes": body,
                          "relationships": {"appStoreVersion": {
                              "data": {"type": "appStoreVersions", "id": ev["id"]}}}}})
            print("appStoreVersionLocalization[%s] created" % locale)

    print("done - nothing was submitted for review, only listing text was written")


def cmd_attach(argv):
    if not argv:
        print("usage: attach <build-id>")
        sys.exit(2)
    build_id = argv[0]
    ev = _editable_version()
    if not ev:
        print("no editable appStoreVersion - run create-version first")
        sys.exit(2)
    _req("PATCH", "/v1/appStoreVersions/%s/relationships/build" % ev["id"],
         {"data": {"type": "builds", "id": build_id}})
    print("build %s attached to appStoreVersion %s" % (build_id, ev["id"]))


def cmd_submit(argv):
    if "--yes" not in argv:
        print("refusing to submit without --yes (this puts the actual Store listing in "
              "front of a real Apple App Review, not the Beta App Review)")
        sys.exit(2)
    ev = _editable_version()
    if not ev:
        print("no editable appStoreVersion - run create-version first")
        sys.exit(2)
    existing = _get("/v1/appStoreVersions/%s/appStoreVersionSubmission" % ev["id"]).get("data")
    if existing:
        print("already submitted: id=%s" % existing["id"])
        return
    d = _req("POST", "/v1/appStoreVersionSubmissions", {
        "data": {"type": "appStoreVersionSubmissions",
                 "relationships": {"appStoreVersion": {"data": {"type": "appStoreVersions", "id": ev["id"]}}}}})
    print("submitted for App Review: id=%s (Apple typically answers in 24-48h, can take longer)"
          % d["data"]["id"])


CMDS = {"show": cmd_show, "create-version": cmd_create_version, "apply": cmd_apply,
        "attach": cmd_attach, "submit": cmd_submit}

if __name__ == "__main__":
    c = sys.argv[1] if len(sys.argv) > 1 else "show"
    if c not in CMDS:
        print(__doc__)
        sys.exit(2)
    CMDS[c](sys.argv[2:])
