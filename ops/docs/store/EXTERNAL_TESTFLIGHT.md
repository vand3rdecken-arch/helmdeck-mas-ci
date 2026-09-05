# Externer TestFlight-Test — Runbook

Owner-Entscheidung 2026-09-02: iOS wechselt von **internem** auf **externes**
TestFlight-Testing. Diese Datei ist der Ablauf, der Stand und — wichtigster
Teil — die zwei Schritte, die **nur der Owner** machen kann.

## Warum überhaupt

Interner TestFlight-Test hat **keinen öffentlichen Beitrittslink**. Apple lädt
ausschließlich per Apple-ID-E-Mail ein. Deshalb hatte die iOS-Karte auf
helmdeck.de nichts zu verlinken und bot ersatzweise ein `mailto:` an — das im
echten Browser nachweislich **gar nichts** tat (`navigated away? False`,
`new tabs opened: 0`), weil `mailto:` einen im Betriebssystem registrierten
Mail-Client braucht. Webmail-Nutzer klickten ins Leere.

Externes Testing erzeugt eine echte `https://testflight.apple.com/join/…`-URL,
die jeder anklicken kann. Das ist der einzige Weg dorthin.

## Werkzeuge

| Skript | Zuständig für |
|---|---|
| `ops/deploy/asc_metadata_draft.py` | **Texte**: Review-Kontakt, Beta-Beschreibung, „What to Test" |
| `ops/deploy/asc_external_beta.py` | **Zugang**: externe Gruppe, Beta App Review, öffentlicher Link |

Beide nutzen dieselbe ASC-Anbindung (`.env`: `ASC_KEY_ID` / `ASC_ISSUER_ID` /
`ASC_API_KEY_PATH`, siehe `DEPLOY.md` §2b) — es gibt genau einen ASC-Client im
Repo, `asc_external_beta.py` importiert ihn aus `asc_metadata_draft.py`.

```bash
py -3.12 ops/deploy/asc_external_beta.py show                 # nur lesen
py -3.12 ops/deploy/asc_external_beta.py create-group         # externe Gruppe, Link noch AUS
py -3.12 ops/deploy/asc_external_beta.py submit <build-id> --yes   # -> Apple Review
py -3.12 ops/deploy/asc_external_beta.py attach <build-id>    # freigegebenen Build der Gruppe geben
py -3.12 ops/deploy/asc_external_beta.py enable-link --yes    # öffentliche URL live, wird ausgegeben
```

`submit` und `enable-link` verweigern ohne `--yes` — das eine stellt die App vor
einen Apple-Reviewer, das andere veröffentlicht eine URL für alle.

## Stand 2026-09-02

- [x] Beta App Review Detail befüllt — Name, Mail, Telefon (Telefon steht nur
      live in ASC, **nicht** im Repo, s. `ASC_METADATA.md`) und die
      Reviewer-Notiz, die auf den **Demo-Modus** zeigt. Ohne die wäre die
      Review eine sichere 2.1-Ablehnung: HelmDeck braucht sonst eine gepairte
      Desktop-Installation, die ein Reviewer nicht hat
- [x] Beta App Localizations de-DE + en-US (Beschreibung, Feedback-Mail,
      Marketing-URL, Datenschutz-URL)
- [x] Externe Gruppe **„Public Beta"** `38bffcb8-9db6-49e3-96b2-4b994ddc6bb8`
      angelegt — öffentlicher Link bewusst noch **aus**
- [x] Build **1.0.45 (7)** gebaut, hochgeladen, von Apple verarbeitet (`VALID`)
- [x] **Zur Beta App Review eingereicht** — Build-ID
      `2173daef-c3fc-48be-8e48-2cb92109694f`, Stand `WAITING_FOR_REVIEW`
      (2026-09-02). Antwort kommt per Mail an `tienduyvo@googlemail.com`
- [x] iOS-Karte auf helmdeck.de interim repariert (sichtbare + kopierbare
      Adresse statt wirkungslosem `mailto:`, App-Store-Link auf `/de/`)
- [ ] **App-Privacy-Angaben** ← nur im Web-UI, siehe unten
- [ ] **Altersfreigabe** ← nur im Web-UI, siehe unten
- [ ] Öffentlichen Link einschalten und auf helmdeck.de setzen

## Was nur der Owner machen kann

Die App-Store-Connect-**API bietet diese beiden Formulare nicht an**. Das ist
keine Bequemlichkeitsfrage — es gibt schlicht keinen Endpunkt. Beides braucht
Login mit Apple-ID und 2FA.

> **Zeitkritisch.** Der Build steht seit 2026-09-02 auf `WAITING_FOR_REVIEW`,
> diese beiden Felder sind aber noch leer. Apple akzeptiert die Einreichung in
> der Warteschlange trotzdem — ob der Reviewer sie mangels Privacy-Angaben
> zurückweist oder sie vorher noch nachgetragen werden, entscheidet sich daran,
> wer zuerst dran ist. Je früher ausgefüllt, desto wahrscheinlicher geht die
> Review beim ersten Anlauf durch. Eine Ablehnung ist kein Drama (neu
> einreichen, keine neue Build-Nummer nötig), kostet aber einen Tag.

