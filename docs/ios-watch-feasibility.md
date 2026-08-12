# Machbarkeitsstudie: HelmDeck auf iOS + Apple Watch Ultra

**Analyse-Stand:** 2026-08-12, Branch-Basis `b3f756e`. Reine Analyse — kein Code,
keine Migration. Grundlage: `app/app.json`, `app/package.json`, `app/src/data/*`
(Transport/Push/OTA/E2EE), `app/plugins/withLanCleartext.js`, `relay/relay.py`,
`daemon/notify.py`, `DEPLOY.md`, `deploy/*.sh`, `desktop/main.js`,
`desktop/electron-builder.yml`, `desktop/tray.py`.

**Kurzfazit vorweg:** Die App ist überraschend iOS-freundlich. Der gesamte
Transport ist plain `fetch` + Long-Poll über den versiegelten Relay (kein
WebSocket, kein SSE, kein natives Netzwerkmodul), die Krypto ist reines JS
(tweetnacl), der OTA-Server ist bereits plattform-parametrisiert. Es gibt genau
**zwei** echte Baustellen: **Push** (FCM ist Android-gebunden) und der
**Build-/Verify-Weg ohne Mac**. Die Watch Ultra bekommt man in Phase 1
**gratis** über Notification-Mirroring + Action-Buttons — eine native
watchOS-App ist ein eigenes (Swift-)Projekt und für den gewünschten Scope
zunächst unnötig.

---

## 1. Inventar der nativen Abhängigkeiten — Urteil je Eintrag

### 1.1 app.json-Plugins

| Plugin | Zweck | Urteil iOS |
|---|---|---|
| `expo-router` | Routing/Typed Routes | **läuft unverändert** |
| `expo-updates` | OTA vom Relay (`/updates/manifest`, Channel `production`) | **läuft unverändert** — Details in §1.4 |
| `./plugins/withLanCleartext` | Android network-security-config für Direct-LAN-HTTP | **braucht Ersatz** — reines Android-Konzept (NSC). iOS-Pendant: ATS-Ausnahme `NSAllowsLocalNetworking` + `NSLocalNetworkUsageDescription` (iOS-14-Privacy-Prompt für lokales Netz) via `app.json → ios.infoPlist`. Kein eigenes Plugin nötig. Relay-/HTTPS-Pfad braucht **nichts** (ATS-konform). |
| `expo-splash-screen` | Splash | **läuft unverändert** |
| `expo-secure-store` | Pairing-Keys | **läuft unverändert** (iOS Keychain — sogar das Heimatsystem dieses Moduls) |
| `expo-image` | Bilder | **läuft unverändert** |
| `expo-notifications` | Push-Empfang + lokale Notifications | **Client läuft, Sender fehlt** — siehe §1.3 (die eigentliche Baustelle liegt im Daemon, nicht in der App) |
| `expo-camera` (Permission-Text de) | QR-Pairing-Scan | **läuft unverändert** — der konfigurierte `cameraPermission`-Text wird zur `NSCameraUsageDescription` |

Weitere app.json-Punkte:

| Konfig | Urteil iOS |
|---|---|
| `ios.bundleIdentifier: app.helmdeck` | bereits vorhanden ✓ |
| `ios.icon: ./assets/expo.icon` (Icon Composer) | bereits vorhanden ✓ |
| `scheme: helmdeck` (Custom-Scheme-Deep-Link) | **läuft unverändert** — deckt QR-/Code-Pairing ab (`app/src/app/pair.tsx` nutzt `Linking.useURL()`) |
| `android.intentFilters` für `https://<relay>/pair` (App Links) | **fehlt auf iOS** — Pendant = Universal Links: `ios.associatedDomains` Entitlement **plus** eine `/.well-known/apple-app-site-association`-Datei, die `relay/relay.py` ausliefern müsste (kleine Relay-Änderung). Nicht kritisch: QR-Scan und Code-Eingabe funktionieren ohne. |
| `android.googleServicesFile` | Android-only (FCM). iOS braucht das **nicht**, wenn Push über Expo-Push oder APNs-direkt läuft (§1.3). |
| `newArchEnabled`, `reactCompiler`, `typedRoutes` | plattformneutral ✓ |

