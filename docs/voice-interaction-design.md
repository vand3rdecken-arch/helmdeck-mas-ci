# Sprachinteraktion je Plattform — Design

**STATUS: ENTWURF ZUR FREIGABE.** Kein Code in diesem Kartenlauf. Dieses
Dokument soll entschieden werden, *bevor* plattformspezifisch gebaut wird — die
offenen Entscheidungen stehen in §7.

**Stand:** 2026-08-21. Alles unter „verifiziert" ist in diesem Worktree gelesen
(Datei:Zeile) oder aus einer Primärquelle belegt (URL). Alles andere ist als
**unverifiziert** markiert und darf nicht als Grundlage für einen Bau dienen.

Pflichtlektüre vorab und Grundlage dieses Dokuments:
`docs/glasses-reference.md` (§3.1, §4.4, §11.6, §11.7, §11.9).

---

## 1. Der eine Satz

> **Erkennen ist Plattformarbeit, Sprechen ist Serverarbeit, und dazwischen
> liegt genau eine Naht: Text rein, Prosa + Clip + Optionen raus.**

Diese Naht existiert bereits zweimal und ist transportagnostisch:

| Naht | Rein | Raus |
|---|---|---|
| `POST /glance/talk` | `{token, message}` | `{reply, question, refused, voice: <URL>}` (`routes_glance.py:182-192`) |
| `POST /chat` | `{text, voice: true}` | `{reply, …, voice: {id, mime, b64}}` (`routes_copilot.py:53-61`) |

Beide interessiert es nicht, ob die Wörter aus einem HFP-Mikro, dem Telefonmikro
oder einer Tastatur kamen (`glasses-reference.md` §11.7). **Deshalb ist
„plattformspezifisch bauen" ausschließlich: die Aufnahme-Hälfte und die
Abspiel-Hälfte.** Es gibt keinen zweiten Konversationsmotor und darf keinen
geben.

Der Grund, warum Sprechen serverseitig bleibt und nicht per Geräte-TTS: die
Linse hat **kein `speechSynthesis`** (on-device gemessen 2026-07-16,
`glasses-reference.md` §3.1) — spielt aber Audio ab. Eine Plattform, die die
härteste Anforderung stellt, definiert die Naht für alle; sonst hätte HelmDeck
pro Oberfläche eine andere Stimme, ein anderes Register und einen zweiten Ort,
an dem die Vorlese-Regeln aus §3 durchgesetzt werden müssten.

---

## 2. Ist-Stand — was heute wirklich läuft

| Oberfläche | Spricht (out) | Hört (in) | Rückfrage-Kanal | Zustand |
|---|---|---|---|---|
| **Linse** (`glasses/`, MRBD-Webview) | ✅ Talk-Antwort + Blocker-Ansage, `mute`/`repeat` (`app.js:378,420`) | ❌ Webview verweigert jede Aufnahme | D-Pad-Auswahl, `/glance/answer` | **produktiv** |
| **Android-Telefon** (Expo RN) | ⛔ keine Audio-Abhängigkeit im Baum (`app/package.json`: kein `expo-audio`/`expo-speech`) | ⛔ dito | — | **nicht gebaut** |
| **Android nativ** (`GlassVoiceService.kt`) | ✅ `MediaPlayer` auf die Clip-URL (`:319`) | ✅ `SpeechRecognizer` über HFP (`:223`) | ❌ **verworfen — siehe §4.3** | **Code vorhanden, nirgends aufgerufen** |
| **iOS-Telefon** | ⛔ | ⛔ | — | **nicht gebaut** |
| **Apple Watch** | ⛔ | ⛔ | — | **nicht analysiert** (`docs/ios-watch-feasibility.md` behandelt nur Push-Mirroring) |
| **Desktop** (Electron/Web-UI) | ⛔ kein `speechSynthesis`-Aufruf im Baum | ⛔ | — | **nicht gebaut** |
| **WhatsApp-Kanal** | 📄 entschieden, nie gebaut (`glasses-reference.md` §4) | n/a | Textantwort | **Papier** |

Drei Befunde daraus, die den Bau steuern:

