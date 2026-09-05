# watchOS UI/UX-Entwurf: Chat mit Henry, Board/Karten, Sprachwiedergabe

**Status: ENTWURF — reine Bildschirmgestaltung zur Freigabe, kein Code, kein
Xcode-Projekt.** Diese Karte ist als `PREPARE`-Karte angelegt: ein Mensch
prüft die Entwürfe und entscheidet, ob/wie sie weitergehen (Dispatch als
Baukarte, Rückfrage, Scope-Korrektur). Nichts hier ist gebaut oder verifiziert.

**Grundlage:** `ops/docs/ios-watch-feasibility.md` §3 (2026-08-12, Empfehlung
"Phase W1 = Mirroring, kein Watch-Code"), `ops/docs/backlog/watchos-technik-machbarkeit/README.md`
(2026-09-05, technische Grenzen: kein Ambient-Modus, nur Vordergrund oder
suspendiert), sowie das bereits **gebaute** Wear-OS-Modell als Formfaktor-
Vorbild (`ops/docs/backlog/wear-os-integration/README.md`,
`ops/docs/backlog/wear-os-paritaets-audit/README.md`,
`surfaces/app/plugins/wear/{HenryScreen,BoardScreen,CardScreen,VoicePlayer}.kt`).

---

## 0. Scope — vom Owner entschieden: volle Parität zu Wear OS

Die drei angefragten Bildschirme — Chat, Board/Karten, Sprachwiedergabe —
sind **mehr** als `ios-watch-feasibility.md` §3.3 für eine Watch-Phase W2
vorgeschlagen hatte: dort steht wörtlich *"Explizit KEIN Board, kein
Transcript, kein Chat — die Watch ist ein Quittungs- und Ein-Tipp-Gerät"*.
Das Wear-OS-Modell hat diesen engen Scope am 2026-08-28 per Owner-Entscheidung
ausdrücklich verlassen ("ich will W2", volles Board+Chat+Voice).

**Owner-Entscheidung (2026-09-05, diese Karte): derselbe Kurswechsel gilt
für watchOS.** "Full parity" — die drei Bildschirme unten bleiben im vollen
Umfang der Entwurf, `ios-watch-feasibility.md` §3.3s engerer W2-Vorschlag
("kein Board, kein Chat") ist damit für watchOS **überholt**, genau wie er es
für Wear OS bereits war. Der einzige Vorbehalt bleibt technischer, nicht
Scope-Natur (s. unten): watchOS hat keinen Ambient-Modus, jeder Screen lädt
deshalb frisch statt dauerzuverbinden.

Zweiter Hinweis: **jede** hier gezeigte Live-Interaktion setzt voraus, dass
die App im Vordergrund ist. Das watchOS-Technik-Dokument (§2.2) hat
verifiziert, dass es — anders als bei Wear OS' Ambient-Modus — **keine**
Zwischenstufe gibt, in der ein Prozess gedrosselt weiterläuft. Die Entwürfe
unten sind deshalb bewusst als "beim Öffnen frisch laden + Push weckt auf"
gezeichnet, nicht als Dauerverbindung — s. §4.

---

## 1. Bildschirm: Chat mit Henry

Vorbild: `HenryScreen.kt` (Wear OS), aber ohne dessen `WearStream`-Cursor
(kein Ambient-Kanal auf watchOS möglich, §0).

```
┌─────────────────────────┐
│  ⏺ Henry          🔊 an │  <- Titel + Voice-Toggle (global, s. §3)
├─────────────────────────┤
│                          │
│  ┌───────────────────┐  │
│  │ Owner              │  │  <- rechtsbündig, Akzentfarbe
│  │ setz das auf Land   │  │
│  └───────────────────┘  │
│                          │
│ ┌────────────────────┐   │
│ │ Henry               │   │  <- linksbündig, neutral
│ │ Mach ich. Board zeigt│   │
│ │ es gleich.           │   │
│ └────────────────────┘   │
│                          │
│         ⋮ (Krone scrollt)│
├─────────────────────────┤
│   ⬤  Antwort diktieren   │  <- ein großer, daumengroßer Button
└─────────────────────────┘
```

