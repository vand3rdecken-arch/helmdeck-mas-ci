# HelmDeck — App Store Connect / TestFlight-Metadaten (Entwurf)

**Status: ANGEWENDET am 2026-09-02, „What to Test" am 2026-09-05 im Repo
neu entworfen (dieser Commit) für den nächsten Build — noch NICHT
angewendet.** Der Rest der Felder (Beta App Review Detail, Localizations)
steht seit 2026-09-02 live in App Store Connect und ändert sich hier nicht.
Der Kontakt-Telefon-Platzhalter ist gefüllt — der Owner hat die Nummer am
2026-09-02 geliefert.

**Scope-Änderung, Owner-Entscheidung 2026-09-02: internes → EXTERNES
Testing.** `ops/docs/ios-requirements.md` §1/§7 fixierte vorher „TestFlight,
internes Testing, kein App-Store-Release". Das galt, bis sichtbar wurde, was es
kostet: internes Testing hat **prinzipbedingt keinen öffentlichen Beitritts-
Link** (Apple lädt nur per Apple-ID-Mail ein), weshalb die iOS-Karte auf
helmdeck.de nichts zu verlinken hatte und stattdessen einen `mailto:` anbot,
der bei jedem Besucher ohne Mail-Client **wirkungslos** war (im echten Browser
gemessen: kein Navigieren, kein neuer Tab). Externes Testing erzeugt eine echte
`testflight.apple.com/join/...`-URL.

Was der Wechsel zusätzlich verlangt:
- **Beta App Review** für den Build (24–48 h) — `ops/deploy/asc_external_beta.py`.
- **App-Privacy-Angaben und Altersfreigabe.** Die deckt die App-Store-Connect-
  **API nicht ab** — reiner Web-UI-Schritt mit Apple-ID + 2FA, siehe
  `EXTERNAL_TESTFLIGHT.md`.

Store-Listing (Screenshots, Keywords, Kategorie) bleibt weiter zurückgestellt,
bis ein echtes Store-Release ansteht — dann `ops/docs/store/LISTING.md` als
Basis nehmen (DE/EN-Texte existieren schon, nur Apple-Zeichenlimits prüfen:
Subtitle 30, Promotional Text 170, Keywords 100 gesamt).

Live-Werte (siehe `DEPLOY.md` §2b/§2c, `ops/deploy/asc_build_state.py`):
ASC App-ID `6801637667`, Bundle `app.helmdeck`, SKU `helmdeck-001`, primäre
Sprache Deutsch, aktueller Build `e67d1247` (Submission `da233c48`).

---

## 1. Export Compliance — bereits entschieden, hier nur dokumentiert

`app/app.json → ios.infoPlist.ITSAppUsesNonExemptEncryption: false`. Damit
fragt Apple bei jedem Upload **nicht** mehr einzeln nach — die Antwort ist
im Binary hinterlegt und deckt auch TestFlight.

⚠ **Prüfpunkt für den Menschen, nicht stillschweigend geändert:** Die App
verschlüsselt Nachrichteninhalte selbst mit `tweetnacl` (Curve25519/
XSalsa20-Poly1305, `surfaces/app/src/data/e2ee.ts`) — das ist mehr als reines
Transport-TLS. `false` heißt "keine nicht-ausgenommene Verschlüsselung" und
ist trotzdem die verbreitete, korrekte Antwort für Apps, die ausschließlich
**Standard-/Public-Domain-Algorithmen** einsetzen (NaCl ist offen
publiziert, keine Eigenentwicklung) — das fällt unter die Massenmarkt-
Ausnahme (EAR Category 5 Part 2, License Exception ENC/Note 4), genau wie
bei Signal/WhatsApp. Was Apples Formular **nicht** abnimmt: die jährliche
Selbstklassifizierungsmeldung an US BIS/NSA, falls diese für den
Rechtsträger überhaupt zutrifft. **Frage an den Owner:** wurde das je
geprüft/eingereicht, oder ist die Massenmarkt-Ausnahme ohne Meldepflicht der
richtige Stand? (Kein Automatismus hier — das ist eine Rechtsfrage, keine
Code-Frage.)

## 2. Beta App Review Detail (App-weit, ein Objekt)

