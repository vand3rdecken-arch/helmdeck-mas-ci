# Machbarkeitsstudie: HelmDeck-Chat auf Android TV / Google TV

**Analyse-Stand:** 2026-08-22, Branch `chat-android-tv-google-tv`. Reine
Recherche — kein Code, keine Migration. Primärquellen: developer.android.com /
docs.expo.dev / support.google.com (Stand-Datum je Quelle unten notiert), plus
dieses Repos eigene Dateien (`surfaces/app/src/app/pair.tsx`, `surfaces/app/src/app/scan.tsx`,
`surfaces/app/src/data/qrgen.ts`, `surfaces/app/src/data/qrgen.web.ts`, `surfaces/app/src/data/push.ts`,
`app/plugins/withGlassVoice.js`, `app/app.json`, `surfaces/app/package.json`).

**Kurzfazit vorweg:** Anders als bei Android Auto (`ops/docs/android-auto-feasibility.md`)
ist hier die App-Ebene **kein Fremdkörper** — Expo hat TV-Support seit SDK 50
offiziell im eigenen `expo-router`/`expo-dev-client`-Stack (aktueller Stand
2026-07-20), und HelmDeck läuft bereits auf SDK 57 / RN 0.86.2, deutlich über
der SDK-56-Schwelle, ab der der TV-Umstieg nur noch ein Package-Swap
(`react-native` → `react-native-tvos`) plus ein Config-Plugin ist — keine
Google-Beta-Freigabe, kein neues natives Modul für die Grundfunktion nötig.
Die Kernprobleme liegen woanders: **(1)** TVs haben keine Kamera — das
bestehende QR-Pairing (`scan.tsx`) muss umgedreht werden, aber der Code dafür
existiert im Repo bereits (`qrgen.web.ts`, vom Desktop-Pfad), nur nicht am
TV-Plattform-Slot verdrahtet; **(2)** Push-Benachrichtigungen im
Telefon-Stil (`push.ts`) haben auf Android TV **kein** Äquivalent — es gibt
keine Notification-Shade, nur das Recommendations-Channel-System, das für
Content-Kacheln gedacht ist, nicht für Chat-Nachrichten; **(3)** Sprachein-
gabe ist hier, anders als im Auto, **nicht** architektonisch gesperrt — TV-Apps
dürfen laut Googles eigener Leanback-API selbst `RECORD_AUDIO` halten und einen
eigenen `SpeechRecognizer` fahren, das `GlassVoiceService.kt`-Muster wäre also
prinzipiell portabel, nur eben ohne die 5-Wege-Fernbedienung als Trigger,
sondern über eine eigene Bildschirm-Mikrofontaste.

---

## 1. Terminologie: Android TV ist die Plattform, Google TV die Oberfläche

Aus Sicht der App-Entwicklung ist das **eine** Zielplattform. "Android TV" ist
das Betriebssystem/die Lizenzplattform, die Google an TV-Hersteller und
Streaming-Boxen vergibt; "Google TV" ist der Launcher/die Home-Screen-Oberfläche,
die seit ~2020 standardmäßig darauf sitzt und die Google laut mehreren
2026er-Marktbeobachtungen zunehmend als alleinige Verbrauchermarke
positioniert (Android TV als Entwicklerplattform bleibt bestehen, aber die
Konsumentenmarke verschwindet zugunsten "Google TV"). Für einen Play-Store-
Eintrag und einen Manifest-Build ändert das nichts — dieselbe
`CATEGORY_LEANBACK_LAUNCHER`-App läuft auf beiden Brandings. Diese Studie
behandelt sie deshalb als eine Plattform und schreibt "Android TV" für die
technischen Anforderungen.

**Quelle-Einschränkung:** Die Marken-Unterscheidung stammt aus
Sekundärquellen (Marktbeobachtung/Blogs, keine developer.android.com-Seite
direkt dazu gefunden) — technisch unstrittig, aber nicht Google-primärquellen-
zitierfähig wie der Rest dieser Studie.

