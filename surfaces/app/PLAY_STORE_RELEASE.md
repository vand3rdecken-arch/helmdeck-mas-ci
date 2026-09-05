# HelmDeck — Android Play Store Release Checklist

Grounded in the actual repo state (Expo SDK 57 managed workflow, EAS builds,
self-hosted expo-updates OTA, FCM push, E2EE relay). Legend:

- ✅ already in place in this repo
- ⚠ action needed in the repo before submitting
- ☐ owner action in the Play Console / EAS dashboard (needs the Google account
  or EAS credentials — cannot be done from a worktree)

---

## 1. Signing / keystore

- ✅ Local keystores can never leak: `*.jks`, `*.p12`, `*.key`, `*.pem` are
  git-ignored (`app/.gitignore`). There is no `android/` dir — managed
  workflow, so signing is entirely EAS-side.
- ☐ Let **EAS manage the upload keystore** (default on first
  `eas build -p android`). Do NOT generate a local keystore; inspect any time
  with `eas credentials -p android`.
- ☐ Enroll in **Play App Signing** when creating the app in the Play Console
  (default for new apps). The EAS keystore becomes the *upload* key; Google
  holds the *app signing* key. Consequence: every cert fingerprint you publish
  (App Links below) must be the **app signing key** SHA-256 from
  Play Console → Setup → App integrity, not the upload key's.
- ☐ Back up: note the EAS project/account owning the credentials in the team
  vault. Losing EAS account access = losing the upload key (recoverable via
  Play App Signing key reset, but slow).

Build the store artifact (AAB — Play does not accept APKs for new apps):

```
cd surfaces/app && eas build -p android --profile production
```

The `production` profile in `eas.json` has no `buildType` override → defaults
to `app-bundle`. `production-apk` stays for hub/sideload distribution only.

## 2. versionCode / versionName scheme

- ✅ `eas.json` sets `appVersionSource: "remote"` and
  `production.autoIncrement: true` → **EAS owns versionCode** and bumps it
  per production build. The `"versionCode": 36` in `app.json` is a stale local
  value that remote mode ignores; treat EAS (`eas build:version:get`) as truth.
- ✅ versionName = `expo.version` (`app.json`, currently `1.0.0`). Scheme:
  bump **semver by hand** for feature releases; leave it alone for OTA-only
  JS updates.
- ✅ OTA coupling: `runtimeVersion.policy: "appVersion"` — changing
  `expo.version` creates a NEW runtime version. The self-hosted updates server
  (`https://141.144.227.105.sslip.io/updates/manifest`, channel `production`)
  must then receive a fresh publish for that runtime, or updated installs get
  no OTA until one exists. Rule of thumb:
  - JS-only change → publish OTA, do not touch `version`.
  - Native change (new plugin/permission/SDK upgrade) → bump `version`,
    new EAS build, new store release, then publish OTA against the new runtime.
- ☐ First Play submission: set the initial versionCode in EAS
  (`eas build:version:set`) higher than any versionCode ever uploaded to the
  Play account for `app.helmdeck` (fresh app → anything ≥ current is fine).

## 3. Privacy policy URL

- ✅ Privacy policy (DE+EN) is embedded in `surfaces/relay/relay.py` and served at
  **`https://141.144.227.105.sslip.io/privacy`** (alias `/datenschutz`).
  Embedded, not a file, because `ops/deploy/push_relay.sh` ships only `relay.py`.
  Goes live with the next `bash ops/deploy/push_relay.sh`.
- ⚠ The raw-IP `sslip.io` host works but looks disposable to reviewers; when
  a real domain exists, point it at the relay and re-enter the URL — the page
  itself needs no change.
- ☐ Enter the URL in Play Console → App content → Privacy policy.

## 4. Data Safety form (Play Console → App content)

➜ **Full derivation with per-answer code evidence: `ops/docs/store/DATA_SAFETY.md`**
(recommended form answers, permission table, E2EE-exemption discussion).
Summary of what the app actually does with data (verified in `surfaces/app/src`):

| Data | Where it goes | Declare as |
|---|---|---|
| Chat messages / card content | User's own daemon, direct HTTPS or NaCl-sealed via relay | Messages — collected, encrypted in transit, not shared with third parties, user-deletable (unpair) |
| Attachments: gallery photos, camera shots, files (explicit user pick only) | User's own daemon, same encrypted path (`attachments.ts`) | Photos + Files and docs — collected (optional), encrypted in transit, not shared |
| FCM device push token (`getDevicePushTokenAsync`) | User's own daemon (to send pushes); Google FCM infra | Device or other IDs — collected, encrypted in transit |
| Pairing config, keypairs, tokens | On-device only (`expo-secure-store`) | Not collected (never leaves device) |
| Analytics / ads / location / contacts | none — no such SDK in `package.json` | Not collected |

