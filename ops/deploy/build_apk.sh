#!/usr/bin/env bash
# Build the signed release APK (native, bundles JS -> standalone), do a
# best-effort emulator smoke, and distribute to the relay. Used by the fast-track
# (ops/deploy/ship.sh) when a NATIVE change landed - OTA can't ship native code.
set -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"

# JDK 17 - RN 0.86 / Expo 57 need it (Java 8 fails). Microsoft OpenJDK install.
JAVA_HOME="$(ls -d '/c/Program Files/Microsoft/jdk-17'* 2>/dev/null | head -1)"
[ -z "$JAVA_HOME" ] && { echo "[build_apk] JDK 17 missing - winget install Microsoft.OpenJDK.17"; exit 1; }
export JAVA_HOME
export ANDROID_HOME="${ANDROID_HOME:-$HOME/AppData/Local/Android/Sdk}"
export PATH="/c/Program Files/nodejs:$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$PATH"

# ANDROID BUILD MUTEX - taken HERE, before anything below touches shared state.
# This script is the one every Android build path funnels through (the ship
# hook's native branch, a machine/direct card, DEPLOY.md's manual recipe), and
# everything from this line down is machine-global rather than tree-local: the
# Gradle daemon, ~/.gradle, surfaces/app/android, node_modules, adb.
# The POSITION matters as much as the lock. The very next block runs
# `./gradlew --stop`, which stops EVERY Gradle daemon of this user - so a second
# build starting here used to KILL a first build that was ten minutes into
# assembleRelease (owner-reported incident 2026-08-30). Acquiring first turns
# that collision into a queue. Taken AFTER the JDK check above so a box with no
# JDK still fails in a second instead of queueing behind a 15-minute build to
# then fail anyway. See ops/deploy/build_lock.sh for the primitive.
. "$(dirname "$0")/build_lock.sh"
android_build_lock "build_apk.sh :app:assembleRelease (${HELMDECK_CARD:-manuell/kein Karten-Kontext})"

# Nothing else in the ship pipeline runs `npm install` for app/ - a merge that
# adds/bumps a dependency (exactly what routes here via native_fp) leaves the
# main repo's node_modules stale, so Metro/gradle autolinking can't resolve
# the new package ("Unable to resolve module ..."). `npm ci` is only in the
# NATIVE path (~10 min build anyway) so the plain JS-only OTA fast path stays
# seconds, unaffected.
# A leftover Gradle daemon holds jars INSIDE node_modules (expo-* android
# builds cache there) and npm ci then dies on EPERM/EBUSY unlink - hit twice
# on 2026-08-20/21, both times after a prior build was killed (daemon
# restart / stopped task) and its daemon lingered. Ask it to stop first;
# best-effort, a missing wrapper or no daemon is fine.
# --stop is a REQUEST, not a wait: it returns while the daemon is still
# exiting and Windows releases its jar handles a beat later - measured twice
# on 2026-08-23 (ship 3 + ship 5 both died on EBUSY seconds after a clean
# --stop would have "succeeded"). Poll --status until no daemon reports
# IDLE/BUSY, then one settle beat for the handle release.
( cd surfaces/app/android 2>/dev/null && {
    ./gradlew --stop >/dev/null 2>&1
    for _i in 1 2 3 4 5 6 7 8; do
      ./gradlew --status 2>/dev/null | grep -qiE "IDLE|BUSY" || break
      sleep 5
    done
    sleep 3
  } ) || true
echo "HOOK-NOTE: npm ci (node_modules sync with the just-merged lockfile, can take a few min)"
echo "[build_apk] npm ci (sync node_modules with the just-merged lockfile)"
( cd surfaces/app && npm ci ) || { echo "[build_apk] npm ci FAILED"; exit 1; }

# REGENERATE surfaces/app/android FROM app.json + assets (2026-08-26). This script used
# to assume the git-ignored, hand-managed android/ folder was already current
# and only re-applied the 5 custom with*.js patches below - fine for a .kt/
# .java source change, but SILENTLY WRONG for anything Expo's own config-
# plugin system is responsible for (icon.png, splash-icon.png, the
# adaptiveIcon layers, expo-splash-screen's backgroundColor, expo-camera's
# permission strings, ...): those are baked into android/ by `expo prebuild`
# ONLY, so a rebuild without this step ships whatever was baked in on the
# LAST prebuild - a real incident, not hypothetical: the logo redesign this
# line exists for built a real, green, signed APK with the OLD icon still in
# it. `--clean` is safe here because every native customization this repo
# needs beyond Expo's own plugins is ALREADY re-applied unconditionally right
# below (LanCleartext/GlassVoice/MetaDat/SherpaOnnx/UpdateUrl) regardless of
# whether prebuild just ran - so a fresh android/ loses nothing this script
# doesn't already restore. `npx` itself fails on this box with a bare quoting
# error (Program Files' space in the node path breaks its shim), so the
# local binary is invoked directly; CI=1 replaces the unsupported
# --non-interactive flag.
echo "HOOK-NOTE: expo prebuild (regenerate android/ native resources from app.json + assets)"
echo "[build_apk] expo prebuild --platform android --clean"
( cd surfaces/app && CI=1 ./node_modules/.bin/expo prebuild --platform android --clean ) \
  || { echo "[build_apk] expo prebuild FAILED"; exit 1; }