1. **`GlassVoiceService.kt` ist ein Torso.** `grep GlassVoice app/src` findet
   nichts: nichts startet den Service, und **niemand schreibt jemals
   `base_url`/`glance_token` in die SharedPreferences**, die er in `ask()`
   liest (`:276-281`). Er würde heute mit „Nicht verbunden – in HelmDeck
   koppeln" enden. Er ist kein fertiger Pfad, sondern eine sehr gut belegte
   Vorlage.
2. **Der Mikro-Pfad geht direkt gegen den Daemon** (`URL("$base/glance/talk")`,
   `:285`), nicht über den E2EE-Relay. Er erbt damit exakt die
   Erreichbarkeitsfrage aus `glasses-reference.md` §11.9 — die einzige
   ungeklärte Frage, die zwischen `glasses/` und einer festen Installation
   steht.
3. **Das Telefon hat noch gar keine Audio-Abhängigkeit.** Jede Telefon-Sprache
   ist damit eine **native** Änderung → APK/IPA-Rebuild, kein OTA
   (`DEPLOY.md`).

---

## 3. Das Vorlese-Format

### 3.1 Was gesprochen wird — und was nie

| Gesprochen | Nie gesprochen |
|---|---|
| Henrys **Prosa** (max. 2 Sätze) | der ```actions```-Block — Maschinensyntax, unhörbar (`routes_copilot.py:51`) |
| Eine **Zahl** bei proaktiven Meldungen: „3 new cards need you." | Kartentitel, Kundennamen, Pfade in proaktiven Meldungen |
| Bei Bedarf: die **Optionen** (Entscheidung §7.2) | Code, Stacktraces, Gate-Reports (`glasses-reference.md` §4.4) |
| | Transkripte — b64-Audio im Relay ist ~33 % größer (`voice.py:143`) |

Die Zahl-statt-Name-Regel ist keine Stilfrage, sondern **glance-safe by
construction** (`routes_glance.py:80-90`): `n` kommt vom Client und wird
serverseitig auf 1–99 geklemmt, damit ein geteiltes Token niemals beliebigen
Text in edge-tts injizieren kann. **Jede neue Vorlese-Route muss diese Form
haben: feste Phrase, geklemmter Parameter — nie „sprich diesen String".**

### 3.2 Register (übernommen, nicht neu erfunden)

Aus `glasses-reference.md` §4.4, Owner-Entscheidung 2026-07-10/21:

- *„das Register ist ein normales Telefonat"* — kurze, einfache Sätze.
- **Keine Listen, keine Nummerierung, keine Emojis, kein Markdown.**
- **Erster Satz = die Entscheidung, die ansteht.** Das ist, was die Brille
  zuerst liest.
- **Eine Meldung pro echtem Übergang, niemals ein Fortschritts-Ticker.** Ein
  gesprochener Ticker ist deutlich schlimmer als ein Push-Ticker.
- Bestätigungen nur, wenn sie **in gesprochener Sprache eindeutig** sind —
  *„Passt schon"* ist ausdrücklich ausgeschlossen, weil es im Deutschen meist
  „lass es" heißt.

Durchgesetzt wird das heute an genau einer Stelle: `GLASS_BRIEF`
(`routes_glance.py:22-40`). Jede weitere sprechende Oberfläche bekommt ihren
Brief **an derselben Stelle** — nicht ein zweites Prompt-Fragment im Client.

### 3.3 Längenbudget

| Grenze | Wert | Quelle |
|---|---|---|
| Rendern (hart) | 1200 Zeichen ≈ 90 s | `voice.py:43` |
| Talk-Antwort (gekappt) | 600 Zeichen | `routes_glance.py:174` |
| Ziel Linse/Ohr | **2 Sätze** | `GLASS_BRIEF` |
| WhatsApp-Text | < ~900 Zeichen, > ~350 → Voice-Note | `glasses-reference.md` §4.4 |

### 3.4 Wer rendert

