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
