# Machbarkeitsstudie: Chat/Henry auf Android Auto

**Analyse-Stand:** 2026-08-22, Branch `chat-android-auto-integration`. Reine
Recherche — kein Code, keine Migration. Primärquellen: developer.android.com /
source.android.com (Datumsstempel je Quelle unten notiert), plus dieses
Repos eigene Dateien (`app/plugins/withGlassVoice.js`,
`app/plugins/glassvoice/GlassVoiceService.kt`, `app/src/data/voice.ts`,
`docs/voice-interaction-design.md`).

**Kurzfazit vorweg:** Es gibt **zwei völlig verschiedene Wege** in den Wagen,
und sie sind nicht austauschbar. Der eine — eine normale
`MessagingStyle`-Notification mit Voice-Reply — ist heute **frei verfügbar,
ungegatet, und Google Assistant/Gemini übernimmt Vorlesen und Diktat
kostenlos**. Der andere — eine eigene Konversations-UI über die "Android for
Cars App Library" (`androidx.car.app`, `ConversationTemplate`) — ist **per
Google-Beta-Programm gegatet** (nur Internal/Closed Testing, kein
Production-Rollout ohne Freigabeformular), braucht ein komplett neu zu
schreibendes natives Kotlin-Modul (keine brauchbare RN/Expo-Bibliothek
existiert), und die API selbst ist laut Googles eigenem Roadmap-Post noch in
Bewegung. **Empfehlung: Phase 1 ist der Notification-Weg — er kostet keine
Google-Freigabe und keinen neuen Sprachcode, weil Assistant die Sprache
übernimmt, nicht `voice.py`.**

---

## 1. Zwei Wege in den Wagen — und ein dritter, der (noch) nicht offen ist

| Weg | Was | Google-Gate | Aufwand |
|---|---|---|---|
| **(a) Car App Library** (`androidx.car.app`) | Volle Template-App: Media, Navigation, POI, IoT, Weather, **Messaging (`ConversationTemplate`)** | je Kategorie unterschiedlich (§3) | hoch |
| **(b) Notification-Bridge** | Normale `NotificationCompat.MessagingStyle`-Notification mit Reply-`RemoteInput` — Android Auto erkennt und rendert sie **automatisch aus dem System-Notification-Stream**, ohne Car-App-Library-Code | **keins** — Standard-Play-Review | niedrig |
| **(c) ConversationTemplate** (Teilmenge von (a)) | Reiche Konversations-UI auf dem Fahrzeugbildschirm | **Beta-Gate**, s. §3 | hoch, und aktuell nicht production-fähig |