### 1.2 Native Module (package.json)

| Modul | Urteil iOS |
|---|---|
| `expo-blur`, `expo-haptics`, `expo-symbols`, `expo-glass-effect`, `@expo/ui` | **laufen unverändert — sind sogar iOS-first** (SF Symbols, Liquid Glass, SwiftUI-Komponenten). Befund am Rande: `expo-glass-effect`, `expo-symbols`, `@expo/ui` sind installiert, aber in `app/src` **derzeit ungenutzt** — auf iOS würden sie erstmals Wirkung entfalten. |
| `expo-clipboard`, `-constants`, `-device`, `-document-picker`, `-font`, `-image-manipulator`, `-image-picker`, `-linear-gradient`, `-linking`, `-status-bar`, `-system-ui`, `-web-browser` | **laufen unverändert** (Standard-Expo-SDK, beide Plattformen). `image-picker`/`document-picker` bringen ihre iOS-Permission-Strings über Plugin-Defaults mit; deutsche Texte wären ein Einzeiler in `ios.infoPlist`. |
| `react-native-gesture-handler`, `-reanimated`, `-worklets`, `-safe-area-context`, `-screens`, `-svg` | **laufen unverändert** (RN-Standardstack) |
| `react-native-get-random-values` | **läuft unverändert** — polyfillt `crypto.getRandomValues` für tweetnacl auf iOS genauso |
| `tweetnacl`, `tweetnacl-util`, `qrcode`, `zustand`, `@tanstack/react-query` | **pures JS, läuft unverändert** — die gesamte E2EE (`app/src/data/e2ee.ts`, Curve25519/XSalsa20-Poly1305) ist plattformneutral |
| `react-native-sse` | **ungenutzt** — deklariert in package.json, kein Import in `app/src` (der SSE-Pfad wurde durch den Long-Poll ersetzt). Wäre ohnehin pures JS. Kandidat zum Entfernen, kein iOS-Thema. |
| `@react-native-async-storage/async-storage` | **läuft unverändert** |

### 1.3 Push — die echte Baustelle Nr. 1

Ist-Zustand (`daemon/notify.py` + `app/src/data/push.ts`): der Daemon sendet
**FCM-v1-Data-Messages** mit NaCl-versiegeltem Payload direkt an das rohe
FCM-Token (`getDevicePushTokenAsync()` auf Android), Service-Account-JWT via
`fcm_service_account.json`. Die App entschlüsselt und präsentiert lokal;
Fallback-Notification „Neue Meldung – zum Ansehen tippen“ wenn die App nicht
läuft. **Das funktioniert so auf iOS nicht**: `getDevicePushTokenAsync()`
liefert dort ein **APNs**-Token, und FCM-Zustellung auf iOS bräuchte das
Firebase-iOS-SDK (= `@react-native-firebase/messaging`, neues natives Modul —
Expo-notifications spricht auf iOS kein FCM).

Drei Optionen, ehrlich bewertet:

1. **Expo Push Service** (`getExpoPushTokenAsync` + Daemon-POST an
   `https://exp.host/--/api/v2/push`) — **Empfehlung.** Ein Sender für beide
   Plattformen, kein APNs-Schlüsselmanagement im Daemon, nur stdlib-`urllib`
   wie bisher. Zero-Knowledge bleibt intakt: der Payload ist weiterhin der
   versiegelte `cipher`, Expo/Google/Apple transportieren nur Ciphertext —
   exakt dieselbe Vertrauensstellung, die FCM heute schon hat. Kostet: EAS-
   `projectId` in der App (kommt mit dem EAS-Setup aus §2 ohnehin). Könnte
   perspektivisch sogar den Android-FCM-Direktpfad ersetzen (ein Codepfad statt
   zwei).
2. **APNs direkt aus dem Daemon** — sauber, aber APNs verlangt **HTTP/2**;
   Pythons stdlib kann das nicht → neue Abhängigkeit (`httpx[http2]`/`aioapns`)
   + `.p8`-Key-Verwaltung. Mehr Aufwand, kein Zero-Knowledge-Gewinn.
