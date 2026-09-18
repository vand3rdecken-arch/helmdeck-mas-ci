# HelmDeck — App-Store-Listing (Apple, Copy-Paste-fertig)

Apple-Pendant zu `LISTING.md` (das ist Play). Eigene Datei, weil Apples
Felder und Zeichenlimits andere sind als bei Google — Subtitle und Keywords
existieren bei Play gar nicht, die Kurzbeschreibung dort (66–77 Zeichen) ist
für ein 30-Zeichen-Subtitle viel zu lang. Beschreibung/Kategorie/Kontakt
sind inhaltlich identisch zu `LISTING.md`, hier nicht dupliziert.

## Subtitle (max. 30 Zeichen — unter dem App-Namen, nicht durchsuchbar)

| Sprache | Text | Länge |
|---|---|---|
| DE | KI-Agenten erledigen Arbeit | 27 |
| EN | AI agents get the work done | 27 |

## Promotional Text (max. 170 Zeichen — änderbar ohne neue Review)

| Sprache | Text | Länge |
|---|---|---|
| DE | HelmDeck verbindet sich mit deiner eigenen Installation: KI-Agenten arbeiten an echten Aufgaben, du steuerst und nimmst ab – Ende-zu-Ende-verschlüsselt. | 152 |
| EN | HelmDeck connects to your own installation: AI agents work on real tasks while you steer and approve — all end-to-end encrypted. | 128 |

## Keywords (max. 100 Zeichen gesamt, kommagetrennt, keine Leerzeichen nach dem Komma)

| Sprache | Text | Länge |
|---|---|---|
| DE | KI,Agent,Automatisierung,Board,Produktivität,Tickets,Kanban,Projektmanagement,Team,Workflow | 91 |
| EN | AI,agent,automation,board,productivity,tickets,kanban,project management,workflow,team | 86 |

Wörter aus App-Name/Subtitle nicht wiederholen (Apple indexiert die bereits
mit) — „HelmDeck", „Board", „Arbeit"/"work" tauchen deshalb bewusst nicht
in beiden gleichzeitig auf.

## Beschreibung (max. 4000 Zeichen)

Identisch zu `LISTING.md` §„Vollständige Beschreibung" (DE ~1900 / EN ~1700
Zeichen, weit unter dem Limit) — dort pflegen, hier nicht duplizieren.

## Support-URL (Pflichtfeld, getrennt von Marketing-URL)

`https://helmdeck.de` — keine dedizierte Support-Unterseite vorhanden;
Kontakt-Mail steht dort. Marketing-URL identisch (`https://helmdeck.de`).

## Copyright

`2026 Tien Duy Vo` — Apple-Format ist `<Jahr> <Rechtsinhaber>`, kein „©"
davor nötig (Apple fügt es selbst hinzu). **Bitte prüfen**: aus
`git config user.name`, wie bei `contactFirstName`/`contactLastName` in
`ASC_METADATA.md` — falls eine andere Rechtsform (Einzelunternehmen, GmbH)
der korrekte Rechtsinhaber ist, in `surfaces/app/store.config.json` →
`apple.copyright` vor dem Push ändern.

## Kategorie

Primär: **Produktivität** (identisch zu Play, `PRODUCTIVITY` in Apples
Kategorie-Enum). Keine Sekundärkategorie.

## Altersfreigabe (Age Rating / „Advisory")

**Korrektur ggü. `EXTERNAL_TESTFLIGHT.md`:** dort stand, die ASC-API böte
kein Age-Rating-Formular an — Stand 2026-09-02, zu dem Zeitpunkt vermutlich
richtig recherchiert. Inzwischen existiert `ageRatingDeclarations`
(`GET /v1/appStoreVersions/{id}/ageRatingDeclaration`,
`PATCH /v1/ageRatingDeclarations/{id}`, ~29 Attribute, zuletzt erweitert um
Social-Media-Fragen im Juli 2026) — per API schreibbar. Alle Kategorien auf
`NONE`/`false` (kein Glücksspiel, keine Gewalt, keine Kontakte zu
Fremden/UGC-Feed, kein uneingeschränkter Web-Zugriff — die App hat keinen
eingebetteten Browser), erwartete Einstufung: **4+**. Deklariert in
`surfaces/app/store.config.json` → `apple.advisory`, geschrieben via
`eas metadata:push` (s. `APP_STORE_RELEASE.md`) — kein separater
Web-UI-Schritt mehr nötig.

## Export-Compliance

Bereits erledigt, keine weitere Aktion: `ITSAppUsesNonExemptEncryption: false`
steht im Binary (`app.json → ios.infoPlist`, s. `ASC_METADATA.md` §1) und
gilt build-weit — dieselbe Antwort deckt TestFlight **und** Store-Release ab,
da es keine pro-Vertriebskanal-Deklaration ist, sondern am Build hängt.

## Screenshots

**Korrektur ggü. einer früheren Version dieser Datei:** die `play/*-1920.png`
sind **keine** höher aufgelöste Quelle — sie sind 1080×1920 (0,5625
Seitenverhältnis), eine frühere/kleinere Aufnahme *vor* dem finalen
1080×2400-Play-Zuschnitt, also niedriger, nicht höher aufgelöst. Als Basis
dienen die fertigen `01…04*.png` (1080×2400, Seitenverhältnis 0,45).

Generiert per `py -3.12 ops/tools/make_appstore_screenshots.py` →
`ops/docs/store/screenshots/appstore/iphone-6.9/0N-*.png` (1320×2868,
Apples aktuelle iPhone-6,9"-Pflichtgröße, verifiziert per Websuche
2026-09-05 — Zielgröße kann sich seither verschoben haben, vor dem Hochladen
im ASC-Web-UI gegenprüfen). Skaliert auf Zielbreite, dann mittig auf
Zielhöhe zugeschnitten (65px insgesamt, oben+unten je ~33px) — bei allen vier
Screens geprüft: kein Content-Verlust, nur der leere Rand unterhalb der
Tab-Bar wird knapper.