---

## 2. Distribution — kein Gate, aber ein separater Opt-in

Bestätigt aus [Distribute to Android TV](https://developer.android.com/training/tv/publishing/distribute)
(Stand 2026-05-08):

- **Kein automatisches Erscheinen.** Eine App, die die Kern-Qualitätsrichtlinien
  erfüllt, erscheint **nur**, wenn zusätzlich im Play Console unter
  *Setup → Advanced Settings → Form Factors → Add Release Type → Android TV*
  ausdrücklich opt-in gemacht und die TV-Review-Policy akzeptiert wird.
- **Gleicher Package-Name wird ausdrücklich empfohlen** (nicht erzwungen):
  *"Using the same package name for your mobile app and Android TV app is
  strongly recommended"* — `app.helmdeck` könnte also derselbe bleiben.
- Store-Listing braucht mindestens einen Android-TV-Screenshot und eine
  TV-Banner-Grafik, plus "Android TV" in der Beschreibung.
- **Keine Kategorie-Sperre gefunden** — die Seite schließt Chat-/
  Kommunikations-Apps nirgends aus; jede Kategorie ist zulässig, solange die
  Qualitätsrichtlinien erfüllt sind. Bestätigt separat aus einer zweiten Quelle
  (Play-Console-Hilfe zu App-Kategorien): "Communication" (E-Mail/Messaging,
  Beispiele Skype/WhatsApp) ist eine reguläre, TV-fähige Kategorie — kein
  Beta-Antrag wie bei Android Autos `ConversationTemplate` (vgl.
  `ops/docs/android-auto-feasibility.md` §3).
- **Praktische Einschränkung, nicht rechtlich, sondern UX:** Android TVs
  Home-Screen ist content-first organisiert (Empfehlungszeilen, App-Reihe);
  eine Chat-App würde dort nicht wie eine Video-App prominent vorkommen,
  sondern über die normale App-Kachel-Reihe erreichbar sein — für einen
  Zweitschirm/Board-Anwendungsfall (siehe §7) ausreichend, aber kein
  automatischer "vorne dabei"-Effekt wie bei Streaming-Apps.

---

## 3. UI-/Interaktionsanforderungen — D-Pad-Pflicht, kein Touch

Aus [TV app quality](https://developer.android.com/docs/quality-guidelines/tv-app-quality)
(Stand 2026-06-29), wörtlich zitierte Kriterien:

| Kriterium | Text |
|---|---|
| `TV-DP` | *"The app functionality is navigable using five-way D-pad controls"* |
| `TV-DM` | *"The app does not depend on a remote control device having a Menu button"* |
| `TV-DB` | *"Back button presses lead back to the Android TV home screen."* |
| `TV-MT` | *"The app manifest sets the hardware feature `android.hardware.touchscreen` ... to not required."* |
| `TV-VS` | *"The app integrates voice search capabilities for natural language content discovery"* (Tier "TV Optimized", nicht Pflicht für Basis-Zulassung) |
| `TV-NP`/`TV-PA` | Medien-Controls in System-UI bei Hintergrund-Audio — für einen Chat-Client irrelevant, kein Audio-Playback-Anwendungsfall |

**Konsequenz bei Nichterfüllung**, wörtlich: *"the Play Store team will
contact you through the email address specified in the Google Play Console
account"* — kein Hard-Reject beim Upload, sondern ein Nachfass per E-Mail;
im Extremfall (zitiert) Empfehlung, das TV-Artefakt durch eine leere Submission
zu ersetzen, falls es andere Formfaktor-Updates blockiert.

Aus [Create and run a TV app](https://developer.android.com/training/tv/get-started/create)
und [Handle TV hardware](https://developer.android.com/training/tv/get-started/hardware)
(beide über Suche referenziert, exaktes Stand-Datum bei Abruf nicht separat
notiert):

- Pflicht-Manifest-Zeilen: `<uses-feature android:name="android.software.leanback" android:required="false"/>`
  und `android.hardware.touchscreen required="false"` — sonst listet Google
  Play die App gar nicht als TV-App.
- Pflicht-Launcher-Intent: `CATEGORY_LEANBACK_LAUNCHER` auf der Haupt-Activity,
  sonst unsichtbar auf dem TV-Homescreen (auch beim manuellen ADB-Install).
- Pflicht-Banner: **320×180 px, xhdpi-Ordner, Text im Bild eingebrannt, pro
  unterstützter Sprache eine eigene Version.** HelmDeck unterstützt de/en
  (`surfaces/app/src/i18n`) — also zwei Banner-Varianten nötig, zusätzlich zum
  bestehenden `android-icon-foreground.png`/`android-icon-monochrome.png`-Satz
  aus dem Rebrand (`helmdeck-rebrand-redesign`-Memory).

---

## 4. RN/Expo-Ökosystem — der Teil, der bei Android Auto fehlte, ist hier vorhanden

Anders als bei Android Auto (dort: kein brauchbares RN-Paket, totes Repo,
handgeschriebenes Kotlin nötig) gibt es hier **offiziellen Expo-Support**:

- [Build Expo apps for TV](https://docs.expo.dev/guides/building-for-tv/)
  (zuletzt geändert 2026-07-20): TV-Support seit **SDK 50**
  ([Expo-Blogpost](https://expo.dev/blog/how-to-build-tv-apps), 2024-02-14),
  Zielplattformen **Android TV (API 31+)** und **Apple TV (tvOS 17+)**.
- Mechanismus: das native `react-native`-Package wird durch den Fork
  `react-native-tvos` ersetzt (voller Fork, deckt Phone **und** TV ab), dazu
  das Dev-Plugin `@react-native-tvos/config-tv`. Aktivierung über
  `EXPO_TV=1` (Env-Var) **oder** Plugin-Parameter `isTV: true`, dann
  `npx expo prebuild --clean`.
- **Für SDK 56+ (HelmDeck ist auf SDK 57) ist der Swap ein Einzeiler**:
  `"react-native": "npm:react-native-tvos@0.85-stable"` in `package.json`
  (Versionszahl folgt der RN-Version — HelmDecks `react-native@0.86.2`
  entspräche `react-native-tvos@0.86-stable`). Für SDK ≤55 wäre manuelle
  Pin-Pflege nötig — nicht HelmDecks Fall.
- **DevClient-Support (relevant für den Card-Loop dieses Repos) seit SDK 54:**
  *"Android TV: Full support"* — inklusive normalem Metro/EAS-Workflow.
  Apple TV ist dort ausdrücklich schwächer ("Authentication to EAS ...
  not yet supported") — für HelmDeck irrelevant, da nur Android im Scope ist.
- **`expo-router` läuft mittlerweile auf TV** (früher, laut dem 2024er
  Blogpost, explizit *nicht* unterstützt — das ist überholt): Googles/Expos
  eigenes Referenz-Repo [`react-native-tvos/ExpoRouterTV`](https://github.com/react-native-tvos/ExpoRouterTV)
  und das offizielle Beispiel `expo/examples/with-router-tv` demonstrieren
  genau HelmDecks Stack (Expo Router, file-based). Da `surfaces/app/src/app` bereits
  komplett auf `expo-router` (Tabs-Layout, `(tabs)/_layout.tsx`) aufbaut,
  ist die Navigationsschicht grundsätzlich portabel, nicht neu zu schreiben.
- **Ein offener, unverifizierter Stolperstein:** GitHub-Issue
  [react-native-tvos/react-native-tvos#906](https://github.com/react-native-tvos/react-native-tvos/issues/906)
  ("Expo app with TV Router template crashes on Android TV" —
  `EarlyJsError: Property 'setImmediate' doesn't exist`, reproduziert mit
  `EXPO_TV=1 npx expo start` auf einem API-31-TV-Emulator) war zum
  Abrufzeitpunkt dieser Studie **offen, ohne zugewiesenen Fix**. Kein
  Blocker-Beweis (kann Emulator-/Hermes-Polyfill-spezifisch sein), aber ein
  konkretes Risiko, das ein echter Testlauf zuerst klären müsste, bevor
  Aufwand geschätzt wird.

**Was am bestehenden Plugin-Satz vermutlich NICHT TV-tauglich ist** (aus
`app/app.json`s `plugins`-Liste): `withGlassVoice.js`/`GlassVoiceService.kt`
(Bluetooth-Brille — auf einem TV-Gerät ohne Gegenstück, würde einfach nie
feuern, kein Crash-Risiko erwartet, aber ungetestet) und `expo-camera`
(TV-Hardware hat i.d.R. keine Kamera — die Permission bleibt harmlos
deklariert, aber jeder Code-Pfad, der sie *braucht* — namentlich `scan.tsx`,
§5 — funktioniert dort nicht).

---

## 5. Pairing ohne Kamera — die Lösung liegt bereits im Repo, nur falsch verdrahtet

Das ist der konkreteste Befund dieser Studie, weil er sich direkt aus dem
bestehenden Code ableiten lässt, nicht nur aus Doku:

- Heute gibt es bereits **zwei** Rollen im Pairing-Protokoll: das Desktop
  zeigt einen QR (`qrgen.web.ts` — die "echte" Generierung, per Kommentar
  *"the real generation for the desktop UI"*), das Telefon scannt ihn per
  Kamera (`scan.tsx`, `CameraView`+`expo-camera`) und reicht den Code an
  `pair.tsx` weiter, das den Round-Trip über `api.me()` verifiziert.
- Der native Stub `qrgen.ts` (Metro-Plattformauflösung für alles außer
  `.web.ts`) ist wörtlich kommentiert: *"the phone scans a QR ..., it never
  generates one"* — **das ist exakt die Annahme, die für ein TV-Gerät falsch
  ist.** Ein TV hat keine Kamera (§4), aber genau wie das Desktop einen
  Bildschirm, auf dem ein QR angezeigt werden kann.
- **Der Fix ist also kein neues Protokoll** (kein OAuth-Device-Code-Flow wie
  Googles eigener [TV-Sign-in](https://developers.google.com/identity/protocols/oauth2/limited-input-device)
  ihn für sich selbst nutzt — *"open a browser on your phone ... go to
  accounts.google.com/device, enter the code"* — das wäre eine Neuerfindung),
  sondern **dieselbe Rolle wie das Desktop**: die TV-App müsste an der
  Metro-Plattformauflösung einen `.tv.ts`-Slot für `qrgen` bekommen (den
  `react-native-tvos`-Toolchain-Metro-Config laut Doku als Plattform-
  Erweiterung kennt), der dieselbe Generierungslogik wie `qrgen.web.ts`
  aufruft, plus eine TV-Variante der Onboarding-Anzeige aus `ui/onboard.tsx`
  (die bereits QR+Code parallel rendert, mit einem `Platform.OS === "web"`-
  Zweig für Monospace-Font — dort bräuchte es einen dritten Zweig, keinen
  neuen Screen). Das bestehende Telefon scannt die TV-QR genau wie es heute
  die Desktop-QR scannt — kein neuer Code auf der Telefon-Seite.

---

## 6. Benachrichtigungen — der Bruch gegenüber dem Telefon-Modell

Das ist der Punkt mit der schwächsten Primärquellen-Lage dieser Studie, aber
mit übereinstimmenden Sekundärquellen:

- Bestätigt aus Googles eigener Recommendations-Doku
  ([Recommend content on the home screen](https://developer.android.com/training/tv/discovery/recommendations),
  [Channels on the home screen](https://developer.android.com/training/tv/discovery/recommendations-channel)):
  Seit API 26 ist **Recommendations Channels** (`TvContractCompat`,
  Home-Screen-Kachelreihen) der einzige von Google aktiv gepflegte Weg,
  Content proaktiv auf dem TV-Homescreen zu bewerben — die ältere
  Notification-basierte "legacy recommendations row" (API ≤25) ist laut dem
  offiziellen [Android-Developers-Blog-Post "Phasing out legacy
  recommendations"](https://android-developers.googleblog.com/2017/12/phasing-out-legacy-recommendations-on.html)
  ausdrücklich abgekündigt.
- **Nicht primärquellen-bestätigt, aber aus mehreren unabhängigen
  Sekundärquellen übereinstimmend** (u. a. ein Medium-Artikel eines
  Android-Devs, ein B4X-Forenthread, Amazon-Fire-TV-Entwicklerdoku als
  Analogie): Android TV hat **keine Notification-Shade wie ein Telefon** —
  reguläre `NotificationCompat`-Kanäle, wie `push.ts` sie heute per
  `Notifications.setNotificationChannelAsync`/`scheduleNotificationAsync`
  benutzt, sind auf TV entweder gar nicht sichtbar oder Systemapp-Fällen
  vorbehalten; Hintergrund-Push-Payloads (Data-Only-FCM, genau HelmDecks
  Muster in `decryptPush`/`presentDecrypted`) gelten laut denselben Quellen
  als unzuverlässig, wenn die App nicht im Vordergrund ist. **Das ist die
  eine Lücke in dieser Studie, die keine Google-Primärquelle direkt
  bestätigt oder ausschließt** — vor einem Bau am echten Gerät zu prüfen
  (Recommendation: eine `expo-notifications`-Testnachricht auf einem echten
  Android-TV-Gerät im Hintergrund auslösen, nicht nur im Emulator).
- **Für HelmDeck heißt das:** Der proaktive "Henry spricht eine Push-
  Benachrichtigung laut vor"-Pfad aus `push.ts` (`presentDecrypted` +
  `speak`, referenziert in `ops/docs/glasses-reference.md` §11.8) hat auf einem
  TV vermutlich **kein Äquivalent im Hintergrund** — ein TV-Client wäre
  praktisch ein reiner Vordergrund-/Ambient-Display-Client (Board offen auf
  dem Fernseher), kein Ersatz für den proaktiven Phone-Kanal.

---

## 7. Sprache — anders als im Auto architektonisch NICHT gesperrt

Der Kernunterschied zu `ops/docs/android-auto-feasibility.md` §5: dort verbietet
Android Automotive OS Drittanbieter-Apps den direkten Mikrofonzugriff
architektonisch (eine System-Voice-Interaction-App hat exklusiven Zugriff).
**Auf Android TV gilt diese Sperre nicht:**

- TV-Apps dürfen laut Standard-Android-Permission-Modell (kein
  TV-spezifisches Verbot gefunden) `RECORD_AUDIO` deklarieren und einen
  eigenen `android.speech.SpeechRecognizer` fahren — exakt das Muster, das
  `GlassVoiceService.kt` für die Brille bereits implementiert.
- Googles eigene Leanback-Bibliothek (`androidx.leanback.widget.SearchBar`)
  bietet dafür sogar zwei dokumentierte Wege nebeneinander:
  `SpeechRecognitionCallback` (delegiert an eine System-Voice-Search-Intent,
  keine eigene `RECORD_AUDIO`-Permission nötig) **oder** einen eigenen
  `SpeechRecognizer` direkt in der App (App hält die Permission selbst) —
  **Quelle ist ein Community-Artikel, keine developer.android.com-Seite
  direkt gelesen, daher als unverifiziert markiert**, aber konsistent mit dem
  allgemeinen `RECORD_AUDIO`-Permission-Modell, das für TV nirgends
  eingeschränkt dokumentiert ist.
- Der Fernbedienungs-Mikroknopf selbst ist **standardmäßig an
  Assistant/Gemini gebunden**, nicht an die aktive App — ein eigener
  Henry-Mikroknopf müsste als on-screen-UI-Element existieren (fokussierbar
  per D-Pad, §3), nicht als Belegung der Hardware-Mikrofontaste.
- **Zeitlicher Kontext (2026):** Googles [eigener Blogpost "Gemini comes to
  Google TV"](https://blog.google/products-and-platforms/platforms/google-tv/gemini-google-tv/)
  und mehrere Fachmedien (Stand Juni–August 2026) beschreiben den aktuellen
  Gemini-Rollout auf Google TV als **System-Settings-Steuerung** (Helligkeit,
  Kontrast, Lautstärke per Sprache) — exklusiv auf TCL-Geräten mit Android TV
  OS 14+ zum Start, andere Hersteller "later this year". Das ist eine
  System-Funktion, kein App-Actions-Kanal für Drittanbieter-Chat-Apps — für
  HelmDeck also (noch) kein Weg, Henry über Gemini statt über einen eigenen
  Mikroknopf zu erreichen.

---

## 8. Testing

- Android-TV-Emulator über Android Studios AVD-Manager (eigenes
  Geräteprofil "Android TV", kein separates Tool nötig), Fernbedienung wird
  per Maus/Tastatur im Emulatorfenster oder per
  `adb shell input keyevent <KEYCODE_DPAD_*>` simuliert.
- **Kein DHU-Äquivalent nötig** — anders als Android Auto (§6 dort) braucht
  Android TV kein echtes Telefon zur Projektion; der Emulator ist ein
  vollständiges eigenständiges Zielgerät.
- Expo-Setup laut `docs.expo.dev`-Doku: `EXPO_TV=1 npx expo run:android`
  (oder `expo start` gegen einen laufenden TV-Emulator/ein TV-Gerät) — nach
  Aktivierung des `@react-native-tvos/config-tv`-Plugins identisch zum
  normalen Android-Workflow dieses Repos.

---

## 9. Wie das auf HelmDecks eigene Architektur träfe

| Baustein | Heute (Telefon) | Für Android TV |
|---|---|---|
| Navigation | `expo-router`, Tabs+Touch | dieselbe Router-Struktur, D-Pad-fokussierbare Komponenten statt `Pressable`-Touch-Targets (`TVFocusGuideView`/Focus-Styling neu) |
| Pairing | Telefon scannt Desktop-QR (`scan.tsx`+`expo-camera`) | TV übernimmt die **Desktop-Rolle** — zeigt QR via `qrgen.web.ts`-Logik an einem neuen `.tv.ts`-Slot; Telefon scannt wie gewohnt, kein neuer Telefon-Code (§5) |
| Push/proaktiv | `push.ts`: FCM data-only → entschlüsseln → lokale Notification + `speak()` | vermutlich kein Hintergrund-Äquivalent (§6) — TV-Client wäre Vordergrund-/Ambient-Board, kein proaktiver Kanal |
| Sprache (Henry-Mikroknopf) | `GlassVoiceService.kt` (Brille), `voice.ts` (Telefon-TTS-Player) | Muster ist grundsätzlich portierbar (eigener `SpeechRecognizer`, §7) — aber neuer on-screen-Mikroknopf statt Hardware-Taste, keine Assistant-Vorlesen-Abkürzung wie bei Android Auto |
| Native Plugins | `withGlassVoice.js`, `withMetaDat.js`, `expo-camera` | Brillen-Plugin vermutlich no-op auf TV (ungetestet), Kamera-Pfad (`scan.tsx`) auf TV nicht nutzbar (kein Kamera-Hardware) |
| Assets | `android-icon-*` (Rebrand-Satz) | zusätzlich: TV-Banner 320×180, xhdpi, Text eingebrannt, je eine de/en-Version (§3) |

---

## 10. Aufwandsschätzung

| # | Schritt | Aufwand (grob, inkl. Gerätetest) | Bemerkung |
|---|---|---|---|
| 1 | `react-native` → `react-native-tvos`-Swap, `@react-native-tvos/config-tv`-Plugin, `EXPO_TV=1`-Prebuild, Manifest-Flags (`leanback`/`touchscreen required=false`), `CATEGORY_LEANBACK_LAUNCHER` | 0,5–1 T | mechanisch, laut Doku SDK-57-kompatibel |
| 2 | Emulator-Testlauf, Issue-#906-Risiko klären (`setImmediate`-Crash) | 0,5 T | erster echter Blocker-Check, bevor der Rest sinnvoll geplant werden kann |
| 3 | TV-Banner-Assets (2 Sprachen), Store-Listing-Opt-in im Play Console | 0,5 T | reine Asset-/Konfigurationsarbeit |
| 4 | D-Pad-Fokusnavigation für die bestehenden Board/Chat-Screens (Touch-Targets → fokussierbare Komponenten) | 2–4 T | Umfang hängt von Anzahl betroffener Screens ab, nicht in dieser Studie geschätzt |
| 5 | Pairing umdrehen: `qrgen`-`.tv.ts`-Slot + `onboard.tsx`-TV-Zweig | 0,5–1 T | Logik existiert bereits (§5), nur neu verdrahtet |
| 6 | Sprache: eigener Mikroknopf + `SpeechRecognizer`-Modul nach `GlassVoiceService.kt`-Muster | 2–3 T | eigenständiges natives Kotlin-Modul, wie bei der Brille — kein vorhandener Wrapper |
| 7 | Push/proaktiv-Ersatz für TV klären (§6-Lücke) | Entscheidung + Testaufwand, nicht bezifferbar vor Gerätetest | könnte entfallen, wenn TV bewusst nur als Ambient-Board ohne proaktiven Kanal gebaut wird |

**Empfehlung:** Schritt 1–3 zuerst (≈1,5–2 Tage) als reiner
Machbarkeits-Spike — läuft die bestehende App überhaupt auf einem
TV-Emulator, und tritt Issue #906 dort auf? Erst danach lohnt sich eine
Schätzung für Schritt 4–7, weil deren Umfang (wie viele Screens, ob ein
proaktiver Kanal überhaupt gewünscht ist) von Owner-Entscheidungen abhängt,
nicht von der Recherche allein.

---

## 11. Nicht verifiziert — was ein Bau erst klärt

1. **Push-Benachrichtigungen im Hintergrund auf Android TV** (§6) — die
   einzige Lücke ohne Google-Primärquelle, nur übereinstimmende
   Sekundärquellen. Vor jeder Entscheidung über einen proaktiven TV-Kanal an
   einem echten Gerät zu prüfen.
2. **`SpeechRecognitionCallback` vs. eigener `SpeechRecognizer` in
   `androidx.leanback.widget.SearchBar`** (§7) — aus einem Community-Artikel,
   nicht direkt aus der API-Referenz gelesen.
3. **GitHub-Issue #906** (`setImmediate`-Crash, §4) — offen, ungeklärt, ob
   Template- oder Umgebungs-spezifisch.
4. **Ob `withGlassVoice.js`/`withMetaDat.js` auf einem TV-Prebuild überhaupt
   sauber durchlaufen** (§4) — nur aus der Plugin-Funktion abgeleitet
   ("Brille nicht vorhanden → No-op"), nicht getestet.
5. **Praktische Auffindbarkeit einer Chat-App auf dem Google-TV-Homescreen**
   (§2) — keine harte Quelle zur tatsächlichen Platzierung in der
   App-Kachelreihe vs. Content-Empfehlungszeilen.

---

## 12. Offene Entscheidungen — das, was hier freigegeben werden muss

1. **Zielbild bestätigen**: Ein TV-Client als reiner **Ambient-Board-Viewer**
   (Board/Chat-Verlauf auf dem Fernseher sichtbar, kein proaktiver Push-Kanal,
   keine eigene Sprachtaste) — deutlich billiger (§10, Schritte 1–5, ohne 6–7)
   — oder als **vollwertiger Henry-Zugang mit eigenem Mikroknopf** (Schritte
   1–6, TV wird ein dritter Sprachkanal neben Telefon und Brille)?
2. **Reihenfolge**: Schritt 1–3 (Machbarkeits-Spike) jetzt fahren, um Issue
   #906 und die generelle Lauffähigkeit zu klären, bevor über Schritt 4–7
   entschieden wird?
3. **Push/proaktiv-Frage** (§6/§11 Punkt 1): jetzt am Gerät klären (kostet
   einen Testlauf, keinen Bauaufwand) oder zurückstellen, bis das
   Grundgerüst steht?

---

## 13. Provenance

Primärquellen, mit Stand-Datum wie beim Abruf angezeigt (2026-08-22 abgerufen):
- [TV app quality](https://developer.android.com/docs/quality-guidelines/tv-app-quality) (Stand 2026-06-29)
- [Distribute to Android TV](https://developer.android.com/training/tv/publishing/distribute) (Stand 2026-05-08)
- [Create and run a TV app](https://developer.android.com/training/tv/get-started/create)
- [Handle TV hardware](https://developer.android.com/training/tv/get-started/hardware)
- [Recommend content on the home screen](https://developer.android.com/training/tv/discovery/recommendations)
- [Channels on the home screen](https://developer.android.com/training/tv/discovery/recommendations-channel)
- [Phasing out legacy recommendations on Android TV](https://android-developers.googleblog.com/2017/12/phasing-out-legacy-recommendations-on.html) (Android-Developers-Blog, 2017, weiterhin die maßgebliche Abkündigungsquelle)
- [Build Expo apps for TV](https://docs.expo.dev/guides/building-for-tv/) (zuletzt geändert 2026-07-20)
- [How to build TV apps with Expo and React Native](https://expo.dev/blog/how-to-build-tv-apps) (Expo-Blog, 2024-02-14)
- [OAuth 2.0 for TV and Limited-Input Device Applications](https://developers.google.com/identity/protocols/oauth2/limited-input-device) (zum Vergleich, nicht als HelmDeck-Lösung übernommen, §5)
- [Gemini comes to Google TV](https://blog.google/products-and-platforms/platforms/google-tv/gemini-google-tv/) (Google-Blog, 2026)
- `github.com/react-native-tvos/react-native-tvos` Issue #906, `github.com/react-native-tvos/ExpoRouterTV`, `github.com/expo/examples` (`with-router-tv`)

Aus diesem Repo gelesen: `surfaces/app/src/app/pair.tsx`, `surfaces/app/src/app/scan.tsx`,
`surfaces/app/src/data/qrgen.ts`, `surfaces/app/src/data/qrgen.web.ts`, `surfaces/app/src/ui/onboard.tsx`,
`surfaces/app/src/data/push.ts`, `app/app.json`, `surfaces/app/package.json`, `surfaces/app/src/i18n`.
Kein Treffer für "Android TV"/"Google TV"/"leanback"/"react-native-tvos" im
restlichen Repo vor dieser Studie (grep, 2026-08-22) — dies ist der erste
Kartenlauf zu diesem Thema, wie schon `ops/docs/android-auto-feasibility.md` für
Android Auto.

Recherche-Vorbehalt: mehrere Antworten stammen aus einer
AI-Zusammenfassungs-Stufe des WebSearch/WebFetch-Tools über die
Original-Doku, nicht aus wortgenauem Lesen jeder Zeile (im Text als
unverifiziert markiert, wo zutreffend, siehe §11). Vor einem tatsächlichen
Bau die als unverifiziert markierten Punkte direkt gegen die Live-Doku bzw.
ein echtes Gerät nachprüfen.
