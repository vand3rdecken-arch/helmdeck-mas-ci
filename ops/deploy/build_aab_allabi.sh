#!/usr/bin/env bash
# All-ABI variant of build_aab.sh, meant to run from a SHORT, space-free mirror
# path (C:\hd), not from this repo checkout.
#
# WHY THIS EXISTS: the 2026-08-25 owner decree scoped every release build to
# arm64-v8a only because the default 4-ABI build dies in armeabi-v7a's CMake
# step (`ninja: manifest 'build.ninja' still dirty after 100 tries`), reproduced
# 3/3 times, root cause suspected to be the space in this checkout's path
# ("Tien Duy Vo") - a known class of CMake/Ninja fragility. DEPLOY.md's
# worktree section documents the same failure class from path LENGTH and its
# fix: mirror to a short path (e.g. C:\hd\app) and build there. This script is
# that fix applied to the AAB path, with the arm64-only override REMOVED so
# gradle.properties' default (4 ABIs, matching production release 43) applies.
#
# This file lives in the real repo only as a SOURCE COPY - the actual script
# that runs is placed at C:\hd\ops\deploy\build_aab_allabi.sh (mirrored, so its
# own $(dirname "$0")/../.. resolves ROOT to C:\hd, matching the mirrored
# surfaces/app and daemon/certs/apk-signing trees placed alongside it).
set -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"

JAVA_HOME="$(ls -d '/c/Program Files/Microsoft/jdk-17'* 2>/dev/null | head -1)"
[ -z "$JAVA_HOME" ] && { echo "[build_aab_allabi] JDK 17 missing"; exit 1; }
export JAVA_HOME
export ANDROID_HOME="${ANDROID_HOME:-$HOME/AppData/Local/Android/Sdk}"
export PATH="/c/Program Files/nodejs:$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$PATH"

. "$(dirname "$0")/build_lock.sh"
android_build_lock "build_aab_allabi.sh :app:bundleRelease (${HELMDECK_CARD:-manuell/kein Karten-Kontext})"

( cd surfaces/app/android 2>/dev/null && {
    ./gradlew --stop >/dev/null 2>&1
    for _i in 1 2 3 4 5 6 7 8; do
      ./gradlew --status 2>/dev/null | grep -qiE "IDLE|BUSY" || break
      sleep 5
    done
    sleep 3
  } ) || true

# node_modules was mirrored via robocopy from the real repo's already-`npm ci`d
# tree, so it should already be in sync with package-lock.json. Verify rather
# than trust the copy - a partial/interrupted robocopy is silent otherwise.
echo "[build_aab_allabi] verifying mirrored node_modules (npm ci would re-download here; ci instead of install to catch drift)"
( cd surfaces/app && npm ci ) || { echo "[build_aab_allabi] npm ci FAILED"; exit 1; }

echo "[build_aab_allabi] expo prebuild --platform android --clean"
( cd surfaces/app && CI=1 ./node_modules/.bin/expo prebuild --platform android --clean ) \
  || { echo "[build_aab_allabi] expo prebuild FAILED"; exit 1; }

sed -i 's/-XX:MaxMetaspaceSize=512m/-XX:MaxMetaspaceSize=1024m/' \
  surfaces/app/android/gradle.properties
grep -q "MaxMetaspaceSize=1024m" surfaces/app/android/gradle.properties \
  || { echo "[build_aab_allabi] Metaspace bump did not apply"; exit 1; }

printf 'sdk.dir=%s\n' "$(cygpath -m "$ANDROID_HOME" 2>/dev/null || echo "$ANDROID_HOME")" \
  > surfaces/app/android/local.properties

node surfaces/app/plugins/withLanCleartext.js surfaces/app/android \
  || { echo "[build_aab_allabi] network-security-config apply FAILED"; exit 1; }
node surfaces/app/plugins/withReleaseSigning.js surfaces/app/android \
  || { echo "[build_aab_allabi] release-signing apply FAILED"; exit 1; }
node surfaces/app/plugins/withGlassVoice.js surfaces/app/android \
  || { echo "[build_aab_allabi] glass-voice manifest apply FAILED"; exit 1; }
node surfaces/app/plugins/withMetaDat.js surfaces/app/android \
  || { echo "[build_aab_allabi] meta-dat wiring apply FAILED"; exit 1; }
node surfaces/app/plugins/withSherpaOnnx.js surfaces/app/android \
  || { echo "[build_aab_allabi] sherpa-onnx wiring apply FAILED"; exit 1; }
node surfaces/app/plugins/withUpdateUrl.js surfaces/app/android \
  || { echo "[build_aab_allabi] update-url manifest apply FAILED"; exit 1; }
node surfaces/app/plugins/withWearApp.js surfaces/app/android \
  || { echo "[build_aab_allabi] wear-module wiring apply FAILED"; exit 1; }

if [ -z "$GITHUB_TOKEN" ]; then
  GITHUB_TOKEN="$(gh auth token 2>/dev/null || true)"
  export GITHUB_TOKEN
  [ -n "$GITHUB_TOKEN" ] && echo "[build_aab_allabi] GITHUB_TOKEN derived from the gh CLI"
fi
if [ -z "$GITHUB_TOKEN" ] \
   && ! grep -q "github_token" surfaces/app/android/local.properties 2>/dev/null \
   && grep -q "com.meta.wearable" surfaces/app/android/app/build.gradle 2>/dev/null; then
  echo "[build_aab_allabi] NO read:packages CREDENTIAL - the Meta DAT artifacts cannot resolve."
  exit 1
fi

node -e '
  const fs = require("fs");
  const e = JSON.parse(fs.readFileSync("surfaces/app/app.json", "utf8")).expo;
  const ver = e.version, vc = String(e.android.versionCode);
  const g = "surfaces/app/android/app/build.gradle";
  fs.writeFileSync(g, fs.readFileSync(g, "utf8")
    .replace(/versionCode\s+\d+/, "versionCode " + vc)
    .replace(/versionName\s+"[^"]*"/, "versionName \"" + ver + "\""));
  const m = "surfaces/app/android/app/src/main/AndroidManifest.xml";
  fs.writeFileSync(m, fs.readFileSync(m, "utf8")
    .replace(/(EXPO_RUNTIME_VERSION"\s+android:value=")[^"]*(")/, "$1" + ver + "$2"));
  console.log("[build_aab_allabi] native version synced from app.json -> " + ver + " / " + vc);
' || { echo "[build_aab_allabi] native version sync FAILED"; exit 1; }

echo "[build_aab_allabi] gradle :app:bundleRelease, ALL ABIs (no reactNativeArchitectures override)"
( cd surfaces/app/android && ./gradlew :app:bundleRelease -x lint --console=plain ) \
  || { echo "[build_aab_allabi] AAB BUILD FAILED"; exit 1; }

AAB="surfaces/app/android/app/build/outputs/bundle/release/app-release.aab"
[ -f "$AAB" ] || { echo "[build_aab_allabi] no AAB produced"; exit 1; }
echo "[build_aab_allabi] AAB: $(du -h "$AAB" | cut -f1) -> $AAB"
echo "[build_aab_allabi] done"