### 1. App-Privacy („App-Datenschutz")

<https://appstoreconnect.apple.com> → **Apps** → HelmDeck → linke Spalte
**App-Datenschutz** → *Bearbeiten*.

Inhaltliche Vorlage steht in `ops/docs/store/DATA_SAFETY.md` (dort für Googles
Data-Safety-Formular ausgefüllt, dieselben Sachverhalte). Kernpunkte:

- **Analytics** — PostHog, siehe `relay.helmdeck.de/privacy`
- **Kontaktdaten / Kennungen** — Pairing-Token, Push-Token
- **Nutzerinhalte** — Karteninhalte, Anhänge; Ende-zu-Ende-verschlüsselt und
  ausschließlich auf der eigenen Installation des Nutzers

### 2. Altersfreigabe

Gleiche Seite → **Altersfreigabe** → Fragebogen. Steht aktuell auf `null`
(gemessen über die API: `appStoreAgeRating: null`).

**Ohne diese beiden Angaben lässt Apple den externen Test nicht durch.**

## Stand 2026-09-05 — nächste Auslieferung vorbereitet, noch nicht ausgeführt

Seit dem letzten Eintrag oben (Build `1.0.45 (7)`, 2026-09-02) ist
`surfaces/app` auf `1.0.48`/versionCode 91 gewachsen, mit einem native-relevanten
Zwischenstand `1.0.46 (88)` (`fe8a204`). App-sichtbar seither u. a.: Mehr-Tab
neu sortiert (mehrere `fix(settings)`/`fix(more)`-Commits), PM-Dashboard als
ein Übersichtsblatt statt Dreieck-Report, Prozess-Schritte bearbeiten, ein
History-500er behoben, Brillen-Mikrofon jetzt von der Brille selbst gestartet.

Diese Karte (worktree-Card, kein Zugriff auf `.env`/ASC-Secrets — by design,
siehe `CLAUDE.md`) hat vorbereitet, was **ohne** Secrets geht:
- `ops/deploy/asc_metadata_draft.py` — `BUILD_WHATS_NEW` auf die Änderungen
  seit `1.0.45` umgeschrieben (DE/EN).
- `ops/docs/store/ASC_METADATA.md` §4 — derselbe Entwurfstext, dokumentiert.

**Noch offen — nur von der Hauptbox aus, mit `.env` (`DEPLOY.md` §2b/§2c):**

```bash
bash ops/deploy/ios_credentials.sh --check                                   # preflight
bash ops/deploy/ios_credentials.sh --build                                   # neuer .ipa (EAS, unattended)
cd surfaces/app && npx eas-cli submit --platform ios --latest --non-interactive --wait   # HOCHLADEN
py -3.12 ops/deploy/asc_build_state.py --wait                                 # Apple-Verarbeitung: VALID?
py -3.12 ops/deploy/asc_metadata_draft.py show                                # Kontrolle vor apply
py -3.12 ops/deploy/asc_metadata_draft.py apply --yes                        # What-to-Test-Text auf den neuen Build schreiben
py -3.12 ops/deploy/asc_external_beta.py show                                 # App-Privacy/Altersfreigabe/Link-Status jetzt prüfen —
                                                                               # der Stand von 2026-09-02 unten könnte veraltet sein
py -3.12 ops/deploy/asc_external_beta.py submit <build-id> --yes             # falls dieser Build erneut zur Beta App Review muss
py -3.12 ops/deploy/asc_external_beta.py attach <build-id>                   # FREIGABE AN TESTER — Apple benachrichtigt die Gruppe
```

`submit` braucht nur, wenn Apple für diesen Build tatsächlich eine neue Beta
App Review verlangt (nicht jeder Build einer laufenden Version braucht das,
Apple entscheidet das serverseitig) — `show` danach macht sichtbar, ob
`betaReview` schon `APPROVED` ist oder erst `WAITING_FOR_REVIEW`. Falls
App-Privacy/Altersfreigabe (oben, „Was nur der Owner machen kann") seit
2026-09-02 noch nicht nachgetragen wurden, blockiert das jede Freigabe
unabhängig vom Build.

## Danach

Sobald Apple die Review freigegeben hat (üblicherweise 24–48 h; die Freigabe
kommt per Mail an `tienduyvo@googlemail.com`):

```bash
py -3.12 ops/deploy/asc_external_beta.py show                  # betaReview: APPROVED?
py -3.12 ops/deploy/asc_external_beta.py attach <build-id>
py -3.12 ops/deploy/asc_external_beta.py enable-link --yes     # gibt die Join-URL aus
```

Die ausgegebene URL ersetzt dann in `ops/deploy/waitlist/src/index.js` die
Interim-Lösung der iOS-Karte (`TESTFLIGHT_REQUEST_URL` /
`#ios-copy`-Kopierbutton) durch einen echten „Beta beitreten"-Button —
anschließend `bash ops/deploy/push_site.sh` und **im echten Browser**
nachklicken, nicht mit curl. Genau diese Abkürzung hat den ursprünglichen
Fehler verdeckt: Apple lieferte die kaputte Seite nur echten Browsern aus.
