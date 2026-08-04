# HelmDeck — deploy & dev runbook

How to ship a change to the phone/desktop, and the traps that cost us hours.
An agent on a deploy/fast-track card should follow THIS, not guess.

## First decision: OTA or native rebuild?

- **JS / React / assets only** (a screen, logic, styling, a new expo-router
  route) → **OTA**. Seconds, no rebuild.
- **Native** (a new native module like `expo-camera`, an Android permission, an
  `app.json` plugin, a `runtimeVersion` bump) → **APK rebuild**. ~10 min. You
  CANNOT ship native code over OTA.

---

## 1) OTA update (JS-only) — the fast path

```bash
bash deploy/push_update.sh
```

Runs `expo export --platform android` and uploads the JS bundle to the relay's
`/updates` channel (runtimeVersion `1.0.0`). The phone applies it over the next
**two** launches (1st downloads, 2nd applies). Verify on the phone: **More tab
footer** shows the new `OTA <id>`.

### ⚠ CRITICAL: after a native APK, push a matching OTA
The **relay is the source of truth**: on launch the app pulls the relay's bundle
for its runtimeVersion **even if that bundle is older**, and it overwrites the
APK's embedded JS. So if you build a native APK with new JS but forget to push a
matching OTA, the old relay bundle reverts the JS on next launch — the native
module stays, but its UI vanishes ("OTA works but the update is gone"). Always
`push_update.sh` right after a native release.