3. **FCM auch für iOS** — bräuchte react-native-firebase (natives Modul,
   Prebuild-Eingriff) nur um beim alten Sender zu bleiben. **Lohnt nicht.**

Ehrlicher iOS-Vorbehalt unabhängig vom Sender: iOS hat **kein Headless-JS**.
Der versiegelte Inhalt kann bei gesperrtem Gerät **nicht** im Hintergrund
entschlüsselt und angezeigt werden — dafür bräuchte es eine **Notification
Service Extension** (natives Swift-Target, Key-Sharing via App
Group/Keychain). Für v1 reicht das bestehende Fallback-Muster: generischer
Titel auf dem Lockscreen, Entschlüsselung + Deep-Link beim Antippen
(`decryptPush` on tap existiert schon in `_layout.tsx`). NSE = bewusst
verschobene Phase-2-Politur.

### 1.4 OTA / expo-updates

- **Client:** `expo-updates` + der Silent-OTA-Hook (`app/src/data/ota.ts`) sind
  plattformneutral; der Kommentar dort behandelt iOS-`inactive` sogar schon
  korrekt. Updates-URL ist HTTPS → ATS-konform. **Läuft unverändert.**
- **Server:** `relay/relay.py` liest bereits `expo-platform`-Header und
  `fileMetadata[platform]` aus `metadata.json` — der Manifest-Endpunkt ist
  **schon heute plattformfähig**. Es fehlt nur, dass je ein iOS-Bundle
  exportiert und hochgeladen wird.
- **Deploy-Skript:** `deploy/push_update.sh` exportiert hart
  `--platform android`. Änderung: `--platform all` (ein Export, eine
  `metadata.json` mit beiden Plattformen) + der Verify-curl einmal je Plattform.
- **Optional:** expo-updates Code-Signing ist auf iOS nicht Pflicht — kann
  bleiben wie es ist.

### 1.5 Relay-Transport, TLS, Deep-Links — Kurzurteile

| Baustein | Befund | Urteil iOS |
|---|---|---|
| Relay-Transport | `fetch`-POST mit versiegelten Frames + `boardWait`/`transcriptLive` **Long-Poll** (~22 s); SSE/WebSocket werden **nicht** benutzt (`client.ts`, `_layout.tsx`) | **läuft unverändert** — kein natives Netzwerkmodul im Spiel |
| TLS Relay | `https://141.144.227.105.sslip.io` (echtes Zertifikat) | **läuft unverändert** (ATS zufrieden) |
| Cleartext Direct-LAN | Android NSC via Plugin | **braucht Ersatz** (ATS-Keys, §1.1) — betrifft nur den Direct-LAN-Modus, nicht den Relay-Alltag |
| Pairing per QR/Code/`helmdeck://` | expo-camera + `Linking.useURL()` | **läuft unverändert** |
| Pairing per `https://…/pair`-Link | Android App Links | **fehlt** — Universal Links = Entitlement + AASA-Datei auf dem Relay (klein, optional) |
| E2EE | tweetnacl, byte-kompatibel zu PyNaCl | **läuft unverändert** |

**Zwischenfazit Inventar:** ~90 % „läuft unverändert“. Ersatz brauchen nur
(a) der Push-Sendepfad im Daemon, (b) die Cleartext-/LAN-Konfiguration,
(c) optional Universal Links. Es existiert **kein** hand-gemanagtes `ios/`-
Verzeichnis (anders als `app/android/`) — iOS könnte sauber über
`expo prebuild`/EAS-managed laufen, ohne die Android-Handverwaltung anzutasten.

---

## 2. Build- und Distributionsweg

### 2.1 EAS Build vs. lokaler Mac-Build

