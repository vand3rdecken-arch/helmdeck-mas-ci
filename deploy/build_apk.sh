#!/usr/bin/env bash
# Build the signed release APK (native, bundles JS -> standalone), do a
# best-effort emulator smoke, and distribute to the relay. Used by the fast-track
# (deploy/ship.sh) when a NATIVE change landed - OTA can't ship native code.
set -o pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"

# JDK 17 - RN 0.86 / Expo 57 need it (Java 8 fails). Microsoft OpenJDK install.
JAVA_HOME="$(ls -d '/c/Program Files/Microsoft/jdk-17'* 2>/dev/null | head -1)"
[ -z "$JAVA_HOME" ] && { echo "[build_apk] JDK 17 missing - winget install Microsoft.OpenJDK.17"; exit 1; }
export JAVA_HOME
export ANDROID_HOME="${ANDROID_HOME:-$HOME/AppData/Local/Android/Sdk}"
export PATH="/c/Program Files/nodejs:$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$PATH"

# Nothing else in the ship pipeline runs `npm install` for app/ - a merge that
# adds/bumps a dependency (exactly what routes here via native_fp) leaves the
# main repo's node_modules stale, so Metro/gradle autolinking can't resolve
# the new package ("Unable to resolve module ..."). `npm ci` is only in the
# NATIVE path (~10 min build anyway) so the plain JS-only OTA fast path stays
# seconds, unaffected.
echo "HOOK-NOTE: npm ci (node_modules sync with the just-merged lockfile, can take a few min)"
echo "[build_apk] npm ci (sync node_modules with the just-merged lockfile)"
( cd app && npm ci ) || { echo "[build_apk] npm ci FAILED"; exit 1; }

# local.properties MUST use forward slashes - the Java properties parser eats
# backslashes ("filename syntax incorrect" in the NDK locator).
printf 'sdk.dir=%s\n' "$(cygpath -m "$ANDROID_HOME" 2>/dev/null || echo "$ANDROID_HOME")" \
  > app/android/local.properties

# app/android is git-ignored/hand-managed, so re-apply the source-of-truth
# native config before every build: scope cleartext to the direct-LAN hosts
# from app.json (pays debt [android-cleartext-lan]; same plugin runs on a
# future `expo prebuild`, so the two paths cannot drift).
node app/plugins/withLanCleartext.js app/android \
  || { echo "[build_apk] network-security-config apply FAILED"; exit 1; }

# Same rule, same reason: the glasses-voice permissions + the typed foreground
# service. Without this line the APK builds perfectly clean and the microphone
# is simply never grantable at runtime - a silent, on-device-only failure, which
# is the exact class the line above exists to prevent.
node app/plugins/withGlassVoice.js app/android \
  || { echo "[build_apk] glass-voice manifest apply FAILED"; exit 1; }

# Sync the hand-managed native version from app.json BEFORE building. The bump
# automation (ship.sh) only touches app.json version + versionCode, but the
# git-ignored app/android is hand-managed and does NOT regenerate: build.gradle's
# versionName and the AndroidManifest's EXPO_RUNTIME_VERSION were silently left on
# the old value, so a "1.0.3" bump produced an APK whose runtimeVersion was still
# 1.0.2 - it matched neither the old nor the new OTA target. Write all three from
# app.json so the APK, its runtimeVersion, and the OTA target can never drift.
node -e '
  const fs = require("fs");
  const e = JSON.parse(fs.readFileSync("app/app.json", "utf8")).expo;
  const ver = e.version, vc = String(e.android.versionCode);
  const g = "app/android/app/build.gradle";
  fs.writeFileSync(g, fs.readFileSync(g, "utf8")
    .replace(/versionCode\s+\d+/, "versionCode " + vc)
    .replace(/versionName\s+"[^"]*"/, "versionName \"" + ver + "\""));
  const m = "app/android/app/src/main/AndroidManifest.xml";
  fs.writeFileSync(m, fs.readFileSync(m, "utf8")
    .replace(/(EXPO_RUNTIME_VERSION"\s+android:value=")[^"]*(")/, "$1" + ver + "$2"));
  console.log("[build_apk] native version synced from app.json -> " + ver + " / " + vc);
' || { echo "[build_apk] native version sync FAILED"; exit 1; }

echo "HOOK-NOTE: npm ci done - gradle assembleRelease (native APK build, ~10-15 min)"
echo "[build_apk] gradle assembleRelease (native, ~10 min first time)"
( cd app/android && ./gradlew assembleRelease -x lint --console=plain ) \
  || { echo "[build_apk] APK BUILD FAILED"; exit 1; }
APK="app/android/app/build/outputs/apk/release/app-release.apk"
[ -f "$APK" ] || { echo "[build_apk] no APK produced"; exit 1; }
echo "[build_apk] APK: $(du -h "$APK" | cut -f1)"
echo "HOOK-NOTE: APK built ($(du -h "$APK" | cut -f1)) - smoke test + distributing to relay"

# best-effort emulator smoke: install + launch + screenshot + crash check
if command -v adb >/dev/null 2>&1 && adb get-state 1>/dev/null 2>&1; then
  echo "[build_apk] emulator smoke"
  adb uninstall app.helmdeck >/dev/null 2>&1   # signature may differ -> clean install
  adb install -r "$APK" 2>&1 | tail -1
  adb shell monkey -p app.helmdeck -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
  sleep 9
  adb exec-out screencap -p > deploy/last_apk_smoke.png 2>/dev/null \
    && echo "[build_apk] smoke shot -> deploy/last_apk_smoke.png"
  if adb shell pidof app.helmdeck >/dev/null 2>&1; then
    echo "[build_apk] app running after launch (no immediate crash)"
  else
    echo "[build_apk] WARN: app not running after launch - check the smoke shot"
  fi
else
  echo "[build_apk] no emulator/device connected - smoke skipped"
fi

echo "[build_apk] distribute APK to relay (/apk/helmdeck.apk)"
bash deploy/push_relay.sh 2>&1 | tail -3 || echo "[build_apk] WARN: relay upload failed"
echo "[build_apk] done - APK at $APK"
