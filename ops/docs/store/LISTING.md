# HelmDeck — Play-Store-Listing (Copy-Paste-fertig)

App-Name: **HelmDeck** · Kategorie: **Produktivität** · Ads: nein · IAP: nein.
Listing-Sprachen: **Deutsch (de-DE, primär)** + **Englisch (en-US)** — die App-UI
ist deutsch mit englischem Fallback, also beide pflegen.

---

## Kurzbeschreibung (max. 80 Zeichen)

**DE** (77 Zeichen):

> Das Board, auf dem KI-Agenten arbeiten – gesteuert von deinem eigenen Rechner

**EN** (66 Zeichen):

> The board where AI agents do the work — run from your own computer

## Vollständige Beschreibung (max. 4000 Zeichen)

**DE** (~1900 Zeichen):

> HelmDeck ist die Fernbedienung für deine eigene HelmDeck-Installation: ein
> Board, auf dem Tickets sich nicht nur verwalten lassen, sondern sich selbst
> erledigen. KI-Agenten arbeiten auf deinem Rechner an echten Projekten – du
> steuerst, beantwortest Rückfragen und nimmst Ergebnisse ab, vom Telefon aus.
>
> DEIN BOARD, ÜBERALL
> • Aufträge anlegen – mit Priorität, Wert, Kunde und Anhängen (Fotos, Dateien)
> • Live zusehen, wie der Agent arbeitet: jeder Schritt im Verlauf, Turn für Turn
> • „Wartet auf dich": Rückfragen des Agenten direkt im Chat beantworten
> • Qualitäts-Gate vor jeder Abnahme: Prüfungen laufen automatisch, du siehst
>   das Ergebnis, erst deine Freigabe merged und deployt
> • Push-Benachrichtigung, wenn eine Antwort da ist oder etwas zur Abnahme steht
> • Übersicht mit echten Zahlen: gelieferter Wert, KI-Kosten, Marge pro Karte
>
> DEINE DATEN BLEIBEN DEINE
> • Die App verbindet sich ausschließlich mit deinem eigenen HelmDeck-Daemon –
>   direkt im LAN oder von unterwegs über ein Zero-Knowledge-Relay
> • Ende-zu-Ende-Verschlüsselung (Curve25519/XSalsa20-Poly1305): das Relay
>   sieht nur Chiffretext, niemals Inhalte
> • Auch Push-Nachrichten sind Ende-zu-Ende-verschlüsselt
> • Keine Werbung, keine Analytics, kein Konto beim Entwickler
>
> WICHTIG
> HelmDeck ist eine Begleit-App: Sie benötigt eine laufende
> HelmDeck-Installation auf deinem eigenen Rechner. Die Kopplung dauert eine
> Minute – QR-Code auf dem Desktop scannen, fertig.
>
> Datenschutz: https://relay.helmdeck.de/privacy

**EN** (~1700 Zeichen):

> HelmDeck is the remote control for your own HelmDeck installation: a board
> where tickets don't just get tracked — they get done. AI agents work on
> real projects on your machine; you steer, answer their questions and
> approve results from your phone.
>
> YOUR BOARD, ANYWHERE
> • File requests with priority, value, client and attachments (photos, files)
> • Watch the agent work live: every step in the timeline, turn by turn
> • "Needs you": answer the agent's questions right in the chat
> • Quality gate before every acceptance: checks run automatically, you see
>   the report, and only your approval merges and deploys
> • Push notifications when a reply arrives or work is ready for review
> • A dashboard with real numbers: value delivered, AI cost, margin per card
>
> YOUR DATA STAYS YOURS
> • The app talks exclusively to your own HelmDeck daemon — directly on your
>   LAN, or remotely through a zero-knowledge relay
> • End-to-end encryption (Curve25519/XSalsa20-Poly1305): the relay only ever
>   sees ciphertext, never content
> • Push messages are end-to-end encrypted too
> • No ads, no analytics, no developer-hosted account
>
> NOTE
> HelmDeck is a companion app: it requires a running HelmDeck installation on
> your own computer. Pairing takes a minute — scan the QR code on your
> desktop and you're in.
>
> Privacy policy: https://relay.helmdeck.de/privacy

## Grafiken

