#!/usr/bin/env bash
# Fast-track deploy step (the repo 'deploy' hook points here). Decides HOW to ship
# the just-accepted change:
#   - JS / assets only        -> OTA (deploy/push_update.sh), seconds
#   - native change (a native module, permission, app.json plugin, manifest)
#     -> build a fresh APK, emulator-smoke it, distribute it (deploy/build_apk.sh),
#        THEN also push a matching OTA so the relay bundle can't revert the APK's JS.
# Native-vs-JS is decided by a fingerprint of the files that change the APK.
set -o pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"

native_fp() {
  { sed -n 's/.*\("expo[^"]*"\|"react-native[^"]*"\).*/\1/p' app/package.json
    cat app/app.json 2>/dev/null
    cat app/android/app/src/main/AndroidManifest.xml 2>/dev/null
  } | sha256sum | cut -d' ' -f1
}

CUR="$(native_fp)"
LAST="$(cat deploy/.native_fp 2>/dev/null || true)"

if [ -n "$LAST" ] && [ "$CUR" = "$LAST" ]; then
  echo "[ship] JS-only change -> OTA"
  bash deploy/push_update.sh
else
  echo "[ship] native change detected -> APK build + emulator test + distribute"
  bash deploy/build_apk.sh || { echo "[ship] APK path failed - NOT recording fingerprint"; exit 1; }
  # keep the OTA bundle matched to the new APK (else the old relay bundle reverts
  # the APK's JS on next launch - the source-of-truth trap in DEPLOY.md).
  bash deploy/push_update.sh
  echo "$CUR" > deploy/.native_fp
fi
echo "[ship] done"