- ☐ Fill the form accordingly. "Shared" = No (data goes to infrastructure the
  user themself operates). "Data encrypted in transit" = Yes. "Users can
  request deletion" = Yes (unpairing; document it in the privacy policy).
- ☐ Google Play services / FCM itself is covered by Google's own disclosure;
  you still declare the push token as a device identifier you collect.
- Account deletion requirement: N/A — the app has no developer-hosted
  accounts (pairing codes against the user's own daemon). State that in the
  form's account section.

## 5. Store listing

- ☐ App name: **HelmDeck** (matches `expo.name`).
- ✅ Short description (≤80 chars) + full description (≤4000), DE+EN,
  copy-paste-ready: `ops/docs/store/LISTING.md`.
- ☐ Graphics:
  - App icon 512×512 PNG (export from `assets/images/icon.png` pipeline).
  - Feature graphic 1024×500 (still to build — spec in LISTING.md).
  - ✅ 4 phone screenshots 1080×2400: `ops/docs/store/screenshots/` (Board,
    card timeline, Needs-you, dashboard — shot on emulator against a demo
    daemon, no real client data). 7"/10" tablet shots optional but listed.
- ☐ Category: Productivity (or Tools). Tags: no ads, no in-app purchases.
- ☐ Content rating questionnaire: utility app; chat content is private
  self-to-own-server, so answer the UGC section as "no publicly visible UGC".
  Expect "Everyone" rating.
- ☐ Target audience: 18+ / not designed for children (avoids Families policy).
- ☐ Contact email + website in Store settings.
- ☐ Countries: pick; note store copy language (app UI contains German strings
  — either list German first or localize the listing DE+EN).
- ☐ New personal developer accounts (created after Nov 2023): production
  requires a **closed test with ≥12 testers for 14 days** first. Plan the
  internal→closed→production track promotion into the timeline.

## 6. Permission justifications

Managed workflow — the manifest is generated. **Updated 2026-09-01**: this used
to say "no sensitive/declaration-form permissions are used" — that's stale
since the glasses voice feature shipped. Expected merged permissions and why:

| Permission | Source | Justification |
|---|---|---|
| `INTERNET` | core | talk to daemon/relay |
| `CAMERA` | `expo-camera` plugin in app.json | QR pairing scan (`src/app/scan.tsx`) + attachment photos (`src/data/attachments.ts` `takePhoto`); runtime-prompted, never in background |
| `POST_NOTIFICATIONS` | `expo-notifications` | push for agent replies/review-ready; runtime-prompted in `src/data/push.ts` (`requestPermissionsAsync`) — only after pairing, good |
| `VIBRATE`, `WAKE_LOCK`, `RECEIVE_BOOT_COMPLETED`, `SCHEDULE_EXACT_ALARM` (maybe, from expo-notifications) | `expo-notifications` | notification delivery/rescheduling |
| `RECORD_AUDIO` | `expo-speech-recognition`'s AUTO-APPLIED config plugin (it is autolinked; it is NOT listed in `app.json`'s `plugins`) | the PHONE's own mic for the in-app voice mode (`modules/livemic`, `src/ui/voice_mode.tsx`) — runtime-prompted, foreground-only, no service. Needs NO declaration form and NO video (see the bullets below). |
| `MODIFY_AUDIO_SETTINGS` | `expo-audio` plugin (adds it unconditionally, no way to opt out) | normal (non-dangerous) permission — no runtime prompt, no form |
| ~~⚠ `FOREGROUND_SERVICE` + `FOREGROUND_SERVICE_MICROPHONE`~~ | ~~`./plugins/withGlassVoice`, `GlassVoiceService.kt`~~ | **GONE from the build since versionCode 91 (2026-09-05).** This was the ONLY row that required a Play Console declaration form + demo video, and it is why the release was blocked. `withGlassVoice` is now unregistered in `app.json`'s `plugins` AND skipped in `ops/deploy/build_aab.sh`, so neither the permissions nor the typed `<service>` are declared. Nothing was deleted — see `withGlassVoice.js`'s header for the re-introduction checklist. §6.1 below is KEPT for that future re-introduction, not because anything in the current build needs it. |

- ✅ CAMERA needs no Play declaration form (only location/SMS/etc. do); it
  must simply match the Data Safety answers — see `ops/docs/store/DATA_SAFETY.md`.
