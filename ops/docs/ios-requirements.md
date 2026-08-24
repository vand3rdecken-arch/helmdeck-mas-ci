# iOS-Anforderungen — fixierte Checkliste

**Stand:** 2026-08-14. Abgeleitet aus der Machbarkeitsstudie
`ops/docs/ios-watch-feasibility.md` (Commit `ed1c25d`) und **gegen den aktuellen
Baum verifiziert** (`app/app.json` v1.0.3, `surfaces/app/package.json`,
`surfaces/app/src/data/push.ts`, `surfaces/app/src/data/attachments.ts`, `app/eas.json`).
Dieses Dokument ist die verbindliche Anforderungsliste; die Studie bleibt die
Begründung. Abweichungen vom Studienstand `b3f756e` sind markiert **[NEU]**.

---

## 1. Identität, Konten, Build-Grundlagen

| Punkt | Wert / Entscheidung | Status |
|---|---|---|
| Bundle-Identifier | **`app.helmdeck`** — steht bereits in `app.json → ios.bundleIdentifier`, identisch zum Android-Package. **Fixiert, nicht mehr ändern** (Bundle-ID ist nach dem ersten App-Store-Connect-Anlegen unumkehrbar). | ✅ vorhanden |
| iOS-Icon | `app.json → ios.icon: ./assets/expo.icon` (Icon Composer, Glass-H) | ✅ vorhanden |
| Deep-Link-Scheme | `helmdeck` (QR-/Code-Pairing über `Linking.useURL()`) | ✅ vorhanden |
| Apple Developer Program | **Pflicht**, 99 €/Jahr. Deckt iOS-Provisioning **und** Mac-Notarization (Studie §5.3) mit ab. | ⬜ Konto anlegen |
| EAS-Projekt | `eas.json` existiert bereits (Android-Profile; `production`-Profil ist plattformneutral nutzbar). **Fehlt:** `extra.eas.projectId` in `app.json` — kommt beim ersten `eas init`; wird auch für Expo-Push (§3) gebraucht. | ⬜ `eas init` |
| Build-Weg | **EAS Build (Cloud), managed prebuild** — es gibt kein `ios/`-Verzeichnis und es wird **keines eingecheckt**. Entscheidung fixiert (Studie §2.1). | fixiert |
| Distribution | **TestFlight, internes Testing** (ohne Review, bis 100 Tester). Kein App-Store-Release im Scope. | fixiert |

## 2. Native Module — Inventar-Urteil (verifiziert)

**~90 % läuft unverändert.** Vollständige Modultabelle in Studie §1.1–1.2;
hier nur, was **Handlung erfordert** oder sich seit der Studie geändert hat:

| Modul / Konfig | Handlung für iOS |
|---|---|
| `./plugins/withLanCleartext` (Android NSC) | **Ersatz nötig:** ATS-Keys via `app.json → ios.infoPlist`: `NSAppTransportSecurity.NSAllowsLocalNetworking = true` + `NSLocalNetworkUsageDescription` (deutscher Text). Betrifft **nur** den Direct-LAN-Modus; Relay/HTTPS ist ATS-konform und braucht nichts. Kein eigenes Plugin nötig. |
| `expo-notifications` | Client läuft; **Sender ist die Baustelle** → §3. |
| `android.googleServicesFile` (FCM) | iOS-Pendant **entfällt ersatzlos** (kein Firebase-SDK auf iOS — Entscheidung fixiert, Studie §1.3 Option 3 verworfen). |
| `android.intentFilters` (`https://…/pair`) | iOS-Pendant = Universal Links (`ios.associatedDomains` + AASA-Datei auf dem Relay, ~20 Zeilen `surfaces/relay/relay.py`). **Optional / verschoben** — QR-Scan + Code-Eingabe decken Pairing ab. |
| `react-native-sse` | ungenutzt (kein Import in `surfaces/app/src`, verifiziert) — Aufräum-Kandidat, **kein** iOS-Blocker. |
| **[NEU]** `posthog-react-native` (seit der Studie dazugekommen) | Pures JS + async-storage, **läuft unverändert**. Kein IDFA/Tracking → **kein ATT-Prompt nötig**. Merkposten: App-Privacy-Angaben in App Store Connect erst bei externem TestFlight/Store-Release fällig; für internes Testing ohne Review irrelevant. Opt-out existiert in der App (More → Datenschutz). |
| `expo-symbols`, `expo-glass-effect`, `@expo/ui` | installiert, derzeit ungenutzt — auf iOS erstmals wirksam. Keine Handlung, nur Hinweis. |

