# App-Store-Release (Apple) — Runbook

Owner-Entscheidung 2026-09-05: **direkt einreichen**, genau wie beim bereits
veröffentlichten Play-Store-Listing — kein zusätzlicher Zwischenschritt.
`ops/docs/ios-requirements.md` §1 ist entsprechend aktualisiert (vorher: „kein
App-Store-Release im Scope"). TestFlight External Beta
(`EXTERNAL_TESTFLIGHT.md`) bleibt daneben bestehen — der Store-Release ist
zusätzlich, kein Ersatz für den Testkanal künftiger Builds.

## Unterschied zu TestFlight

| | TestFlight (Beta) | App Store (Store) |
|---|---|---|
| Prüfung | Beta App Review (leichter, 24–48h) | App Review (voller Umfang, kann länger dauern) |
| Objekt | `betaGroups` / Build-Zuordnung | eigenes `appStoreVersion`-Objekt |
| Text | Beta-Beschreibung, „What to Test" | volles Listing: Subtitle, Keywords, Beschreibung, Promotional Text |
| Sichtbarkeit | nur über Link/Einladung | öffentlich im App Store gelistet, durchsuchbar |
| App-Privacy/Altersfreigabe | schon erledigt (app-weit, gilt für beide) | dieselben Angaben, kein erneuter Schritt |

## Werkzeuge

| Skript | Zuständig für |
|---|---|
| `ops/deploy/asc_store_release.py` | Store-Version anlegen, Listing-Text schreiben, Build anhängen, zur echten Review einreichen |

Nutzt dieselbe ASC-Anbindung wie die anderen Skripte (`.env`:
`ASC_KEY_ID`/`ASC_ISSUER_ID`/`ASC_API_KEY_PATH`, `DEPLOY.md` §2b) — importiert
`_get`/`_req`/`APP_ID` aus `asc_metadata_draft.py`, genau wie
`asc_external_beta.py`. Es gibt weiterhin genau einen ASC-Client im Repo.

Inhalt (Subtitle/Keywords/Promotional Text/Beschreibung) steht dokumentiert
in `ops/docs/store/APPSTORE_LISTING.md` und ist im Skript als Konstanten
gespiegelt — bei Textänderungen **beide** pflegen.

## Reihenfolge

```bash
py -3.12 ops/deploy/asc_store_release.py show                        # nur lesen, Endpunkt-Annahmen prüfen
py -3.12 ops/deploy/asc_store_release.py create-version 1.0.48       # neue Store-Version anlegen
py -3.12 ops/deploy/asc_store_release.py apply --yes                 # Subtitle + Listing-Text schreiben
# ... Build bauen/hochladen/verarbeiten lassen, falls noch nicht geschehen (DEPLOY.md 2c) ...
py -3.12 ops/deploy/asc_store_release.py attach <build-id>            # verarbeiteten Build der Version geben
py -3.12 ops/deploy/asc_store_release.py submit --yes                 # -> echte App Review
```

`show` zuerst laufen lassen, **bevor** irgendetwas geschrieben wird — die
Feld-/Endpunkt-Zuordnung im Skript ist der best bekannte Stand der ASC-API,
die hat sich in der Vergangenheit schon mal verschoben (s. Hinweis zu
`appPriceSchedules` unten). Ein 404 dort zeigt eine verschobene API, bevor
`apply`/`submit` live etwas anfasst — das Skript schluckt HTTP-Fehler
bewusst nicht.

`apply` und `submit` verweigern ohne `--yes`.

## Was nur der Owner machen kann (Web-UI, Apple-ID + 2FA)

Diese zwei Punkte hat die App-Store-Connect-**API nicht** (bzw. bewusst hier
nicht automatisiert, s. Begründung):

### 1. Preise und Verfügbarkeit

<https://appstoreconnect.apple.com> → Apps → HelmDeck → **Preise und
Verfügbarkeit** → „Kostenlos" + Länder auswählen. Kein Skript hier: Apples
Preisschema-API (`appPriceSchedules`) hat über ASC-API-Versionen hinweg
mehrfach die Form gewechselt (Tier-IDs → territoriale `appPricePoints`) —
lieber der einmalige Web-UI-Klick als ein Skript, das auf veralteter
API-Doku eine falsche Preiszeile schreibt.

### 2. Screenshots hochladen

Gleiche App-Seite → App-Store-Version → Screenshots. Bild-Upload läuft über
einen mehrstufigen Reservierungs-Flow (Asset-Reservation, Checksum, Commit) —
das ist im ASC-Web-UI oder mit Apples `Transporter`-Tool schneller erledigt
als über ein schlankes Skript. **Vor dem Hochladen die aktuell verlangten
Pixelmaße im ASC-UI prüfen** — Apple ändert die Pflichtgrößen zwischen
Xcode-/ASC-Versionen öfter als andere Store-Vorgaben. Quelle für den
Zuschnitt: `ops/docs/store/screenshots/play/*-1920.png` (gleicher UI-Stand
wie die fertigen Play-Assets, aber höhere Ausgangsauflösung).

App-Privacy und Altersfreigabe sind **nicht** hier aufgeführt — die sind
app-weit bereits erledigt (siehe `EXTERNAL_TESTFLIGHT.md` „Was nur der Owner
machen kann") und gelten für TestFlight und Store gleichermaßen.

## Falls ein Build noch fehlt

Ein für den Store einreichbarer Build braucht keinen neuen Build-Vorgang,
falls der zuletzt für TestFlight hochgeladene Build (`1.0.45 (7)` bzw. der
aktuelle Stand aus `EXTERNAL_TESTFLIGHT.md`) inhaltlich passt — Apple
akzeptiert denselben verarbeiteten Build für Beta **und** Store, solange er
noch nicht „superseded" ist. Falls ein frischer Build nötig ist:
`ios_credentials.sh --build` → `eas-cli submit` → `asc_build_state.py --wait`,
wie in `EXTERNAL_TESTFLIGHT.md` „Stand 2026-09-05" beschrieben.

## Nach dem Absenden

`submit` schickt die Version an die reguläre App Review, keine automatische
Freischaltung. Antwort kommt per Mail an `tienduyvo@googlemail.com`. Bei
Freigabe: da `releaseType: MANUAL` gesetzt ist, muss die Version danach
noch einmal explizit über **„Diese Version veröffentlichen"** im ASC-Web-UI
freigegeben werden (bewusst kein Auto-Release direkt nach Apple-Freigabe —
ein manueller letzter Klick, kein Skript, für den ersten Store-Release).
