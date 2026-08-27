#!/usr/bin/env bash
# ONE-TIME provisioning for a fresh relay VM (Oracle Always Free or similar,
# Ubuntu 22.04+): installs nginx + certbot, writes the helmdeck-relay systemd
# unit (bound to 127.0.0.1:6790, matching the old box), an nginx vhost that
# TLS-terminates + reverse-proxies to it, and mints a Let's Encrypt cert via
# certbot's nginx plugin. Uses RELAY_DOMAIN=<RELAY_HOST>.sslip.io by default
# so no real DNS record is needed (sslip.io resolves to the IP embedded in
# the hostname).
#
# Run ONCE per box, before the first `bash ops/deploy/push_relay.sh`. Re-running
# is safe (idempotent) but does not undo manual changes.
#
#   bash ops/deploy/setup_relay_vm.sh
set -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
[ -f .env ] && set -a && . ./.env && set +a

: "${RELAY_HOST:?set RELAY_HOST (VM public IP) in .env}"
RELAY_DOMAIN="${RELAY_DOMAIN:-${RELAY_HOST}.sslip.io}"
SSH_USER="${RELAY_SSH_USER:-ubuntu}"
SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
[ -n "${RELAY_SSH_KEY:-}" ] && SSH_OPTS+=(-i "$RELAY_SSH_KEY")
TARGET="$SSH_USER@$RELAY_HOST"

echo "==> shipping relay.py to $TARGET (pre-seed, so the service has something to start)"
scp "${SSH_OPTS[@]}" surfaces/relay/relay.py "$TARGET:/tmp/relay.py" || exit 1

ssh "${SSH_OPTS[@]}" "$TARGET" RELAY_DOMAIN="$RELAY_DOMAIN" 'bash -s' <<'REMOTE'
set -e
echo "==> packages"
sudo apt-get update -qq
sudo apt-get install -y -qq nginx certbot python3-certbot-nginx python3 >/dev/null

echo "==> relay code + apk channel dir"
sudo install -m755 /tmp/relay.py /opt/helmdeck-relay.py
sudo mkdir -p /opt/helmdeck-apk

echo "==> systemd unit"
sudo tee /etc/systemd/system/helmdeck-relay.service >/dev/null <<UNIT
[Unit]
Description=HelmDeck relay (zero-knowledge tunnel)
After=network.target

[Service]
ExecStart=/usr/bin/python3 /opt/helmdeck-relay.py
Environment=HELMDECK_RELAY_BIND=127.0.0.1
Environment=HELMDECK_RELAY_PORT=6790
Environment=HELMDECK_APK_DIR=/opt/helmdeck-apk
Restart=always
RestartSec=2
User=www-data

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now helmdeck-relay

echo "==> nginx vhost (HTTP first; certbot upgrades it to TLS)"
sudo tee /etc/nginx/sites-available/helmdeck-relay >/dev/null <<VHOST
server {
    listen 80;
    server_name $RELAY_DOMAIN;
    location / {
        proxy_pass http://127.0.0.1:6790;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_read_timeout 130s;
    }
}
VHOST
sudo ln -sf /etc/nginx/sites-available/helmdeck-relay /etc/nginx/sites-enabled/helmdeck-relay
sudo nginx -t && sudo systemctl reload nginx

echo "==> certbot (Let's Encrypt, nginx plugin, auto-redirect http->https)"
sudo certbot --nginx -d "$RELAY_DOMAIN" --non-interactive --agree-tos \
  --redirect -m "${CERTBOT_EMAIL:-tienduyvo@googlemail.com}" --no-eff-email

sudo systemctl is-active helmdeck-relay
sudo systemctl is-active nginx
REMOTE

echo
echo "==> verifying https://$RELAY_DOMAIN/health"
curl -s -m 20 "https://$RELAY_DOMAIN/health" && echo
echo
echo "Box provisioned. From now on, ship relay updates with:"
echo "  bash ops/deploy/push_relay.sh"