# lintVitalAnalyzeRelease is NOT covered by the `-x lint` below and OOMs on
# the expo-template default Metaspace (512m) since the module count grew
# (measured 2026-08-29: OutOfMemoryError:Metaspace in :expo-modules-core /
# :expo-updates lint analysis, BUILD FAILED after ~6min). gradle.properties
# is REGENERATED by the prebuild --clean above, so the bump must be patched
# in here on every build - editing the generated file by hand does not stick.
sed -i 's/-XX:MaxMetaspaceSize=512m/-XX:MaxMetaspaceSize=1024m/' \
  surfaces/app/android/gradle.properties
grep -q "MaxMetaspaceSize=1024m" surfaces/app/android/gradle.properties \
  || { echo "[build_apk] Metaspace bump did not apply (template changed?)"; exit 1; }

# local.properties MUST use forward slashes - the Java properties parser eats
# backslashes ("filename syntax incorrect" in the NDK locator).
printf 'sdk.dir=%s\n' "$(cygpath -m "$ANDROID_HOME" 2>/dev/null || echo "$ANDROID_HOME")" \
  > surfaces/app/android/local.properties

# surfaces/app/android is git-ignored/hand-managed, so re-apply the source-of-truth
# native config before every build: scope cleartext to the direct-LAN hosts
# from app.json (pays debt [android-cleartext-lan]; same plugin runs on a
# future `expo prebuild`, so the two paths cannot drift).
node surfaces/app/plugins/withLanCleartext.js surfaces/app/android \
  || { echo "[build_apk] network-security-config apply FAILED"; exit 1; }

# Same rule, most silent-wrong-artifact yet: the release-signing keystore.
# `expo prebuild --clean` (added 2026-08-26 for the icon pipeline fix)
# regenerates build.gradle's signingConfigs from scratch, wiping a hand-edit
# with no script anywhere else to reproduce it - every release build then
# silently fell back to the debug keystore. The build still succeeds and
# EXITS ZERO; the only symptom is Android refusing to INSTALL the result
# over an already-installed copy ("Konflikt mit einem bestehenden Paket" /
# INSTALL_FAILED_UPDATE_INCOMPATIBLE) - discovered live on the owner's phone.
node surfaces/app/plugins/withReleaseSigning.js surfaces/app/android \
  || { echo "[build_apk] release-signing apply FAILED"; exit 1; }

# Same rule, same reason: the glasses-voice permissions + the typed foreground
# service. Without this line the APK builds perfectly clean and the microphone
# is simply never grantable at runtime - a silent, on-device-only failure, which
# is the exact class the line above exists to prevent.
node surfaces/app/plugins/withGlassVoice.js surfaces/app/android \
  || { echo "[build_apk] glass-voice manifest apply FAILED"; exit 1; }

# Same rule, third time: the Meta DAT (glasses camera) gradle wiring + the
# camera/device sources. WITHOUT THIS LINE THE BUILD IS SILENTLY WRONG in the
# worst way available - surfaces/app/android is git-ignored and hand-managed, so nothing
# else ever puts the GitHub Packages repository, the mwdat-* dependencies, the
# <service> declaration or GlassCameraService.kt / GlassesDevice.kt into the
# tree. Gradle then compiles an APK with no camera code at all and EXITS ZERO,
# because there is nothing to fail - the feature is simply absent. That is the
# exact class DEPLOY.md 2 records ("the skips are SILENT: the build goes green
# and the artifact is wrong"), and the reason the two lines above exist.
#
# It is also the only plugin here that can fail for an EXTERNAL reason, so it
# gets its own note: resolving com.meta.wearable needs a GitHub token with
# read:packages AT GRADLE TIME. The owner's ordinary `gh` token already carries
# it (measured 2026-08-21: HTTP 200 on all four 0.9.0 artifacts), so if the
# gradle step later dies on an unauthorized com.meta.wearable lookup, export it
# and re-run - it is not a code failure:
#     export GITHUB_TOKEN="$(gh auth token)"
node surfaces/app/plugins/withMetaDat.js surfaces/app/android \
  || { echo "[build_apk] meta-dat wiring apply FAILED"; exit 1; }

