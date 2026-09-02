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