| Asset | Spez | Quelle |
|---|---|---|
| App-Icon | 512×512 PNG, ≤1 MB | Export aus `surfaces/app/assets/images/icon.png`-Pipeline (`ops/tools/gen_tokens.py`-Palette) |
| Feature-Grafik | 1024×500 PNG/JPG | noch bauen: Glass-H-Logo auf Board-Backdrop, Claim „Das Board, auf dem Arbeit sich selbst erledigt" |
| Phone-Screenshots | 1080×2400 PNG, min. 2, max. 8 | ✅ `ops/docs/store/screenshots/01-board.png` … `04-uebersicht.png` (auf Emulator gegen Demo-Daemon aufgenommen, keine echten Kundendaten) |
| 7"/10"-Tablet | optional | Board skaliert; bei Gelegenheit vom Tablet-Emulator |

Screenshot-Reihenfolge im Listing = Story: 1 Board (Hero) → 2 Karten-Verlauf
(Agent arbeitet nachvollziehbar) → 3 Wartet-auf-dich (Mensch bleibt am Steuer)
→ 4 Übersicht (Wert/Kosten/Marge).

## Sonstige Store-Angaben

- Kontakt-E-Mail: tienduyvo@googlemail.com · Website: Relay-URL bis Domain da
- Content-Rating-Fragebogen: Utility; kein öffentlich sichtbarer UGC (Chat ist
  privat gegen die eigene Installation) → erwartet „Everyone"/USK 0
- Zielgruppe: 18+ / nicht für Kinder gestaltet (vermeidet Families-Policy)
- Ads: No · In-App-Käufe: keine
- Länder: DACH zuerst (deutsche UI), Rest optional

---

## Team-Harness-Entwurf (2026-09-18, PREPARE, NICHT eingetragen)