**Offen: iPad-Screenshots.** `surfaces/app/app.json` setzt
`ios.supportsTablet: true`, Apples aktuelle Pflichtgröße dafür ist 13"
(2064×2752, Seitenverhältnis 0,75). Die vorhandenen Screenshots sind
Phone-Aufnahmen (0,45) — auf die iPad-Fläche zuschneiden würde den Großteil
der Breite abschneiden, aufpolstern (Letterboxing) sähe wie ein
plattgedrücktes Phone-Bild aus, nicht wie eine echte iPad-Aufnahme. Bewusst
**nicht** generiert, drei Optionen für den Owner:
1. Echten Screenshot vom iPad-Simulator aufnehmen (braucht Xcode — nicht auf
   dieser Windows-Box verfügbar, nur auf einem Mac).
2. Im ASC-Upload-Dialog prüfen, ob für dieses Build (keine dedizierte
   iPad-Oberfläche, nur hochskaliertes Phone-Layout) überhaupt ein
   eigenständiges iPad-Set zwingend verlangt wird, bevor man Zeit investiert.
3. `ios.supportsTablet` auf `false` setzen — braucht aber einen **neuen**
   Build (Info.plist-Flag), widerspricht damit „kein Re-Upload nötig" für
   den aktuellen TestFlight-Build.

## Team-Harness-Entwurf: Promotional Text + nächste Versionsbeschreibung (2026-09-18, PREPARE, NICHT eingetragen)

Owner-Auftrag: gleicher „Team-Harness"-Sprachentwurf wie in `LISTING.md`,
hier für die zwei ASC-Felder, um die die Karte ausdrücklich bittet:
Promotional Text und die Versionsbeschreibung des nächsten Release
(„What's New in This Version"). Dieses Skript-Feld ist NICHT dasselbe wie
`ops/deploy/asc_metadata_draft.py`s `BUILD_WHATS_NEW` (das ist der
TestFlight-„What to Test"-Text für Beta-Tester); hier geht es um die Notizen
für ein tatsächliches App-Store-Release, das laut `ASC_METADATA.md` §5 und
der Site-Kopie noch aussteht („Der App-Store-Eintrag folgt"). Reine Prosa,
nichts davon läuft über ein Skript, damit nichts versehentlich live
geschrieben wird, solange kein Store-Release ansteht.

### Promotional Text, Team-Harness (max. 170 Zeichen, ohne neue Review änderbar)

| Sprache | Text | Länge |
|---|---|---|
| DE | HelmDeck ist der Harness für dein KI-Team: mehrere Agenten erledigen echte Aufgaben, du steuerst und nimmst ab. Ende zu Ende verschlüsselt. | 139 |
| EN | HelmDeck is the harness for your AI team: several agents get real work done while you steer and approve. End to end encrypted. | 126 |

### Versionsbeschreibung für das nächste Release ("What's New in This Version")

Fasst zusammen, was seit der letzten dokumentierten Versionsbeschreibung
(§4 oben, Build für 1.0.48/versionCode 91) tatsächlich an Nutzer-sichtbaren
Änderungen im Baum liegt, aus Commit-Historie verifiziert (nicht erfunden):
Chat-Aufwach-/Catch-up-Fix (`d3171075`/`4a5981bf`), Henry zeigt jetzt
eigene Hintergrund-Agenten statt Stille (`e50e6a61`/`3c1ef81f`), Hands-
Ergebnisse erscheinen als klar abgegrenzte Ergebnis-Box statt Rohtext
(`8eb469ce`), kleinere Wear-OS-Fixes (Ambient-Modus, Kopplungs-Screen,
`4f360250`/`a0d88137`). Aktueller Stand laut `app.json`: Version 1.0.51,
versionCode 94.

| Sprache | Text |
|---|---|
| DE | Antworten kommen jetzt zuverlässig an, auch nachdem Handy, Desktop oder Uhr aufgewacht sind. Henry zeigt jetzt an, wenn er im Hintergrund weiterarbeitet, und liefert Ergebnisse aus dem Hintergrund klar aufbereitet zurück statt als Rohtext. Kleinere Verbesserungen an der Wear-OS-Uhr-App (Ambient-Modus, Kopplung). |
| EN | Replies now arrive reliably, even after your phone, desktop or watch wakes up. Henry now shows when it keeps working in the background, and hands results come back as a clear summary instead of raw text. Small fixes to the Wear OS watch app (ambient mode, pairing). |

**Hinweis für den Owner:** dieser Text ist für die ÖFFENTLICHE
App-Store-Version geschrieben, sobald der TestFlight-Only-Stand endet — bis
dahin bleibt `ASC_METADATA.md` §4 (TestFlight-„What to Test") die aktive
Baustelle, dieser Absatz hier ist Vorrat für danach.

## Pricing & Availability

Kostenlos, keine IAP (identisch zu Play), **weltweit verfügbar** (Owner-
Entscheidung 2026-09-05 — nicht DACH-first wie ursprünglich bei Play
überlegt). Apples Preisschema-API (`appPriceSchedules`) hat mehrfach über
Versionen hinweg die Form gewechselt (Tier-IDs → territoriale
`appPricePoints`) — hier bewusst **kein** Skript dafür, um nicht auf
veralteter API-Doku eine falsche Preis-Zeile zu schreiben. Web-UI-Schritt,
einmalig: App Store Connect → App → **Preise und Verfügbarkeit** →
„Kostenlos" + „Alle Länder/Regionen verfügbar machen".
