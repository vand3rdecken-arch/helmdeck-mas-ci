#!/usr/bin/env bash
# Publish a self-hosted OTA update (Paseo-style silent updates): export the JS
# bundle and ship it to the relay's /opt/helmdeck-updates. The app pulls it on
# next launch - no reinstall, no APK, no Expo cloud. Only JS/asset changes ride
# OTA; native changes still need `release.sh android`.
#
#   bash ops/deploy/push_update.sh                 # export + upload (production)
#   bash ops/deploy/push_update.sh --no-build      # upload the existing surfaces/app/dist-ota as-is
#   bash ops/deploy/push_update.sh --channel beta  # publish to the "beta" channel
#
# Channels: production = /opt/helmdeck-updates (what every stock build follows);
# any other name lands in /opt/helmdeck-updates-<name> and is only served to
# builds whose expo-channel-name matches (app.json updates.requestHeaders).
# Publishing also clears any rollback marker for that channel (the dir swap).
#
# Desktop OTA (Paseo auto-update for the Electron shell): the same run ALSO
# exports the web bundle and publishes it + a desktop.json manifest to the
# "desktop" channel dir (/opt/helmdeck-updates-desktop, or -desktop-<name>).
# The desktop clients (surfaces/desktop/updater.js in the Electron app, surfaces/desktop/tray.py
# via desktop_update.py) poll that manifest silently - check at start + every
# 30 min, download + sha256-verify, swap in on quit / when the shell is idle -
# so the desktop follows every publish without a reinstall, like the phone.
# A desktop-side failure warns loudly but never blocks the phone OTA that
# already shipped.
#
# Needs .env with RELAY_HOST / RELAY_SSH_* (same as push_relay.sh) - UNLESS a
# relay is running on this box (see LOCAL FALLBACK below), in which case
# neither is read.
set -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
[ -f .env ] && set -a && . ./.env && set +a
export PATH="/c/Program Files/nodejs:$PATH"

# LOCAL FALLBACK (2026-09-08: trooper, the VM RELAY_HOST used to point at, is
# dead). If a relay answers on THIS box (ops/deploy/relay_local.cmd), publish
# straight into the directories it reads from - surfaces/relay/relay.py
# rebuilds every manifest from disk per request, so no restart is needed. No
# SSH, no VM, and a stale RELAY_HOST in .env no longer blocks a ship. A live
# /health probe is the signal (never a stored flag - the same rule as
# drivers.turn_active): the moment a real relay comes back at RELAY_HOST, this
# probe simply stops matching and the old remote path resumes untouched.
RELAY_PORT="${HELMDECK_RELAY_PORT:-6790}"
RELAY_LOCAL=0; WORKER=0
RELAY_DOMAIN="${RELAY_DOMAIN:-relay.helmdeck.de}"
if curl -s -m3 "http://127.0.0.1:$RELAY_PORT/health" 2>/dev/null | grep -q '"ok": *true'; then
  RELAY_LOCAL=1
  # Same default relay.py itself falls back to (HELMDECK_UPDATES_DIR unset in
  # relay_local.cmd) - os.path resolves a leading "/" against the process's
  # current drive, which MSYS bash maps to /c/opt/... for the identical target.
  LOCAL_UPDATES_DIR="${HELMDECK_UPDATES_DIR:-/c/opt/helmdeck-updates}"
  echo "==> local relay answering on 127.0.0.1:$RELAY_PORT - publishing to $LOCAL_UPDATES_DIR (no SSH)"
elif curl -s -m8 "https://$RELAY_DOMAIN/health" 2>/dev/null | grep -q '"edge": *true'; then
  # CLOUDFLARE WORKER (2026-09-22, surfaces/relay/worker): the public relay is
  # the worker, which serves OTA bundles as its own static assets. Stage into
  # the same local channel dirs the local-relay path uses, then let
  # publish_relay_worker.sh pack every channel and deploy - that deploy IS the
  # upload. Same probe-not-flag rule as above: if the public URL ever answers
  # from something else again, this branch simply stops matching.
  RELAY_LOCAL=1; WORKER=1
  LOCAL_UPDATES_DIR="${HELMDECK_UPDATES_DIR:-/c/opt/helmdeck-updates}"
  echo "==> public relay is the Cloudflare worker - staging to $LOCAL_UPDATES_DIR, deploying via publish_relay_worker.sh"
