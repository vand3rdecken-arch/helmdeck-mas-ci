#!/usr/bin/env bash
# Fast-track deploy step (the repo 'deploy' hook points here). Decides HOW to ship
# the just-accepted change:
#   - JS / assets only        -> OTA (ops/deploy/push_update.sh), seconds
#   - native change (a native module, permission, app.json plugin, manifest)
#     -> build a fresh APK, emulator-smoke it, distribute it (ops/deploy/build_apk.sh),
#        THEN also push a matching OTA so the relay bundle can't revert the APK's JS.
# Native-vs-JS is decided by a fingerprint of the files that change the APK.
set -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"

# SHIP SINGLETON (2026-08-21): one ship per repo, join-or-wait, never stack.
# Measured incident: two accepts minutes apart each fired this hook - two
# `npm ci` + two Gradle builds in the SAME app/ tree shredded each other
# (EPERM/EBUSY on node_modules), and a daemon restart earlier orphaned a
# Gradle tree that then held locks against the next build. The lock is a
# LIVE-PID observation, not a stored flag: a lock whose pid is dead is stale
# and taken over (the Paseo rule - derive state from the runtime's own
# signals). A waiting ship simply proceeds when the holder exits; the
# fingerprint check right below then makes it a no-op if the holder already
# shipped this exact tree.
LOCK="$ROOT/.loop/ship.lock"
mkdir -p "$ROOT/.loop"
while ! mkdir "$LOCK" 2>/dev/null; do
  HOLDER="$(head -n1 "$LOCK/pid" 2>/dev/null)"
  if [ -n "$HOLDER" ] && kill -0 "$HOLDER" 2>/dev/null; then
    echo "[ship] another ship is running (pid $HOLDER) - waiting to join"
    sleep 15
  else
    echo "[ship] stale ship lock (pid ${HOLDER:-?} dead) - taking over"
    rm -rf "$LOCK"
  fi
done
# Line 1 = $$ (MSYS pid - what THIS script's own kill -0 check above needs).
# Line 2 = the real Windows PID (what the daemon's Python-side os.kill(pid, 0)
# health check needs - measured 2026-08-23: a live 40min gradle build was
# reported "dead" because only the MSYS pid was ever recorded, and Windows'
# process table has no such pid).
echo $$ > "$LOCK/pid"
cat /proc/$$/winpid 2>/dev/null >> "$LOCK/pid" || echo $$ >> "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT

cfg_fp() {
  # Fingerprint the ANDROID-relevant native config only. EXCLUDE the version
  # fields that bump_version + build_apk.sh change (app.json version/
  # versionCode, the manifest's EXPO_RUNTIME_VERSION): including them made
  # every post-bump accept look like a fresh native change and bump again, so
  # the version crept 1.0.2->1.0.3->1.0.4 with no real native change. Now a
  # version bump never moves the fingerprint, so it stabilises after one cycle
  # and JS-only accepts stop bumping.
  #
  # ALSO excludes app.json's "ios" and "extra" objects (fixed 2026-08-15 -
  # incident: three straight accepts that only touched ios.infoPlist,
  # ios.runtimeVersion and extra.eas.projectId/owner - all iOS/EAS metadata
  # with zero effect on the generated Android app - still fingerprinted as a
  # "native change" because the old version grepped the whole file. Android's
  # runtimeVersion policy is the shared top-level "appVersion", so each bump
  # forced a fresh Android runtimeVersion for a change Android never made -
  # orphaning every already-installed APK from OTA the moment app.json's
  # version outran the phone's baked-in one). Known residual gap: an
  # iOS-only field nested INSIDE a shared `plugins` entry (e.g. expo-camera's
  # `microphonePermission`, which only affects iOS's Info.plist) still moves
  # this fingerprint - accepted as a false positive (one extra APK build)
  # since the other direction (a false negative shipping an incompatible
  # native change as a bare OTA) is the one this must never get wrong.
  py -3.12 - <<'PY'
import hashlib, json
d = json.load(open("surfaces/app/app.json", encoding="utf-8"))
e = {k: v for k, v in d.get("expo", {}).items() if k not in ("ios", "extra")}
e.pop("version", None)
android = dict(e.get("android") or {})
android.pop("versionCode", None)
e["android"] = android
blob = json.dumps(e, sort_keys=True)
try:
    blob += open("surfaces/app/package.json", encoding="utf-8").read()
except FileNotFoundError:
    pass
try:
    manifest = open("surfaces/app/android/app/src/main/AndroidManifest.xml", encoding="utf-8").read()
    blob += "\n".join(l for l in manifest.splitlines() if "EXPO_RUNTIME_VERSION" not in l)
except FileNotFoundError:
    pass
# ICON/SPLASH ASSET BYTES (2026-08-26): app.json only stores PATHS to these
# files ("./assets/images/icon.png" etc.), so a redesign that swaps the PNG
# bytes without touching app.json moved this fingerprint by zero - a native
# rebuild (new launcher icon, new splash) silently classified as "JS-only"
# and shipped as a bare OTA that could never carry it. web-only favicon.png
# is deliberately excluded - it needs no native rebuild.
import glob, os
for path in sorted(
    ["surfaces/app/assets/images/icon.png",
     "surfaces/app/assets/images/splash-icon.png",
     "surfaces/app/assets/images/android-icon-foreground.png",
     "surfaces/app/assets/images/android-icon-background.png",
     "surfaces/app/assets/images/android-icon-monochrome.png"]
    + glob.glob("surfaces/app/assets/expo.icon/**/*", recursive=True)
):
    if not os.path.isfile(path):  # the glob also yields directories, and
        continue                  # Windows raises PermissionError (not
    try:                          # IsADirectoryError) opening those
        with open(path, "rb") as f:
            blob += path + hashlib.sha256(f.read()).hexdigest()
    except FileNotFoundError:
        pass
print(hashlib.sha256(blob.encode("utf-8")).hexdigest())
PY
}