- **Liste:** SwiftUI `List` (kein `ScrollView`+`VStack`, sonst kein
  Digital-Crown-Scroll "for free"), Bubbles linksbündig/rechtsbündig wie
  `ChatRows.kt`. Schrift auf 41 mm klein genug halten, dass 2 Zeilen ohne
  Abschneiden passen (Referenzwert: `voice-interaction-design.md`s 2-Satz-
  Register — die Antworten sind ohnehin kurz, weil sie fürs Vorlesen gebaut
  sind).
- **Ein Eingabeweg:** Diktat, kein Tastaturfeld (`presentTextInputController`
  mit `.plain`-Mode + Diktat-Vorschlag — Freitext-Autorenschaft ist laut
  `glasses-reference.md` §1 ohnehin nicht die Watch-Aufgabe, Diktat ersetzt
  hier nur das, was der Wear-OS-Mikro-Intent tut).
- **Laden statt Streamen:** beim Öffnen (`.onAppear`) einmal den Chat-Stand
  holen (Äquivalent zu `GET /wear/chat`), kein hängendes GET im Hintergrund.
  Ein Push-Weckruf (APNs, watchOS-eigener Device-Token laut
  Technik-Dokument §3) triggert bei geöffneter App einen erneuten Fetch,
  ersetzt aber **nicht** die Notwendigkeit, beim Wiederöffnen frisch zu laden.
- **Kein zweiter Chat-Speicher:** die history ist Server-Wahrheit
  (`copilot.history()`), keine lokale Kopie, die den Screen-Wechsel überlebt
  — genau die Eigenschaft, deren Fehlen der Wear-Audit auf der Karten-Seite
  bemängelt hat (§2 unten).

---

## 2. Bildschirm: Board / Karten

Vorbild: `BoardScreen.kt` + `CardScreen.kt`.

```
Board:                          Karte:
┌─────────────────────────┐    ┌─────────────────────────┐
│  Board          3 warten │    │  ← Zurück                │
├─────────────────────────┤    ├─────────────────────────┤
│ ● fix(copilot): re-plan  │    │ fix(copilot): re-plan…   │
│   working                │    │                          │
│ ● Settings-IA Phase 2    │    │ Henry fragt:              │
│   needs_you              │    │ "OTA jetzt oder Gate      │
│ ○ watchOS UI-Entwurf      │    │  abwarten?"               │
│   backlog                 │    │                          │
│         ⋮ (Krone scrollt) │    │ ┌──────┐ ┌─────────────┐ │
└─────────────────────────┘    │ │ OTA   │ │ Gate abwarten│ │
                                │ └──────┘ └─────────────┘ │
                                │                          │
                                │   ⬤ Henry fragen          │
                                └─────────────────────────┘
```

- **Board:** eine Liste, Statusfarbe als Punkt vor dem Titel (●=working,
  ○=backlog, wie die Lane-Farben aus `settings.policy.lane_labels`), kein
  Drag&Drop (kleiner Screen, kein Formfaktor dafür — vgl. auch
  `pm-board-move-ux-on-device` Karte: selbst auf dem Telefon ist das schon
  ein eigenes Feature, auf der Watch erst recht Overkill).
- **Karte:** zeigt Titel + die anstehende Frage + **echte Optionsbuttons**
  (max. 2–3, wie in W1c für Notifications bereits gelöst — Labels reisen
  wörtlich, kein Kürzen, sonst liest der Worker einen Button-Druck als
  Freitext, s. `wear-os-integration/README.md` §4.4 Punkt 2). Tippen ruft das
  Äquivalent zu `POST /tracks/<id>/answer`.
- **"Henry fragen"-Button auf der Karte — bewusst in denselben Chat, nicht
  in einen zweiten:** der Wear-Audit hat genau hier einen Bug gefunden
  (`wear-os-paritaets-audit/README.md` §2 — `CardScreen`s eigener
  Henry-Dialog lebt in lokalem State, überlebt keinen Screen-Wechsel, ist
  keine Chat-Historie). Der watchOS-Entwurf übernimmt das **nicht**: der
  Button navigiert in den EINEN Henry-Chat-Screen (§1) mit der Karte als
  Kontext-Referenz, statt einen zweiten, schwächeren Chat-Dialog auf dem
  Karten-Screen selbst zu zeichnen.