| | EAS Build (Cloud) | Lokaler Mac-Build |
|---|---|---|
| Hardware | keine — läuft von Windows aus | Mac + Xcode zwingend (existiert hier nicht) |
| Signing/Zertifikate | EAS verwaltet Certs + Provisioning-Profile automatisch | Handarbeit in Xcode |
| Upload zu TestFlight | `eas submit` direkt aus der CLI | Xcode/Transporter |
| Kosten | Free-Tier: ~30 Builds/Monat (iOS inklusive, langsamere Queue); bezahlt ab ~19–99 $/Monat erst bei ernsthaftem Volumen | Mac-Anschaffung |
| Passung zum Repo | gut: kein `ios/`-Ordner nötig (managed prebuild) | bricht das „kein Mac im Spiel“-Setup |

**Urteil: EAS, ohne Diskussion.** Ein nativer iOS-Build ist selten nötig
(nur bei neuen nativen Modulen / runtimeVersion-Bump) — das Free-Tier reicht
absehbar. Der JS-Alltag läuft weiterhin über den eigenen Relay-OTA-Kanal,
**nicht** über EAS Update — die bestehende Infrastruktur bleibt Herr des
Verfahrens.

### 2.2 Apple-Developer-Konto & TestFlight

- **Apple Developer Program: 99 USD/Jahr** (in DE ≈ 99 €/Jahr). Ohne Konto kein
  TestFlight, kein Push-Entitlement, keine 1-Jahres-Zertifikate — Pflicht.
- **TestFlight statt Play-Internal-Testing:** Internes Testing (bis 100 Tester
  über App Store Connect-Rollen) ist **ohne Review** und in Minuten verfügbar —
  das Äquivalent zum heutigen „APK vom Relay ziehen“. Externes Testing (bis
  10 000) bräuchte Beta-App-Review — für den Eigenbedarf irrelevant.
- **Ehrliche Wartungssteuer:** TestFlight-Builds **verfallen nach 90 Tagen** →
  mindestens quartalsweise ein neuer nativer Build+Upload, auch ohne jede
  Code-Änderung. Ein Relay-`/apk/`-Pendant (Ad-hoc-IPA) existiert praktisch
  nicht sinnvoll (UDID-Registrierung, 7-Tage-Free-Signing etc. — Sackgassen).
- Ein App-Store-Release ist für den Scope **nicht nötig** (kein Review-Risiko).

### 2.3 Was sich am DEPLOY.md-Runbook ändern müsste

| Runbook-Stelle | Änderung für iOS |
|---|---|
| `push_update.sh` | Export `--platform all` statt `android`; Verify-curl je Plattform (`expo-platform: ios`). Relay-Seite: keine Änderung nötig. |
| `push_relay.sh` / `/apk/helmdeck.apk` | bekommt **kein** iOS-Pendant — natives Ausliefern läuft über `eas build` + `eas submit` → TestFlight. Neues, kleines Skript (`deploy/push_testflight.sh`) statt Erweiterung. |
| `build_apk.sh` (JDK 17, Pfadlängen, Emulator-Smoke) | bleibt Android-only. Die ganze Windows-Trap-Sektion (ninja/CMake-Pfade, robocopy-Mirror) entfällt für iOS — EAS baut in der Cloud. |
| **Emulator-Verify** | größte Lücke: **kein iOS-Simulator auf Windows.** Verify = echtes iPhone via TestFlight (Minuten-Latenz statt Sekunden) — der `adb screencap`-Reflex hat kein iOS-Gegenstück. Ehrlich einpreisen: iOS-Verifikation ist langsamer und bleibt Handarbeit am Gerät. |
| **`runtimeVersion` (policy `appVersion`)** | Entscheidungsbedarf: `ship.sh` bumpt die Version bei **jedem** nativen Android-Change → dieselbe runtimeVersion gilt für iOS → ohne gleichzeitigen iOS-Rebuild bekommt das iPhone **keine OTAs mehr** (rtv-Mismatch, absichtlich). Optionen: (a) bei jedem Bump beide Plattformen bauen (EAS-Build ist billig, aber TestFlight-Upload nervt), (b) **per-Plattform-runtimeVersion** in app.json (`ios.runtimeVersion` getrennt führen) — sauberer, kleine ship.sh-Logik. Empfehlung: (b). |
| Fast-Track-Hook (`ship.sh`) | Fingerprint-Logik muss iOS-native-affecting Files mit aufnehmen, wenn (a) gewählt wird; bei (b) genügt: iOS-Bump nur bei iOS-relevanten Änderungen. |