Weg (b) ist **bestätigt aktuell** (Quelle mit Stand 2026-07-13):
> [Messaging apps for Android Auto](https://developer.android.com/training/cars/communication/notification-messaging)
> — verlangt ausdrücklich **kein** `CarAppExtender`, keine Car-App-Library.
> Voraussetzung ist nur eine korrekt gebaute `MessagingStyle`-Notification:
> zwei Actions (`SEMANTIC_ACTION_REPLY` mit genau einem `RemoteInput`,
> `PendingIntent.FLAG_MUTABLE`; `SEMANTIC_ACTION_MARK_AS_READ`), gepostet aus
> einem Hintergrunddienst, nie aus einer Activity.

Einschränkung, direkt aus derselben Quelle: dieser Weg zeigt nur die
Nachrichten, die **während der aktiven Android-Auto-Sitzung** eintreffen —
kein Backlog/Verlauf. Für Verlauf verweist Google auf Weg (a)/(c).

Weg (c) verlangt in der Manifest-Deklaration `androidx.car.app.CarAppService`
mit `<category android:name="androidx.car.app.category.MESSAGING"/>` plus
`res/xml/automotive_app_desc.xml` (`<uses name="notification"/><uses
name="template"/>`), Quelle:
[Templated messaging](https://developer.android.com/training/cars/communication/templated-messaging)
(Stand 2026-06-24).

---

## 2. Was der Car-App-Library-Weg konkret braucht (Weg a/c)

Aus derselben Quelle (2026-06-24):

- `CarAppService` + `Session` + `Screen` (Standard-Lifecycle der Bibliothek).
- `minCarApiLevel = 7` als `<meta-data>` (Pflicht, weil `ConversationItem`
  Car API 7+ verlangt).
- Kernklassen: `ConversationItem`, `CarMessage`
  (`setSender`/`setBody`/`setReceivedTimeEpochMillis`/`setRead`),
  `ConversationCallbackDelegate` (play/mark-read/reply), `Person`, `Header`,
  gerendert über `ListTemplate`/`SectionedItemTemplate`.
- Googles eigene Empfehlung (keine harte API-Grenze): ~5–10 Konversationen,
  ~5 jüngste Nachrichten je Konversation, Refresh ≤ 500 ms oder ein
  Ladezustand.
- **Weg (c) ersetzt Weg (b) nicht — er ergänzt ihn.** Apps mit
  Templated-Messaging müssen laut derselben Quelle **zusätzlich** den
  Notification-Weg implementieren.
- Gradle (aus [androidx.car.app-Release-Notes](https://developer.android.com/jetpack/androidx/releases/car-app), Stand grob geprüft gegen unabhängige mvnrepository-Treffer):
  ```
  implementation "androidx.car.app:app:1.7.0"            // stabil, 2025-07-16
  implementation "androidx.car.app:app-projected:1.7.0"  // Android Auto
  implementation "androidx.car.app:app-automotive:1.7.0" // Android Automotive OS
  ```
  Pre-Release: `1.8.0-beta01` (2026-04-22), `1.9.0-alpha01` (2026-05-19).
  **Minimum-API seit `1.8.0-alpha03` (2025-11-19): API 23** (vorher 21) —
  liegt weit unter HelmDecks eigenem Minimum, kein Blocker.
- `androidx.car.app.ACCESS_SURFACE`-Permission: in der allgemeinen
  Library-Übersicht erwähnt, aber **nicht bestätigt**, ob sie speziell für
  `MESSAGING` gebraucht wird (eher mit Navigation/Surface-Zeichnen assoziiert)
  — **unverifiziert**, vor einem Bau direkt gegen
  `training/cars/apps/library/request-permissions` prüfen.

---

## 3. Vertrieb — Weg (b) ist offen, Weg (c) ist ein Beta-Antrag

- **Weg (b) (Notification-Bridge):** keine separate Freigabe — normale
  Play-Review (plus die allgemeine, kategorieunabhängige
  Fahrsicherheits-Zusatzprüfung, die laut
  [Distribute your car app](https://developer.android.com/training/cars/distribute)
  (Stand 2026-08-13) für *jede* Auto-geflaggte App gilt — dort steht
  ausdrücklich **"No Separate Allowlist Form"** für diesen Pfad).
- **Weg (c) (`ConversationTemplate`) ist explizit gegated.** Wörtlich aus der
  Templated-Messaging-Doku (Stand 2026-06-24):
  > *"Templated messaging experiences are currently in beta and can only be
  > published to Internal Testing and Closed Testing tracks... Builds
  > submitted to Open Testing or Production will be rejected."*
  Mit eigenem Early-Access-Partner-Nominierungsformular
  (`forms.gle/VsXEdDEBidxw8q8u8`) — Antrag, nicht Self-Service.

**Für HelmDeck bedeutet das:** Weg (b) ist heute ohne jedes Google-Gate
ausrollbar. Weg (c) könnte selbst bei sofortigem Bau **nicht über
Internal/Closed Testing hinaus** an den Owner ausgeliefert werden, ohne dass
Google den Antrag freigibt — für ein Ein-Personen-Projekt mit
Internal-Testing-Vertrieb (wie iOS/TestFlight-Analogie in
`docs/ios-watch-feasibility.md` §2.2) wäre das **kein hartes Veto**, aber ein
Abhängigkeits-Fremdkörper im sonst selbstbestimmten Rollout (Relay-OTA,
`deploy/push_apk.sh`-Analogie), der jederzeit von Google entschieden wird.

---

## 4. Ablenkungs-/Qualitätsregeln

- **Kein Custom-View/WebView** in der Fahr-UI — nur Templates. WebViews sind
  laut den Library-Grundlagen nur für Settings-/Sign-in-Screens erlaubt, nie
  für Fahr-Inhalte (Quelle: `training/cars/apps`-Übersichtsseiten,
  Formulierung beim Abruf nicht wortgenau zitierfähig — **vor Bau erneut
  direkt lesen**).
- **Row-Komponente, exakt zitiert** (Stand 2026-05-19,
  [Row-Guide](https://developer.android.com/design/ui/cars/guides/components/row)):
  Titel bis 2 Zeilen (Pflicht), Sekundärtext bis 2 Zeilen (optional). *"If
  secondary text is longer than 2 lines, it will be truncated while driving.
  The full text will be visible only when parked."* — Text, der beim Fahren
  gelesen werden soll, muss also **vorne** stehen.
- **Kein exaktes Zeichenlimit für `ConversationTemplate`-Bubbles gefunden** —
  weder in der API-Referenz (`CarText`) noch in der Templated-Messaging-Doku.
  Nur die generische 2-Zeilen-Row-Regel ist belegt. HelmDecks eigenes
  `GLASS_BRIEF`-Register (max. 2 Sätze, kein Markdown,
  `docs/voice-interaction-design.md` §3) liegt in derselben Größenordnung wie
  diese Regel, ist aber nicht dieselbe Quelle — beide zufällig kompatibel,
  nicht dasselbe Gesetz.
- **`DISTRACTION_OPTIMIZED`-Flag** entscheidet laut
  [Driver Distraction Guidelines](https://source.android.com/docs/automotive/driver_distraction/guidelines)
  (Stand 2026-07-16) nur den *Mechanismus*, nicht das konkrete Regelwerk
  (Freitexteingabe-Verbote etc.) — das eigentliche Regelwerk liegt auf einer
  Folgeseite, die in diesem Rechercheschritt nicht gefunden wurde. **Offen.**
- Sprache ist für Messaging explizit der Erstweg (Vorlesen/Diktat via
  Assistant/Gemini), nicht Freitext-Tippen während der Fahrt.

---

## 5. Sprache im Auto — der eine Punkt, der vor einem Design geklärt werden muss

Zwei belegte Fakten, und eine echte, **nicht auflösbare** Lücke:

1. **`CarAudioRecord`** (`androidx.car.app.media.CarAudioRecord`) ist eine
   reale, dokumentierte API, mit der eine `CarAppService` **roh vom
   Auto-Mikrofon aufnimmt** — am Assistant/Gemini vorbei, für einen
   "in-app digital assistant". Push-to-Talk-Modell: Tap auf den
   App-Mikroknopf, sichtbarer Aufnahme-Indikator, Audio geht direkt an die
   App. Kein Wake-Word. Quelle:
   [Access the car's microphone](https://developer.android.com/training/cars/apps/library/car-microphone)
   (Stand 2026-06-24).
2. **Auf Automotive OS ist der Gegenweg — eine App öffnet selbst einen
   `SpeechRecognizer`** — laut
   [AAOS Voice Interaction Guide](https://source.android.com/docs/automotive/voice/voice_interaction_guide/app_development)
   (Stand 2026-07-14) **ausgeschlossen**: Mikrofonzugriff ist architektonisch
   der einen aktiven System-Voice-Interaction-App (Gemini/Assistant)
   vorbehalten; Drittanbieter-Apps integrieren über
   Voice-Action-Fulfillment/Intents, nicht über eine eigene Recognizer-Session.

**Die Lücke: ob `CarAudioRecord` (Punkt 1) auch auf Android Auto
(Telefon-Projektion, `app-projected`) läuft oder nur auf Android Automotive
OS (`app-automotive`).** Weder die API-Doku noch die Voice-UX-Guideline
grenzen das explizit ein — zwei gezielte Nachschläge (API-Referenz,
UX-Guideline direkt) fanden keine Plattformzeile, weder bestätigend noch
ausschließend. **Das ist die einzige Tatsache in dieser Studie, die dieses
Dokument nicht selbst klären kann** und die vor jedem Push-to-Talk-Design auf
dem Auto-Bildschirm am Gerät (oder per DHU, §6) geprüft werden muss.

Warum das für HelmDeck konkret zählt: `GlassVoiceService.kt` ist genau dieses
Muster — eine App, die direkt gegen `SpeechRecognizer` spricht, am
System-Assistant vorbei. Wenn `CarAudioRecord` AAOS-exklusiv ist, hat dieses
Muster **kein Äquivalent auf Android Auto (projiziert)**, und jede
Sprachinteraktion dort liefe zwangsläufig über Gemini/Assistant-Vorlesen +
-Diktat (also über Weg (b), nicht über einen eigenen Henry-Mikrofonknopf im
Auto).

---

## 6. Testing — Desktop Head Unit (DHU) ist weiterhin der Weg

Quelle: [Test with the DHU](https://developer.android.com/training/cars/testing/dhu)
(Stand 2026-07-13).

- Läuft unter Windows/macOS/Linux; DHU 2.x unter Linux braucht
  `libc++1`/`libc++abi1` (GLIBC ≥ 2.32).
- **Braucht ein echtes Telefon**, kein Emulator-zu-Emulator-Aufbau — Projektion
  via ADB (`adb forward tcp:5277 tcp:5277`) oder USB-Accessory-Mode.
- Telefon: Android 9 (API 28)+ Minimum; ab Android 10 muss die
  Android-Auto-App vorher aktualisiert und "Start head unit server" in ihren
  Einstellungen aktiviert werden.
- **Kein dokumentierter Unterschied Debug- vs. signierter Release-Build** —
  die Doku sagt nur "compile and install your app", ein Debug-Build sollte
  reichen.
- **Kein Hinweis auf Expo-managed vs. hand-verwaltet** — DHU arbeitet auf
  Ebene des installierten APKs über ADB, nicht auf Build-Tool-Ebene. Sollte
  also identisch gegen HelmDecks hand-verwaltetes `app/android` funktionieren,
  sobald gebaut — das ist eine Ableitung aus dem Schweigen der Doku, keine
  explizite Bestätigung.

---

## 7. RN/Expo-Ökosystem — nichts Brauchbares für Messaging, Weg (b) braucht ohnehin keine Bibliothek

| Kandidat | Status | Umfang | Urteil |
|---|---|---|---|
| `Shopify/react-native-android-auto` | **Vom Maintainer archiviert 2026-06-08**, read-only | React-Renderer über Car-App-Library-Templates, Navigations-fokussiert (`useCarNavigation`), kein `ConversationTemplate` erkennbar | Tot — nicht darauf aufbauen |
| `birkir/react-native-carplay` | Aktiv wirkendes Repo (804★, 134 Forks), aber 49 offene Issues; exaktes Datum des letzten Release nicht geprüft | primär CarPlay(iOS)-first; Android-Auto-Umfang unklar (eigene `AndroidAuto.md` nicht gelesen) | Nachprüfung nötig, nicht ausgeschlossen |
| `@g4rb4g3/react-native-carplay` (Fork) | npm-Seite nicht abrufbar (403) | behauptet Expo-SDK-53-Kompat. | unverifiziert |
| `expo-car-app` o. ä. | **existiert nicht** | — | nichts gefunden, das `androidx.car.app` als Expo-Modul kapselt |

**Für Weg (a)/(c) (Car App Library) gilt:** kein brauchbarer Wrapper — ein
handgeschriebenes Kotlin-Modul wäre nötig, nach demselben Muster, das
`GlassVoiceService.kt`/`withGlassVoice.js` bereits für die Brille etabliert
haben (natives `Service`/hier `CarAppService`, per Config-Plugin in **beide**
Android-Pfade eingehängt — Prebuild **und** hand-verwaltetes `app/android`).

**Für Weg (b) (Notification-Bridge) ist das irrelevant** — das ist reines
`NotificationCompat.MessagingStyle` + `PendingIntent`/`IntentService`, keine
Car-App-Library, kein Template-System, kein `CarAppService`-Lifecycle zu
kapseln. Deutlich billiger zu bauen, weil es keine neue Bibliothek und keinen
neuen Google-Freigabepfad braucht.

---

## 8. Zeitlicher Kontext

- [Android for Cars, unifying platforms](https://android-developers.googleblog.com/2026/05/android-for-cars-unifying-platforms-premium-experiences.html)
  (Google-Blog, 2026-05-19): kündigt Car App Library 1.8/1.9-Vorabversionen
  an (Media-Template-Upgrades), Video-while-parked, Android-Auto-Widgets
  "later this year". **Roadmap-Zeile nennt "new conversational templates"
  explizit als geplant/zukünftig** — der aktuelle `ConversationTemplate`-Beta
  ist also erkennbar noch nicht stabil, keine erwartbare baldige GA.
- **Gemini ersetzt Google Assistant** auf Android Auto/Automotive ist ein
  laufender 2026-Rollout (Drittquellen/Pressemeldungen, nicht Google-Doku:
  GM-Flotte ab 2026-04-28, breiterer AAOS-Rollout 2026-06-26, Android Auto
  bekommt laut Googles eigenem How-to ebenfalls eine "Ask Google Gemini"-UI).
  Relevant für HelmDeck: **egal welcher Weg**, das Vorlese-/Diktier-Verhalten
  dahinter ist ein bewegliches Ziel unter Google-Kontrolle in 2026 — kein
  Grund, Weg (b) nicht zu bauen, aber ein Grund, keine tiefe
  Assistant-Verhaltensannahme in den Bau zu schreiben.
- Alle in dieser Studie zitierten Google-Doku-Seiten tragen sehr frische
  "Stand"-Daten (2026-05-19 bis 2026-08-13) — Google überarbeitet diese
  gesamte Fläche aktiv durch Mitte 2026, ein weiteres Indiz, dass der
  Messaging-Template-Beta kein stabiles Bauziel ist.

---

## 9. Wie das auf HelmDecks eigene Architektur träfe

Der Konversationsmotor bleibt unangetastet — dieselbe Naht wie überall sonst
(`docs/voice-interaction-design.md` §1: *"Erkennen ist Plattformarbeit,
Sprechen ist Serverarbeit"*). Konkret für Weg (b), den empfohlenen Start:

| Baustein | Heute | Für Android Auto (Weg b) |
|---|---|---|
| Antworttext | `POST /chat` liefert `reply` (Prosa, GLASS_BRIEF-Register) | derselbe `reply`-String wird der `MessagingStyle`-Notification-Body — **kein neuer Server-Code** |
| Vorlesen | `voice.py`/edge-tts rendert eine mp3 | **entfällt für diesen Weg** — Assistant/Gemini liest die Notification selbst vor, kostenlos, ohne HelmDeck-TTS |
| Diktat/Antwort | `expo-speech-recognition` (Telefon) bzw. `SpeechRecognizer` (Brille) | Assistant transkribiert den `RemoteInput` selbst; die App bekommt nur den fertigen Text im `PendingIntent` — **kein STT-Code nötig** |
| Rückfrage-Optionen (`<helmdeck-ask>`) | Voice: B2-Hybrid (Prosa gesprochen, Optionen auf der Linse) | **ungeklärt** — eine `MessagingStyle`-Notification kann feste `Action`-Buttons NEBEN der Reply tragen (analog zum iOS-Watch-Kategorien-Muster aus `docs/ios-watch-feasibility.md` §3.1), aber Android Autos übliche Sichtbarkeitsgrenze liegt bei sehr wenigen Buttons — HelmDecks Protokoll erlaubt bis zu 6 Optionen. Dieselbe Design-Entscheidung wie B1 vs. B2 im Voice-Dokument steht hier erneut an, nur mit Notification-Actions statt Display. **Nicht in dieser Studie entschieden.** |
| Native Config | `withGlassVoice.js` patcht Prebuild **und** hand-verwaltetes `app/android` in einer Datei | ein neues `withAndroidAuto.js` nach demselben Muster — Notification-Permission (`POST_NOTIFICATIONS`, bereits fürs Push-System vorhanden, s. `docs/ios-watch-feasibility.md` §1.3) plus `automotiveApp`-Metadaten in der Manifest, keine neue Laufzeit-Permission wie `RECORD_AUDIO` |

Weg (c) (eigene Konversations-UI) würde dagegen ein komplett neues
`CarAppService` in Kotlin verlangen, mit demselben Dual-Pfad-Muster wie
`GlassVoiceService`, **plus** eine Google-Freigabe, die dieses Dokument nicht
erzwingen kann (§3) — das ist ein eigenständiges, größeres Vorhaben, kein
Ausbau von Weg (b).

---

## 10. Aufwandsschätzung

| # | Schritt | Aufwand (grob, inkl. Gerätetest) | Bemerkung |
|---|---|---|---|
| 1 | Weg (b): `MessagingStyle`-Notification aus dem bestehenden Push-Pfad (`daemon/notify.py`/`app/src/data/push.ts`) ableiten, Reply-`RemoteInput`+Mark-as-read-Action, `IntentService` empfängt die Antwort und ruft denselben `/chat`-Turn wie heute | 1–2 T | größter Teil ist Notification-Umbau, kein neuer Server-Code |
| 2 | DHU-Testaufbau (ADB-Forward gegen ein echtes Telefon, `app/android`-Build) | 0,5 T | einmalig |
| 3 | `withAndroidAuto.js` (Manifest/`automotiveApp`-Deklaration, dual-path wie `withGlassVoice.js`) | 0,5 T | Muster ist im Repo bereits belegt |
| 4 | Rückfrage-Optionen-Design (B1/B2-Äquivalent für Notification-Actions, §9) | Entscheidung, kein Bauaufwand vorab | Owner-Entscheidung nötig, siehe unten |
| | **Summe Weg (b)** | **≈ 2–3 T** | kein Google-Gate, kein neues STT/TTS |
| 5 | Weg (c): `CarAppService` + `ConversationTemplate` in Kotlin, Early-Access-Antrag bei Google, minCarApiLevel-7-Templates | groß, unbeziffert — abhängig von Googles Freigabe-Timing, nicht nur von Baustunden | aktuell nicht Production-fähig ohne Googles Ja |
| 6 | `CarAudioRecord`-Push-to-Talk (Henry-Mikroknopf im Auto, GlassVoiceService-Analogie) | blockiert an §5s ungeklärter Plattformfrage | erst Gerätetest, dann Design |

**Empfehlung: Schritt 1→3 zuerst** (Weg b, ≈ 2–3 Tage, kein Gate). Schritt 4
ist eine Owner-Entscheidung, kein Bauaufwand. Schritte 5–6 (die "echte"
Auto-UI mit eigenem Mikroknopf) erst angehen, wenn (a) Google die
Early-Access-Anfrage beantwortet und (b) die `CarAudioRecord`-Plattformfrage
an einem Gerät/DHU geklärt ist — beides liegt außerhalb dessen, was diese
Studie allein entscheiden kann.

---

## 11. Nicht verifiziert — was ein Bau erst klärt

1. **Ob `CarAudioRecord` auf Android Auto (projiziert) läuft oder nur auf
   Automotive OS** (§5) — die einzige Lücke mit echtem Design-Gewicht,
   weder API-Referenz noch UX-Guideline grenzen es ein. Vor jedem
   Push-to-Talk-Design am Gerät/DHU zu prüfen.
2. **`androidx.car.app.ACCESS_SURFACE`** — ob diese Permission für
   `MESSAGING`-Kategorie-Apps gebraucht wird (§2), nicht direkt bestätigt.
3. **Exaktes Zeichenlimit für `ConversationTemplate`-Nachrichten-Bubbles**
   (§4) — nur die generische 2-Zeilen-Row-Regel ist belegt.
4. **Das genaue Ablenkungs-Regelwerk** (Freitext-Verbote während der Fahrt
   etc.) — die Guidelines-Seite dokumentiert nur den `DISTRACTION_OPTIMIZED`-
   Mechanismus, nicht das Regelwerk selbst (§4).
5. **`birkir/react-native-carplay`s tatsächlicher Android-Auto-Umfang** (§7)
   — eigene `AndroidAuto.md` nicht gelesen, 49 offene Issues sind ein
   Warnsignal, kein Ausschluss.
6. **Wie viele Notification-`Action`-Buttons Android Auto tatsächlich
   gleichzeitig anzeigt** neben einer Reply-Action (§9) — bestimmt, ob
   HelmDecks bis-zu-6-Optionen-Protokoll dort überhaupt abbildbar ist, ohne
   eine Notification-spezifische Kürzungsregel (analog zur
   iOS-Watch-"3 feste Buttons"-Lösung) einzuführen.

---

## 12. Offene Entscheidungen — das, was hier freigegeben werden muss

1. **Reihenfolge bestätigen**: Weg (b) zuerst (empfohlen), Weg (c) parken bis
   Google antwortet? Oder beide Anträge (Early-Access-Formular) schon jetzt
   parallel stellen, ohne zu bauen, um die Wartezeit vorzuziehen?
2. **Rückfrage-Format im Auto** (§9, Punkt 4): feste Notification-Actions
   (analog iOS-Watch-Lösung, max. 3) oder Optionen im Antworttext ausschreiben
   und auf Diktat-Freitext setzen (der Owner sagt/tippt eine Nummer oder ein
   Stichwort, der Server interpretiert es wie einen WhatsApp-Textkanal)?
3. **`CarAudioRecord`/eigener Mikroknopf im Auto** (§5/§10 Punkt 6): jetzt
   schon am Gerät/DHU klären, oder zurückstellen, bis Weg (b) im Alltag läuft
   und der Bedarf an einem eigenen Mikroknopf (statt Gemini-Diktat) belegt
   ist?
4. **Early-Access-Antrag für `ConversationTemplate`** (§3): jetzt stellen
   (kostet nur ein Formular, Wartezeit unbekannt) oder erst, wenn Weg (b)
   nachweislich zu wenig ist?

---

## 13. Provenance

Primärquellen, mit Stand-Datum wie beim Abruf angezeigt (2026-08-22 abgerufen):
- [Car app quality guidelines](https://developer.android.com/docs/quality-guidelines/car-app-quality) (Stand 2026-08-13)
- [Messaging apps for Android Auto (Notification-Bridge)](https://developer.android.com/training/cars/communication/notification-messaging) (Stand 2026-07-13)
- [Templated messaging](https://developer.android.com/training/cars/communication/templated-messaging) (Stand 2026-06-24)
- [Distribute your car app](https://developer.android.com/training/cars/distribute) (Stand 2026-08-13)
- [Row component guide](https://developer.android.com/design/ui/cars/guides/components/row) (Stand 2026-05-19)
- [Driver Distraction Guidelines](https://source.android.com/docs/automotive/driver_distraction/guidelines) (Stand 2026-07-16)
- [Access the car's microphone (`CarAudioRecord`)](https://developer.android.com/training/cars/apps/library/car-microphone) (Stand 2026-06-24)
- [Communicate with the driver by voice](https://developer.android.com/design/ui/cars/guides/ux-requirements/communicate-app-by-voice) (Stand 2025-09-05)
- [AAOS Voice Interaction Guide](https://source.android.com/docs/automotive/voice/voice_interaction_guide/app_development) (Stand 2026-07-14)
- [Test with the Desktop Head Unit](https://developer.android.com/training/cars/testing/dhu) (Stand 2026-07-13)
- [androidx.car.app Release Notes](https://developer.android.com/jetpack/androidx/releases/car-app)
- [Android for Cars: unifying platforms](https://android-developers.googleblog.com/2026/05/android-for-cars-unifying-platforms-premium-experiences.html) (Google-Blog, 2026-05-19)
- `github.com/Shopify/react-native-android-auto` (archiviert 2026-06-08), `github.com/birkir/react-native-carplay` (Umfang nicht vollständig geprüft)

Aus diesem Repo gelesen: `app/plugins/withGlassVoice.js`,
`app/plugins/glassvoice/GlassVoiceService.kt`, `app/src/data/voice.ts`,
`docs/voice-interaction-design.md`, `docs/ios-watch-feasibility.md`,
`app/app.json`. Kein Treffer für "Android Auto"/"CarApp"/"androidx.car" im
restlichen Repo vor dieser Studie (grep, 2026-08-22) — dies ist der erste
Kartenlauf zu diesem Thema.

Recherche-Vorbehalt: einige Antworten stammen aus einer
AI-Zusammenfassungs-Stufe des WebFetch-Tools über die Original-Doku, nicht
aus wortgenauem Lesen jeder Zeile (im Text als "SUMMARY-RISK"/unverifiziert
markiert, wo zutreffend). Vor einem tatsächlichen Bau die als unverifiziert
markierten Punkte (§11) direkt gegen die Live-Doku nachlesen.