**Empfehlung: serverseitig bleibt kanonisch, auf allen Plattformen.**
`voice.render()` cached inhaltsadressiert, scheitert weich (kein edge-tts, kein
Netz → `None` → die Oberfläche zeigt Text) und liefert überall dieselbe Stimme
(`en-US-AndrewMultilingualNeural`, gewählt für gemischt deutsch/englische
Kartentitel, `voice.py:37-41`).

Geräte-TTS *wäre* auf Telefon, Watch und Desktop verfügbar (§5) — als
**Offline-Rückfall**, nicht als Standard. Das ist eine Owner-Entscheidung
(§7.3), weil es eine zweite Stimme und einen zweiten Ort für das Register
bedeutet.

⚠ **Risiko, das benannt gehört: edge-tts ist unsanktioniert.** Es ist gepflegt
(7.2.8, 2026-03-22) und funktioniert, aber der Maintainer selbst schreibt
*„absolutely not reliable and could stop working at any moment"*
(github.com/rany2/edge-tts, Discussion #261), es gab 2025 eine mehrmonatige
401-Phase (7.2.2 → behoben in 7.2.6), und es gibt **kein dokumentiertes
Rate-Limit** (Issue #366: *„Call request rate and concurrency is unknown"*). Für
Nutzsprache akzeptabel; die vertragliche Alternative wäre Azure AI Speech.
`available()` fängt den Ausfall bereits ab — die Oberflächen werden dann still,
nicht kaputt.

---

## 4. Rückfrage-Flows

### 4.1 Ein Format für alles: `<helmdeck-ask>`

HelmDeck hat schon ein Rückfrageprotokoll — dasselbe, das jeder Karten-Worker
benutzt und das `ask.parse` liest. Glass Mode hat **keinen zweiten** erfunden,
und Sprache darf das auch nicht (`glasses-reference.md` §11.5). Der Brief
zwingt jede Antwort, mit 2–6 Optionen zu enden; eine Antwort ohne Optionen wird
als „Ask again" gezeigt, **niemals verschluckt** — auf einer tastaturlosen
Oberfläche ist eine Antwort ohne etwas zum Antippen eine Sackgasse.

### 4.2 Flow A — **Auge**: sehen und tippen (produktiv)

```
/glance  →  Prosa (gesprochen)  +  Optionen (angezeigt)  →  D-Pad/Enter
                                                            →  nächste Nachricht
```

Bewusst wird hier **nur die Prosa gesprochen**: *„sechs Optionen vorzulesen ist
langsamer als sie anzusehen, und die Optionen sind genau das, was das Display
gut kann"* (`routes_glance.py:176-179`). Das gilt, **solange der Owner
hinschaut**.

### 4.3 Flow B — **Ohr**: sprechen und hören (nicht gebaut, und hier ist die Lücke)

```
Wake  →  HFP-Mikro auf  →  STT  →  MIKRO FREIGEBEN  →  POST /glance/talk
      →  Clip abspielen (A2DP)  →  ??? Optionen ???
```

⚠ **Der Torso verliert die Rückfrage.** `GlassVoiceService.ask()` liest aus der
Antwort `reply` und `voice` — **und ignoriert `question`** (`:304-306`). Der
Daemon liefert die Optionen mit, der Client wirft sie weg. Ein Owner, der nicht
hinschaut, bekommt also eine Antwort und keinen Weg weiter: exakt die
Sackgasse, die §4.1 verbietet.

**Das ist die eine Design-Entscheidung, die dieses Dokument braucht** (§7.2).
Drei Möglichkeiten, keine davon gratis:

| Variante | Wie | Kosten |
|---|---|---|
| **B1 Vorlesen + Sprechauswahl** | Prosa + „Sag eins, zwei oder drei" + Labels; nächste Erkennungsrunde mappt auf das Label | zweite Mikro-Runde pro Zug; **max. 3 Optionen** hörbar, das Protokoll erlaubt 6 |
| **B2 Hybrid (empfohlen)** | Prosa sprechen, **Optionen auf die Linse** — Ohr rein, Auge raus | braucht die Linse offen; Brille kann das, weil beide Oberflächen dasselbe Gerät sind |
| **B3 Nur Prosa** | wie heute | bleibt eine Sackgasse — **ausgeschlossen** |

B2 ist die ehrlichste Anwendung der Hausregel: *„die Webapp ist Output +
Auswahl"* und *„Autoren und Konsumieren sind verschiedene Momente"*
(`glasses-reference.md` §1, §3.6). B1 bleibt nötig, sobald eine Oberfläche
**ohne Display** spricht (Telefon in der Tasche, Watch am Ohr, WhatsApp-Anruf).

### 4.4 Flow C — **Proaktiv**: sprechen ohne Rückkanal

Die Linse kann von sich aus nichts melden — keine Hintergrundausführung, keine
Notification-API (`glasses-reference.md` §3.2). Proaktives *muss* von außen
kommen: heute `/glance/banner` **während die Seite offen ist**, morgen der
`outbox/events/`-Weg über WhatsApp.

Regel: eine proaktive Ansage ist **immer nur eine Zahl** (§3.1) und **immer
stummschaltbar** (`voiceMuted` in `localStorage`, `app.js:412-439`) — ein
Meeting bleibt ein Meeting. Und sie braucht ein **Repeat**, weil sie nicht in
einer Nutzergeste liegt und die Autoplay-Policy sie still verschlucken darf.

### 4.5 Regeln, die für jede Plattform gelten

1. **`listen → Mikro freigeben → sprechen`. Nie gleichzeitig.** HFP und A2DP
   schließen sich aus — auf **beiden** Plattformen (Android:
   `AudioManager`-Javadoc *„the format must be mono; the sampling must be 8kHz"*;
   iOS: *„If an application uses `setPreferredInput` to select a Bluetooth HFP
   input, the output automatically changes to the corresponding Bluetooth HFP
   output"*). Wer beim Sprechen die Route hält, klingt nach schlechtem Telefonat —
   und die Schuld landet bei der TTS, nicht beim Routing. `releaseMic()`
   (`:208`) gibt die Route aktiv zurück, auch im Fehlerfall (`:256`).
2. **Kein Barge-in.** Solange der Clip läuft, ist das Mikro zu — siehe 1.
3. **Nie eine Antwort ohne Weg weiter** (§4.1).
4. **Bestätigung nur bei sprachlicher Eindeutigkeit** (§3.2).
5. **Sprache darf die Antwort nie wegnehmen**: jeder Renderfehler fällt auf
   Text zurück (`voice.py:24-27`).
6. **Erst entsperren, dann sprechen**: Browser verweigern programmatisches
   `play()` ohne vorherige Geste; die Antwort kommt ~2 s *nach* dem Tap. Ein
   stummes `play()` **innerhalb** der Geste entsperrt das Element
   (`app.js:368-376`). Ohne das ist die Linse still und **nichts wirft einen
   Fehler**.

---

## 5. Was jede SDK erlaubt und verbietet

| Plattform | Vorlesen (TTS) | Zuhören (STT) | Verboten / Falle |
|---|---|---|---|
| **MRBD-Webview** (Linse) | **kein `speechSynthesis`** — aber Audio-Wiedergabe funktioniert | **verboten**: *„Mic no, Sprache-to-text no, Kamera no"* (on-device 2026-07-13) | kein Hintergrund, keine Notification-API, kein Wake; kein deutsches TTS-Voice auf dem Gerät |
| **Android** (Expo) | `expo-speech` 57.0.1 (Geräte-TTS, **keine Datei-Ausgabe**); Wiedergabe: `expo-audio` 57.0.4 | **kein First-Party-Modul**; Community `expo-speech-recognition` steht auf **56.0.1, kein 57.x** | jede davon ist **nativ** → Rebuild, kein OTA |
| **Android** (nativ, heute im Baum) | `MediaPlayer` auf die Clip-URL | `SpeechRecognizer`, on-device ab API 31 | AOSP selbst: *„not intended to be used for continuous recognition"*; `startForeground` mit `microphone`-Typ **wirft SecurityException** ohne `RECORD_AUDIO` (bereits abgefangen, `:110-121`); **Mikro-FGS darf nicht aus dem Hintergrund und nicht aus `BOOT_COMPLETED` starten** |
| **iOS** (Expo) | `expo-speech`; **`AVSpeechSynthesizer.write(_:toBufferCallback:)` kann in Puffer schreiben** (iOS 13+) — die Datei-Ausgabe, die Android fehlt | `SFSpeechRecognizer` via Community-Plugin, **min. iOS 16.4**; `NSSpeechRecognitionUsageDescription` + `NSMicrophoneUsageDescription` | Apple dokumentiert **1-Minuten-Limit pro Äußerung** und **Tageskontingente pro Gerät und pro App**; im Stummschalter-Modus gibt `expo-speech` **keinen Ton** |
| **watchOS** | `AVSpeechSynthesizer` ✅ (watchOS 2+) | **Speech-Framework existiert auf watchOS nicht** | Diktat nur über `presentTextInputController` (braucht ein watchOS-Target) **oder** `UNTextInputNotificationAction` **ohne** `.foreground` — dann rendert die Uhr das Diktat und die Antwort landet in der iPhone-App. **Unverifiziert**, ob das ganz ohne watchOS-Target trägt |
| **Desktop** (Electron) | `speechSynthesis` ✅ | 🔴 **`webkitSpeechRecognition` existiert, funktioniert aber nicht**: `start()` gelingt, dann `error: "network"` (electron#46143, *confirmed*, kein Fix). Googles Speech-Endpunkt ist *„intended for use by Chromium only"* | Gegenrichtung: Electron ist bei Autoplay **großzügig** (`no-user-gesture-required`) — der Entsperr-Trick aus §4.5.6 ist dort unnötig |
| **WhatsApp-Kanal** | Voice-Note via `[[voice:<ogg>]]`, ogg/opus mono 32 k | Textantwort des Owners | „speak first" wurde **nie programmatisch beschrieben** (`glasses-reference.md` §4.6.1); der Fork-Patch ist **veraltet** und enthält weder `outbox/events/` noch `[[voice:]]` |

**Was keine SDK-Freigabe braucht:** Sprachein- *und* -ausgabe. Das Ray-Ban-Mikro
ist ein gewöhnliches Bluetooth-Headset-Mikro (`mwdat-core` enthält **null**
Audio-Klassen, Meta liefert gar kein Audio-Artefakt), und die Ausgabe ist eine
abgespielte URL. **Kein GitHub-PAT, keine Meta-Freigabe, kein DAT-Modul**
(`glasses-reference.md` §11.7).

**Der eine harte EU-Befund:** Apples Ausweg aus der HFP-Verschlechterung,
`bluetoothHighQualityRecording` (iOS 26+), ist laut Apple *„not currently
supported in the European Union"*. Für eine deutsche Installation gilt §4.5.1
also ohne Ausnahme. Der andere Ausweg — LE Audio ab Android 13 — hängt an
BT-5.2-Hardware auf beiden Seiten.

---

## 6. Was der Bau je Plattform bedeutet

Empfohlene Reihenfolge, teuerst-zuletzt:

| # | Karte | Inhalt | Warum hier |
|---|---|---|---|
| 1 | **Torso anschließen** (Android/Brille) | `question` in `GlassVoiceService` auswerten (§4.3 B2), RN-Trigger + Schreiben von `base_url`/`glance_token` in die Prefs, APK-Build aus `C:\hd\app` | der Code ist da und belegt; es fehlen ~3 Nähte. Kein PAT, keine SDK |
| 2 | **Erreichbarkeit entscheiden** | TLS-Tunnel zum Daemon **oder** kleiner Origin, der `/glance*` proxied | blockiert sowohl feste Linsen-Installation (§11.9) als auch den Mikro-Pfad (§2.2) — **Entscheidung, keine Forschung** |
| 3 | **Telefon spricht** (Android + iOS) | `expo-audio` einziehen, `voice: true` an `/chat`, b64 abspielen | ein nativer Rebuild, beide Plattformen auf einmal; reine Ausgabe, kein STT-Risiko |
| 4 | **Telefon hört** | STT-Modul; auf iOS 1-Minuten-Limit + Kontingent einplanen | teuerste Naht, größtes Plattformrisiko (kein 57.x-Plugin) |
| 5 | **WhatsApp proaktiv** | erster programmatischer Producer für `outbox/events/` | eigene Infrastruktur (zweite Nummer, Fork-Daemon), unabhängig vom Rest |

**Nicht bauen:** Desktop-STT (Sackgasse, §5), Ticket-Registry
(`glasses-reference.md` §11.1), Companion-APK als *Renderer* — die native App
zeichnet nie ein Pixel auf die Brille.

---

## 7. Offene Entscheidungen — das, was hier freigegeben werden muss

1. **Reihenfolge** — ist §6 die richtige, oder soll Telefon-Sprache (Henry
   voice-first) vor die Brille?
2. **Rückfrage im Ohr-Flow** — B1 (Optionen vorlesen, max. 3) oder B2 (Prosa
   ins Ohr, Optionen auf die Linse)? *Empfehlung: B2, mit B1 als Nachrüstung,
   sobald eine Oberfläche ohne Display spricht.*
3. **Geräte-TTS als Offline-Rückfall** ja/nein — zweite Stimme und zweiter Ort
   fürs Register, dafür Sprache ohne Netz. *Empfehlung: nein, Text-Rückfall
   genügt.*
4. **edge-tts-Risiko** — so lassen (kostenlos, fällt weich aus) oder Azure AI
   Speech als vertragliche Reserve einplanen? *Empfehlung: so lassen, Risiko
   notiert.*

---

## 8. Nicht verifiziert — Risiken, die ein Bau erst schließt

1. Ob Apples 1-Minuten- und Tageslimits **auch on-device** gelten. Apple
   schränkt die Aussage nirgends ein — **nicht dagegen designen**.
2. Ob der Apple-Watch-Diktatweg **ohne watchOS-Target** trägt (§5) — aus zwei
   starken, aber indirekten Apple-Sätzen geschlossen. Vor jedem Design darauf:
   ein Gerätetest.
3. Ob Chromes on-device-STT (Chrome 139, `processLocally`) in Electron läuft —
   **kein Bericht in beide Richtungen**. Der einzige Desktop-Spike, der sich
   lohnen würde.
4. Numerische Obergrenze für Androids `SpeechRecognizer` — nicht dokumentiert;
   der sanktionierte Weg für lange Sitzungen ist `EXTRA_SEGMENTED_SESSION`.
5. edge-tts-Kontingente (§3.4).
6. **Die WhatsApp-Zustellung ist nie end-to-end belegt worden**
   (`glasses-reference.md` §4.6.2) — einmal messen, nicht als bewiesen erben.
7. `GlassVoiceService` ist `exported=false` und war **nie auf einem Gerät** —
   die gesamte Mikro-Route ist konstruktiv verteidigt, nicht getestet
   (`:104-108`).

---

## 9. Provenance

Aus erster Hand in diesem Worktree gelesen: `daemon/spine/media/voice.py`,
`daemon/spine/http/routes/routes_glance.py`,
`daemon/cells/copilot/routes_copilot.py`, `glasses/app.js`,
`app/plugins/withGlassVoice.js`, `app/plugins/glassvoice/GlassVoiceService.kt`,
`app/package.json`, `docs/glasses-reference.md`, `docs/ios-watch-feasibility.md`.
Der Ist-Stand in §2 ist gegriffen, nicht angenommen — inklusive der beiden
Befunde, dass nichts den Voice-Service startet und dass er `question` verwirft.

Plattformregeln in §5 stammen aus Primärquellen (developer.apple.com,
developer.android.com, docs.expo.dev, MDN, electron#46143, AOSP-Javadoc) und
sind mit Datum belegt; alles, was dort nicht bestätigt werden konnte, steht in
§8 statt in §5. Meta bewegt sich schnell (`glasses-reference.md` §9) — die
Linsen-Zeile ist gegen die gemessenen On-Device-Befunde von 2026-07 belegt,
nicht gegen aktuelle Meta-Dokumentation.