Owner-Auftrag: „Team-Harness"-Sprache draften, dem Owner zeigen, bevor
irgendetwas in Play Console/App Store Connect eingetragen wird. Fasst
HelmDeck bewusst als **Harness für ein Team aus mehreren spezialisierten
Agenten** (Entwicklung, PM, Prozesse, Anbindungen), nicht als einzelnen
Chatbot — deckt sich mit der bereits gebauten Cell-Architektur und der
Team-Formulierung, die die Landingpage (`ops/deploy/waitlist/src/index.js`)
schon nutzt (FAQ „Was sehen die anderen im Team?"). Ersetzt die Texte oben
NICHT — eigener Abschnitt zum Vergleich, Owner entscheidet, was übernommen
wird. Grund für die neue Formulierung: die bisherige Kurzbeschreibung nennt
„KI-Agenten" nur beiläufig als Werkzeug des Boards; dieser Entwurf macht das
Team selbst zur Hauptaussage.

**Wichtiger Realitätscheck, gemessen, nicht angenommen:** Wear OS hat aktuell
**keinen eigenen und keinen gebündelten Play-Eintrag** (live geprüft
2026-09-10, siehe Kommentar zu `WEAR_REQUEST_URL` in
`ops/deploy/waitlist/src/index.js:110-115` — die Uhr-App ist bisher nur
Sideload per E-Mail-Anfrage). Die Owner-Architekturentscheidung ist zwar,
Wear OS als Formfaktor in den bestehenden `app.helmdeck`-Eintrag zu bündeln
(commit `c64c37a6`), aber das ist noch nicht hochgeladen. Der Wear-Absatz
unten ist deshalb als Baustein für DANN geschrieben, nicht zum sofortigen
Einfügen — bis zum ersten `:wear:bundleRelease`-Upload bitte NUR den
Phone-Teil verwenden.

### Kurzbeschreibung, Team-Harness (max. 80 Zeichen)

**DE** (62 Zeichen):

> Dein KI-Team arbeitet auf dem Board, du steuerst und nimmst ab

**EN** (53 Zeichen):

> Your AI team works the board, you steer and approve

### Vollständige Beschreibung, Team-Harness (max. 4000 Zeichen)

**DE:**

> HelmDeck ist der Harness für dein KI-Team: mehrere spezialisierte Agenten
> (Entwicklung, Projektmanagement, Prozesse, Anbindungen) arbeiten gemeinsam
> auf deinem eigenen Rechner an echten Aufträgen. Du bist der Kopf des Teams,
> vom Telefon aus.
>
> DEIN TEAM, IMMER ERREICHBAR
> • Jeder Auftrag wird eine Karte auf dem Board, mit Priorität, Wert und
>   Anhängen
> • Live mitverfolgen, welcher Agent gerade was tut, Schritt für Schritt im
>   Verlauf
> • „Wartet auf dich": Rückfragen direkt im Chat beantworten, ohne
>   Kontextwechsel
> • Qualitäts-Gate vor jeder Abnahme: Prüfungen laufen automatisch, erst
>   deine Freigabe merged und deployt
> • Push-Benachrichtigung, sobald das Team etwas von dir braucht oder fertig
>   ist
> • Übersicht mit echten Zahlen: gelieferter Wert, KI-Kosten, Marge je Karte
>
> DEINE DATEN BLEIBEN DEINE
> • Die App verbindet sich ausschließlich mit deinem eigenen HelmDeck-Daemon,
>   direkt im LAN oder unterwegs über ein Zero-Knowledge-Relay
> • Ende zu Ende verschlüsselt (Curve25519/XSalsa20-Poly1305): das Relay
>   sieht nur Chiffretext, nie Inhalte
> • Auch Push-Nachrichten sind Ende zu Ende verschlüsselt
> • Keine Werbung, keine Analytics, kein Konto beim Entwickler
>
> WICHTIG
> HelmDeck ist eine Begleit-App: Sie braucht eine laufende
> HelmDeck-Installation auf deinem eigenen Rechner. Kopplung dauert eine
> Minute, QR-Code auf dem Desktop scannen, fertig.
>
> Datenschutz: https://relay.helmdeck.de/privacy

**EN:**

> HelmDeck is the harness for your AI team: several specialized agents
> (engineering, project management, process, connectors) work together on
> your own machine on real tasks. You're the lead of the team, from your
> phone.
>
> YOUR TEAM, ALWAYS REACHABLE
> • Every request becomes a card on the board, with priority, value and
>   attachments
> • Watch live which agent is doing what, step by step in the timeline
> • "Needs you": answer questions right in the chat, no context switch
> • Quality gate before every approval: checks run automatically, only your
>   sign off merges and deploys
> • Push notification the moment the team needs you or finishes something
> • A dashboard with real numbers: value delivered, AI cost, margin per card
>
> YOUR DATA STAYS YOURS
> • The app talks only to your own HelmDeck daemon, directly on your LAN or
>   remotely through a zero knowledge relay
> • End to end encrypted (Curve25519/XSalsa20-Poly1305): the relay only ever
>   sees ciphertext, never content
> • Push messages are end to end encrypted too
> • No ads, no analytics, no developer hosted account
>
> NOTE
> HelmDeck is a companion app: it needs a running HelmDeck installation on
> your own computer. Pairing takes a minute, scan the QR code on your
> desktop and you're in.
>
> Privacy policy: https://relay.helmdeck.de/privacy

### Wear-OS-Zusatzabsatz (für DANN, sobald der Play-Eintrag den Formfaktor trägt)

Anhängen ans Ende der vollständigen Beschreibung, vor „WICHTIG"/"NOTE":

**DE:**

> AUCH AM HANDGELENK
> Die Wear-OS-App liegt im selben Paket wie das Telefon. Board-Stand sehen,
> mit dem Team sprechen (Diktat), und eine offene Frage mit einem Tipp
> beantworten, direkt von der Uhr.

**EN:**

> ON YOUR WRIST TOO
> The Wear OS app ships in the same package as the phone. Check the board,
> talk to the team by dictation, and answer an open question with a single
> tap, right from the watch.

### Play-Store-„Neuigkeiten"-Text für das Wear-Release (kurz, für das
Freigabeformular, sobald der erste `:wear`-Upload passiert)

**DE:** Neu: HelmDeck ist jetzt auch als Wear-OS-App verfügbar, im selben
Paket wie das Telefon. Board ansehen, dem Team etwas diktieren, eine
Rückfrage mit einem Tipp beantworten.

**EN:** New: HelmDeck is now also available as a Wear OS app, bundled with
the phone. Check the board, dictate to the team, answer a question with one
tap.