---

## 3. Apple Watch Ultra — ehrliche Bewertung

### 3.1 Was mit Expo/React Native überhaupt geht

**Nichts läuft direkt auf der Watch.** React Native hat kein watchOS-Target,
Expo auch nicht — jede „RN-Watch-App“ ist in Wahrheit eine native
SwiftUI-App im selben Xcode-Projekt. Das ist die harte Wahrheit vorweg.

**Aber:** watchOS spiegelt iPhone-Benachrichtigungen **automatisch** (iPhone
gesperrt/abgelegt → Push erscheint auf der Watch, inkl. Haptik auf der Ultra).
Und `expo-notifications` unterstützt **Notification-Categories mit
Action-Buttons und Text-Input-Actions** (`setNotificationCategoryAsync`) —
diese Actions erscheinen **auch auf der gespiegelten Watch-Notification**, und
Text-Input heißt auf der Watch: **Diktat**. Die Antwort wird an die iPhone-App
zurückgeliefert (`addNotificationResponseReceivedListener` bzw.
`getLastNotificationResponseAsync` beim Kaltstart), die daraus ein
`api.answer(...)`/`api.steer(...)` über den versiegelten Relay macht — die
Infrastruktur dafür (Ask-Protokoll mit `options`, Steer-Endpoint) existiert
vollständig.

**Das heißt: der gewünschte Kern — Push bei `needs_you`, ein Tipp =
Antwort/Steer — geht ohne eine Zeile Watch-Code.** Vorbehalt, ehrlich: die
Ask-Optionen sind dynamisch, iOS-Categories werden zur Laufzeit registriert —
praktikabel ist ein fester Satz generischer Actions („Weiter so“, „Stopp“,
„Antwort diktieren…“) plus Deep-Link in die App für die echte Options-Auswahl.
Und die Zuverlässigkeit von Action-Handling aus dem Killed-State muss am
echten Gerät verifiziert werden (bekannte Expo-Schwachstelle; Fallback: App
öffnet sich kurz — akzeptabel).

### 3.2 Was natives watchOS (SwiftUI) bräuchte

Eine echte Watch-App (Karten-Status-Liste am Handgelenk, Antwort-UI,
Komplikation auf dem Ultra-Zifferblatt) heißt:

- **SwiftUI-Target** im iOS-Projekt — mit Expo nur über Community-Wege
  (`@bacons/apple-targets`, experimentell) oder Bare-Prebuild + Hand-Xcode.
  Realistisch braucht die Entwicklung dann doch einen Mac (Iterieren über
  EAS-Cloud-Builds ist Qual).
- **Datenweg:** entweder WatchConnectivity zur iPhone-App (die dann den
  Relay-I/O macht — aber die iPhone-App muss geweckt werden, fummelig) oder
  die Watch spricht **selbst** mit dem Relay (watchOS kann URLSession auch
  ohne iPhone) — dann muss die NaCl-Box (XSalsa20-Poly1305) in Swift nachgebaut
  werden (`swift-sodium`, byte-kompatibel machbar, plus Key-Sharing über
  App Group/Keychain).
- Eigene UI, eigenes Update-Regime (kein OTA — jede Änderung ist ein
  TestFlight-Build), eigene Pflege für immer.

### 3.3 Vorschlag: realistischer Scope der Begleit-App

**Phase W1 — „Watch gratis“ (Teil des iOS-Basispakets, kein Watch-Code):**
- `needs_you`-/Gate-/Done-Pushes erscheinen auf der Watch (Mirroring).
- Category-Actions: 2–3 feste Buttons + „Diktieren…“ (Text-Input-Action) →
  Steer/Answer über die iPhone-App im Hintergrund.
- Karten-Status „ansehen“ = Notification zeigt Titel + Frage-Summary (steht
  schon heute im Push-Body, `notify.py` kürzt auf 120 Zeichen).