else
  : "${RELAY_HOST:?set RELAY_HOST (VM public IP) in .env, or start the local relay (ops/deploy/relay_local.cmd)}"
  RELAY_DOMAIN="${RELAY_DOMAIN:-${RELAY_HOST}.sslip.io}"
  SSH_USER="${RELAY_SSH_USER:-ubuntu}"
  SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
  [ -n "${RELAY_SSH_KEY:-}" ] && SSH_OPTS+=(-i "$RELAY_SSH_KEY")
  TARGET="$SSH_USER@$RELAY_HOST"
fi

NO_BUILD=0; CHANNEL=""; RUNTIME=""; RT_PLATFORM="android"; DESKTOP_ONLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --no-build) NO_BUILD=1 ;;
    --channel)  CHANNEL="${2:-}"; shift ;;
    # --desktop-only: web export + "desktop" channel only. Phones are NOT
    # touched - for a change that only matters in the Electron shell (the
    # desktop settings panel, 2026-09-22) there is no reason to push a new
    # OTA to every phone.
    --desktop-only) DESKTOP_ONLY=1 ;;
    # --runtime X: publish THIS bundle for a STRANDED runtimeVersion X - an APK
    # still on X after app.json moved on (e.g. an iOS-only version bump). Only
    # valid when that platform's native is unchanged since X. Lands in the
    # channel dir "rt-X"; the relay serves it to a phone asking for X
    # (surfaces/relay/relay.py, manifest route). Android only - no desktop leg.
    --runtime)  RUNTIME="${2:-}"; shift ;;
    # --platform P (with --runtime only): which phone platform that runtime is
    # for. Default android; the per-platform split below calls itself with ios.
    --platform) RT_PLATFORM="${2:-}"; shift ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
  shift
done
case "$CHANNEL" in production) CHANNEL="" ;; *[!A-Za-z0-9._-]*) echo "bad channel name"; exit 2 ;; esac
if [ -n "$RUNTIME" ]; then
  case "$RUNTIME" in *[!0-9.]*) echo "bad runtime"; exit 2 ;; esac
  [ -n "$CHANNEL" ] && { echo "--runtime and --channel are exclusive"; exit 2; }
  CHANNEL="rt-$RUNTIME"
  case "$RT_PLATFORM" in android|ios|both) ;; *) echo "bad platform"; exit 2 ;; esac
fi

# Phone platforms this publish serves. BOTH land in the one dist-ota export
# (metadata.json fileMetadata.<platform>, which relay.py picks per the client's
# expo-platform header). Until 2026-09-14 this was android only - no iOS bundle
# was ever published, every iPhone got 404. A --runtime publish stays android
# only (the stranded-APK case it was built for).
# runtimeVersion is PER PLATFORM since 2026-10-19 (app.json android/ios
# .runtimeVersion, Expo's platform-specific form): a native change on one
# platform no longer moves the other's runtime. While both agree, one export
# serves both, as before. When they differ, this run publishes android on the
# main channel and calls itself once for ios into "rt-<ios runtime>" - the
# relay's existing stranded-runtime fallback serves it (relay.py / worker).
APPJSON_RT() { py -3.12 -c "import json,sys;e=json.load(open('surfaces/app/app.json',encoding='utf-8'))['expo'];print((e.get(sys.argv[1]) or {}).get('runtimeVersion') or e['version'],end='')" "$1" 2>/dev/null; }
RTV_ANDROID="$(APPJSON_RT android)"; RTV_IOS="$(APPJSON_RT ios)"
OTA_PLATFORMS="android ios"
IOS_SPLIT=0
[ -z "$RUNTIME" ] && [ "$RTV_IOS" != "$RTV_ANDROID" ] && { OTA_PLATFORMS="android"; IOS_SPLIT=1; }
[ -n "$RUNTIME" ] && OTA_PLATFORMS="$RT_PLATFORM"
# both: ONE export for a runtime two platforms share - the channel dir is
# swapped whole on publish, so two single-platform publishes into the same
# rt-X would each delete the other's bundle (2026-10-20: ios rt-1.0.53 and the
# previous android 1.0.53 APK).
[ "$OTA_PLATFORMS" = "both" ] && OTA_PLATFORMS="android ios"
[ "$DESKTOP_ONLY" = "1" ] && { OTA_PLATFORMS=""; [ -n "$RUNTIME" ] && { echo "--desktop-only and --runtime are exclusive"; exit 2; }; }

# Record the runtimeVersion this bundle was exported for (policy=appVersion, so it
# is expo.version). The relay reads this marker to VALIDATE the client's
# expo-runtime-version instead of echoing it back - without it the crash-loop
# protection never fires (see relay.py _bundle_rtv). Packed with the export.
RTV="${RUNTIME:-$RTV_ANDROID}"

