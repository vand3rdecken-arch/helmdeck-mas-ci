#!/usr/bin/env bash
# STALE (pre-expo-migration): this targets the old web/ (Next.js) and apk/
# (Kotlin) trees. For the current Expo stack use tools/release.sh instead
# (Expo APK + Expo-web desktop installer, optional --push to the relay).
# Kept only for the `glasses` target.
#
# Build every HelmDeck deliverable from the current source, in one command:
#   Windows installer (.exe)  +  Android APK  +  the Meta glasses webapp bundle.
#
#   bash tools/build_all.sh            # build all three
#   bash tools/build_all.sh win        # just the Windows installer
#   bash tools/build_all.sh apk        # just the APK
#   bash tools/build_all.sh glasses    # just zip the glasses webapp
#
# Prereqs (this machine already has them): Node, Python 3.12, the Android SDK,
# and a JDK 17+ (Android Studio's JBR). Adjust the paths below if they move.
set -o pipefail        # NOT -u: this script reads many Windows env vars that
                       # Git Bash may leave unset (USER, LOCALAPPDATA, ...).
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

NODE_DIR="/c/Program Files/nodejs"
JBR="/c/Program Files/Android/Android Studio1/jbr"
ANDROID_SDK="${ANDROID_HOME:-$HOME/AppData/Local/Android/Sdk}"
export PATH="$NODE_DIR:$PATH"

WHAT="${1:-all}"
ok=(); fail=()

build_web() {
  echo "==> web: next build (standalone)"
  ( cd web && npm run build ) && echo "    web OK" || return 1
}

build_win() {
  build_web || { fail+=("web"); return 1; }
  echo "==> windows: prepare winCodeSign cache (skip darwin symlinks)"
  local cache="$LOCALAPPDATA/electron-builder/Cache/winCodeSign"
  local sevenz="desktop/node_modules/7zip-bin/win/x64/7za.exe"
  local arc; arc=$(ls "$cache"/*.7z 2>/dev/null | head -1)
  if [ -n "$arc" ] && [ -x "$sevenz" ]; then
    rm -rf "$cache/winCodeSign-2.6.0"
    "$sevenz" x "$arc" "-o$cache/winCodeSign-2.6.0" "-xr!darwin" -y >/dev/null 2>&1 && echo "    cache ready"
  fi
  echo "==> windows: electron-builder --win (unsigned)"
  ( cd desktop && CSC_IDENTITY_AUTO_DISCOVERY=false node_modules/.bin/electron-builder --win --config electron-builder.yml ) \
    && ok+=("win: $(ls desktop/release/*.exe 2>/dev/null | head -1)") || fail+=("win")
}

build_apk() {
  # release (signed via apk/keystore.properties) - that is what ships; the AAB
  # is what Google Play needs, the APK is for sideloading.
  echo "==> apk: gradlew bundleRelease assembleRelease (JBR 17+)"
  ( cd apk && JAVA_HOME="$JBR" ANDROID_HOME="$ANDROID_SDK" PATH="$JBR/bin:$PATH" \
      ./gradlew bundleRelease assembleRelease --no-daemon --console=plain ) \
    && ok+=("apk: apk/app/build/outputs/apk/release/app-release.apk + bundle/release/app-release.aab") \
    || fail+=("apk")
}

build_glasses() {
  echo "==> glasses: bundle the Meta Ray-Ban Display webapp"
  mkdir -p glasses/dist
  # `zip` isn't on Git Bash here; use Python's zipfile (always present).
  py -3.12 -c "import zipfile;z=zipfile.ZipFile('glasses/dist/helmdeck-glasses.zip','w',zipfile.ZIP_DEFLATED);[z.write('glasses/'+f,f) for f in ('index.html','styles.css','app.js','README.md')];z.close()" \
    && ok+=("glasses: glasses/dist/helmdeck-glasses.zip (upload via the toolkit /test-on-device)") || fail+=("glasses")
}

case "$WHAT" in
  all) build_win; build_apk; build_glasses ;;
  win) build_win ;;
  apk) build_apk ;;
  glasses) build_glasses ;;
  *) echo "usage: build_all.sh [all|win|apk|glasses]"; exit 2 ;;
esac

echo; echo "===== build summary ====="
for a in "${ok[@]:-}"; do [ -n "$a" ] && echo "  OK   $a"; done
for f in "${fail[@]:-}"; do [ -n "$f" ] && echo "  FAIL $f"; done
[ ${#fail[@]} -eq 0 ]
