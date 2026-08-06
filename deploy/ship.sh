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
  # Fingerprint the NATIVE config only. EXCLUDE the version fields that bump_version
  # + build_apk.sh change (app.json version/versionCode, the manifest's
  # EXPO_RUNTIME_VERSION): including them made every post-bump accept look like a
  # fresh native change and bump again, so the version crept 1.0.2->1.0.3->1.0.4 with
  # no real native change. Now a version bump never moves the fingerprint, so it
  # stabilises after one cycle and JS-only accepts stop bumping.
  { sed -n 's/.*\("expo[^"]*"\|"react-native[^"]*"\).*/\1/p' app/package.json
    grep -vE '"version"[[:space:]]*:|"versionCode"[[:space:]]*:' app/app.json 2>/dev/null
    grep -v "EXPO_RUNTIME_VERSION" app/android/app/src/main/AndroidManifest.xml 2>/dev/null
  } | sha256sum | cut -d' ' -f1
}

# Bump expo.version (patch) + android.versionCode in app/app.json. runtimeVersion
# policy is "appVersion", so bumping the version bumps the runtimeVersion too: an
# OLD APK (old version) then REJECTS this new JS (rtv mismatch) instead of loading
# it and crashing on a native module it doesn't have (the ExpoDocumentPicker trap).
# JS-only ships keep the version, so phones still receive those OTAs. Prints the
# new "version versionCode".
bump_version() {
  py -3.12 - <<'PY'
import json
p = "app/app.json"
d = json.load(open(p, encoding="utf-8"))
e = d["expo"]
parts = (e.get("version", "1.0.0").split(".") + ["0", "0"])[:3]
e["version"] = f"{parts[0]}.{parts[1]}.{int(parts[2]) + 1}"
e.setdefault("android", {})
e["android"]["versionCode"] = int(e["android"].get("versionCode", 0)) + 1
with open(p, "w", encoding="utf-8") as f:
    json.dump(d, f, indent=2, ensure_ascii=False)
    f.write("\n")
print(e["version"], e["android"]["versionCode"])
PY
}

CUR="$(native_fp)"
LAST="$(cat deploy/.native_fp 2>/dev/null || true)"

if [ -n "$LAST" ] && [ "$CUR" = "$LAST" ]; then
  echo "[ship] JS-only change -> OTA"
  bash deploy/push_update.sh
else
  echo "[ship] native change detected -> bump runtimeVersion, APK build + emulator test + distribute"
  BUMP="$(bump_version)" || { echo "[ship] version bump failed"; exit 1; }
  echo "[ship] version -> $BUMP (new runtimeVersion; old APKs will reject this JS instead of crashing)"
  if ! bash deploy/build_apk.sh; then
    echo "[ship] APK path failed - reverting version bump, NOT recording fingerprint"
    git checkout -- app/app.json 2>/dev/null || true
    exit 1
  fi
  # keep the OTA bundle matched to the new APK (else the old relay bundle reverts
  # the APK's JS on next launch - the source-of-truth trap in DEPLOY.md). The OTA
  # manifest inherits the new runtimeVersion from the bumped app.json.
  bash deploy/push_update.sh
  git add app/app.json && git commit -q -m "deploy: bump version+runtimeVersion for native change ($BUMP)" 2>/dev/null || true
  # record the POST-bump fingerprint so the next unchanged ship is seen as JS-only
  native_fp > deploy/.native_fp
fi
echo "[ship] done"
