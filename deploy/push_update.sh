#!/usr/bin/env bash
# Publish a self-hosted OTA update (Paseo-style silent updates): export the JS
# bundle and ship it to the relay's /opt/helmdeck-updates. The app pulls it on
# next launch - no reinstall, no APK, no Expo cloud. Only JS/asset changes ride
# OTA; native changes still need `release.sh android`.
#
#   bash deploy/push_update.sh                 # export + upload (production)
#   bash deploy/push_update.sh --no-build      # upload the existing app/dist-ota as-is
#   bash deploy/push_update.sh --channel beta  # publish to the "beta" channel
#
# Channels: production = /opt/helmdeck-updates (what every stock build follows);
# any other name lands in /opt/helmdeck-updates-<name> and is only served to
# builds whose expo-channel-name matches (app.json updates.requestHeaders).
# Publishing also clears any rollback marker for that channel (the dir swap).
#
# Needs .env with RELAY_HOST / RELAY_SSH_* (same as push_relay.sh).
set -o pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
[ -f .env ] && set -a && . ./.env && set +a
: "${RELAY_HOST:?set RELAY_HOST (VM public IP) in .env}"
RELAY_DOMAIN="${RELAY_DOMAIN:-${RELAY_HOST}.sslip.io}"
SSH_USER="${RELAY_SSH_USER:-ubuntu}"
SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
[ -n "${RELAY_SSH_KEY:-}" ] && SSH_OPTS+=(-i "$RELAY_SSH_KEY")
TARGET="$SSH_USER@$RELAY_HOST"
export PATH="/c/Program Files/nodejs:$PATH"

NO_BUILD=0; CHANNEL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --no-build) NO_BUILD=1 ;;
    --channel)  CHANNEL="${2:-}"; shift ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
  shift
done
case "$CHANNEL" in production) CHANNEL="" ;; *[!A-Za-z0-9._-]*) echo "bad channel name"; exit 2 ;; esac

if [ "$NO_BUILD" != "1" ]; then
  echo "==> expo export (android)"
  # export to a SEPARATE dir, not app/dist: app/dist is the WEB build the Electron
  # desktop serves - clobbering it with the android bundle 404s the desktop.
  ( cd app && rm -rf dist-ota && npx expo export --platform android --output-dir dist-ota ) || exit 1
fi
[ -f app/dist-ota/metadata.json ] || { echo "no app/dist-ota/metadata.json - run without --no-build"; exit 1; }

# Record the runtimeVersion this bundle was exported for (policy=appVersion, so it
# is expo.version). The relay reads this marker to VALIDATE the client's
# expo-runtime-version instead of echoing it back - without it the crash-loop
# protection never fires (see relay.py _bundle_rtv). Packed with the export.
RTV="$(py -3.12 -c "import json;print(json.load(open('app/app.json',encoding='utf-8'))['expo']['version'],end='')" 2>/dev/null)"
[ -n "$RTV" ] && { printf '%s' "$RTV" > app/dist-ota/runtimeVersion; echo "==> bundle runtimeVersion marker: $RTV"; }

echo "==> pack + upload the export"
tar -C app/dist-ota -czf /tmp/hd-update.tgz . || exit 1
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

echo "==> verify live manifest"
# runtimeVersion policy is "appVersion", so the live rtv == expo.version. Derive
# it (don't hardcode) or the verify HEAD mismatches after a native version bump.
RTV="$(py -3.12 -c 'import json;print(json.load(open("app/app.json",encoding="utf-8"))["expo"]["version"])' 2>/dev/null || echo 1.0.0)"
curl -s -m20 -H "expo-platform: android" -H "expo-runtime-version: $RTV" \
     -H "expo-protocol-version: 1" ${CHANNEL:+-H "expo-channel-name: $CHANNEL"} \
     "https://$RELAY_DOMAIN/updates/manifest" \
  | head -c 240
echo
