# HelmDeck — Data-Safety-Formular (Play Console → App content → Data safety)

Abgeleitet aus dem **tatsächlichen Transportverhalten** im Code, nicht aus
Absichten. Jede Antwort unten trägt ihren Beleg (Datei:Zeile, Stand dieses
Commits). Wenn sich der Transport ändert, dieses Dokument im selben Commit
nachziehen — das Formular muss der Prüfung standhalten (M4).

## 1. Transport-Inventar (was das Gerät tatsächlich verlässt)

| # | Daten | Weg | Beleg |
|---|---|---|---|
| T1 | Karten/Chat/Steuerkommandos (Request-Bodies) | **Relay-Modus:** NaCl-versiegelt (Curve25519/XSalsa20-Poly1305) als opaker Chiffretext an das Relay, nur der eigene Daemon kann öffnen | `surfaces/app/src/data/client.ts:34-60` (relayReq: seal→POST /relay), `surfaces/app/src/data/e2ee.ts`, `surfaces/relay/relay.py` (Docstring: zero-knowledge, nichts persistiert) |
| T2 | dieselben Daten | **Direkt-Modus:** HTTP(S) mit Bearer-Token an die vom Nutzer eingetragene eigene Daemon-URL | `surfaces/app/src/data/client.ts:62-95` (req: fetch baseUrl), `surfaces/app/src/data/config.ts:32-35` |
| T3 | Anhänge: Galerie-Fotos, Kamera-Aufnahmen, beliebige Dateien (base64, nur nach expliziter Auswahl) | wie T1/T2 an den eigenen Daemon (`POST /tracks/<id>/attach`) | `surfaces/app/src/data/attachments.ts` (pickImages/takePhoto/pickFiles), `surfaces/app/src/data/client.ts:191-194` |
| T4 | FCM-Geräte-Push-Token | an den eigenen Daemon (`POST /push/register`); Zustellung der Pushes läuft über Google FCM, Payload ist E2EE-Chiffretext | `surfaces/app/src/data/push.ts:18-31` (getDevicePushTokenAsync→api.post), `surfaces/app/src/data/push.ts:36-40` (decryptPush), `daemon/notify.py` (seal) |
| T5 | OTA-Update-Abfrage (Runtime-Version, Kanalname — keine Nutzerdaten) | GET an den eigenen Update-Server (Relay-VM) | `app/app.json` updates.url, `surfaces/relay/relay.py` /updates/manifest |
| — | Kopplungsdaten (relayUrl, room, Schlüsselpaar, daemonPub, Token) | **verlassen das Gerät nicht**; verschlüsselter Gerätespeicher | `surfaces/app/src/data/config.ts:39-45` (expo-secure-store) |
| — | Kamera beim QR-Scan | Bild wird nur lokal dekodiert, nie übertragen | `surfaces/app/src/app/scan.tsx` (CameraView onBarcodeScanned) |

**Nicht vorhanden** (geprüft `surfaces/app/package.json`): keine Analytics-, Werbe-,
Crash-Reporting- oder Tracking-SDKs; kein Standort, keine Kontakte.

Wichtig fürs Formular: T1–T3 gehen ausschließlich an **Infrastruktur, die der
Nutzer selbst betreibt**; über das Relay sind sie Ende-zu-Ende-verschlüsselt
(Play-Ausnahme für E2EE-Daten). Der App-Entwickler kann sie nie lesen.

## 2. Formular-Antworten (empfohlen: konservativ deklarieren)

**Overview-Fragen**

| Frage | Antwort | Warum |
|---|---|---|
| Does your app collect or share any of the required user data types? | **Yes** | T4 (Push-Token = Device ID) verlässt das Gerät nicht-E2EE; T1–T3 konservativ mitdeklariert |
| Is all of the user data collected by your app encrypted in transit? | **Yes** | Relay: E2EE + TLS; direkt: HTTPS (Release-Build blockt Cleartext); FCM: TLS |
| Do you provide a way for users to request that their data is deleted? | **Yes** | Entkoppeln rotiert Raum+Schlüssel und löscht das Push-Token (`daemon/relay_client.py:unpair`); Inhalte liegen ohnehin nur beim Nutzer |

**Datentypen**