# Fourth re-apply, same silent-wrong-artifact class: the sherpa-onnx AAR for
# the on-device STT option. Without it the build goes green and initLocalStt
# throws NoClassDefFoundError at runtime (see surfaces/app/plugins/withSherpaOnnx.js).
node surfaces/app/plugins/withSherpaOnnx.js surfaces/app/android \
  || { echo "[build_apk] sherpa-onnx wiring apply FAILED"; exit 1; }

# THE CREDENTIAL, and WHY IT IS DERIVED HERE rather than assumed to be present.
# Resolving com.meta.wearable needs a read:packages token at GRADLE time. Every
# build so far supplied it by hand from an interactive shell - but this script's
# real caller is ops/deploy/ship.sh, run by the DAEMON's accept hook, which has no
# interactive shell and no exported GITHUB_TOKEN. Left as-is, the deploy would
# npm ci, apply plugins, and then die ~15 minutes later inside gradle on an
# unauthorized lookup that reads like a code failure and is not one.
#
# The owner's ordinary `gh` login already carries read:packages (DEPLOY.md:405,
# measured 2026-08-21: HTTP 200 on all four 0.9.0 artifacts), so ask it. Note
# that gradle also accepts `github_token` in surfaces/app/android/local.properties -
# checked below so a box without the gh CLI can still build.
if [ -z "$GITHUB_TOKEN" ]; then
  GITHUB_TOKEN="$(gh auth token 2>/dev/null || true)"
  export GITHUB_TOKEN
  [ -n "$GITHUB_TOKEN" ] && echo "[build_apk] GITHUB_TOKEN derived from the gh CLI"
fi
# FAIL EARLY AND CLEARLY. Without this the same missing credential surfaces a
# quarter of an hour later as a gradle resolution error - the expensive place to
# learn it. Only blocks when the DAT deps are actually declared, so a tree
# without the glasses camera still builds with no token at all.
if [ -z "$GITHUB_TOKEN" ] \
   && ! grep -q "github_token" surfaces/app/android/local.properties 2>/dev/null \
   && grep -q "com.meta.wearable" surfaces/app/android/app/build.gradle 2>/dev/null; then
  echo "[build_apk] NO read:packages CREDENTIAL - the Meta DAT artifacts cannot resolve."
  echo "[build_apk] Fix with ONE of:"
  echo "[build_apk]   export GITHUB_TOKEN=\"\$(gh auth token)\"   # needs the gh CLI logged in"
  echo "[build_apk]   echo 'github_token=<PAT>' >> surfaces/app/android/local.properties"
  exit 1
fi

# Same rule once more: the OTA update URL + /pair deep-link host from
# app.json. This was the one nobody wrote: the relay cutover changed app.json
# but the stale manifest kept the dead Oracle VM, so builds 48 + the first 49
# shipped with an OTA URL that can never answer - and an OTA cannot fix a
# wrong OTA URL. Emulator-proven (UpdateFailedToLoad, connect timeout).
node surfaces/app/plugins/withUpdateUrl.js surfaces/app/android \
  || { echo "[build_apk] update-url manifest apply FAILED"; exit 1; }

# Seventh re-apply, same rule, DIFFERENT SHAPE: this one does not patch the
# phone module, it lays down a whole SEPARATE one (:wear, W2a - Wear OS
# companion). Same reason it has to happen here: android/ is regenerated from
# nothing on --clean, so a module that lives only in the git-ignored tree
# vanishes on the next prebuild unless something re-creates it every time.
# UNVERIFIED beyond this script's own text-patching (no Android SDK/Gradle
# reachable from the card worktree that wrote it - see
# ops/docs/backlog/wear-os-integration/README.md §9.1). This is also why the
# gradlew invocation below is scoped to `:app:assembleRelease` explicitly -
# :wear now exists in settings.gradle the moment this line runs, and the
# PHONE release pipeline's tested behaviour (single APK, ~10-15 min, one
# output path) must not silently start building a second, unsigned,
# never-built module as a side effect of this addition.
node surfaces/app/plugins/withWearApp.js surfaces/app/android \
  || { echo "[build_apk] wear-module wiring apply FAILED"; exit 1; }

# Sync the hand-managed native version from app.json BEFORE building. The bump
# automation (ship.sh) only touches app.json version + versionCode, but the
# git-ignored surfaces/app/android is hand-managed and does NOT regenerate: build.gradle's
# versionName and the AndroidManifest's EXPO_RUNTIME_VERSION were silently left on
# the old value, so a "1.0.3" bump produced an APK whose runtimeVersion was still
# 1.0.2 - it matched neither the old nor the new OTA target. Write all three from
# app.json so the APK, its runtimeVersion, and the OTA target can never drift.
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
  console.log("[build_apk] native version synced from app.json -> " + ver + " / " + vc);
' || { echo "[build_apk] native version sync FAILED"; exit 1; }

