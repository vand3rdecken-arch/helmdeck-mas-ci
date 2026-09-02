#!/usr/bin/env bash
# Build + install the HelmDeck WEAR OS module (:wear, W2a) onto a paired
# Wear emulator or device via adb. NOT part of ops/deploy/ship.sh or the
# fast-track pipeline on purpose - unlike the phone app, the watch module
# has never been through Gradle even once (no Android SDK reachable from the
# card worktree that wrote it, see ops/docs/backlog/wear-os-integration/
# README.md §9.1), so it must never run unattended off an owner-triggered
# accept. Run this BY HAND, after Android Studio + a Wear OS emulator/device
# are already set up (developer.android.com/training/wearables/get-started/
# emulator - Device Manager -> Wear OS, then Pair Wearable).
#
# Assumes ops/deploy/build_apk.sh has ALREADY regenerated surfaces/app/android
# in this run (it lays down :wear as its 7th plugin step) - this script does
# NOT re-run `expo prebuild`, so `:wear` must already exist in settings.gradle
# or the gradlew call below fails fast with "project ':wear' not found",
# which is the honest failure, not a silent skip.
set -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"

JAVA_HOME="$(ls -d '/c/Program Files/Microsoft/jdk-17'* 2>/dev/null | head -1)"
[ -z "$JAVA_HOME" ] && { echo "[build_wear_apk] JDK 17 missing - winget install Microsoft.OpenJDK.17"; exit 1; }
export JAVA_HOME
export ANDROID_HOME="${ANDROID_HOME:-$HOME/AppData/Local/Android/Sdk}"
export PATH="/c/Program Files/nodejs:$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$PATH"

[ -d surfaces/app/android/wear ] || {
  echo "[build_wear_apk] surfaces/app/android/wear is missing - run"
  echo "[build_wear_apk]   ops/deploy/build_apk.sh"
  echo "[build_wear_apk] at least once first (it regenerates android/ and lays :wear down)."
  exit 1
}

# Same machine-global Android build mutex the phone build takes. :wear is a
# different Gradle MODULE but the same Gradle daemon, the same ~/.gradle and the
# same surfaces/app/android tree - so a watch build racing a phone
# assembleRelease contends for exactly the resources that collided on
# 2026-08-30. Taken after the JDK + :wear-exists checks above so both keep
# failing fast instead of queueing behind a long build to then fail anyway.
. "$(dirname "$0")/build_lock.sh"
android_build_lock "build_wear_apk.sh :wear:assembleDebug (${HELMDECK_CARD:-manuell/kein Karten-Kontext})"

# RE-COPY THE SOURCES FIRST (2026-09-02). This script used to go straight to
# gradlew, on the assumption that build_apk.sh had just regenerated android/.
# Editing plugins/wear/*.kt and running THIS script therefore built the stale
# generated copy and reported "BUILD SUCCESSFUL ... 68 up-to-date" - green, and
# the change simply not in the APK. Measured, not reasoned: the encoding fix in
# BoardScreen.kt was installed onto the owner's watch that way and was still the
# old string on the wrist. Same silent-wrong-artifact class the ERROR at the
# bottom of withWearApp.js already guards, so it is guarded here the same way.
# The copy is idempotent ("already current" when nothing changed), so this costs
# nothing on the common path and makes an edit impossible to lose.
echo "[build_wear_apk] syncing plugins/wear -> android/wear before the build"
node surfaces/app/plugins/withWearApp.js surfaces/app/android \
  || { echo "[build_wear_apk] withWearApp sync FAILED - refusing to build a stale :wear"; exit 1; }

echo "[build_wear_apk] gradle :wear:assembleDebug (debug-signed - adb install needs no release key)"
( cd surfaces/app/android && ./gradlew :wear:assembleDebug -x lint --console=plain ) \
  || { echo "[build_wear_apk] WEAR APK BUILD FAILED"; exit 1; }

APK="surfaces/app/android/wear/build/outputs/apk/debug/wear-debug.apk"
[ -f "$APK" ] || { echo "[build_wear_apk] no APK produced at $APK"; exit 1; }
echo "[build_wear_apk] APK: $(du -h "$APK" | cut -f1)"

# Installs onto whatever device/emulator adb currently targets - a paired
# Wear emulator, or a real watch over adb-over-Wi-Fi (developer.android.com/
# training/wearables/get-started/connect-devices). -r allows reinstall over a
# previous debug build; there is no release keystore for :wear yet (see
# README.md §9.1), so this path is dev-only by construction.
if command -v adb >/dev/null 2>&1 && adb get-state >/dev/null 2>&1; then
  echo "[build_wear_apk] adb install -r"
  adb install -r "$APK" || { echo "[build_wear_apk] adb install FAILED"; exit 1; }
  # The "no launcher icon asset yet" note this line used to carry is OBSOLETE
  # since 2026-08-29: withWearApp.js copies the phone's own brand PNGs into
  # wear/res/mipmap-xxhdpi plus an adaptive-icon wrapper, verified in the built
  # APK (`aapt2 dump badging` -> icon='res/mipmap-anydpi-v26/ic_launcher.xml').
  echo "[build_wear_apk] installed - open it from the watch's app drawer (HelmDeck)"
else
  echo "[build_wear_apk] no adb device/emulator reachable - built but not installed."
  echo "[build_wear_apk] pair a Wear emulator or device, then: adb install -r $APK"
fi