- **Was bewusst fehlt:** kein Transcript, kein Worker-Live-Tab, keine
  Freitext-Autorenschaft — dieselbe Grenze wie bei der Brille
  (`glasses-reference.md` §1) und wie im Wear-OS-Modell (§4.7 dort).

---

## 3. Bildschirm/Element: Sprachwiedergabe

Kein eigener Vollbild-Screen — ein globaler Zustand + eine kleine Indikator-
Leiste, die auf Chat- und Karten-Screen gleichermaßen gilt.

```
┌─────────────────────────┐
│  ⏺ Henry          🔊 an │  <- EIN Schalter, oben auf JEDEM Screen
├─────────────────────────┤
│  ▁▃▅▇▅▃▁  spricht …      │  <- Wellenform-Indikator während Wiedergabe
│                          │
│         ↻ nochmal        │  <- Wiederholen, falls überhört
└─────────────────────────┘
```

- **Ein Schalter, ein Ort:** die Wear-Audit-Karte hat als einzigen echten
  Bug (nicht nur Verifikationslücke) genau das Fehlen davon benannt —
  `voiceOn` existierte nur auf `HenryScreen`, `CardScreen`s eigener Dialog
  sprach unconditional weiter (`wear-os-paritaets-audit/README.md` §3/§ Offene
  Punkte 1). Für watchOS: `voiceOn` gehört auf den App-weiten State
  (`ObservableObject` auf App-Root-Ebene, nicht auf einem einzelnen View),
  genau EIN Ort, der von jedem Screen gelesen wird — kein zweiter,
  Karten-eigener Schalter.
- **Server-gerendert, kein Geräte-TTS** (stehende Owner-Entscheidung,
  `glasses-reference.md` §4) — der Client spielt nur eine MP3-URL über
  `AVAudioPlayer` ab, dieselbe Vertragsform wie `/glance/talk`/`/wear/voice`.
- **"Nochmal"-Button statt Auto-Repeat:** auf watchOS gibt es (wie bei Wear
  OS) keinen zuverlässigen "war das Handgelenk gerade oben"-Sensor für
  Sprachausgabe: `WKInterfaceDevice.current().play(.success)`-Haptik beim
  Eintreffen einer neuen Antwort + expliziter Wiederholen-Button ist robuster
  als Auto-Play-on-wake-Heuristiken.
- **Nur die jüngste sprechbare Zeile, nie Historie nachplappern** —
  identisches Muster zu `_wear_msg_key`/`spokenKey`
  (`wear-os-paritaets-audit/README.md` §3), identitätsbasiert (Hash aus
  Rolle+Zeitstempel+Text), nicht positionsbasiert.

---

## 4. Warum kein Dauerkanal gezeichnet ist

Die watchOS-Technikkarte (§2.2 dort) hat verifiziert: es gibt keinen
Sessiontyp, der zu "Chat-Kanal offenhalten" passt — normale
`URLSession`-Requests laufen nur, solange die App aktiv im Vordergrund ist,
danach Suspend innerhalb weniger Sekunden. Die drei Entwürfe oben ziehen
daraus die UI-Konsequenz:

- Jeder Screen lädt **beim Erscheinen** frisch (kein Erwartungswert
  "aktualisiert sich von selbst, während ich woanders hinschaue").
- Ein Push (APNs, eigener watchOS-Device-Token) ist der **Weckruf**, nicht
  der Datenkanal — er sollte beim Eintreffen (App im Vordergrund) einen
  Refetch auslösen, aber keine UI versprechen, die im Hintergrund
  weiterläuft.
- Für den reinen Benachrichtigungsfall (App nicht offen) bleibt Phase-W1-
  Mirroring (`ios-watch-feasibility.md` §3.3) der Weg — die drei Bildschirme
  hier sind der Vordergrund-Fall "App ist offen, Handgelenk ist oben".

## 5. Build-Weg: kein lokaler Mac nötig — dasselbe Muster wie Desktop/iOS