| Play-Datentyp | Collected? | Shared? | Processed ephemerally? | Required? | Purpose |
|---|---|---|---|---|---|
| Messages → Other in-app messages | Yes (T1/T2) | **No** | No | Yes (Kernfunktion) | App functionality |
| Photos and videos → Photos | Yes (T3, nur nach Auswahl) | **No** | No | No (optional) | App functionality |
| Files and docs | Yes (T3, nur nach Auswahl) | **No** | No | No (optional) | App functionality |
| Device or other IDs | Yes (T4 FCM-Token) | **No** | No | Yes (für Push nach Opt-in) | App functionality |
| alles andere (Standort, Kontakte, Finanzen, Gesundheit, Browsing, …) | **No** | — | — | — | — |

Begründung „Shared = No": Empfänger ist ausschließlich der vom Nutzer selbst
betriebene Daemon; Google FCM handelt als Service-Provider des Entwicklers
(Play-Definition: Übermittlung an Service-Provider zählt nicht als „sharing").

**Alternative (minimal):** Play nimmt Ende-zu-Ende-verschlüsselte Daten von
der Deklarationspflicht aus („data sent off device that is end-to-end
encrypted … does not need to be disclosed"). Streng gelesen bleibt dann nur
„Device or other IDs" (T4). Empfehlung trotzdem: die konservative Tabelle
oben einreichen — sie übersteht auch eine strenge Prüfung des Direkt-Modus
(HTTPS ist Transportverschlüsselung, nicht E2EE) und wirkt im Listing ehrlich.

**Account-Sektion:** Die App hat keine vom Entwickler geführten Konten
(Login nur gegen die eigene Installation; `daemon/auth.py`, users.json beim
Nutzer). „App requires account creation" → **No**; Account-Deletion-URL
entfällt.

## 3. Berechtigungen (konsistent zum Formular)

Managed Workflow — das Manifest wird generiert, also ist die **einzige
belastbare Quelle das gebaute Artefakt**, nicht die Plugin-Liste. Unten steht,
was der aktuell ausgelieferte Build (`app.helmdeck`, versionCode 36,
nicht-debuggable) tatsächlich anfordert — ausgelesen mit:

```
adb shell dumpsys package app.helmdeck | sed -n '/requested permissions/,/install permissions/p'
```

| Permission | Quelle (verifiziert) | Rechtfertigung / Play-Relevanz |
|---|---|---|
| `INTERNET`, `ACCESS_NETWORK_STATE` | Core / React Native | eigener Daemon/Relay |
| `CAMERA` | `expo-camera` + `expo-image-picker` (beide Library-Manifeste) | QR-Kopplung (`scan.tsx`), Anhang-Fotos (`attachments.ts:takePhoto`) |
| `POST_NOTIFICATIONS`, `RECEIVE_BOOT_COMPLETED` | `expo-notifications` (Library-Manifest) | Push-Zustellung, Runtime-Prompt in `push.ts` |
| `VIBRATE`, `WAKE_LOCK` | `expo-notifications` | Zustellung |
| `com.google.android.c2dm.permission.RECEIVE` | FCM | Push-Transport |
| Badge-Permissions (`READ_APP_BADGE`, `*.permission.BADGE_COUNT_*`, launcher-spezifisch) | ShortcutBadger via `expo-notifications` | App-Icon-Badge; harmlos, keine Deklaration nötig |
| `USE_BIOMETRIC`, `USE_FINGERPRINT` | `expo-secure-store` → `androidx.biometric:1.1.0` (dessen `build.gradle`) | biometrisch abgesicherter Keystore; keine Play-Deklaration nötig |
| `BIND_GET_INSTALL_REFERRER_SERVICE` | Play-Services-AAR | Install-Referrer; keine Deklaration nötig |
| `RECORD_AUDIO`, `BLUETOOTH_CONNECT`, `MODIFY_AUDIO_SETTINGS` | `./plugins/withGlassVoice` (2026-08 hinzugekommen — unten war das noch "nicht enthalten", jetzt korrigiert) | Brillen-Mikro-Gespräch mit Henry (`GlassVoiceService.kt`) + Telefon-Mikro für den normalen Sprachmodus (`modules/livemic`) |
| ⚠ `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_MICROPHONE` | `./plugins/withGlassVoice`, `GlassVoiceService.kt` | **Braucht das Play-Console-Formular „Foreground service permissions" (Begründungstext + Demo-Video) — fertiger Text + Video-Shotlist: `surfaces/app/PLAY_STORE_RELEASE.md` §6.1.** Echtes, verdrahtetes Feature (`chat.tsx`-Toggle startet den Service); läuft als Foreground Service, weil das Gespräch weiterlaufen muss, während der Bildschirm aus ist und der Owner auf die Brille schaut. |
| ⚠ `SYSTEM_ALERT_WINDOW` | **nicht abschließend zugeordnet** — im JS-Baum nur in `react-native/ReactAndroid/src/debug/AndroidManifest.xml` deklariert, der Build ist aber nicht debuggable ⇒ vermutlich aus einem AAR | **Vor der Einreichung klären.** „Über anderen Apps anzeigen" ist für Nutzer sichtbar und zieht Rückfragen; die App nutzt keinerlei Overlay-API (`grep -ri overlay surfaces/app/src` → nichts) |

**Absichtlich NICHT im Build** (2026-09-01): `FOREGROUND_SERVICE_CONNECTED_DEVICE`
und `FOREGROUND_SERVICE_MEDIA_PLAYBACK`. MEDIA_PLAYBACK kam aus `expo-audio`s
Plugin-Default (`enableBackgroundPlayback: true`, jetzt in `app.json` explizit
`false` — die App hat keine Lockscreen-Mediensteuerung, die das gebraucht
hätte). CONNECTED_DEVICE gehört zur Brillen-KAMERA (`withMetaDat`/
`GlassCameraService`) — der Capture-Pfad hat noch keinen einzigen UI-Trigger
in `surfaces/app/src` (`glasses.ts:capture()`/`stopCamera()` wird nirgends
aufgerufen), also wäre die Play-Deklaration + das Pflicht-Video nicht ehrlich
zu erfüllen gewesen. Plugin bleibt im Repo, ist aber aus `app.json`s
`plugins`-Liste entfernt, bis die Kamera-Funktion einen echten Screen hat.

**Nicht enthalten** (im ausgelieferten Build geprüft): kein `READ_MEDIA_IMAGES`,
kein Standort, kein `QUERY_ALL_PACKAGES`.

`RECORD_AUDIO` von `expo-camera` selbst ist weiterhin deaktiviert
(`recordAudioAndroid` ist in dessen `plugin/build/withCamera.js` auf `true`
vorbelegt, deshalb `"recordAudioAndroid": false` in `app.json`) — `RECORD_AUDIO`
steht trotzdem im Build, aber jetzt korrekt zugeordnet zu `withGlassVoice`
(Tabelle oben), nicht mehr fälschlich als "nicht enthalten" geführt.
`expo-image-picker` ist nicht in `plugins` gelistet, sein Plugin läuft also
nicht; sein Library-Manifest deklariert `CAMERA` und
`READ/WRITE_EXTERNAL_STORAGE` mit `maxSdkVersion="32"` (unkritisch, kein
`READ_MEDIA_IMAGES`).

### Pflicht-Check vor der Einreichung

Das Store-Artefakt ist ein AAB aus einem anderen Build-Profil als der
Hub-APK oben — die Liste **muss am Release-Artefakt** gegengeprüft werden:

```
cd surfaces/app && npx expo prebuild -p android --no-install   # Wegwerf-Ausgabe, android/ NICHT committen
grep uses-permission android/app/src/main/AndroidManifest.xml
```

Taucht `SYSTEM_ALERT_WINDOW` (oder `RECORD_AUDIO`/`READ_MEDIA_IMAGES`) dort
auf, in `app.json` hart blocken — `android.blockedPermissions` setzt
`tools:node="remove"` und gewinnt gegen jedes Library-Manifest
(verifiziert in `@expo/config-plugins/build/android/Permissions.js:64`):

```json
"android": { "blockedPermissions": ["android.permission.SYSTEM_ALERT_WINDOW"] }
```

Nicht auf Verdacht blocken: stammt das Recht doch aus dem RN-Debug-Manifest,
nimmt ein globaler Block dem Dev-Build sein Overlay (LogBox/Dev-Menü).

## 4. Privacy-Policy-URL

`https://relay.helmdeck.de/privacy` (DE+EN, in `surfaces/relay/relay.py`
eingebettet, deployt via `ops/deploy/push_relay.sh`). In Play Console → App
content → Privacy policy eintragen. Inhalt deckt: Datenarten, E2EE-Relay,
FCM, Speicherung nur beim Nutzer, Löschung via Entkoppeln, Kontakt.
