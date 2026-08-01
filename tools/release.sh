#!/usr/bin/env bash
# One-command release for the CURRENT (Expo) stack: the Windows desktop
# installer and the Android APK, built from the working tree and (optionally)
# shipped to the relay so the phone can install the update.
#
# Supersedes tools/build_all.sh, which still targets the pre-migration web/
# (Next.js) and apk/ (Kotlin) trees. The pieces it drives already exist and are
# current: desktop/electron-builder.yml bundles app/dist + daemon; the desktop
# `dist:win` script does the Expo web export; deploy/push_relay.sh ships the
# Expo APK and bumps the relay's /apk/version.json.
#
#   bash tools/release.sh windows                 # desktop installer (.exe)
#   bash tools/release.sh android                 # signed APK only
#   bash tools/release.sh android --push          # APK + ship to relay
#   bash tools/release.sh android --push --bump    # + bump versionCode first
#   bash tools/release.sh all --push --bump        # both, bumped, shipped
#
# Prereqs (this machine has them): Node, Python 3.12, the Android SDK, and a
# JDK 17+ (Android Studio's JBR). A .env with RELAY_HOST/RELAY_SSH_* is needed
# only for --push. Adjust the two paths below if the toolchain moves.
set -o pipefail        # NOT -u: Git Bash leaves some Windows env vars unset
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

JBR="/c/Program Files/Android/Android Studio1/jbr"
ANDROID_SDK="${ANDROID_HOME:-$HOME/AppData/Local/Android/Sdk}"
export PATH="/c/Program Files/nodejs:$PATH"

WHAT="${1:-all}"; shift 2>/dev/null || true
PUSH=0; BUMP=0
for a in "$@"; do
  case "$a" in
    --push) PUSH=1 ;;
    --bump) BUMP=1 ;;
    *) echo "unknown flag: $a"; exit 2 ;;
  esac
done
ok=(); fail=()

bump_version() {
  # Android updates an installed APK in place only if versionCode is higher, and
  # the code lives in TWO places kept in sync: app/app.json (what push_relay.sh
  # reports in version.json) and the prebuilt android/app/build.gradle (what the
  # APK actually carries). Bump both. versionName is left for a human to set.
  py -3.12 - "$ROOT" <<'PY'
import json, re, sys
root = sys.argv[1]
aj = root + "/app/app.json"; gr = root + "/app/android/app/build.gradle"
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
  ( cd app/android && JAVA_HOME="$JBR" ANDROID_HOME="$ANDROID_SDK" PATH="$JBR/bin:$PATH" \
      ./gradlew assembleRelease --no-daemon --console=plain ) || { fail+=("android"); return 1; }
  local apk="app/android/app/build/outputs/apk/release/app-release.apk"
  [ -f "$apk" ] || { echo "    APK missing at $apk"; fail+=("android"); return 1; }
  ok+=("android: $apk")
  if [ "$PUSH" = 1 ]; then
    echo "==> relay: ship APK + version.json (phone installs it from the pairing link)"
    bash deploy/push_relay.sh || { fail+=("push"); return 1; }
    ok+=("push: relay updated")
  fi
}

build_windows() {
  echo "==> windows: expo web export + electron-builder (unsigned NSIS installer)"
  ( cd desktop && npm run dist:win ) || { fail+=("windows"); return 1; }
  ok+=("windows: $(ls desktop/release/*.exe 2>/dev/null | head -1)")
}

case "$WHAT" in
  android) build_android ;;
  windows) build_windows ;;
  all)     build_android; build_windows ;;
  *) echo "usage: release.sh [android|windows|all] [--push] [--bump]"; exit 2 ;;
esac

echo; echo "===== release summary ====="
for a in "${ok[@]:-}"; do [ -n "$a" ] && echo "  OK   $a"; done
for f in "${fail[@]:-}"; do [ -n "$f" ] && echo "  FAIL $f"; done
[ ${#fail[@]} -eq 0 ]
