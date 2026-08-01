#!/usr/bin/env bash
# Publish a self-hosted OTA update (Paseo-style silent updates): export the JS
# bundle and ship it to the relay's /opt/helmdeck-updates. The app pulls it on
# next launch - no reinstall, no APK, no Expo cloud. Only JS/asset changes ride
# OTA; native changes still need `release.sh android`.
#
#   bash deploy/push_update.sh            # export + upload
#   bash deploy/push_update.sh --no-build # upload the existing app/dist as-is
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

if [ "${1:-}" != "--no-build" ]; then
  echo "==> expo export (android)"
  ( cd app && rm -rf dist && npx expo export --platform android ) || exit 1
fi
[ -f app/dist/metadata.json ] || { echo "no app/dist/metadata.json - run without --no-build"; exit 1; }

echo "==> pack + upload the export"
tar -C app/dist -czf /tmp/hd-update.tgz . || exit 1
scp "${SSH_OPTS[@]}" /tmp/hd-update.tgz "$TARGET:/tmp/hd-update.tgz" || exit 1

# atomic swap on the VM so the relay never serves a half-written update dir
ssh "${SSH_OPTS[@]}" "$TARGET" 'bash -s' <<'REMOTE'
set -e
sudo rm -rf /opt/helmdeck-updates.new
sudo mkdir -p /opt/helmdeck-updates.new
sudo tar -C /opt/helmdeck-updates.new -xzf /tmp/hd-update.tgz
sudo rm -rf /opt/helmdeck-updates.old
[ -d /opt/helmdeck-updates ] && sudo mv /opt/helmdeck-updates /opt/helmdeck-updates.old || true
sudo mv /opt/helmdeck-updates.new /opt/helmdeck-updates
sudo chmod -R a+rX /opt/helmdeck-updates
echo "published: $(sudo test -f /opt/helmdeck-updates/metadata.json && echo ok)"
REMOTE

echo "==> verify live manifest"
curl -s -m20 -H "expo-platform: android" -H "expo-runtime-version: 1.0.0" \
     -H "expo-protocol-version: 1" "https://$RELAY_DOMAIN/updates/manifest" \
  | head -c 240
echo