Alle übrigen Module (Expo-SDK-Standard, RN-Stack, tweetnacl-E2EE,
`react-native-get-random-values`, async-storage): **unverändert lauffähig** —
in der Studie einzeln geprüft.

## 3. Push — fixierte Entscheidung

**Sender = Expo Push Service** (Studie §1.3, Option 1 — Entscheidung fixiert):

- [ ] `surfaces/app/src/data/push.ts`: auf iOS `getExpoPushTokenAsync({ projectId })`
      statt des rohen Device-Tokens (`push.ts:28` ist heute Android-FCM-roh).
- [ ] `daemon/notify.py`: Sender-Pfad an `https://exp.host/--/api/v2/push`
      (stdlib-`urllib` wie bisher, kein neues Paket). Payload bleibt der
      **NaCl-versiegelte `cipher`** — Zero-Knowledge unverändert.
- [ ] Notification-Categories mit Action-Buttons + Text-Input („Diktieren…")
      via `setNotificationCategoryAsync` → das ist zugleich der **komplette
      Watch-Phase-W1-Scope** (Mirroring, Studie §3.1). Kein Swift, keine
      Watch-App.
- [ ] Push-Entitlement (`aps-environment`) verwaltet EAS automatisch.
- Verworfen (fixiert): APNs-direkt (HTTP/2-Abhängigkeit im Daemon),
  FCM-via-Firebase-SDK (natives Modul ohne Gewinn).
- Bekannte, akzeptierte v1-Grenze: **kein Klartext auf dem Lockscreen**
  (kein Headless-JS auf iOS) — generischer Titel, Entschlüsselung beim
  Antippen. Notification Service Extension = bewusst Phase 2.

## 4. Berechtigungen — konkrete Info.plist-Liste

Nutzung im Code verifiziert (`scan.tsx` QR-Scan, `attachments.ts`
Kamera/Galerie/Dateien):

| Key | Quelle | Aktion |
|---|---|---|
| `NSCameraUsageDescription` | `expo-camera`-Plugin — deutscher Text steht schon in `app.json` | ✅ nichts zu tun |
| `NSPhotoLibraryUsageDescription` | `expo-image-picker` (`launchImageLibraryAsync` in `attachments.ts:91`) | ⬜ deutschen Text als Plugin-Prop (`photosPermission`) setzen |
| Kamera-Text für `expo-image-picker` (`launchCameraAsync`, `attachments.ts:105`) | Plugin-Prop `cameraPermission` | ⬜ deutschen Text setzen (sonst englischer Default) |
| `NSMicrophoneUsageDescription` | **nicht benötigt** (nur Fotos, kein Video; `recordAudioAndroid: false` analog) | ⬜ per Plugin-Props (`microphonePermission: false`) entfernen |
| `NSLocalNetworkUsageDescription` | Direct-LAN-Modus (iOS-14-Prompt) | ⬜ deutschen Text in `ios.infoPlist` |
| `NSAppTransportSecurity → NSAllowsLocalNetworking` | Direct-LAN-HTTP (Ersatz für withLanCleartext) | ⬜ in `ios.infoPlist` |
| `aps-environment` (Entitlement) | Push | ⬜ automatisch via EAS |
| `NSFaceIDUsageDescription` | nicht benötigt (SecureStore ohne Biometrie-Gate) | — |
| `ios.associatedDomains` (Entitlement) | Universal Links | optional, verschoben (§2) |

Kein Standort, kein Bluetooth, keine Kontakte, kein HealthKit — nichts
weiteres zu deklarieren.

## 5. OTA / Deploy — fixierte Entscheidungen

- [x] **Per-Plattform-`runtimeVersion`** (`ios.runtimeVersion` getrennt) —
      Studie §2.3, Option (b) **fixiert**, umgesetzt vor dem ersten iOS-Build:
      `app.json → ios.runtimeVersion` ist jetzt ein fester String (`"1.0.5"`),
      unabhängig vom geteilten `expo.version`, den `ship.sh` bei jedem
      Android-Native-Bump weiterschiebt. Android bleibt exakt wie zuvor
      (Top-Level-Policy `appVersion`) — am laufenden Kanal auf dem Phone ändert
      sich nichts. Ein künftiger iOS-Native-Change muss diesen String von Hand
      bumpen (kleine `ship.sh`-Logik dafür ist noch offen, siehe unten).
- [ ] `ops/deploy/push_update.sh`: Export `--platform all` statt `android`;
      Verify-curl zusätzlich mit `expo-platform: ios`. Relay-Server
      (`surfaces/relay/relay.py`) ist bereits plattformfähig — keine Server-Änderung.
- [ ] `ship.sh`: Fingerprint-/Bump-Logik lernt die Plattform-Trennung
      (iOS-Bump nur bei iOS-relevanten Änderungen). Achtung Memory-Falle:
      `native_fp` läuft über git-bash, muss die `package.json`-Zeile enthalten.
- [ ] Neues kleines Skript `ops/deploy/push_testflight.sh` (`eas build` +
      `eas submit`) — **kein** iOS-Pendant zu `/apk/helmdeck.apk` (Ad-hoc-IPA
      = Sackgasse, fixiert).
- `build_apk.sh` und die ganze Windows-Native-Trap-Sektion bleiben
  Android-only — EAS baut iOS in der Cloud.

## 6. Offene Risiken (Register)

| # | Risiko | Einordnung / Gegenmaßnahme |
|---|---|---|
| R1 | **TestFlight-Builds verfallen nach 90 Tagen** | Wartungssteuer: ≥ 1 nativer Build+Upload pro Quartal, auch ohne Code-Änderung. Einpreisen, ggf. Kalender-/Cron-Erinnerung. |
| R2 | **Kein iOS-Simulator auf Windows** | Verify = echtes iPhone via TestFlight (Minuten- statt Sekunden-Latenz). Der `adb screencap`-Reflex hat kein Gegenstück — iOS-QA bleibt Handarbeit am Gerät. |
| R3 | **Action-Handling aus dem Killed-State** (Push-Buttons/Diktat) | Bekannte Expo-Schwachstelle; am echten Gerät verifizieren. Akzeptierter Fallback: App öffnet sich kurz. |
| R4 | **Kein Klartext auf dem Lockscreen** (kein Headless-JS) | v1: generischer Titel + Entschlüsselung beim Tippen (existiert in `_layout.tsx`). NSE = Phase 2 (2–3 T), erst nach W1-Alltagserfahrung. |
| R5 | **runtimeVersion-Kopplung** bis §5 umgesetzt ist | Per-Plattform-rtv **vor** dem ersten iOS-Build umsetzen, sonst verliert das iPhone OTAs beim nächsten Android-Native-Bump. |
| R6 | **Long-Poll im Hintergrund**: iOS suspendiert die App; `boardWait`/`transcriptLive` laufen nur im Vordergrund | Erwartetes Verhalten (auf Android ähnlich); Aktualität im Hintergrund kommt über Push. In der Geräte-QA explizit prüfen (Studie §4.1 Schritt 5). |
| R7 | **EAS Free-Tier** (~30 Builds/Monat, langsamere Queue) | Reicht absehbar (native Builds sind selten); bei Engpass ab ~19 $/Monat. |
| R8 | **[NEU]** PostHog: App-Privacy-Angaben („Data Safety" Apple-Pendant) | Erst bei externem TestFlight/Store fällig; für internes Testing nicht. Bei Scope-Wechsel: Privacy-Nutrition-Labels ausfüllen (Events, kein Tracking/IDFA). |
| R9 | Credentials-Gefummel beim EAS-Erstsetup (Zertifikate, ASC-API-Key) | In Studie §4.1 Schritt 1 mit 1–2 T ehrlich eingepreist; einmalig. |

## 7. Explizit außerhalb des Scopes (fixiert)

- **Watch-Phase W2** (native SwiftUI-App): erst wenn W1 (Mirroring + Actions)
  im Alltag nachweislich nicht reicht — Beweislast beim Bedarf (Studie §3.3).
- **Vollboard auf der Watch**: falscher Formfaktor, dauerhaft aus dem Scope.
- **FCM via Firebase-iOS-SDK**, **Ad-hoc-IPA-Verteilung**, **App-Store-Release**.
- **App-Builder/Flutter-Rewrite**: verifiziert verworfen (Studie §6, Stand 08/2026).

## 8. Umsetzungsreihenfolge (aus der Studie übernommen, fixiert)

1. Apple-Konto + `eas init` + erster TestFlight-Build (§1) — *vorher §5
   per-Plattform-rtv umsetzen (R5)*.
2. ATS/Permissions (§2, §4) + Pairing-Smoke auf dem iPhone.
3. OTA dual-platform (§5).
4. Push-Umbau + Categories = Watch W1 (§3).
5. Geräte-QA (Pairing, Hintergrund, Killed-State-Actions, OTA-Zyklus).

**Summe Basispaket inkl. Watch W1: ≈ 6–9 Personentage** + 99 €/Jahr +
Quartals-Build (R1). Mac-Desktop (Electron, Studie §5) bei Schritt 1 direkt
danebenlegen (~1–2 T Zusatz) — gleiches Konto, gleiche Signing-Grundlage.