# NO OTA FOR A RUNTIME NO ANDROID PHONE CAN RUN (2026-10-18): app.json went to 1.0.53 on 10-10 for an iOS
# fix, no 1.0.53 APK was ever released, and eight days of OTAs went to a runtime no Android phone had -
# while apk/version.json still said 1.0.52, so the in-app "new APK" banner never fired either. The
# released APK (the relay's version.json, the same file the banner reads) must BE this runtime before
# any phone OTA ships for it: release the native build first (build_apk.sh + push_apk.sh).
if [ "$DESKTOP_ONLY" != "1" ] && [ -z "$RUNTIME" ] && [ "${ALLOW_NO_APK:-0}" != "1" ]; then
  # push_apk.sh writes the staged version.json only AFTER the APK upload is proven, and THIS run's worker
  # deploy is what puts it live - so the staged file is the truth for this publish, the live one the fallback.
  APK_VJ="${HELMDECK_APK_DIR:-/c/opt/helmdeck-apk}/version.json"
  if [ -f "$APK_VJ" ]; then APK_SRC=$(cat "$APK_VJ"); else APK_SRC=$(curl -s -m20 "https://$RELAY_DOMAIN/apk/version.json"); fi
  # runtimeVersion (push_apk.sh since 2026-10-19), versionName for an older version.json
  LIVE_APK=$(printf '%s' "$APK_SRC" | py -3.12 -c "import json,sys;d=json.load(sys.stdin);print(d.get('runtimeVersion') or d.get('versionName',''),end='')" 2>/dev/null)
  if [ "$LIVE_APK" != "$RTV" ]; then
    echo "!!! REFUSING: this OTA targets runtime $RTV, the released Android APK is '${LIVE_APK:-unreadable}'."
    echo "!!! No Android phone could receive it. Release the APK first: bash ops/deploy/build_apk.sh && bash ops/deploy/push_apk.sh"
    echo "!!! (ALLOW_NO_APK=1 overrides - only when no Android install exists.)"
    exit 1
  fi
fi

if [ "$DESKTOP_ONLY" != "1" ]; then
if [ "$NO_BUILD" != "1" ]; then
  echo "==> expo export ($OTA_PLATFORMS)"
  # export to a SEPARATE dir, not surfaces/app/dist: surfaces/app/dist is the WEB build the Electron
  # desktop serves - clobbering it with the phone bundles 404s the desktop.
  PLAT_ARGS=(); for p in $OTA_PLATFORMS; do PLAT_ARGS+=(--platform "$p"); done
  ( cd surfaces/app && rm -rf dist-ota && npx expo export "${PLAT_ARGS[@]}" --output-dir dist-ota ) || exit 1
fi
[ -f surfaces/app/dist-ota/metadata.json ] || { echo "no surfaces/app/dist-ota/metadata.json - run without --no-build"; exit 1; }
[ -n "$RTV" ] && { printf '%s' "$RTV" > surfaces/app/dist-ota/runtimeVersion; echo "==> bundle runtimeVersion marker: $RTV"; }

if [ "$RELAY_LOCAL" = "1" ]; then
  echo "==> publish locally"
  DEST="${LOCAL_UPDATES_DIR}${CHANNEL:+-$CHANNEL}"
  # same atomic .new/.old swap as the remote path, just without ssh/sudo
  rm -rf "$DEST.new"
  mkdir -p "$DEST.new"
  cp -r surfaces/app/dist-ota/. "$DEST.new/" || exit 1
  rm -rf "$DEST.old"
  [ -d "$DEST" ] && mv "$DEST" "$DEST.old"
  mv "$DEST.new" "$DEST"
  echo "published to $DEST: $([ -f "$DEST/metadata.json" ] && echo ok)"
else
  echo "==> pack + upload the export"
  tar -C surfaces/app/dist-ota -czf /tmp/hd-update.tgz . || exit 1
  scp "${SSH_OPTS[@]}" /tmp/hd-update.tgz "$TARGET:/tmp/hd-update.tgz" || exit 1

  # atomic swap on the VM so the relay never serves a half-written update dir
  ssh "${SSH_OPTS[@]}" "$TARGET" 'bash -s' -- "$CHANNEL" <<'REMOTE'