### runtimeVersion bump on native change (automated in ship.sh)
`runtimeVersion` policy is `appVersion`, so the runtimeVersion == `expo.version`.
`deploy/ship.sh` now **bumps `version` + `android.versionCode` on every native
change** before building the APK. Effect: an OLD APK (old version) *rejects* the
new JS (rtv mismatch) instead of loading it and crashing on a native module it
doesn't ship — the `Cannot find native module 'ExpoDocumentPicker'` crash-loop.
JS-only ships keep the version, so phones still receive those OTAs. Belt-and-
suspenders: `app/src/app/_layout.tsx` `ErrorBoundary` turns any such missing-
native-module error into a clear "App-Update nötig" screen instead of a crash.
Recovery if a bad bundle already shipped: `deploy/rollback_update.sh --embedded`
(reverts every phone to its APK's own bundle), then distribute the matching APK.

---

## 2) Native APK build

Prereqs (once per machine):
- **JDK 17** — RN 0.86 / Expo 57 need it; Java 8 fails. `winget install Microsoft.OpenJDK.17`
- Android SDK + NDK 27 (already installed here).
- `app/android/local.properties` must use **forward slashes**:
  `sdk.dir=C:/Users/.../AppData/Local/Android/Sdk`. Backslashes are eaten by the
  Java properties parser → build dies with "The filename, directory name, or
  volume label syntax is incorrect".

Build (release = signed + JS bundled = standalone APK):
```bash
cd app/android
export JAVA_HOME="/c/Program Files/Microsoft/jdk-17.0.20.8-hotspot"
export ANDROID_HOME="$HOME/AppData/Local/Android/Sdk"
export PATH="/c/Program Files/nodejs:$JAVA_HOME/bin:$PATH"
./gradlew assembleRelease -x lint --console=plain
# -> app/build/outputs/apk/release/app-release.apk  (~140MB, signed w/ archive/apk/swarmdeck-release.jks)
```

Native config note: `app/android/` is **git-ignored / hand-managed**. A native
permission (e.g. CAMERA) must go in BOTH `app/app.json` `plugins` (so a future
`expo prebuild` reproduces it) AND the hand-managed
`app/android/app/src/main/AndroidManifest.xml` (what THIS build uses).

Cleartext / direct-LAN: cleartext HTTP is **scoped, not global** — a
network-security-config allows it only for `10.0.2.2`/loopback plus the hosts
in the `./plugins/withLanCleartext` entry in `app.json` (Android can't express
IP ranges). `deploy/build_apk.sh` re-applies it to the hand-managed
`app/android` before every gradle build (`node app/plugins/withLanCleartext.js
app/android`), and the same file is the expo config plugin for a future
prebuild. Direct-LAN from a real phone ⇒ add the PC's IP to that host list and
rebuild the APK; relay/HTTPS need nothing.

---

## 3) Get the APK onto the phone

- **Relay** (served at `https://<relay>/apk/helmdeck.apk`):
  `bash deploy/push_relay.sh` (also ships relay.py + restarts the service), or
  minimal file-only (no restart): scp the apk to the VM and
  `sudo install -m644 helmdeck.apk /opt/helmdeck-apk/helmdeck.apk`.
- **Google Drive**: copy to `G:\My Drive\HelmDeck.apk` (Drive-for-Desktop syncs).

Signature: our APK is signed with `swarmdeck-release.jks`. If that differs from
the currently-installed app, Android says "app not installed" → **uninstall the
old app first** (you re-pair anyway; the relay/pairing keys may have rotated).

---

## 4) Emulator test — verify before shipping (TEST = judged, not assumed)

```bash
adb install -r app-release.apk          # uninstall old first if the signature differs
adb exec-out screencap -p > shot.png    # NOT `adb shell screencap /sdcard/x.png` — Git Bash mangles the /sdcard path
adb shell pm grant app.helmdeck android.permission.CAMERA   # grant a runtime perm directly
adb shell input tap X Y                 # coordinates are ACTUAL device px (1080x2400)
```
The emulator gets ANR-heavy ("Pixel Launcher isn't responding") while the dev
daemon is hammering the CPU — dismiss with the "Wait" button and retry.

---

## 5) Pairing / relay (how the phone reaches the desktop)

- The "desktop" IS your PC's daemon (`swarm.py serve 8140`), fronted by the
  Electron app (`desktop/main.js` — runs the daemon + UI + injects an owner
  token via `#cfg`). Don't run a second supervisor against :8140.
- Phone → zero-knowledge relay (NaCl-sealed frames) → daemon. **"Desktop nicht
  erreichbar" = relay HTTP 503 = the daemon isn't polling the relay** (i.e. the
  daemon/desktop isn't running). Not a pairing problem.
- **Multi-device**: up to 8 devices (`relay.phone_pubs` allowlist); pairing is an
  explicit 15-min single-use window (Settings → Mobile app → "Telefon koppeln" →
  QR / link / code). `unpair` rotates room + keypair (kill switch → every device
  must re-pair).
- Pair from the app: **More → "QR-Code scannen"**, or paste the code, or tap the
  link. The desktop web UI needs a token too; the Electron app injects it, or in
  a browser open `http://localhost:8140/#cfg=<base64{baseUrl,token}>`.
- Gotcha we hit: after pairing, queries that ran BEFORE pairing don't auto-refetch
  → "paired but empty board". The app now invalidates all queries on a successful
  pair; on an old build, just restart the app.

---

## Fast-track policy (make agent cards flow without babysitting)
The gate is fixed (always runs — your safety net), but the human steps are policy:
- `policy.auto_accept_green: true` → green-gated cards auto-accept + merge.
- `policy.auto_dispatch_priority: "high"` → high-prio backlog self-dispatches.
- a deploy hook that runs `deploy/push_update.sh` on accept → auto-OTA on merge.
With all three: file a card → agent works → gate green → auto-merge → auto-deploy,
same as a hand deploy, gate still guarding.

## Fast-track deploy (deploy/ship.sh)
The repo `deploy` hook runs `deploy/ship.sh`: it fingerprints the native-affecting
files and ships JS-only changes via OTA, or on a native change **bumps the
version/runtimeVersion** (so old APKs can't pull incompatible JS), builds the APK
(deploy/build_apk.sh: JDK17 + gradle + emulator smoke + relay distribute) AND
pushes a matching OTA, then commits the version bump. So a fast-track card just
works whether the change is JS or native, and a native change never crash-loops
an un-updated phone.
