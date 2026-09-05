# watchOS-Technik-Machbarkeit: WebSocket, Background-Limits, Companion-Connectivity

**Analyse-Stand:** 2026-09-05. Reine Analyse, kein Code, keine Migration.
Klärt drei konkrete technische Fragen, die `ops/docs/ios-watch-feasibility.md`
§3 (2026-08-12) nur auf Empfehlungsebene behandelt ("native Watch-App ist ein
eigenes Swift-Projekt, für Phase W1 unnötig"), und stellt sie dem bereits
**gebauten** Wear-OS-Modell gegenüber (`ops/docs/backlog/wear-os-integration/README.md`,
`ops/docs/backlog/wear-os-paritaets-audit/README.md`). Quellen: Apple-
Entwicklerdokumentation und Apple-Developer-Forum-Threads mit Antworten von
Apple-Frameworks-Ingenieuren, per `WebSearch`/`WebFetch` am 2026-09-05
verifiziert (Liste am Ende).

**Kurzfazit vorweg:** Die Kartenbezeichnung "WebSocket-Zustellung" ist auch
für watchOS ein Fehlgriff — genau wie im Wear-OS-Audit (§4 dort) bereits für
Android festgestellt. Gut so: HelmDeck braucht kein WebSocket, der ganze
Fleet-Transport ist sealed long-polling HTTP GET. Die eigentliche Frage ist,
ob dieses Long-Poll-Muster auf watchOS trägt — und die Antwort ist **schlechter
als bei Wear OS**: watchOS kennt keinen Ambient-Zustand, in dem ein
Dritt-App-Prozess mit gedrosselter UI weiterläuft; es kennt nur "aktiv im
Vordergrund" oder "suspendiert", mit genau vier schmalen, zweckgebundenen
Ausnahmen (§2). Das bestätigt und verschärft die bestehende Empfehlung aus
`ios-watch-feasibility.md` §3.3 (Phase W1 = Mirroring, kein Watch-Code) — nicht
als Verlegenheitslösung, sondern weil die Plattform selbst keinen
gleichwertigen Ersatz für Wear OS' Foreground-Long-Poll-plus-FCM-Weckruf-Modell
anbietet.

---

## 1. WebSocket-Support auf watchOS

**Befund: existiert technisch (`URLSessionWebSocketTask`, seit watchOS 6/7),
ist aber für den hier relevanten Fall irrelevant und zusätzlich eingeschränkt.**

- `URLSessionWebSocketTask`/`URLSessionStreamTask` sind seit watchOS 6 verfügbar
  ([Apple-Doku](https://developer.apple.com/documentation/foundation/urlsessionwebsockettask)).
- Ein Apple-Frameworks-Ingenieur im Developer-Forum, auf die konkrete Frage
  "warum verbindet mein `NSURLSessionWebSocketTask` nicht, wenn die Uhr nicht
  am iPhone hängt, obwohl normale `NSURLSession`-Requests funktionieren":
  > „Sockets are only available on watch in the context of streaming audio."
  ([Forum-Thread](https://developer.apple.com/forums/thread/700783))
- Praktische Konsequenz: eine unabhängige (standalone) watchOS-App kann sich
  **nicht** verlässlich per WebSocket verbinden, wenn sie nicht am iPhone hängt
  — unabhängig von WLAN/LTE. Das ist keine App-seitige Fehlkonfiguration,
  sondern eine bewusste Plattformgrenze (Sockets sind für Audio-Streaming
  reserviert, nicht als generisches Netzwerk-Primitiv gedacht).
- **Für HelmDeck ohne Belang**, weil kein WebSocket im Baum existiert
  (bestätigt im Wear-OS-Audit §4) — der Transport ist überall sealed
  long-polling `GET /stream/wait` bzw. `GET /wear/board`/`/wear/chat`. Genau
  diese Art normaler HTTP-Requests (`NSURLSession`, kein Socket-Task)
  funktioniert laut demselben Forum-Beleg **auch unabhängig vom iPhone**.

**Einordnung:** Die Karten-Frage "WebSocket-Support" ist damit **beantwortet,
aber die Antwort ist ein Hinweis, kein Blocker** — solange kein Sockel-Layer
gebaut wird, betrifft die WebSocket-Einschränkung HelmDeck nicht. Sie ist hier
dokumentiert, damit niemand versehentlich einen `URLSessionWebSocketTask`-Weg
vorschlägt, weil er auf iOS/macOS ginge.

---

## 2. Background-Execution-Limits auf watchOS

**Befund: strenger als Wear OS, und mit einer strukturellen Lücke — es gibt
keinen Sessiontyp, der zum "bleib verbunden für Chat/Notifications"-Zweck
passt.**

### 2.1 Was watchOS anbietet (vollständige Liste, keine ist ein Fit)

| Mechanismus | Trigger/Laufzeit | Läuft im Hintergrund? | Passt zu "Live-Chat-Kanal offenhalten"? |
|---|---|---|---|
| **Normale Netzwerk-Requests (`NSURLSession`)** | solange App **aktiv im Vordergrund** | nein (wird beim Wechsel weg sofort suspendiert) | ✅ für Vordergrund — deckt exakt das, was `WearStream.kt` im Vordergrund tut |
| **`WKExtendedRuntimeSession`** | nur 4 feste Zwecke: Self Care, Mindfulness (beide **Vordergrund-only**), Physical Therapy, Smart Alarm (beide **können im Hintergrund laufen**) | ja, aber nur für diese 4 Zwecke | ❌ — "Chat-App offenhalten" ist kein anerkannter Sessiontyp; ein Missbrauch (z. B. als getarnter "Smart Alarm") wäre App-Review-Risiko |
| **`WKApplicationRefreshBackgroundTask`** | System-terminiert, **~1×/Std. pro App im Dock**, bis zu 4×/Std. falls die App eine aktive Complication auf dem Zifferblatt hat | ja, aber Budget-limitiert und vom System, nicht von der App bestimmt | ❌ zu selten/unplanbar für "needs_you jetzt" |
| **`WKURLSessionRefreshBackgroundTask`** (Background-URL-Session) | ein einzelner, vom System eingeplanter Download-Task | ja, für genau einen Transfer | ❌ kein Dauerkanal, eher ein "hol eine Datei nach" |
| **Remote Push (APNs, watchOS 6+ eigener Device-Token)** | serverseitig ausgelöst, kann `content-available` (silent) sein | ja, kurzes Zeitfenster nach Empfang | ⚠️ am nächsten dran — s. §2.2 |

Quellen: [WKExtendedRuntimeSession-Doku](https://developer.apple.com/documentation/watchkit/wkextendedruntimesession),
Session-Zweck-Aufschlüsselung und "nur im Vordergrund startbar" bestätigt in
mehreren Apple-Forum-Threads (u. a. [737794](https://developer.apple.com/forums/thread/737794),
[794730](https://developer.apple.com/forums/thread/794730));
Refresh-Budget "~1×/Std. pro Dock-App, 4×/Std. mit aktiver Complication" aus
[WKApplicationRefreshBackgroundTask-Doku](https://developer.apple.com/documentation/watchkit/wkapplicationrefreshbackgroundtask)
und Community-Zusammenfassung ([wjwickham.com](https://wjwickham.com/posts/refreshing-data-in-the-background-on-watchOS/));
eigener APNs-Device-Token seit watchOS 6 aus WWDC 2019 "Creating Independent
Watch Apps" ([mackuba.eu-Zusammenfassung](https://mackuba.eu/notes/wwdc19/creating-independent-watch-apps/)).

### 2.2 Der entscheidende Unterschied zu Wear OS

Wear OS hat für genau diese Situation ein **explizites, dokumentiertes
Muster**, das HelmDeck bereits gebaut und gefahren hat
(`wear-os-integration/README.md` §6.1, Zeile 682-686):

> „Kein Long-Poll auf der Uhr. Hintergrund-Jobs off-charger sind gesperrt,
> Ambient aktualisiert im Minutentakt, Battery-Saver schaltet Funk ab. Richtig
> ist: `GET /glance` beim Öffnen/Aufwachen + FCM als Weckruf."

Der Kern: Wear OS kennt einen **Ambient-Modus**, in dem der App-**Prozess
weiterläuft** (nicht suspendiert wird), nur die UI auf Minutentakt gedrosselt
wird — der Long-Poll aus `WearStream.kt` (bis zu 40 s hängendes GET,
exponentielles Backoff) läuft dort bereits produktiv, solange die App aktiv
ist (Vordergrund **oder** Ambient), und wird nur beim echten "App verlassen"
beendet, wofür FCM als Weckruf einspringt.

**watchOS hat keinen Ambient-Modus für Dritt-Apps in diesem Sinne.** Sobald die
App nicht mehr die aktive Vordergrund-App ist (Digital Crown gedrückt,
Zifferblatt, andere App geöffnet, Handgelenk gesenkt), wird der Prozess
**innerhalb weniger Sekunden suspendiert** — es gibt keine Zwischenstufe.
"Always On"-Displays (watchOS 9+) halten nur den zuletzt gezeichneten Screen
gedimmt sichtbar, sie halten **nicht** den App-Code am Laufen. Die einzigen vier
in §2.1 gelisteten Ausnahmen sind zweckgebunden und keine davon deckt "generischer
Nachrichtenkanal bleibt offen".

**Praktische Folge:** Ein watchOS-Pendant zu `WearStream.kt` würde im
Vordergrund 1:1 funktionieren (normale `NSURLSession`, kein Plattform-Blocker),
aber sobald der Nutzer die App verlässt oder das Handgelenk senkt, bricht der
Kanal ab und es gibt **keinen** Weg, ihn "sanft" bis zum nächsten Aufwachen am
Laufen zu halten — nur den robusteren, aber deutlich selteneren Weg über
Remote-Push (§2.1, letzte Zeile), der wie bei Wear OS als Weckruf taugt, aber
kein Ersatz für den Ambient-Long-Poll ist, den Wear OS zusätzlich bietet.

---

## 3. Companion-/Standalone-Connectivity

**Befund: dieselbe Architekturentscheidung wie bei Wear OS (§6 im
Integrations-Dokument) trägt auch hier — direkt zum Relay, nicht über die
Telefon-App —, aber aus einem eigenen, watchOS-spezifischen Grund.**

- **`WatchConnectivity`/`WCSession.isReachable`** (das iOS-Pendant zu Wear OS'
  Data-Layer-API) gilt für **interaktives Messaging zwischen App und
  Companion-App**, ist aber laut Apple-Forum-Konsens **unzuverlässig als
  Verbindungsindikator** — `isReachable` wird `false`, sobald eine der beiden
  Apps suspendiert/im Hintergrund ist, selbst wenn die physische
  Bluetooth-Verbindung besteht. Genau dasselbe Argument, das
  `wear-os-integration/README.md` §6.1 gegen die Wear-Data-Layer-API anführt
  ("kein Geräte-zu-Geräte-Pfad", Google rät selbst davon ab), gilt hier
  spiegelbildlich für `WatchConnectivity`.
- **Standalone-Networking ist seit watchOS 6 offizieller Weg**: eine
  unabhängige watchOS-App bekommt einen **eigenen APNs-Device-Token**,
  installiert **direkt aus dem App Store auf die Uhr** (nicht zwingend über
  die iPhone-App) und kann eigene `NSURLSession`-Requests unabhängig vom
  iPhone fahren — funktional dasselbe Modell wie Wear OS' T2/T3
  ("Uhr routet eigenes HTTPS über BT-Proxy → WLAN → LTE", §6 dort).
  ([WWDC 2019 "Creating Independent Watch Apps"](https://mackuba.eu/notes/wwdc19/creating-independent-watch-apps/))
- **Hardware-Voraussetzung, symmetrisch zu Wear OS:** eine GPS-only Apple
  Watch (kein Cellular) kann eigenständig nur über WLAN, das sie zuvor über
  das gekoppelte iPhone kennengelernt hat — sie braucht das iPhone nicht
  *aktiv*, aber ein einmaliges Setup darüber. Eine Cellular-Apple-Watch ist
  vollständig unabhängig (eigene SIM/eSIM). Das ist dieselbe Geräteklassen-
  Abhängigkeit, die Wear OS mit "WLAN oder LTE-Variante" ohnehin hat — kein
  watchOS-spezifischer Nachteil.
- **Konsequenz für die Architektur, falls je eine native watchOS-App gebaut
  wird:** dieselbe Hausregel wie für Uhr und Brille (`glasses-reference.md`
  §1, `wear-os-integration/README.md` §6.1) — **kein** Pfad über
  `WatchConnectivity`/Companion-iPhone-Relay, sondern direkt Uhr → Relay mit
  eigenem, watchOS-registriertem Push-Token (Expo-Push kann das abbilden,
  s. `ios-watch-feasibility.md` §1.3 — Expo Push Service sendet plattform-
  parametrisiert; ein watchOS-Zieltoken bräuchte denselben Sender-Codepfad,
  keinen zweiten).

---

## 4. Risikovergleich ggü. dem gebauten Wear-OS-Modell

| Dimension | Wear OS (gebaut, `4e1f4e1`/`8aaf30c`) | watchOS (Analyse, kein Code) | Risiko ggü. Wear OS |
|---|---|---|---|
| Transport-Primitiv | Sealed long-poll GET, kein WS | identisch möglich (normales `NSURLSession`, kein WS-Task) | **kein Mehrrisiko** — §1 |
| Vordergrund-Long-Poll | läuft produktiv (`WearStream.kt`) | würde 1:1 funktionieren | **kein Mehrrisiko** |
| "Ambient"/gedrosselter Weiterlauf | existiert (Minutentakt-UI, Prozess lebt) | **existiert nicht** — nur aktiv oder suspendiert | **höheres Risiko** — §2.2, strukturelle Plattformlücke |
| Zweckgebundene Hintergrund-Sessions | n/a (Wear OS braucht sie nicht, Ambient reicht) | 4 feste Zwecke, keiner passt | **höheres Risiko** |
| Background-Refresh-Takt | n/a (kein Refresh-Modell, Ambient+FCM reicht) | ~1×/Std. (4×/Std. mit Complication), System-terminiert | **höheres Risiko** für "nahezu live" |
| Weckruf-Push aus Killed/Background-State | FCM, geteilter Sender mit Telefon | eigener APNs-Token seit watchOS 6, gleicher Sender-Codepfad (Expo Push) erweiterbar | **kein Mehrrisiko**, nur zusätzliche Plumbing (Token-Registrierung) |
| Companion-Kopplung nötig? | nein (T2/T3 direkt zum Relay) | nein (Standalone seit watchOS 6, dieselbe Architekturentscheidung) | **kein Mehrrisiko** |
| Device-zu-Device-API vermeiden | Data-Layer-API bewusst nicht genutzt | `WatchConnectivity` aus denselben Gründen zu vermeiden | **kein Mehrrisiko**, gleiche Hausregel anwendbar |
| Diktat/Voice | System-Intent `ACTION_RECOGNIZE_SPEECH`, eigenes Mikro | `WKAudioFilePlayer`/`presentTextInputController` mit Diktat-Option, eigenes Mikro — nicht in dieser Karte tiefer geprüft | **nicht bewertet**, siehe offene Punkte |

**Kernrisiko in einem Satz:** Wear OS erlaubt "die App bleibt (gedrosselt) am
Leben, solange sie nicht explizit verlassen wird" — watchOS erlaubt nur
"die App lebt, solange sie der aktive Vordergrund ist, danach ausschließlich
system-getaktete Ausnahmefenster". Jede watchOS-Companion-App, die versucht,
das Wear-OS-Long-Poll-Muster nachzubauen, würde beim ersten Handgelenk-Senken
scheitern — das ist keine Implementierungsschwäche, sondern die Plattform
selbst (bestätigt durch Apple-Frameworks-Ingenieur-Aussage in §1 und die
Session-Typ-Beschränkung in §2.1).

---

## 5. Konsequenz für den Scope

Das bestätigt die bereits getroffene Empfehlung in `ios-watch-feasibility.md`
§3.3/§4.2, jetzt mit technischer Begründung statt nur Aufwandsschätzung:

- **Phase W1 ("Watch gratis", Notification-Mirroring + Action-Buttons +
  Diktat) bleibt der richtige v1-Scope, nicht nur der billigste.** Sie
  umgeht das Background-Problem komplett, weil die Zustellung auf
  Betriebssystem-Ebene passiert (Notification-Mirroring vom iPhone), nicht
  über einen App-eigenen Kanal, der ohnehin nur im Vordergrund liefe.
- **Phase W2 (native SwiftUI-Watch-App mit eigenem Live-Kanal) hat jetzt einen
  benannten technischen Deckel:** "nahezu live" heißt dort realistisch
  Vordergrund-Long-Poll (funktioniert) plus Push-Weckruf für den
  Hintergrundfall (funktioniert, aber ist ein Weckruf, kein Dauerkanal) —
  **kein** Wear-OS-artiges "läuft im Ambient-Modus weiter". Wer W2 baut, sollte
  UI-mäßig planen, dass die Liste beim Öffnen einmal frisch lädt (`GET`, wie
  Wear OS es beim Board tut) statt eine Dauerverbindung zu erwarten.
- **Kein neuer Blocker gefunden.** Nichts hier verändert das Urteil aus
  `ios-watch-feasibility.md` §4 (Empfehlung: iOS-Basispaket ja, natives
  Watch-W2 später/beweisbedürftig) — es untermauert es nur mit Plattform-
  Fakten statt Vermutung.

## Offene Punkte (nicht in dieser Karte geklärt)

1. Diktat-Weg auf watchOS (`WKExtendedRuntimeSession`-frei, vermutlich über
   `presentTextInputController(withSuggestions:allowedInputMode:.plain)` mit
   Diktat-Option) — nicht recherchiert, wäre für ein eventuelles W2 relevant.
2. Ob ein watchOS-Ziel im bestehenden Expo/EAS-Managed-Workflow
   (`ios-watch-feasibility.md` §2) überhaupt ohne Bare-Prebuild geht — dort
   bereits als "realistisch nur mit Mac + Hand-Xcode" eingeordnet, hier nicht
   erneut geprüft.
3. Kein Gerätetest möglich aus diesem Worktree (kein Mac/Simulator erreichbar)
   — dieselbe Verifikationsgrenze wie im Wear-OS-Audit, hier von Anfang an
   offen benannt statt stillschweigend übernommen.

## Quellen

Abgerufen 2026-09-05 via `WebSearch`/`WebFetch`:
- [URLSessionWebSocketTask (Apple-Doku)](https://developer.apple.com/documentation/foundation/urlsessionwebsockettask)
- ["Sockets are only available on watch in the context of streaming audio" — Apple-Forum](https://developer.apple.com/forums/thread/700783)
- [WKExtendedRuntimeSession (Apple-Doku)](https://developer.apple.com/documentation/watchkit/wkextendedruntimesession)
- [Forum: Smart-Alarm/Physical-Therapy als einzige Hintergrund-Sessiontypen](https://developer.apple.com/forums/thread/794730)
- [Forum: Extended-Runtime-Session nur aus dem Vordergrund startbar](https://developer.apple.com/forums/thread/737794)
- [WKApplicationRefreshBackgroundTask (Apple-Doku)](https://developer.apple.com/documentation/watchkit/wkapplicationrefreshbackgroundtask)
- [Background-Refresh-Budget-Zusammenfassung (wjwickham.com)](https://wjwickham.com/posts/refreshing-data-in-the-background-on-watchOS/)
- [WWDC 2019 "Creating Independent Watch Apps" — eigener APNs-Token seit watchOS 6](https://mackuba.eu/notes/wwdc19/creating-independent-watch-apps/)
- [WatchConnectivity `isReachable`-Unzuverlässigkeit — Apple-Forum-Tags](https://developer.apple.com/forums/tags/watchconnectivity)