set -e
DEST="/opt/helmdeck-updates${1:+-$1}"
sudo rm -rf "$DEST.new"
sudo mkdir -p "$DEST.new"
sudo tar -C "$DEST.new" -xzf /tmp/hd-update.tgz
sudo rm -rf "$DEST.old"
[ -d "$DEST" ] && sudo mv "$DEST" "$DEST.old" || true
sudo mv "$DEST.new" "$DEST"
sudo chmod -R a+rX "$DEST"
echo "published to $DEST: $(sudo test -f "$DEST/metadata.json" && echo ok)"
REMOTE
fi
fi   # DESKTOP_ONLY

# A REAL check per platform: the status code, not a piped preview (a `| head`
# preview SIGPIPEs curl under pipefail and once had to be `|| true`'d, which is
# how a platform that 404'd every time shipped green). Any non-200 fails the
# run - after the desktop leg, so a phone-side miss never holds the desktop.
# In worker mode this runs AFTER the worker deploy (that is the upload).
VERIFY_FAILED=""
phone_verify() {
  echo "==> verify live manifest"
  local PLAT CODE
  for PLAT in $OTA_PLATFORMS; do
    CODE=$(curl -s -m20 -o /dev/null -w '%{http_code}' -H "expo-platform: $PLAT" -H "expo-runtime-version: $RTV" \
         -H "expo-protocol-version: 1" ${CHANNEL:+-H "expo-channel-name: $CHANNEL"} \
         "https://$RELAY_DOMAIN/updates/manifest")
    echo "  $PLAT @ $RTV: HTTP $CODE"
    [ "$CODE" = "200" ] || VERIFY_FAILED="$VERIFY_FAILED $PLAT"
  done
}
[ "$WORKER" = "1" ] || phone_verify

# ---- desktop channel (phone OTA above already shipped; failures here WARN) ----
desktop_publish() {
  local DCHAN="desktop${CHANNEL:+-$CHANNEL}"
  if [ "$NO_BUILD" != "1" ]; then
    echo "==> expo export (web) for the desktop channel"
    # separate dir for the same reason as dist-ota: surfaces/app/dist is what a local
    # Electron dev run serves, and dist-ota is the android bundle.
    ( cd surfaces/app && rm -rf dist-desktop && npx expo export --platform web --output-dir dist-desktop ) || return 1
  fi
  [ -f surfaces/app/dist-desktop/index.html ] || { echo "no surfaces/app/dist-desktop/index.html - web export missing"; return 1; }
  echo "==> desktop.json manifest"
  py -3.12 ops/deploy/desktop_manifest.py surfaces/app/dist-desktop "$RTV" || return 1

  if [ "$RELAY_LOCAL" = "1" ]; then
    echo "==> publish desktop export locally ($DCHAN)"
    DEST="${LOCAL_UPDATES_DIR}-$DCHAN"
    rm -rf "$DEST.new"
    mkdir -p "$DEST.new"
    cp -r surfaces/app/dist-desktop/. "$DEST.new/" || return 1
    rm -rf "$DEST.old"
    [ -d "$DEST" ] && mv "$DEST" "$DEST.old"
    mv "$DEST.new" "$DEST"
    echo "published to $DEST: $([ -f "$DEST/desktop.json" ] && echo ok)"
  else
    echo "==> pack + upload the desktop export ($DCHAN)"
    tar -C surfaces/app/dist-desktop -czf /tmp/hd-desktop.tgz . || return 1
    scp "${SSH_OPTS[@]}" /tmp/hd-desktop.tgz "$TARGET:/tmp/hd-desktop.tgz" || return 1
    # same atomic swap as the phone dir; the channel dir sits BESIDE the root
    # updates dir, so neither swap can take the other along.
    ssh "${SSH_OPTS[@]}" "$TARGET" 'bash -s' -- "$DCHAN" <<'REMOTE' || return 1
set -e
DEST="/opt/helmdeck-updates-$1"
sudo rm -rf "$DEST.new"
sudo mkdir -p "$DEST.new"
sudo tar -C "$DEST.new" -xzf /tmp/hd-desktop.tgz
sudo rm -rf "$DEST.old"
[ -d "$DEST" ] && sudo mv "$DEST" "$DEST.old" || true
sudo mv "$DEST.new" "$DEST"
sudo chmod -R a+rX "$DEST"
echo "published to $DEST: $(sudo test -f "$DEST/desktop.json" && echo ok)"
REMOTE
  fi

  [ "$WORKER" = "1" ] && return 0     # verified after the worker deploy below
  echo "==> verify live desktop manifest"
  # same SIGPIPE-vs-head note as the phone verify above - cosmetic, not a check.
  curl -s -m20 "https://$RELAY_DOMAIN/updates/assets?path=desktop.json&channel=$DCHAN" | head -c 200 || true
  echo
}
if [ -n "$RUNTIME" ]; then
  echo "==> --runtime $RUNTIME: $RT_PLATFORM-only stranded-runtime publish, desktop untouched"