- ✅ `RECORD_AUDIO` is still disabled at BOTH plugins that would otherwise add
  it on our own say-so — `expo-camera` and `expo-audio` are each configured
  `"recordAudioAndroid": false` (app.json) and both were re-read on 2026-09-05
  to confirm they honour it. It is nevertheless in the build, from a THIRD
  source that takes no configuration: `expo-speech-recognition` is autolinked
  and its `app.plugin.js` applies itself, adding `RECORD_AUDIO`
  unconditionally. Don't "fix" the two app.json flags when you see it — they
  are already correct and are not the source.
- ✅ **`RECORD_AUDIO` alone needs no declaration form and no video.** Google's
  form + demo-video requirement applies to the *foreground-service types*
  (and to location/SMS/call-log/all-files), not to holding the mic permission
  for a foreground, user-initiated feature. That is the whole reason
  versionCode 91 unblocks the release while the phone voice mode keeps
  working: the FGS row above is gone, this row is ordinary. If you ever DO
  need it gone as well, the mechanism is `android.blockedPermissions` in
  app.json (same as SYSTEM_ALERT_WINDOW) — but that makes the permission
  ungrantable and therefore KILLS the in-app voice mode, so it is a product
  decision, not a compliance chore.
- ✅ **`FOREGROUND_SERVICE_CONNECTED_DEVICE` and `FOREGROUND_SERVICE_MEDIA_PLAYBACK`
  are deliberately NOT in this build** (2026-09-01). MEDIA_PLAYBACK was a
  default-on trap in `expo-audio`'s plugin (`enableBackgroundPlayback`
  defaults to `true`; nothing in the app uses lock-screen media controls) —
  fixed by setting it `false` in app.json. CONNECTED_DEVICE would have needed
  a declaration + video for the glasses CAMERA (`withMetaDat`/
  `GlassCameraService`), but that capture path has no UI trigger anywhere in
  `surfaces/app/src` yet — the plugin is written but deliberately unregistered
  in `app.json`'s `plugins` until it does (see `withMetaDat.js`'s header).
- ✅ **`SYSTEM_ALERT_WINDOW` is NOT in the versionCode 91 AAB** — measured
  2026-09-05 on the bundle's own merged manifest (see the recipe below). The
  `android.blockedPermissions` entry in app.json is doing its job. Full
  permission table: `ops/docs/store/DATA_SAFETY.md` §3.
- ✅ Verified absent from the shipped build: location, `READ_MEDIA_IMAGES`,
  QUERY_ALL_PACKAGES. Also measured absent in vc91: `SCHEDULE_EXACT_ALARM`,
  `USE_EXACT_ALARM`, and every `FOREGROUND_SERVICE*` permission — the build
  declares no foreground service of any type at all.
- ✅ **How to verify the artifact you are actually uploading** (do this, not a
  throwaway prebuild — a prebuild proves what the config *would* generate, not
  what the .aab in your hand *contains*). Gradle leaves the bundle's own
  merged manifest as plain XML:

  ```
  surfaces/app/android/app/build/intermediates/bundle_manifest/release/\
    processApplicationManifestReleaseForBundle/AndroidManifest.xml
  ```

  Grep that for `uses-permission` / `foregroundServiceType`. Note the trap
  that cost time on 2026-09-05: `aapt2 dump` REFUSES an `.aab`
  ("could not identify format of APK") — it only reads APKs — and the
  `base/manifest/AndroidManifest.xml` inside the .aab is protobuf, not XML,
  so a plain grep of it is unreliable. Use the path above, or run the .aab
  through `bundletool build-apks` first.

### 6.1 FOREGROUND_SERVICE_MICROPHONE — Play Console declaration form

> **NOT NEEDED FOR THE CURRENT BUILD (versionCode 91+).** The permission and
> the service are no longer declared, so Play will not ask for this and the
> video does not have to be recorded. Everything below is kept verbatim for
> the day `withGlassVoice` goes back into `app.json`'s `plugins` and
> `ops/deploy/build_aab.sh` — do not fill this in before then.

Play Console → App content → **Permissions** (or the in-review prompt asking
"what is this foreground service used for" + a video) — paste/adapt:

> HelmDeck lets the owner talk to their AI assistant ("Henry") hands-free
> through paired Meta Ray-Ban Display smart glasses. Tapping the glasses-voice
> control starts a foreground service that listens on the glasses' Bluetooth
> microphone, sends the recognized speech to the user's own backend, and
> speaks the reply back through the glasses. The service must run as a
> foreground service because the entire point of the feature is that it keeps
> listening while the phone screen is off and the owner is looking at the
> glasses display, not the phone — an ordinary background-restricted service
> would be killed the moment the phone is put away, which is exactly when this
> feature is used. A persistent notification ("Henry — Bereit/Hört zu…") is
> shown the whole time the service is active, and it stops the instant the
> user ends the conversation or the app is unpaired.

