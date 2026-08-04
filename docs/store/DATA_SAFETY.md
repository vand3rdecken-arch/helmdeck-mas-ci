# HelmDeck — Data-Safety-Formular (Play Console → App content → Data safety)

Abgeleitet aus dem **tatsächlichen Transportverhalten** im Code, nicht aus
Absichten. Jede Antwort unten trägt ihren Beleg (Datei:Zeile, Stand dieses
Commits). Wenn sich der Transport ändert, dieses Dokument im selben Commit
nachziehen — das Formular muss der Prüfung standhalten (M4).

## 1. Transport-Inventar (was das Gerät tatsächlich verlässt)

| # | Daten | Weg | Beleg |
|---|---|---|---|
| T1 | Karten/Chat/Steuerkommandos (Request-Bodies) | **Relay-Modus:** NaCl-versiegelt (Curve25519/XSalsa20-Poly1305) als opaker Chiffretext an das Relay, nur der eigene Daemon kann öffnen | `app/src/data/client.ts:34-60` (relayReq: seal→POST /relay), `app/src/data/e2ee.ts`, `relay/relay.py` (Docstring: zero-knowledge, nichts persistiert) |
| T2 | dieselben Daten | **Direkt-Modus:** HTTP(S) mit Bearer-Token an die vom Nutzer eingetragene eigene Daemon-URL | `app/src/data/client.ts:62-95` (req: fetch baseUrl), `app/src/data/config.ts:32-35` |
| T3 | Anhänge: Galerie-Fotos, Kamera-Aufnahmen, beliebige Dateien (base64, nur nach expliziter Auswahl) | wie T1/T2 an den eigenen Daemon (`POST /tracks/<id>/attach`) | `app/src/data/attachments.ts` (pickImages/takePhoto/pickFiles), `app/src/data/client.ts:191-194` |
| T4 | FCM-Geräte-Push-Token | an den eigenen Daemon (`POST /push/register`); Zustellung der Pushes läuft über Google FCM, Payload ist E2EE-Chiffretext | `app/src/data/push.ts:18-31` (getDevicePushTokenAsync→api.post), `app/src/data/push.ts:36-40` (decryptPush), `daemon/notify.py` (seal) |
| T5 | OTA-Update-Abfrage (Runtime-Version, Kanalname — keine Nutzerdaten) | GET an den eigenen Update-Server (Relay-VM) | `app/app.json` updates.url, `relay/relay.py` /updates/manifest |
| — | Kopplungsdaten (relayUrl, room, Schlüsselpaar, daemonPub, Token) | **verlassen das Gerät nicht**; verschlüsselter Gerätespeicher | `app/src/data/config.ts:39-45` (expo-secure-store) |
| — | Kamera beim QR-Scan | Bild wird nur lokal dekodiert, nie übertragen | `app/src/app/scan.tsx` (CameraView onBarcodeScanned) |

**Nicht vorhanden** (geprüft `app/package.json`): keine Analytics-, Werbe-,
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

Managed Workflow — Manifest wird generiert. Erwartete sensible Einträge:

| Permission | Quelle | Rechtfertigung |
|---|---|---|
| `INTERNET` | Core | eigener Daemon/Relay |
| `CAMERA` | `expo-camera` (app.json-Plugin) | QR-Kopplung (`scan.tsx`), Anhang-Fotos (`attachments.ts:takePhoto`) |
| `POST_NOTIFICATIONS` | `expo-notifications` | Push nach Runtime-Prompt (`push.ts`) |
| `VIBRATE`, `WAKE_LOCK`, `RECEIVE_BOOT_COMPLETED` | `expo-notifications` | Zustellung |

`RECORD_AUDIO` ist per `"recordAudioAndroid": false` im expo-camera-Plugin
abgeschaltet (die App nimmt nie Audio auf). Vor dem Store-Build das gemergte
Manifest prüfen (`npx expo prebuild -p android --no-install`, wegwerfen):
falls `READ_MEDIA_IMAGES`/`READ_EXTERNAL_STORAGE` auftaucht, via
expo-build-properties strippen — der Bild-Picker nutzt den System-Photo-Picker,
und `READ_MEDIA_IMAGES` löst seit 2024 eine eigene Play-Deklaration aus.

## 4. Privacy-Policy-URL

`https://141.144.227.105.sslip.io/privacy` (DE+EN, in `relay/relay.py`
eingebettet, deployt via `deploy/push_relay.sh`). In Play Console → App
content → Privacy policy eintragen. Inhalt deckt: Datenarten, E2EE-Relay,
FCM, Speicherung nur beim Nutzer, Löschung via Entkoppeln, Kontakt.