echo "HOOK-NOTE: npm ci done - gradle assembleRelease (native APK build, ~10-15 min)"
echo "[build_apk] gradle assembleRelease (native, ~10 min first time)"
# arm64-v8a ONLY (owner decree 2026-08-25): the default 4-ABI build
# (gradle.properties reactNativeArchitectures) deterministically fails on
# armeabi-v7a - `ninja: error: manifest 'build.ninja' still dirty after 100
# tries` in react-native-reanimated's CMake step, reproduced 3/3 times
# (including after clearing its .cxx cache, so NOT stale-cache corruption).
# Root cause not fixed here - likely this checkout's Windows path containing
# a space ("Tien Duy Vo"), a known class of CMake/Ninja fragility - just
# scoped around: arm64-v8a covers virtually every real Android phone sold
# since ~2020, so this is a real (if temporary) device-support narrowing,
# not a free workaround. Tracked as debt - see spine/registry/debt.py.
#
# `:app:assembleRelease`, NOT the bare `assembleRelease` this line used before
# the :wear module existed - a bare task name builds EVERY module in
# settings.gradle, which would now silently pull in :wear (no release
# signingConfig, never built once) as a side effect of a phone-only release.
# Scoping to :app keeps this exact command's tested behaviour unchanged; the
# watch module is built on demand by ops/deploy/build_wear_apk.sh instead.
# WITH_AAB=1 additionally builds the Play Store bundle IN THE SAME gradle
# invocation (2026-09-01, owner: "can't wait 20 min each time"). The APK and
# the AAB share the entire compile graph - built together, the AAB costs ~1-2
# extra minutes of packaging instead of a second full clean build. This is the
# preferred way to produce a Play artifact; build_aab.sh remains for an
# AAB-only run.
GRADLE_TASKS=":app:assembleRelease"
if [ -n "$WITH_AAB" ]; then
  GRADLE_TASKS=":app:assembleRelease :app:bundleRelease"
  echo "[build_apk] WITH_AAB=1 - building the Play AAB in the same run"
fi
( cd surfaces/app/android && ./gradlew $GRADLE_TASKS -x lint --console=plain \
    -PreactNativeArchitectures=arm64-v8a ) \
  || { echo "[build_apk] BUILD FAILED"; exit 1; }
APK="surfaces/app/android/app/build/outputs/apk/release/app-release.apk"
[ -f "$APK" ] || { echo "[build_apk] no APK produced"; exit 1; }
if [ -n "$WITH_AAB" ]; then
  AAB="surfaces/app/android/app/build/outputs/bundle/release/app-release.aab"
  if [ -f "$AAB" ]; then
    # Same copy-out as build_aab.sh: the next prebuild --clean wipes android/,
    # so the artifact must leave the tree immediately (measured loss 2026-09-01).
    VCODE=$(py -3.12 -c "import json;print(json.load(open('surfaces/app/app.json',encoding='utf-8'))['expo']['android']['versionCode'])")
    mkdir -p .loop/artifacts
    cp "$AAB" ".loop/artifacts/helmdeck-vc${VCODE}.aab" \
      && echo "[build_apk] AAB: $(du -h "$AAB" | cut -f1) -> .loop/artifacts/helmdeck-vc${VCODE}.aab"
  else
    echo "[build_apk] WARN: WITH_AAB was set but no AAB was produced"
  fi
fi
echo "[build_apk] APK: $(du -h "$APK" | cut -f1)"
echo "HOOK-NOTE: APK built ($(du -h "$APK" | cut -f1)) - smoke test + distributing to relay"

# best-effort emulator smoke: install + launch + screenshot + crash check
if command -v adb >/dev/null 2>&1 && adb get-state 1>/dev/null 2>&1; then
  echo "[build_apk] emulator smoke"
  adb uninstall app.helmdeck >/dev/null 2>&1   # signature may differ -> clean install
  adb install -r "$APK" 2>&1 | tail -1
  adb shell monkey -p app.helmdeck -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
  sleep 9
  adb exec-out screencap -p > ops/deploy/last_apk_smoke.png 2>/dev/null \
    && echo "[build_apk] smoke shot -> ops/deploy/last_apk_smoke.png"
  if adb shell pidof app.helmdeck >/dev/null 2>&1; then
    echo "[build_apk] app running after launch (no immediate crash)"
  else
    echo "[build_apk] WARN: app not running after launch - check the smoke shot"
  fi
else
  echo "[build_apk] no emulator/device connected - smoke skipped"
fi

echo "[build_apk] distribute APK to relay (/apk/helmdeck.apk)"
bash ops/deploy/push_relay.sh 2>&1 | tail -3 || echo "[build_apk] WARN: relay upload failed"
echo "[build_apk] done - APK at $APK"
