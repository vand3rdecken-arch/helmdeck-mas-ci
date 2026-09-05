# App-Store-Release (Apple) — Runbook

Owner-Entscheidung 2026-09-05: **direkt einreichen**, genau wie beim bereits
veröffentlichten Play-Store-Listing — Play-Metadaten/Screenshots/
Beschreibung/Datenschutzangaben sind die Basis. Preis: **kostenlos, weltweit
verfügbar**. `ops/docs/ios-requirements.md` §1 ist entsprechend aktualisiert
(vorher: „kein App-Store-Release im Scope"). TestFlight External Beta
(`EXTERNAL_TESTFLIGHT.md`) bleibt daneben bestehen — der Store-Release ist
zusätzlich, kein Ersatz für den Testkanal künftiger Builds.

**Alles bis auf den finalen Submit-Klick ist vorbereitet.** Diese Karte hat
keinen Zugriff auf `.env`/ASC-Secrets (Worktree-Isolation, by design) und
**wird `submit` nicht selbst aufrufen** — das ist ausdrücklich eine
Entscheidung des Owners, auf der Hauptbox, nach eigenem Blick auf `show`.

## Kein Re-Upload nötig

Der bereits für TestFlight hochgeladene, von Apple geprüfte und
**freigegebene** Build **`1.0.45 (7)`**
(`2173daef-c3fc-48be-8e48-2cb92109694f`, `betaReview: APPROVED`, s.
`EXTERNAL_TESTFLIGHT.md`) wird direkt für den Store-Release verwendet.
Apple akzeptiert denselben verarbeiteten Build für Beta **und** Store,
solange er nicht „superseded" ist. `store.config.json` (unten) ist deshalb
bewusst auf `"version": "1.0.45"` gesetzt — **nicht** auf den in Arbeit
befindlichen `1.0.48`-Stand, damit `eas metadata:push` keine neue Version
anlegt, die einen neuen Build verlangen würde.

## Werkzeuge — zwei, mit klarer Aufgabenteilung

| Werkzeug | Zuständig für |
|---|---|
| `surfaces/app/store.config.json` + `eas metadata:push` | Store-Version anlegen (falls nötig), **volles Listing**: Titel, Subtitle, Beschreibung, Keywords, Promotional Text, Support-/Marketing-URL, Copyright, Kategorie, **Altersfreigabe (Advisory)**, Review-Kontakt/Demo-Notiz, Release-Modus |
| `ops/deploy/asc_store_release.py` | Die zwei Dinge, die `eas metadata` **nicht** kann: Build an die Version hängen, zur echten App Review einreichen |

`eas metadata` ist Expos eigenes, bereits installiertes Werkzeug
(`eas-cli 23.2.0`, `npx eas-cli metadata:lint/push/pull`) — kein
Custom-Skript nötig, das dieselbe Fläche (appStoreVersion,
appStoreVersionLocalizations, appInfoLocalizations, ageRatingDeclarations)
nochmal von Hand gegen die ASC-API nachbaut. Nutzt dieselben Credentials wie
`eas submit` (`surfaces/app/eas.json` → `submit.production.ios`, Key-ID
`AZQRY4K34W`, Rolle **Admin** — s. `DEPLOY.md` §2b, derselbe Key wie in
`.env` für die Python-ASC-Skripte).

`ops/deploy/asc_store_release.py` importiert weiterhin `_get`/`_req`/`APP_ID`
aus `asc_metadata_draft.py` — genau ein roher JSON:API-Client bleibt im
Repo, für genau die Lücke, die `eas metadata` offen lässt.

## Bereits validiert, ohne Secrets

```bash
cd surfaces/app && npx eas-cli metadata:lint
```

→ `✅ Store configuration is valid.` (Stand dieses Commits, `store.config.json`
gegen das aktuelle `eas metadata`-Schema geprüft). Läuft rein lokal, braucht
keine ASC-Credentials — genau deshalb aus diesem Worktree ausführbar.

**Achtung vor dem `push`:** `apple.review.phone` steht auf dem Platzhalter
`"+00000000000"` — echte Nummer ist bereits seit 2026-09-02 in ASC
hinterlegt (s. `ASC_METADATA.md`), aber **nicht** im Repo (PII in
Git-History wird nicht rückgängig gemacht, gleiche Begründung wie
`contactPhone` in `asc_metadata_draft.py`). Anders als eine rohe
JSON:API-PATCH (die ausgelassene Felder unangetastet lässt) ist unklar, ob
`eas metadata:push` ein volles Replace macht und den Platzhalter tatsächlich
schreibt. **Vor dem Push:** echte Nummer lokal eintragen (nicht committen),
oder direkt danach in der ASC-Web-UI gegenprüfen und bei Bedarf
nachtragen.

## Reihenfolge (auf der Hauptbox, mit `.env` + EAS-Login)

```bash
cd surfaces/app
npx eas-cli metadata:lint                      # nochmal, falls store.config.json seither geändert wurde
# apple.review.phone lokal auf die echte Nummer setzen (nicht committen)
npx eas-cli metadata:push                      # Version + volles Listing + Age Rating schreiben
cd ../..
py -3.12 ops/deploy/asc_store_release.py show                              # Version-ID + State prüfen
py -3.12 ops/deploy/asc_store_release.py attach 2173daef-c3fc-48be-8e48-2cb92109694f   # bestehenden Build anhängen
py -3.12 ops/deploy/asc_store_release.py show                              # Build-Zuordnung bestätigen
py -3.12 ops/deploy/asc_store_release.py submit --yes                      # -> echte App Review — NUR nach Owner-Go
```

`submit` verweigert ohne `--yes`. Dieses Skript ruft `submit` unter keinen
Umständen von sich aus auf.

## Der bestehende ASC-Key kann das bereits — trotzdem keine Automatik

Der Admin-Key `AZQRY4K34W` (`DEPLOY.md` §2b, Rolle **Admin** — dieselbe
Kategorie, die schon Zertifikate erstellt und den TestFlight-Build zur Beta
App Review eingereicht hat) hat plausibel auch die Berechtigung für
`POST /v1/appStoreVersionSubmissions` (die echte App-Review-Einreichung) —
Admin ist die höchste ASC-API-Rolle, App-Manager/Developer/Marketing sind
enger. **Das ändert nichts am Ablauf:** `submit --yes` ist ein expliziter,
separater Befehl, den nur ein Mensch auf der Hauptbox auslöst, nie ein
Automatismus dieser oder einer anderen Karte.

## Was nur der Owner machen kann (Web-UI, Apple-ID + 2FA)

### 1. Preise und Verfügbarkeit

<https://appstoreconnect.apple.com> → Apps → HelmDeck → **Preise und
Verfügbarkeit** → „Kostenlos" + **alle Länder/Regionen**. Kein Skript hier,
s. `APPSTORE_LISTING.md` „Pricing & Availability" für die Begründung.

### 2. Screenshots hochladen

iPhone-6,9"-Set ist fertig generiert (`ops/tools/make_appstore_screenshots.py`
→ `ops/docs/store/screenshots/appstore/iphone-6.9/`, 1320×2868). iPad-Set
ist **offen** — s. `APPSTORE_LISTING.md` „Screenshots" für die drei Optionen
(echte iPad-Aufnahme / im ASC-Dialog prüfen ob zwingend / `supportsTablet`
abschalten, kostet aber einen neuen Build). Upload selbst läuft über einen
mehrstufigen Reservierungs-Flow — im ASC-Web-UI oder mit Apples
`Transporter`-Tool schneller erledigt als über ein Skript.

App-Privacy-Nutrition-Label ist **nicht** hier aufgeführt — app-weit bereits
erledigt (s. `EXTERNAL_TESTFLIGHT.md` „Was nur der Owner machen kann") und
gilt für TestFlight und Store gleichermaßen. Altersfreigabe und
Export-Compliance sind ebenfalls **nicht** mehr hier aufgeführt — beide sind
jetzt vorbereitet bzw. bereits erledigt, s. `APPSTORE_LISTING.md`.

## Nach dem Absenden

`submit` schickt die Version an die reguläre App Review, keine automatische
Freischaltung. Antwort kommt per Mail an `tienduyvo@googlemail.com`. Bei
Freigabe: `store.config.json` setzt `release.automaticRelease: false`, die
Version muss danach noch einmal explizit über **„Diese Version
veröffentlichen"** im ASC-Web-UI freigegeben werden — bewusst kein
Auto-Release direkt nach Apple-Freigabe für den ersten Store-Release.
