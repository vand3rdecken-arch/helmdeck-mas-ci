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
davor nötig (Apple fügt es selbst hinzu). **Bitte prüfen**: Skript übernimmt
`git config user.name`-Herkunft wie bei `contactFirstName`/`contactLastName`
in `ASC_METADATA.md` — falls eine andere Rechtsform (Einzelunternehmen,
GmbH) der korrekte Rechtsinhaber ist, hier vor `apply` ändern.

## Kategorie

Primär: **Produktivität** (identisch zu Play, `PRODUCTIVITY` in Apples
Kategorie-Enum). Keine Sekundärkategorie.

## Screenshots

Play-Screenshots (`ops/docs/store/screenshots/01…04*.png`, 1080×2400) sind
**nicht** in Apples Pflichtgrößen. Apples Anforderungen ändern sich
erfahrungsgemäß zwischen Xcode-/ASC-Versionen häufiger als andere Store-
Vorgaben — **vor dem Hochladen im ASC-Web-UI die aktuell verlangten
Pixelmaße nachsehen**, nicht diese Datei als Wahrheit nehmen. Stand
Erstellung dieser Notiz: 6,9"/6,7"-iPhone-Format ist die praktisch
unvermeidbare Pflichtgröße, alles andere skaliert Apple aus dieser hoch/
runter, sofern keine eigenen kleineren Formate hochgeladen werden.

Kein API-Pfad hier vorbereitet — Bild-Upload läuft über einen mehrstufigen
Reservierungs-Flow (asset-Upload-Operationen, Checksum, Commit), den macht
man praktisch schneller im ASC-Web-UI oder mit Apples `Transporter`-Tool
als über ein schlankes Skript. Quelle für den Zuschnitt: die 1920px-Rohaufnahmen
unter `ops/docs/store/screenshots/play/*-1920.png` (gleicher UI-Stand,
höhere Auflösung als die fertig zugeschnittenen Play-Assets).

## Pricing & Availability

Kostenlos, keine IAP (identisch zu Play). Apples Preisschema-API
(`appPriceSchedules`) hat mehrfach über Versionen hinweg die Form
gewechselt (Tier-IDs → territoriale `appPricePoints`) — hier bewusst
**kein** Skript dafür, um nicht auf veralteter API-Doku eine falsche
Preis-Zeile zu schreiben. Web-UI-Schritt, einmalig: App Store Connect →
App → **Preise und Verfügbarkeit** → „Kostenlos" + Länder (DACH zuerst,
wie bei Play, oder gleich alle — kein technischer Unterschied).