elif ! desktop_publish; then
  echo "!!! DESKTOP OTA PUBLISH FAILED - the phone update above is live, but the"
  echo "!!! desktop stays on its old bundle until the next successful publish."
fi

if [ "$WORKER" = "1" ]; then
  # Every channel dir under /c/opt is packed and deployed together - the ones
  # this run did not touch simply ship again unchanged.
  bash ops/deploy/publish_relay_worker.sh || { echo "!!! WORKER DEPLOY FAILED - nothing went live"; exit 1; }
  phone_verify
  # a --runtime publish leaves the desktop untouched (above) - there is no
  # desktop-rt-X channel, so checking one only printed a scary 404
  if [ -z "$RUNTIME" ]; then
    DCHAN="desktop${CHANNEL:+-$CHANNEL}"
    CODE=$(curl -s -m20 -o /dev/null -w '%{http_code}' "https://$RELAY_DOMAIN/updates/assets?path=desktop.json&channel=$DCHAN")
    echo "  desktop.json ($DCHAN): HTTP $CODE"
  fi
fi
# STRANDED RUNTIMES - the phones whose binary is not the current one.
#  - iOS on its own runtime (IOS_SPLIT, the 1.0.53 incident above);
#  - NO BREAK FOR THE PREVIOUS APK (owner 2026-10-20, "keine Brüche mehr für
#    version"): after a native ship the phones still on the previous APK got NO
#    OTA at all - not even the screen telling them to install the new one. The
#    bundle also goes to rt-<previous android runtime>, but ONLY when
#    test_native_optional proves it cannot white-screen there (every native
#    package added since that APK is reached via requireOptionalNativeModule).
#    If the proof fails, it says so loudly and that channel is left alone.
# Both targets collected first: when they share a runtime it is ONE publish
# with both platforms (the channel dir is swapped whole - see --platform both).
if [ -z "$RUNTIME" ] && [ "$NO_BUILD" != "1" ] && [ "$DESKTOP_ONLY" != "1" ]; then
  RT_IOS_T=""; RT_AND_T=""
  [ "$IOS_SPLIT" = "1" ] && RT_IOS_T="$RTV_IOS"
  PREV_RT="$(py -3.12 ops/tests/test_native_optional.py --print-prev 2>/dev/null | tail -1)"
  if [ -n "$PREV_RT" ] && [ "$PREV_RT" != "$RTV_ANDROID" ]; then
    if py -3.12 ops/tests/test_native_optional.py --runtime "$PREV_RT"; then
      RT_AND_T="$PREV_RT"
    else
      echo "!!! rt-$PREV_RT (android) NOT published: this bundle imports a native module the $PREV_RT APK"
      echo "!!! does not have (see above). Phones on that APK keep their old JS until they install the new APK."
    fi
  fi
  if [ -n "$RT_IOS_T" ] && [ "$RT_IOS_T" = "$RT_AND_T" ]; then
    echo "==> ios and the previous android APK share runtime $RT_IOS_T - one publish into rt-$RT_IOS_T"
    bash "$0" --runtime "$RT_IOS_T" --platform both || VERIFY_FAILED="$VERIFY_FAILED ios+android-$RT_IOS_T"
  else
    if [ -n "$RT_IOS_T" ]; then
      echo "==> ios runtime $RTV_IOS differs from android $RTV_ANDROID - publishing ios into rt-$RTV_IOS"
      bash "$0" --runtime "$RT_IOS_T" --platform ios || VERIFY_FAILED="$VERIFY_FAILED ios"
    fi
    if [ -n "$RT_AND_T" ]; then
      echo "==> previous android runtime $RT_AND_T keeps receiving this bundle (rt-$RT_AND_T)"
      bash "$0" --runtime "$RT_AND_T" --platform android || VERIFY_FAILED="$VERIFY_FAILED android-$RT_AND_T"
    fi
  fi
fi
if [ -n "$VERIFY_FAILED" ]; then
  echo "!!! PHONE OTA VERIFY FAILED for:$VERIFY_FAILED - the relay serves no update"
  echo "!!! for runtimeVersion $RTV on that platform. Phones there stay on their old JS."
  exit 1
fi
