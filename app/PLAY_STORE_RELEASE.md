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
cd app && eas build -p android --profile production
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

- ✅ Privacy policy (DE+EN) is embedded in `relay/relay.py` and served at
  **`https://141.144.227.105.sslip.io/privacy`** (alias `/datenschutz`).
  Embedded, not a file, because `deploy/push_relay.sh` ships only `relay.py`.
  Goes live with the next `bash deploy/push_relay.sh`.
- ⚠ The raw-IP `sslip.io` host works but looks disposable to reviewers; when
  a real domain exists, point it at the relay and re-enter the URL — the page
  itself needs no change.
- ☐ Enter the URL in Play Console → App content → Privacy policy.

## 4. Data Safety form (Play Console → App content)

➜ **Full derivation with per-answer code evidence: `docs/store/DATA_SAFETY.md`**
(recommended form answers, permission table, E2EE-exemption discussion).
Summary of what the app actually does with data (verified in `app/src`):

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
  copy-paste-ready: `docs/store/LISTING.md`.
- ☐ Graphics:
  - App icon 512×512 PNG (export from `assets/images/icon.png` pipeline).
  - Feature graphic 1024×500 (still to build — spec in LISTING.md).
  - ✅ 4 phone screenshots 1080×2400: `docs/store/screenshots/` (Board,
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

Managed workflow — the manifest is generated. Expected merged permissions and
why (no sensitive/declaration-form permissions are used):

| Permission | Source | Justification |
|---|---|---|
| `INTERNET` | core | talk to daemon/relay |
| `CAMERA` | `expo-camera` plugin in app.json | QR pairing scan (`src/app/scan.tsx`) + attachment photos (`src/data/attachments.ts` `takePhoto`); runtime-prompted, never in background |
| `POST_NOTIFICATIONS` | `expo-notifications` | push for agent replies/review-ready; runtime-prompted in `src/data/push.ts` (`requestPermissionsAsync`) — only after pairing, good |
| `VIBRATE`, `WAKE_LOCK`, `RECEIVE_BOOT_COMPLETED`, `SCHEDULE_EXACT_ALARM` (maybe, from expo-notifications) | `expo-notifications` | notification delivery/rescheduling |

- ✅ CAMERA needs no Play declaration form (only location/SMS/etc. do); it
  must simply match the Data Safety answers — see `docs/store/DATA_SAFETY.md`.
- ✅ `RECORD_AUDIO` from expo-camera is disabled via
  `"recordAudioAndroid": false` (app.json) — its plugin defaults that to
  `true`, so this was actively being merged in. Verified absent from the
  shipped build.
- ⚠ **`SYSTEM_ALERT_WINDOW` is in the currently shipped build** (verified via
  `adb shell dumpsys package app.helmdeck`) and nothing in `app/src` uses an
  overlay. Confirm it is absent from the release AAB before submitting; if
  present, block it via `android.blockedPermissions`. Full verified permission
  table + the check: `docs/store/DATA_SAFETY.md` §3.
- ✅ Verified absent from the shipped build: mic, location,
  `READ_MEDIA_IMAGES`, QUERY_ALL_PACKAGES.
- ⚠ Verify the final merged manifest before submitting:
  `cd app && npx expo prebuild -p android --no-install` (throwaway; don't
  commit `android/`) and read
  `android/app/src/main/AndroidManifest.xml`. If `SCHEDULE_EXACT_ALARM` /
  `USE_EXACT_ALARM` appears and nothing schedules exact alarms, strip it via
  `expo-build-properties` — Google asks for justification on those.

## 7. Target SDK & cleartext compliance

- ✅ Expo SDK 57 targets **API 36 (Android 16)** — satisfies Google's
  target-API requirement (≥35 for updates since Aug 2025; 36-ready).
- ✅ **Cleartext is scoped, not global** (was the gotcha here; debt
  `android-cleartext-lan` paid). `app/plugins/withLanCleartext.js` ships a
  `networkSecurityConfig` that blocks cleartext app-wide and allows it only
  for `10.0.2.2`/`localhost`/`127.0.0.1` plus the hosts listed in its
  `app.json` plugin entry (Android NSC has no RFC1918 ranges — explicit
  hosts only). Applied on `expo prebuild` AND re-applied to the hand-managed
  `app/android` by `deploy/build_apk.sh`. Consequence for the Play build:
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
  pair-links open the browser, not the app. Wire this into `relay/` and
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
`docs/store/INTERNAL_TESTING.md`** (uses the pieces below in order).

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