**Phase W2 — nur falls W1 nachweislich nicht reicht:**
- Native SwiftUI-Watch-App: Liste der letzten ~10 Karten mit Status-Farbe,
  Detail mit Ask-Optionen als echte Buttons, Diktat-Steer, eine Komplikation
  („N Karten warten auf dich“). **Explizit KEIN Board**, kein Transcript, kein
  Chat — die Watch ist ein Quittungs- und Ein-Tipp-Gerät.

---

## 4. Aufwandsschätzung und Empfehlung

### 4.1 Aufwand je Teilschritt (Personentage, ehrlich inkl. Gerätetest)

| # | Teilschritt | Aufwand | Anmerkung |
|---|---|---|---|
| 1 | Apple-Konto, EAS-Setup, `eas.json`, erster TestFlight-Build (managed prebuild neben hand-managed `app/android`) | **1–2 T** | einmalig; enthält Credentials-Gefummel |
| 2 | ATS/Direct-LAN-Keys, iOS-Permission-Texte, `pair.tsx`-Smoke auf iPhone; optional AASA/Universal-Links auf dem Relay | **0,5–1 T** | Relay-Änderung ist ~20 Zeilen |
| 3 | Push-Umbau: Expo-Push-Token-Pfad in `push.ts`, Daemon-Sender (`notify.py`) auf Expo-Push-API, Categories + Action-Handling (inkl. Diktat) | **2–3 T** | größter Einzelposten; Zero-Knowledge bleibt |
| 4 | OTA dual-platform: `push_update.sh --platform all`, per-Plattform-`runtimeVersion`, `ship.sh`-Fingerprint, `rollback_update.sh`-Check | **1 T** | Relay-Server kann es schon |
| 5 | End-to-End-QA am echten iPhone + Watch (Pairing, Long-Poll-Verhalten im Hintergrund, Push-Actions aus Killed-State, OTA-Zyklus) | **1–2 T** | kein Simulator auf Windows — Gerät nötig |
| | **Summe iOS-Basispaket inkl. Watch-Phase W1** | **≈ 6–9 T** | plus 99 €/Jahr, plus ~1 Build/Quartal Wartungssteuer |
| 6 | Watch-Phase W2 (native SwiftUI-App) | **5–10 T** | hohes Risiko/Unbekannte (apple-targets experimentell, realistisch Mac nötig, NaCl-Port in Swift); dauerhafte Pflege |
| 7 | Notification Service Extension (Klartext auf dem Lockscreen statt „Neue Meldung“) | **2–3 T** | Politur, erst nach W1-Erfahrung entscheiden |

### 4.2 Empfehlung

**iOS: ja — aber als bewusst kleines Basispaket, und nur wenn iPhone + Watch
tatsächlich Alltagsgeräte sind.** Die technische Hürde ist niedriger als das
Android-Runbook vermuten lässt: kein WebSocket-/SSE-Native-Code, plattform-
fertiger OTA-Server, reine JS-Krypto, kein hand-gemanagtes `ios/`-Erbe. Das
Basispaket (≈ 6–9 Tage) liefert die volle App auf dem iPhone **und** den
kompletten gewünschten Watch-Scope (Status sehen, `needs_you`-Push, ein Tipp
bzw. ein Diktat = Antwort) ohne eine Zeile Swift.

**Watch-Phase W2 (native App): später, Beweislast beim Bedarf.** Erst wenn
Mirroring + Actions im Alltag nachweislich zu wenig sind. Sie kostet so viel
wie das gesamte Basispaket, altert unabhängig und bringt gegenüber W1 vor
allem „Liste am Handgelenk“ — nice, nicht nötig.

**Gar nicht:** Vollboard auf der Watch (falscher Formfaktor, explizit aus dem
Scope), FCM-via-Firebase-SDK auf iOS (natives Modul nur um beim alten Sender
zu bleiben), Ad-hoc-IPA-Verteilung als TestFlight-Ersatz (Sackgasse).

