#!/usr/bin/env bash
# One-command release for the CURRENT (Expo) stack: the Windows desktop
# installer and the Android APK, built from the working tree and (optionally)
# shipped to the relay so the phone can install the update.
#
# Supersedes ops/tools/build_all.sh, which still targets the pre-migration web/
# (Next.js) and apk/ (Kotlin) trees. The pieces it drives already exist and are
# current: surfaces/desktop/electron-builder.yml bundles surfaces/app/dist + daemon; the desktop
# `dist:win` script does the Expo web export; ops/deploy/push_relay.sh ships the
# Expo APK and bumps the relay's /apk/version.json.
#
#   bash ops/tools/release.sh windows                 # desktop installer (.exe)
#   bash ops/tools/release.sh android                 # signed APK only
#   bash ops/tools/release.sh android --push          # APK + ship to relay
#   bash ops/tools/release.sh android --push --bump    # + bump versionCode first
#   bash ops/tools/release.sh all --push --bump        # both, bumped, shipped
#   bash ops/tools/release.sh ota "what changed"       # SILENT JS OTA (no APK, no
#                                                  # prompt) - needs one-time
#                                                  # eas login + update:configure
#
# Prereqs (this machine has them): Node, Python 3.12, the Android SDK, and a
# JDK 17+ (Android Studio's JBR). A .env with RELAY_HOST/RELAY_SSH_* is needed
# only for --push. Adjust the two paths below if the toolchain moves.
set -o pipefail        # NOT -u: Git Bash leaves some Windows env vars unset
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

JBR="/c/Program Files/Android/Android Studio1/jbr"
ANDROID_SDK="${ANDROID_HOME:-$HOME/AppData/Local/Android/Sdk}"
export PATH="/c/Program Files/nodejs:$PATH"

WHAT="${1:-all}"; shift 2>/dev/null || true
PUSH=0; BUMP=0
# Only --push/--bump are recognized flags; other args (e.g. the `ota` message)
# are left for the target to consume.
for a in "$@"; do
  case "$a" in
    --push) PUSH=1 ;;
    --bump) BUMP=1 ;;
  esac
done
ok=(); fail=()

bump_version() {
  # Android updates an installed APK in place only if versionCode is higher, and
  # the code lives in TWO places kept in sync: surfaces/app/app.json (what
  # push_relay.sh reports in version.json) and the prebuilt android/app/
  # build.gradle (what the APK actually carries). Bump both. versionName is
  # left for a human to set.
  py -3.12 - "$ROOT" <<'PY'
import json, re, sys
root = sys.argv[1]
aj = root + "/surfaces/app/app.json"; gr = root + "/surfaces/app/android/app/build.gradle"
d = json.load(open(aj, encoding="utf-8"))
cur = int(d["expo"]["android"]["versionCode"]); new = cur + 1
d["expo"]["android"]["versionCode"] = new
json.dump(d, open(aj, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
open(aj, "a", encoding="utf-8").write("\n")
g = open(gr, encoding="utf-8").read()
open(gr, "w", encoding="utf-8").write(re.sub(r"versionCode\s+\d+", "versionCode %d" % new, g, count=1))
print("    versionCode %d -> %d" % (cur, new))
PY
}

build_android() {
  if [ "$BUMP" = 1 ]; then echo "==> bump versionCode"; bump_version || { fail+=("bump"); return 1; }; fi
  echo "==> android: gradlew assembleRelease (signed, bundles JS via Metro, JBR 17+)"
  # arm64-v8a ONLY (owner decree 2026-08-25, same workaround as
  # ops/deploy/build_apk.sh - see spine/registry/debt.py's
  # android-build-arm64-only): the default 4-ABI build deterministically
  # fails on armeabi-v7a (`ninja: error: manifest 'build.ninja' still dirty
  # after 100 tries` in react-native-reanimated's CMake step). This script
  # was missing the flag build_apk.sh already carries - confirmed live
  # 2026-08-25: BUILD FAILED after looping "Re-running CMake..." for
  # armeabi-v7a, exactly this signature.
  ( cd surfaces/app/android && JAVA_HOME="$JBR" ANDROID_HOME="$ANDROID_SDK" PATH="$JBR/bin:$PATH" \
      ./gradlew assembleRelease --no-daemon --console=plain \
      -PreactNativeArchitectures=arm64-v8a ) || { fail+=("android"); return 1; }
  local apk="surfaces/app/android/app/build/outputs/apk/release/app-release.apk"
  [ -f "$apk" ] || { echo "    APK missing at $apk"; fail+=("android"); return 1; }
  ok+=("android: $apk")
  if [ "$PUSH" = 1 ]; then
    echo "==> relay: ship APK + version.json (phone installs it from the pairing link)"
    bash ops/deploy/push_relay.sh || { fail+=("push"); return 1; }
    ok+=("push: relay updated")
    echo "==> notify: paired phone (sealed FCM push, best-effort)"
    py -3.12 -c "
from spine.comms import notify
import json
build = json.load(open('surfaces/app/app.json', encoding='utf-8'))['expo']['android']['versionCode']
notify.push_fcm('Update verfuegbar', 'Build %d ist bereit - unter Mehr installieren' % build)
" || echo "    (notify skipped - daemon not importable from here, non-fatal)"
  fi
}

build_windows() {
  echo "==> windows: expo web export + electron-builder (unsigned NSIS installer)"
  ( cd desktop && npm run dist:win ) || { fail+=("windows"); return 1; }
  ok+=("windows: $(ls surfaces/desktop/release/*.exe 2>/dev/null | head -1)")
}

build_ota() {
  # JS/asset-only OTA (expo-updates / EAS Update): the phone applies it SILENTLY
  # on its next launch - no APK, no install prompt, like paseo. Native changes
  # (new native module/permission, an SDK bump that moves runtimeVersion) still
  # need `release.sh android`. One-time setup first: `eas login` then
  # `eas update:configure` (fills updates.url + projectId in app.json).
  local msg="${1:-mobile update}"
  echo "==> ota: eas update --branch production"
  ( cd surfaces/app && npx eas update --branch production --message "$msg" ) || { fail+=("ota"); return 1; }
  ok+=("ota: published - phones pick it up on next launch, no prompt")
}

case "$WHAT" in
  android) build_android ;;
  windows) build_windows ;;
  all)     build_android; build_windows ;;
  ota)     build_ota "$*" ;;   # $* = remaining args = the update message
  *) echo "usage: release.sh [android|windows|all|ota] [--push] [--bump]"; echo "       release.sh ota \"a message\"   # publish a silent JS OTA update"; exit 2 ;;
esac

echo; echo "===== release summary ====="
for a in "${ok[@]:-}"; do [ -n "$a" ] && echo "  OK   $a"; done
for f in "${fail[@]:-}"; do [ -n "$f" ] && echo "  FAIL $f"; done
[ ${#fail[@]} -eq 0 ]
