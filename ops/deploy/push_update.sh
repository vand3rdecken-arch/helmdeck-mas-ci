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
RELAY_LOCAL=0
if curl -s -m3 "http://127.0.0.1:$RELAY_PORT/health" 2>/dev/null | grep -q '"ok": *true'; then
  RELAY_LOCAL=1
  # Same default relay.py itself falls back to (HELMDECK_UPDATES_DIR unset in
  # relay_local.cmd) - os.path resolves a leading "/" against the process's
  # current drive, which MSYS bash maps to /c/opt/... for the identical target.
  LOCAL_UPDATES_DIR="${HELMDECK_UPDATES_DIR:-/c/opt/helmdeck-updates}"
  RELAY_DOMAIN="${RELAY_DOMAIN:-relay.helmdeck.de}"
  echo "==> local relay answering on 127.0.0.1:$RELAY_PORT - publishing to $LOCAL_UPDATES_DIR (no SSH)"
else
  : "${RELAY_HOST:?set RELAY_HOST (VM public IP) in .env, or start the local relay (ops/deploy/relay_local.cmd)}"
  RELAY_DOMAIN="${RELAY_DOMAIN:-${RELAY_HOST}.sslip.io}"
  SSH_USER="${RELAY_SSH_USER:-ubuntu}"
  SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
  [ -n "${RELAY_SSH_KEY:-}" ] && SSH_OPTS+=(-i "$RELAY_SSH_KEY")
  TARGET="$SSH_USER@$RELAY_HOST"
fi

NO_BUILD=0; CHANNEL=""; RUNTIME=""
while [ $# -gt 0 ]; do
  case "$1" in
    --no-build) NO_BUILD=1 ;;
    --channel)  CHANNEL="${2:-}"; shift ;;
    # --runtime X: publish THIS bundle for a STRANDED runtimeVersion X - an APK
    # still on X after app.json moved on (e.g. an iOS-only version bump). Only
    # valid when that platform's native is unchanged since X. Lands in the
    # channel dir "rt-X"; the relay serves it to a phone asking for X
    # (surfaces/relay/relay.py, manifest route). Android only - no desktop leg.
    --runtime)  RUNTIME="${2:-}"; shift ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
  shift
done
case "$CHANNEL" in production) CHANNEL="" ;; *[!A-Za-z0-9._-]*) echo "bad channel name"; exit 2 ;; esac
if [ -n "$RUNTIME" ]; then
  case "$RUNTIME" in *[!0-9.]*) echo "bad runtime"; exit 2 ;; esac
  [ -n "$CHANNEL" ] && { echo "--runtime and --channel are exclusive"; exit 2; }
  CHANNEL="rt-$RUNTIME"
fi

if [ "$NO_BUILD" != "1" ]; then
  echo "==> expo export (android)"
  # export to a SEPARATE dir, not surfaces/app/dist: surfaces/app/dist is the WEB build the Electron
  # desktop serves - clobbering it with the android bundle 404s the desktop.
  ( cd surfaces/app && rm -rf dist-ota && npx expo export --platform android --output-dir dist-ota ) || exit 1
fi
[ -f surfaces/app/dist-ota/metadata.json ] || { echo "no surfaces/app/dist-ota/metadata.json - run without --no-build"; exit 1; }

# Record the runtimeVersion this bundle was exported for (policy=appVersion, so it
# is expo.version). The relay reads this marker to VALIDATE the client's
# expo-runtime-version instead of echoing it back - without it the crash-loop
# protection never fires (see relay.py _bundle_rtv). Packed with the export.
RTV="${RUNTIME:-$(py -3.12 -c "import json;print(json.load(open('surfaces/app/app.json',encoding='utf-8'))['expo']['version'],end='')" 2>/dev/null)}"
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

echo "==> verify live manifest"
# runtimeVersion policy is "appVersion", so the live rtv == expo.version. Derive
# it (don't hardcode) or the verify HEAD mismatches after a native version bump.
RTV="${RUNTIME:-$(py -3.12 -c 'import json;print(json.load(open("surfaces/app/app.json",encoding="utf-8"))["expo"]["version"])' 2>/dev/null || echo 1.0.0)}"
# `|| true`: this is a COSMETIC preview for the human/log, not a functional
# check - under `set -o pipefail`, curl legitimately gets SIGPIPE'd ("(23)
# Failed writing body") the instant `head -c` closes the pipe after its byte
# count, since curl is usually still mid-write on the rest of the (longer)
# manifest response. That's expected, not a real failure, but pipefail was
# letting it read as one - scaring an owner into "deploy hook failed" on a
# publish that fully succeeded (verified: files uploaded, manifest live).
curl -s -m20 -H "expo-platform: android" -H "expo-runtime-version: $RTV" \
     -H "expo-protocol-version: 1" ${CHANNEL:+-H "expo-channel-name: $CHANNEL"} \
     "https://$RELAY_DOMAIN/updates/manifest" \
  | head -c 240 || true
echo

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

  echo "==> verify live desktop manifest"
  # same SIGPIPE-vs-head note as the phone verify above - cosmetic, not a check.
  curl -s -m20 "https://$RELAY_DOMAIN/updates/assets?path=desktop.json&channel=$DCHAN" | head -c 200 || true
  echo
}
if [ -n "$RUNTIME" ]; then
  echo "==> --runtime $RUNTIME: android-only stranded-runtime publish, desktop untouched"
elif ! desktop_publish; then
  echo "!!! DESKTOP OTA PUBLISH FAILED - the phone update above is live, but the"
  echo "!!! desktop stays on its old bundle until the next successful publish."
fi
