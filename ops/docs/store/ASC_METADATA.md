# HelmDeck — App Store Connect / TestFlight-Metadaten (Entwurf)

**Status: ENTWURF.** Nichts hier ist eingereicht oder abgeschickt. Diese
Datei ist die Zuarbeit für `ops/deploy/asc_metadata_draft.py apply` bzw. für
manuelles Ausfüllen in App Store Connect — der Mensch prüft Inhalt und
Zahlen (Kontakt-Telefon fehlt bewusst) und drückt selbst auf Speichern/Absenden.

Fixierter Scope (`ops/docs/ios-requirements.md` §1/§7): **TestFlight, internes
Testing, kein App-Store-Release.** Interne Tests (bis 100 Team-Mitglieder)
brauchen **keine** Beta App Review und **keine** App-Privacy-Nutrition-Label
(die ist erst für externes Testing/Store-Release Pflicht). Diese Datei deckt
deshalb nur, was für TestFlight tatsächlich existiert: Beta App Review
Detail, Beta App Localization, Beta Build Localization. Volles App-Privacy-
Formular und Store-Listing (Screenshots, Keywords, Kategorie) bleiben
zurückgestellt, bis ein Store-Release ansteht — dann `ops/docs/store/LISTING.md`
als Basis nehmen (DE/EN-Texte existieren schon, nur Apple-Zeichenlimits
prüfen: Subtitle 30, Promotional Text 170, Keywords 100 gesamt).

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
| `contactPhone` | *(leer)* | **Owner muss eintragen** — keine Telefonnummer im Repo, wird nicht erfunden |
| `demoAccountRequired` | `false` | Die App hat kein Entwickler-Konto (`daemon/auth.py` ist pro Installation); Login läuft gegen die *eigene* HelmDeck-Instanz des Testers |
| `demoAccountName` / `demoAccountPassword` | *(leer)* | s.o., kein zentrales Konto zum Herausgeben |
| `notes` (DE) | „HelmDeck ist eine Begleit-App: Sie funktioniert nur zusammen mit einer eigenen laufenden HelmDeck-Installation (Desktop/Server). Es gibt kein zentrales Entwickler-Konto und keinen Demo-Login — Pairing erfolgt per QR-Code, den die Installation selbst anzeigt. Für einen reinen UI-Rundgang ohne eigene Installation bitte den Owner kontaktieren." | erklärt Apples Reviewer, warum `demoAccountRequired=false` trotz Login-Bildschirm korrekt ist |

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
| `privacyPolicyUrl` | https://141.144.227.105.sslip.io/privacy |
| `tvOsPrivacyPolicy` | *(leer, keine tvOS-App)* |

### en-US

| Feld | Wert |
|---|---|
| `description` | HelmDeck is the companion app for your own HelmDeck installation: a board where AI agents work on real tasks while you steer, answer questions and approve results — from your phone. The app talks only to your own machine/server; content is end-to-end encrypted (Curve25519/XSalsa20-Poly1305). This beta is the internal test channel ahead of a possible App Store release. |
| `feedbackEmail` | tienduyvo@googlemail.com |
| `marketingUrl` | https://helmdeck.de |
| `privacyPolicyUrl` | https://141.144.227.105.sslip.io/privacy |
| `tvOsPrivacyPolicy` | *(leer)* |

⚠ Die Privacy-Policy-Seite (`surfaces/relay/relay.py PRIVACY_HTML`) ist noch auf dem
Android/FCM-Stand von `ops/docs/store/DATA_SAFETY.md` geschrieben — sie erwähnt
weder PostHog-Analytics (seit `[NEU]` in `ops/docs/ios-requirements.md` §2) noch
Apple/APNs (Push läuft auf iOS aktuell noch über den rohen FCM-Token,
Umbau auf Expo Push ist offener Punkt in `ops/docs/ios-requirements.md` §3).
Die URL selbst ist live und nutzbar, der **Inhalt braucht ein eigenes
Update** sobald Analytics/iOS-Push angepasst sind — nicht Teil dieser Karte,
hier nur vermerkt, damit es nicht als „schon erledigt" gilt.

## 4. Beta Build Localization (pro Build, „What to Test")

Für den aktuellen Build `e67d1247` (erster iOS-TestFlight-Build).

| Sprache | `whatsNew` |
|---|---|
| de-DE | Erster interner Testbuild. Bitte prüfen: Pairing per QR-Code vom Desktop, Board ansehen, eine Karte mit Foto-Anhang anlegen, Push-Benachrichtigung bei einer Agenten-Rückfrage. |
| en-US | First internal test build. Please check: QR-code pairing from the desktop, viewing the board, creating a card with a photo attachment, receiving a push notification for an agent question. |

## 5. Was hier bewusst NICHT gemacht wird

- Kein Absenden zur Beta App Review (interner Test braucht keine).
- Keine App-Privacy-Nutrition-Label-Einträge (erst Store-Release-Pflicht,
  siehe oben) — würde ohnehin die PostHog/Analytics-Aktualisierung aus
  Abschnitt 3 voraussetzen, sonst wären die Angaben selbst schon veraltet.
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