**Video to record** (owner action — needs the paired glasses + phone, cannot
be done from a worktree):
1. Show the phone's Settings → Apps → HelmDeck → Permissions screen with
   Microphone NOT yet granted (or fresh install), for a moment.
2. Open HelmDeck, pair/confirm the Meta glasses are connected.
3. Tap the glasses-voice control in the chat screen (`chat.tsx`) — show the
   RECORD_AUDIO system permission prompt appearing and being granted (skip if
   already granted from a prior run — then just show the toggle turning on).
4. Show the persistent "Henry" notification appear in the status bar / shade
   — this is the foreground-service indicator Google specifically wants to
   see present during use.
5. **Turn the phone screen off (or switch to another app)** and speak a short
   question — this is the crux of the justification, so it must be visibly
   demonstrated, not just claimed. Show Henry's spoken reply still arriving
   with the screen off/app backgrounded.
6. Turn the phone screen back on, tap the control again to stop — show the
   notification disappearing.
Keep it short (30–60s), no narration needed, screen-record the phone (the
glasses' own view doesn't need to be captured).

## 7. Target SDK & cleartext compliance

- ✅ Expo SDK 57 targets **API 36 (Android 16)** — satisfies Google's
  target-API requirement (≥35 for updates since Aug 2025; 36-ready).
- ✅ **Cleartext is scoped, not global** (was the gotcha here; debt
  `android-cleartext-lan` paid). `app/plugins/withLanCleartext.js` ships a
  `networkSecurityConfig` that blocks cleartext app-wide and allows it only
  for `10.0.2.2`/`localhost`/`127.0.0.1` plus the hosts listed in its
  `app.json` plugin entry (Android NSC has no RFC1918 ranges — explicit
  hosts only). Applied on `expo prebuild` AND re-applied to the hand-managed
  `surfaces/app/android` by `ops/deploy/build_apk.sh`. Consequence for the Play build:
  direct mode to an arbitrary `http://` LAN IP fails unless that IP is in
  the host list at build time — for store users the answer is the relay
  (HTTPS + E2EE), which needs nothing.
- ✅ OTA endpoint and relay are HTTPS (`sslip.io` wraps the IP with a valid
  cert) — no cleartext there.
- ⚠ **App Links verification.** `app.json` declares an `autoVerify: true`
  intent filter for `https://141.144.227.105.sslip.io/pair`. On Android 12+
  this ONLY works if the relay serves
  `https://141.144.227.105.sslip.io/.well-known/assetlinks.json` containing
  `app.helmdeck` + the **Play App Signing** SHA-256 fingerprint (Play Console
  → App integrity — available only after the app record exists). Until then,
  pair-links open the browser, not the app. Wire this into `surfaces/relay/` and
  re-check with
  `adb shell pm get-app-links app.helmdeck`.
- ✅ expo-updates OTA is Play-policy-compliant (JS bundle updates via an
  interpreter are the sanctioned exception in the Device & Network Abuse
  policy) as long as OTAs never change the app's core purpose.

## 8. Build-time secrets & submission

- ✅ `google-services.json` is git-ignored (FCM config).
- ⚠ EAS cloud builds therefore won't find it: upload it as an EAS **file
  environment variable** (dashboard → project → Environment variables, type
  "file", name it and reference via `GOOGLE_SERVICES_JSON`), or keep building
  where the file exists locally.
- ☐ For `eas submit -p android`: create a Google Cloud **service account**
  with Play Console "Release manager" access, download its JSON key, and
  either point `submit.production.serviceAccountKeyPath` at it (file stays
  git-ignored) or store it in EAS. `submit.production` in `eas.json` is
  currently empty.
- ☐ First upload must be **manual** (Play Console → create app → upload AAB
  to internal testing) — `eas submit` only works once the app record exists.

## 9. Release-day order of operations

➜ **Owner click-path for the internal-testing submission:
`ops/docs/store/INTERNAL_TESTING.md`** (uses the pieces below in order).

1. Fix the ⚠ items above (privacy policy, cleartext decision, assetlinks,
   EAS file env for `google-services.json`).
2. `eas build -p android --profile production` → AAB.
3. Create the Play app record; enroll Play App Signing; upload AAB to
   **internal testing**; fill App content (privacy policy, Data Safety,
   content rating, target audience, ads = No).
4. Publish `assetlinks.json` with the App Signing fingerprint; verify
   pair-links on a device.
5. Smoke on the internal build: pairing (relay + direct), chat, push
   notification arrives, OTA check-on-resume pulls an update.
6. Promote internal → closed (12 testers / 14 days if personal account) →
   production, staged rollout ≤20%.
7. After release: JS fixes via OTA publish to channel `production`; native
   changes = bump `version`, new build, repeat from step 2.
