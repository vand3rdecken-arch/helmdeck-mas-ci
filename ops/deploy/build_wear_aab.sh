#!/usr/bin/env bash
# Build the signed release AAB (Play form-factor artifact) for the :wear
# module. build_wear_apk.sh's twin, same relationship build_aab.sh has to
# build_apk.sh: everything before the gradle line is copied from
# build_wear_apk.sh so this never skips a re-apply step silently.
#
# WHY AN AAB AND NOT THE SIDELOAD APK: developer.android.com/training/
# wearables/packaging (fetched 2026-09-10) - "If you're creating a Wear OS
# experience, you must use a Wear OS-enabled app bundle" - the Play Console
# "Add form factor -> Wear OS" upload flow does not take a bare APK.
#
# WHY NOT arm64-v8a-only LIKE THE PHONE: build_aab.sh restricts :app to
# arm64-v8a by owner decree (2026-08-25) because react-native-reanimated's
# CMake/ninja build deterministically fails on armeabi-v7a. :wear has no
# React Native and no CMake-compiled native code of its own - its only native
# dependencies (lazysodium-android, jna) ship PREBUILT .so per ABI inside
# their AARs, so there is no known reason to restrict ABIs here. This matters
# for real: Google's 2026-09-15 Wear OS deadline requires apps with native
# code to ship BOTH 32-bit and 64-bit - verify with the unzip/jar recipe at
# the bottom of this file after a build, don't assume it from this comment.
#
# NOT part of ops/deploy/ship.sh or the fast-track pipeline, same reason as
# build_wear_apk.sh: :wear has no track record of successful Gradle runs to
# trust with an unattended accept hook yet. Run BY HAND.
set -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"

JAVA_HOME="$(ls -d '/c/Program Files/Microsoft/jdk-17'* 2>/dev/null | head -1)"
[ -z "$JAVA_HOME" ] && { echo "[build_wear_aab] JDK 17 missing - winget install Microsoft.OpenJDK.17"; exit 1; }
export JAVA_HOME
export ANDROID_HOME="${ANDROID_HOME:-$HOME/AppData/Local/Android/Sdk}"
export PATH="/c/Program Files/nodejs:$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$PATH"

[ -d surfaces/app/android/wear ] || {
  echo "[build_wear_aab] surfaces/app/android/wear is missing - run"
  echo "[build_wear_aab]   ops/deploy/build_apk.sh"
  echo "[build_wear_aab] (or build_aab.sh, either lays :wear down) at least once first."
  exit 1
}

# Provenance guard BEFORE the lock, so a dirty tree fails fast instead of
# queueing behind another build first. See wear_build_guard.sh for the why.
. "$(dirname "$0")/wear_build_guard.sh"
wear_guard_check

# Same machine-global Android build mutex every other build script here takes.
. "$(dirname "$0")/build_lock.sh"
android_build_lock "build_wear_aab.sh :wear:bundleRelease (${HELMDECK_CARD:-manuell/kein Karten-Kontext})"

echo "[build_wear_aab] syncing plugins/wear -> android/wear before the build"
node surfaces/app/plugins/withWearApp.js surfaces/app/android \
  || { echo "[build_wear_aab] withWearApp sync FAILED - refusing to build a stale :wear"; exit 1; }

# Signed with the PHONE module's OWN keystore, not a Wear-specific one - see
# surfaces/app/plugins/wear/build.gradle's header (2026-09-10 owner decision:
# bundle into the existing app.helmdeck Play listing).
node surfaces/app/plugins/withWearReleaseSigning.js surfaces/app/android \
  || { echo "[build_wear_aab] wear release-signing apply FAILED"; exit 1; }

echo "[build_wear_aab] gradle :wear:bundleRelease (~a few min - no CMake compile, just AAR packaging)"
( cd surfaces/app/android && ./gradlew :wear:bundleRelease -x lint --console=plain ) \
  || { echo "[build_wear_aab] WEAR AAB BUILD FAILED"; exit 1; }

AAB="surfaces/app/android/wear/build/outputs/bundle/release/wear-release.aab"
[ -f "$AAB" ] || { echo "[build_wear_aab] no AAB produced at $AAB"; exit 1; }

# COPY OUT IMMEDIATELY - build_apk.sh/build_aab.sh's `expo prebuild --clean`
# wipes android/ wholesale on its next run, same measured-loss trap build_aab.sh
# already guards for the phone AAB (2026-09-01).
mkdir -p .loop/artifacts
WVCODE="$(grep -oE 'versionCode [0-9]+' surfaces/app/plugins/wear/build.gradle | tail -1 | grep -o '[0-9]*')"
SAFE=".loop/artifacts/helmdeck-wear-vc${WVCODE:-unknown}.aab"
cp "$AAB" "$SAFE" || { echo "[build_wear_aab] WARN: artifact copy-out failed - upload from $AAB before any other build runs"; }
echo "[build_wear_aab] AAB: $(du -h "$AAB" | cut -f1) -> $SAFE"
wear_guard_stamp "$SAFE"

# ABI CHECK - do not assume compliance, read it off the actual artifact.
# An AAB is a zip of per-module zips; unzip lists both without needing
# bundletool. Google's 2026-09-15 Wear deadline requires BOTH present.
echo "[build_wear_aab] native libs in the artifact (must show both arm64-v8a and armeabi-v7a):"
unzip -l "$SAFE" 2>/dev/null | grep -oE '/(arm64-v8a|armeabi-v7a|x86|x86_64)/' | sort -u

echo "[build_wear_aab] done"