Nur relevant, sobald extern getestet wird (intern braucht keine Review) —
trotzdem jetzt befüllen, damit ein späterer Wechsel auf externes Testing
keinen Leerlauf-Schritt hat.

| Feld | Entwurfswert | Quelle/Begründung |
|---|---|---|
| `contactFirstName` | Tien Duy | `git config user.name` — **bitte prüfen**, Skript rät nicht weiter |
| `contactLastName` | Vo | s.o. |
| `contactEmail` | tienduyvo@googlemail.com | Kontakt-E-Mail aus `ops/docs/store/LISTING.md` |
| `contactPhone` | *(steht live in ASC, bewusst nicht im Repo)* | Owner-Angabe 2026-09-02, einmal nach App Store Connect geschrieben. Steht **nicht** im Code: eine private Telefonnummer in einer getrackten Datei wäre PII in der Git-History, und History schreiben wir nicht um. `apply` lässt das Feld weg → JSON:API-PATCH erhält den gespeicherten Wert. Ändern über `ASC_CONTACT_PHONE` (env/`.env`, beide git-ignored) oder direkt im ASC-Web-UI |
| `demoAccountRequired` | `false` | Die App hat kein Entwickler-Konto (`daemon/auth.py` ist pro Installation); Login läuft gegen die *eigene* HelmDeck-Instanz des Testers |
| `demoAccountName` / `demoAccountPassword` | *(leer)* | s.o., kein zentrales Konto zum Herausgeben |
| `notes` (EN) | erklärt `demoAccountRequired=false` **und weist den Reviewer auf den Demo-Modus**: erster Screen → „Try it without your own computer" / „Ohne eigenen Rechner ausprobieren" (`surfaces/app/src/ui/pairing_gate.tsx`, Label `demo.cta`) | Der alte Text („für einen UI-Rundgang bitte den Owner kontaktieren") stammt aus der Intern-Ära ohne Review. Bei **externer** Review ist er eine sichere 2.1-Ablehnung: ein Reviewer schreibt keine Mail, er lehnt ab. Demo-Modus (`surfaces/app/src/data/demo.ts`, seit 2026-08-24 im Baum, also in jedem einreichbaren Build) liefert den kompletten Prüfpfad ohne Hardware. Englisch, weil Apples Review-Team international liest |

## 3. Beta App Localization (App-weit, pro Sprache — „Beta App Description")

Texte sind die TestFlight-Kurzbeschreibung + Links, **nicht** das volle
Store-Listing. Basis: `ops/docs/store/LISTING.md` Kurzbeschreibung, gekürzt/
umformuliert auf Beta-Kontext.

### de-DE (primär)

| Feld | Wert |
|---|---|
| `description` | HelmDeck ist die Begleit-App für deine eigene HelmDeck-Installation: ein Board, auf dem KI-Agenten an echten Aufgaben arbeiten, während du steuerst, Rückfragen beantwortest und Ergebnisse abnimmst — vom Telefon aus. Die App verbindet sich ausschließlich mit deinem eigenen Rechner/Server, Inhalte sind Ende-zu-Ende-verschlüsselt (Curve25519/XSalsa20-Poly1305). Diese Beta ist der interne Testkanal vor einem möglichen Store-Release. |
| `feedbackEmail` | tienduyvo@googlemail.com |
| `marketingUrl` | https://helmdeck.de |
| `privacyPolicyUrl` | https://relay.helmdeck.de/privacy |
| `tvOsPrivacyPolicy` | *(leer, keine tvOS-App)* |

### en-US

| Feld | Wert |
|---|---|
| `description` | HelmDeck is the companion app for your own HelmDeck installation: a board where AI agents work on real tasks while you steer, answer questions and approve results — from your phone. The app talks only to your own machine/server; content is end-to-end encrypted (Curve25519/XSalsa20-Poly1305). This beta is the internal test channel ahead of a possible App Store release. |
| `feedbackEmail` | tienduyvo@googlemail.com |
| `marketingUrl` | https://helmdeck.de |
| `privacyPolicyUrl` | https://relay.helmdeck.de/privacy |
| `tvOsPrivacyPolicy` | *(leer)* |

~~⚠ Die Privacy-Policy-Seite erwähnt weder PostHog-Analytics noch Apple/APNs.~~
**Überholt — am 2026-09-02 nachgemessen:** `https://relay.helmdeck.de/privacy`
antwortet HTTP 200 mit 9.555 Bytes und enthält 10 Treffer auf PostHog/Analytics.
Die Warnung stammte aus der Zeit vor dem Analytics-Update der Seite. Offen
bleibt nur der APNs-Punkt (iOS-Push läuft noch über den rohen FCM-Token, Umbau
auf Expo Push ist offener Punkt in `ops/docs/ios-requirements.md` §3) — der
gehört in die Datenschutzerklärung, sobald er umgebaut ist.

## 4. Beta Build Localization (pro Build, „What to Test")

`e67d1247` war der allererste iOS-TestFlight-Build (2026-08-14, §2c in
`DEPLOY.md`); seither sind mehrere Builds gefolgt (zuletzt dokumentiert:
`1.0.45 (7)`, eingereicht 2026-09-02, siehe `EXTERNAL_TESTFLIGHT.md`). Der
Text unten ist der Entwurf für den **nächsten** Build (`app.json` steht auf
`1.0.48`/versionCode 91, App-sichtbare Änderungen seit 1.0.45: Mehr-Tab neu
sortiert, PM-Dashboard als ein Übersichtsblatt, Prozess-Schritte bearbeiten,
History-500er behoben, Brillen-Mikrofon-Steuerung) — er wird erst mit
`apply --yes` **nach** dem nächsten `eas submit` live, weil `apply` ihn an
`_latest_build()` hängt.

| Sprache | `whatsNew` |
|---|---|
| de-DE | Seit dem letzten Testbuild ist einiges dazugekommen. Bitte prüfen: der neu sortierte Mehr-Tab (Zurück-Navigation, doppelte Einträge entfernt), das PM-Dashboard (Ziel, Timeline & Budget als ein Übersichtsblatt statt Dreieck-Report), in einem Prozess einen Schritt hinzufügen/umsortieren/löschen, und der Verlauf (History) sollte wieder laden. Für Brillen-Besitzer: das Mikrofon wird jetzt von der Brille selbst gestartet, gesprochener Text wird vor dem Senden angezeigt und bestätigt. |
| en-US | Many app changes landed since the last test build. Please check: the reorganized Mehr/Settings tab (back navigation, duplicate entries removed), the PM dashboard (goal, timeline & budget as one overview instead of the triangle report), adding/reordering/removing a step in a process, and that History loads again. For glasses owners: the microphone now starts from the glasses themselves, and spoken text is shown and confirmed before it is sent. |

## 5. Was hier bewusst NICHT gemacht wird

- ~~Kein Absenden zur Beta App Review~~ — **gilt nicht mehr.** Mit dem Wechsel
  auf externes Testing ist die Review Pflicht; sie läuft über
  `ops/deploy/asc_external_beta.py submit`, nicht über dieses Skript. Dieses
  Skript schreibt weiterhin ausschließlich Textfelder.
- Keine App-Privacy-Nutrition-Label-Einträge **hier** — nicht weil sie
  entbehrlich wären (für externes Testing sind sie Pflicht), sondern weil die
  App-Store-Connect-API sie **nicht anbietet**. Web-UI-Schritt, siehe
  `EXTERNAL_TESTFLIGHT.md`.
- Kein Ändern von `ITSAppUsesNonExemptEncryption` — reine Rechtsfrage,
  s. Abschnitt 1.
- Kein volles Store-Listing (Kategorie, Keywords, Screenshots) — außerhalb
  des fixierten Scopes (`ops/docs/ios-requirements.md` §7).

## 6. Anwenden

```bash
py -3.12 ops/deploy/asc_metadata_draft.py show     # liest aktuellen ASC-Stand, ändert nichts
py -3.12 ops/deploy/asc_metadata_draft.py apply --yes   # schreibt die Entwürfe oben (PATCH/POST, kein Review-Submit)
```

Braucht `.env` mit `ASC_KEY_ID`/`ASC_ISSUER_ID`/`ASC_API_KEY_PATH` (liegt
nicht in diesem Worktree — auf der Hauptbox ausführen, s. `DEPLOY.md` §2b).
Vor `apply`: `contactPhone` oben ergänzen und die Export-Compliance-Frage in
Abschnitt 1 für sich beantwortet haben.
