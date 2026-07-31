#!/usr/bin/env bash
# Update the relay on the VM: ship relay/relay.py, the app-update channel
# (version.json + signed APK), and restart the service. Does NOT touch the
# web server or TLS - nginx + certbot were set up once and stay as they are
# (the old first-install version of this script wrote a Caddyfile; running
# that against the nginx VM would have two servers fighting over :443).
# Idempotent - safe to re-run after every relay change or APK release.
#
#   bash deploy/push_relay.sh
set -o pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
[ -f .env ] && set -a && . ./.env && set +a

: "${RELAY_HOST:?set RELAY_HOST (VM public IP) in .env}"
RELAY_DOMAIN="${RELAY_DOMAIN:-${RELAY_HOST}.sslip.io}"
SSH_USER="${RELAY_SSH_USER:-ubuntu}"
# array keeps a key path containing spaces ("Tien Duy Vo") in one piece
SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
[ -n "${RELAY_SSH_KEY:-}" ] && SSH_OPTS+=(-i "$RELAY_SSH_KEY")
TARGET="$SSH_USER@$RELAY_HOST"

echo "==> shipping relay.py to $TARGET"
scp "${SSH_OPTS[@]}" relay/relay.py "$TARGET:/tmp/relay.py" || exit 1

APK="apk/app/build/outputs/apk/release/app-release.apk"
if [ -f "$APK" ]; then
  # version.json is derived from the gradle file - single source of truth
  VCODE=$(sed -n 's/.*versionCode = \([0-9]*\).*/\1/p' apk/app/build.gradle.kts)
  VNAME=$(sed -n 's/.*versionName = "\([^"]*\)".*/\1/p' apk/app/build.gradle.kts)
  printf '{"versionCode": %s, "versionName": "%s", "url": "/apk/helmdeck.apk"}\n' \
         "$VCODE" "$VNAME" > /tmp/sd_version.json
  echo "==> shipping APK v$VNAME ($VCODE) + version.json"
  scp "${SSH_OPTS[@]}" "$APK" "$TARGET:/tmp/helmdeck.apk" || exit 1
  scp "${SSH_OPTS[@]}" /tmp/sd_version.json "$TARGET:/tmp/version.json" || exit 1
fi

ssh "${SSH_OPTS[@]}" "$TARGET" 'bash -s' <<'REMOTE'
set -e
# the systemd unit on this VM runs /opt/helmdeck-relay.py (installed that
# way originally); keep /opt/relay.py in sync for older docs
sudo install -m755 /tmp/relay.py /opt/helmdeck-relay.py
sudo install -m755 /tmp/relay.py /opt/relay.py
sudo mkdir -p /opt/helmdeck-apk
[ -f /tmp/helmdeck.apk ] && sudo install -m644 /tmp/helmdeck.apk /opt/helmdeck-apk/helmdeck.apk
[ -f /tmp/version.json ] && sudo install -m644 /tmp/version.json /opt/helmdeck-apk/version.json
sudo systemctl restart helmdeck-relay
sleep 2
systemctl is-active helmdeck-relay
REMOTE

echo
echo "==> verifying https://$RELAY_DOMAIN"
curl -s -m 20 "https://$RELAY_DOMAIN/health" && echo
curl -s -m 20 "https://$RELAY_DOMAIN/apk/version.json" && echo