# NATIVE SOURCE the plugins install into the android tree (measured gap
# 2026-08-23: a GlassVoiceService.kt change shipped as "JS-only" - exactly the
# false negative native_fp's comment says it must never produce). Every
# .kt/.java under app/plugins and surfaces/app/modules is compiled into the APK, so
# they are native config exactly like the manifest. A SEPARATE hash on purpose:
# the config half must be recorded from the END of a ship (build_apk stamps
# versionCode into the hand-managed manifest mid-run), but the source half
# must be recorded from the START (a module created while gradle ran is NOT in
# the APK, and the end-recompute claimed it was - that is how livemic almost
# never shipped). native_fp() combines both, so a stored combined hash of
# (end-config + start-sources) compares correctly against any later fresh one.
kt_fp() {
  py -3.12 - <<'PY'
import glob, hashlib
blob = ""
for src in sorted(glob.glob("surfaces/app/plugins/**/*.kt", recursive=True)
                  + glob.glob("surfaces/app/plugins/**/*.java", recursive=True)
                  + glob.glob("surfaces/app/modules/**/*.kt", recursive=True)
                  + glob.glob("surfaces/app/modules/**/*.java", recursive=True)):
    try:
        blob += src + "\n" + open(src, encoding="utf-8").read()
    except OSError:
        pass
print(hashlib.sha256(blob.encode("utf-8")).hexdigest())
PY
}

# combined fingerprint: sha256("<cfg> <kt>"). Always compare/record THIS shape.
combine_fp() { printf '%s %s' "$1" "$2" | py -3.12 -c "import sys,hashlib;print(hashlib.sha256(sys.stdin.read().encode()).hexdigest())"; }
native_fp() { combine_fp "$(cfg_fp)" "$(kt_fp)"; }

# Bump expo.version (patch) + android.versionCode in surfaces/app/app.json. runtimeVersion
# policy is "appVersion", so bumping the version bumps the runtimeVersion too: an
# OLD APK (old version) then REJECTS this new JS (rtv mismatch) instead of loading
# it and crashing on a native module it doesn't have (the ExpoDocumentPicker trap).
# JS-only ships keep the version, so phones still receive those OTAs. Prints the
# new "version versionCode".
bump_version() {
  py -3.12 - <<'PY'
import json
p = "surfaces/app/app.json"
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

KT_START="$(kt_fp)"
CUR="$(combine_fp "$(cfg_fp)" "$KT_START")"
LAST="$(cat ops/deploy/.native_fp 2>/dev/null || true)"

if [ -n "$LAST" ] && [ "$CUR" = "$LAST" ]; then
  echo "HOOK-NOTE: JS-only change - OTA export + publish (seconds)"
  echo "[ship] JS-only change -> OTA"
  # PROPAGATE a failed OTA: swallowing it printed '[ship] done' over a dead
  # push (expo export died on empty node_modules) - the phone silently never
  # got the update while every caller believed it shipped.
  bash ops/deploy/push_update.sh || { echo "[ship] OTA FAILED"; exit 1; }
else
  echo "HOOK-NOTE: native change detected - APK build starting (npm ci + gradle + emulator smoke, ~15-20 min)"
  echo "[ship] native change detected -> bump runtimeVersion, APK build + emulator test + distribute"
  BUMP="$(bump_version)" || { echo "[ship] version bump failed"; exit 1; }
  echo "[ship] version -> $BUMP (new runtimeVersion; old APKs will reject this JS instead of crashing)"
  if ! bash ops/deploy/build_apk.sh; then
    echo "[ship] APK path failed - reverting version bump, NOT recording fingerprint"
    git checkout -- surfaces/app/app.json 2>/dev/null || true
    exit 1
  fi
  echo "HOOK-NOTE: APK distributed - pushing the matching OTA bundle"
  # keep the OTA bundle matched to the new APK (else the old relay bundle reverts
  # the APK's JS on next launch - the source-of-truth trap in DEPLOY.md). The OTA
  # manifest inherits the new runtimeVersion from the bumped app.json.
  bash ops/deploy/push_update.sh || { echo "[ship] matching OTA FAILED - the old relay bundle would revert this APK's JS (DEPLOY.md trap)"; exit 1; }
  git add surfaces/app/app.json && git commit -q -m "deploy: bump version+runtimeVersion for native change ($BUMP)" 2>/dev/null || true
  # Record end-of-run CONFIG (build_apk stamped the manifest mid-run - that
  # mutation is this build's own deterministic output) + START-time SOURCES
  # (a module created while gradle ran is NOT in this APK - measured
  # 2026-08-23, the livemic near-miss). See kt_fp's header.
  combine_fp "$(cfg_fp)" "$KT_START" > ops/deploy/.native_fp
fi
echo "HOOK-NOTE: ship done - $([ -n "$LAST" ] && [ "$CUR" = "$LAST" ] && echo "OTA live" || echo "APK + matching OTA live")"
echo "[ship] done"