Owner-Vorgabe (2026-09-05): dieselbe Vorgehensweise übernehmen, mit der das
macOS-Desktop-Paket und die iOS-App bereits gebaut wurden. Beide bereits im
Baum geprüft, keine Annahme:

- **macOS-Desktop** (`.github/workflows/desktop-mac.yml`, EXECUTED
  2026-08-15): `runs-on: macos-14` — ein GitHub-Actions-Runner baut,
  signiert (`codesign`) und notarisiert (`notarytool` via App-Store-Connect-
  API-Key) das `.dmg`/`.zip`, **ohne dass irgendwo ein physischer Mac im
  Spiel ist.** Fehlen die Signing-Secrets, läuft der Build trotzdem durch
  (unsigniert) — Secrets lassen sich später nachreichen, ohne den Workflow
  zu ändern.
- **iOS** (`surfaces/app/eas.json`): EAS Build in der Cloud
  (`ios-watch-feasibility.md` §2.1: "EAS, ohne Diskussion"), Submit zu App
  Store Connect über denselben API-Key-Mechanismus (`ascApiKeyId:
  AZQRY4K34W`, bereits konfiguriert, `helmdeck-mac-developer-id-cert`-Memo).

**Für watchOS heißt das:** derselbe `macos-14`-Runner, der heute
`desktop-mac.yml` fährt, hat Xcode vorinstalliert und kann ein watchOS-Ziel
genauso per `xcodebuild` bauen, signieren, notarisieren/zu TestFlight hochladen
— mit demselben ASC-Key. Der Einwand aus `ios-watch-feasibility.md` §3.2
("realistisch braucht die Entwicklung dann doch einen Mac") bezog sich auf
**iteratives** Entwickeln (schneller Run-Debug-Zyklus in Xcode Live Preview);
für den **Build-/Verify-Schritt selbst** trägt dasselbe Muster wie beim
Desktop-Paket: ein neuer, kleiner Workflow (`watchos-app.yml`, Kopie von
`desktop-mac.yml`s Aufbau) statt eines lokalen Macs. Iterieren am UI-Layout
bliebe langsamer (Cloud-Build-Runden statt Live-Preview), aber **"kein Mac
verfügbar" ist damit kein Blocker mehr für Bau + Verifikation** — nur für
schnelles Live-Iterieren am Layout selbst.

## 6. Offene Punkte, die diese Karte nicht klärt

1. **Korrigiert durch §5:** "kein Mac/Simulator erreichbar" gilt nur für
   DIESES Karten-Worktree (Windows, kein Xcode lokal) — nicht für das Projekt
   insgesamt. Diese Entwürfe selbst sind weiterhin nicht gegen einen echten
   watchOS-Renderer geprüft, nur gegen SwiftUI-Idiome (`List`,
   Digital-Crown-Scroll, `presentTextInputController`) aus
   Apple-Dokumentation — der GitHub-Actions-Pfad ändert daran nichts, er löst
   nur die Bau-Frage, nicht die Entwurfsprüfung.
2. Komplikation ("N Karten warten auf dich") ist in `ios-watch-feasibility.md`
   §3.3 als Teil von W2 vorgesehen, hier nicht entworfen — eigener,
   kleinerer Bildschirm-Typ (WidgetKit/ClockKit), separat zu skizzieren falls
   gewünscht.
3. Sprachpfad für die Diktat-Eingabe selbst (`presentTextInputController`
   Diktier-Modus) ist in der Technikkarte als offener Punkt 1 vermerkt,
   nicht recherchiert — vor jeder Umsetzung nachzuholen.
4. Nächster logischer Schritt (Dispatch-Entscheidung des Owners, nicht Teil
   dieser Karte): eine Baukarte für den watchOS-Modul-Rumpf, analog zu W2a
   im Wear-OS-Modell (`wear-os-integration/README.md` §4.5) UND zu
   `desktop-mac.yml` — Xcode-Projekt-Skelett + leere SwiftUI-Views + der neue
   `watchos-app.yml`-Workflow, die laut Plan starten/bauen und nichts sonst
   tun, ohne bereits Netzwerk-/Krypto-Code zu schreiben.