**Reihenfolge, falls „jetzt“:** Schritte 1→2→4 zuerst (App läuft komplett auf
dem iPhone, OTA-Kanal steht — Push fehlt noch), dann 3 (Push + Watch W1), dann
5. Nach zwei Wochen Alltagsnutzung entscheiden, ob W2/NSE je eine Karte wert
sind. Wichtigste vorgelagerte Sachentscheidung: per-Plattform-`runtimeVersion`
(§2.3), sonst koppelt jeder Android-Native-Bump den iOS-OTA-Kanal ab.

---

## 5. Mac Desktop-App (Electron) — Nebenbefund

Nicht Teil der ursprünglichen Frage (iPhone/Watch), aber nah genug dran, um
mitzunehmen: `desktop/main.js` ist die Electron-Hülle, die den Python-Daemon
spawnt und die Expo-Web-Export-SPA lokal serviert. Befund: **strukturell
bereits plattformneutral geschrieben**, nicht Windows-verdrahtet.

### 5.1 Was schon passt

| Baustein | Befund |
|---|---|
| `resolvePython()` (`main.js:59-72`) | verzweigt bereits auf `process.platform !== "win32"` → `python3`/`python` statt `py -3.12`. **Läuft unverändert auf Mac.** |
| Daemon-Spawn, Adopt-or-Detach, `killTree` | `process.platform === "win32"` bereits abgefragt (taskkill vs. `SIGTERM`) — der POSIX-Zweig existiert, ist nur ungetestet. |
| `app.setLoginItemSettings({ openAtLogin: true })` | plattformneutrale Electron-API, funktioniert auf macOS identisch (Login Items). |
| lokal servierte SPA (`app/dist`, statischer HTTP-Server auf `WEB_PORT`) | reines Node, kein Windows-Bezug. |

### 5.2 Was fehlt

| Lücke | Aufwand |
|---|---|
| `desktop/electron-builder.yml` konfiguriert nur `win:` (NSIS) — kein `mac:`-Block (Target `dmg`/`zip`, `category`, `hardenedRuntime: true`, Entitlements-Datei) | klein, ~0,5 T |
| Icon: nur `assets/icon.ico` — macOS braucht `.icns` | klein (Konvertierung aus vorhandenem PNG/Icon-Set) |
| **Code-Signing + Notarization**: braucht ein „Developer ID Application“-Zertifikat. **Kein separates Konto nötig** — dasselbe Apple-Developer-Programm (99 €/Jahr) aus §2.2 deckt Mac-Signing und iOS-Provisioning gleichzeitig ab. Notarization läuft über Apples Notary-Service; **kein eigener Mac erforderlich**, das lässt sich von einem macOS-Runner in GitHub Actions treiben (electron-builder unterstützt `notarize` eingebaut) | ~0,5–1 T (CI-Pipeline einrichten, Cert/Keychain-Handling in Actions) |
| `desktop/tray.py` — der separate Windows-Tray-Supervisor (Autostart über `winreg`-Run-Key, `pythonw.exe`-Auflösung, `CREATE_NO_WINDOW`) ist **echt Windows-only**. Für Mac bräuchte es ein launchd-`.plist`-Pendant (LaunchAgent statt Registry-Key); `pystray` selbst ist plattformneutral (nutzt `rumps` unter der Haube auf macOS) | ~1 T, **optional** — nur nötig, falls der Tray-Supervisor-Pfad (nicht die Haupt-Electron-App) mitgezogen werden soll |

### 5.3 Urteil

Ein Mac-Desktop-Build ist **deutlich billiger als die iOS-Mobile-App**: keine
Push-Baustelle, keine fehlenden nativen Module, kein TestFlight-90-Tage-
Rhythmus (ein signiertes `.dmg` läuft dauerhaft, kein Ablauf). Reine
Packaging-/Signing-Arbeit. **Aufwand: ≈ 1–2 Tage** (electron-builder-Mac-Target
+ Icon + Notarization-CI), **plus optional 1 Tag** für den launchd-Ersatz von
`tray.py`, falls der Autostart-Supervisor mitgezogen werden soll.

