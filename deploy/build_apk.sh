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

echo "[build_apk] gradle assembleRelease (native, ~10 min first time)"
( cd app/android && ./gradlew assembleRelease -x lint --console=plain ) \
  || { echo "[build_apk] APK BUILD FAILED"; exit 1; }
APK="app/android/app/build/outputs/apk/release/app-release.apk"
[ -f "$APK" ] || { echo "[build_apk] no APK produced"; exit 1; }
echo "[build_apk] APK: $(du -h "$APK" | cut -f1)"

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
