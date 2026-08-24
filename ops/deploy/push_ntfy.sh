#!/usr/bin/env bash
# TEARDOWN: ntfy was the interim push channel; FCM (sealed data messages)
# replaced it, so this now REMOVES ntfy from the VM - service, binary,
# config, cache, and the nginx push vhost. Idempotent. The relay vhost and
# everything else on the box are untouched.
#
#   bash ops/deploy/push_ntfy.sh
set -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
[ -f .env ] && set -a && . ./.env && set +a

: "${RELAY_HOST:?set RELAY_HOST (VM public IP) in .env}"
PUSH_DOMAIN="${PUSH_DOMAIN:-push.${RELAY_HOST}.sslip.io}"
SSH_USER="${RELAY_SSH_USER:-ubuntu}"
SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
[ -n "${RELAY_SSH_KEY:-}" ] && SSH_OPTS+=(-i "$RELAY_SSH_KEY")
TARGET="$SSH_USER@$RELAY_HOST"

echo "==> removing ntfy from $TARGET"
ssh "${SSH_OPTS[@]}" "$TARGET" PUSH_DOMAIN="$PUSH_DOMAIN" 'bash -s' <<'REMOTE'
set -e
sudo systemctl disable --now ntfy 2>/dev/null || true
sudo rm -f /etc/systemd/system/ntfy.service /usr/local/bin/ntfy
sudo rm -rf /etc/ntfy /var/cache/ntfy
sudo systemctl daemon-reload
sudo rm -f /etc/nginx/sites-enabled/helmdeck-push /etc/nginx/sites-available/helmdeck-push
sudo certbot delete --cert-name "$PUSH_DOMAIN" --non-interactive 2>/dev/null || true
sudo nginx -t && sudo systemctl reload nginx
echo "ntfy entfernt; nginx laeuft:"
systemctl is-active nginx
REMOTE

echo
echo "==> verifying: push vhost should be gone, relay untouched"
curl -s -o /dev/null -w "push vhost: HTTP %{http_code}\n" -m 15 "https://$PUSH_DOMAIN/v1/health" || true
curl -s -m 15 "https://${RELAY_HOST}.sslip.io/health" && echo