**Synergie mit §2:** Das Apple-Developer-Konto (99 €/Jahr), das für iOS/
TestFlight ohnehin nötig ist, deckt Mac-Notarization **kostenneutral mit ab** —
eine Ausgabe, zwei Plattformen. Empfehlung: **wenn iOS-Schritt 1 (Apple-Konto +
EAS-Setup) gemacht wird, den Mac-Desktop-Build direkt danebenlegen** (~1–2
zusätzliche Tage) statt ihn separat zu terminieren — der teure Teil (Konto,
Signing-Grundlagen) ist derselbe.

---

## 6. „Lovable-artiger App-Builder statt selbst bauen?" — und die Flutter-Frage

Naheliegender Einwand: Gibt es nicht einen KI-App-Builder (Lovable-Klasse), der
Build **und** Publish für iOS + Mac-Desktop übernimmt, statt dass wir EAS/
Electron selbst betreiben? Zwei Ebenen, sauber getrennt:

### 6.1 Die harte Grenze: kein Builder kann dieses Repo „adoptieren"

Alle diese Tools — egal ob No-Code (Bubble, Adalo, Glide) oder KI-Codegen
(Lovable, Bolt, v0, FlutterFlow, RN-Generatoren) — sind **Greenfield-Builder**:
man baut *in* ihrem Modell neu, man importiert keine bestehende Codebase. Es
gibt keinen Pfad, der die vorhandene HelmDeck-App (custom E2EE mit `tweetnacl`,
custom Relay-Protokoll, gewachsene State-/Query-/OTA-Logik) in ein solches Tool
einliest. Ein Builder ergibt nur Sinn für einen **Neuanfang**, nicht für dieses
Repo.

### 6.2 Flutter/FlutterFlow ⇒ **kompletter Rewrite in Dart**

Der einzige verbreitete Builder, der iOS **und** nativen Mac-Desktop aus *einer*
Codebase publisht, ist **FlutterFlow** (Flutter kompiliert nativ zu macOS,
Windows, Linux). Aber Flutter bedeutet **Dart**, und die App ist React Native /
TypeScript. Ein Wechsel heißt neu schreiben:

- die gesamte UI (RN-Komponenten → Flutter-Widgets),
- die E2EE — `tweetnacl` (Curve25519/XSalsa20-Poly1305) → ein Dart-Crypto-Paket,
  **byte-kompatibel zu `daemon/e2ee.py` (PyNaCl) neu zu verifizieren**, sonst
  bricht das gesamte Pairing/Relay,
- der Relay-Transport (`app/src/data/client.ts`) + OTA + State/Query.

Das ist der Neubau des **ganzen Clients**, nicht „ein Tool nutzen". Bewertung:
**lohnt nicht.** Der einzige Gewinn wäre „Mac-Desktop aus derselben Codebase" —
und den liefert Electron (§5) aus dem bestehenden Web-Export schon fast gratis.

### 6.3 Was bliebe: RN-Familie, aber ohne Builder

Builder aus der **React-Native/Expo-Familie** würden zwar bei TypeScript
bleiben, aber auch sie generieren *neuen* RN-Code — sie adoptieren das Repo
nicht (§6.1). Der realistische Weg für HelmDeck bleibt daher: die **bestehende
Expo-App über EAS** bauen (§2), **kein Builder dazwischen**. Der Aufwand steckt
nicht im „Build-Tool" (EAS ist gelöst), sondern in Push (§1.3) und Signing/
Verify (§2) — daran ändert kein App-Builder etwas.

> **Offen / zu verifizieren:** Ein aktueller, belastbarer Vergleich konkreter
> Anbieter (Rork, Draftbit, Thunkable, Base44 u. a. — Stand 2026, Publish-Wege,
> Preise) steht aus, weil `WebSearch`/`WebFetch` in dieser Worker-Karte gesperrt
> sind (siehe Karten-Vorschlag `docs/cards/fix-websearch-permission.md`). Die
> obige Framework-Aussage (Flutter = Rewrite; RN-Familie = kein Sprachwechsel,
> aber kein Repo-Import) ist davon **unabhängig** und gilt so oder so.
