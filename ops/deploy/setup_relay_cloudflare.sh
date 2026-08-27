#!/usr/bin/env bash
# ONE-TIME provisioning for the relay when the target box has NO usable
# inbound ports (e.g. trooper: a GPU-rental box behind its provider's own
# NAT/proxy - even ports it already publishes itself aren't reachable from
# the internet). Fronts the relay with a Cloudflare Tunnel instead of
# nginx+certbot+public-bind: cloudflared dials OUT, so no inbound 80/443,
# no VCN/security-group config, nothing to forward.
#
# Prerequisite: RELAY_DOMAIN's zone (e.g. helmdeck.de) must already be on
# Cloudflare nameservers - `cloudflared tunnel route dns` needs the API to
# manage that zone. Check with: nslookup -type=NS <domain>
#
#   bash ops/deploy/setup_relay_cloudflare.sh
set -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
[ -f .env ] && set -a && . ./.env && set +a

: "${RELAY_HOST:?set RELAY_HOST (SSH host/alias) in .env}"
: "${RELAY_DOMAIN:?set RELAY_DOMAIN (e.g. relay.helmdeck.de) in .env}"
SSH_USER="${RELAY_SSH_USER:-ubuntu}"
SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
[ -n "${RELAY_SSH_KEY:-}" ] && SSH_OPTS+=(-i "$RELAY_SSH_KEY")
TARGET="$SSH_USER@$RELAY_HOST"
TUNNEL_NAME="${RELAY_TUNNEL_NAME:-helmdeck-relay}"

echo "==> shipping relay.py to $TARGET"
scp "${SSH_OPTS[@]}" surfaces/relay/relay.py "$TARGET:/tmp/relay.py" || exit 1

echo "==> relay service (localhost-only - cloudflared fronts it, no public bind)"
ssh "${SSH_OPTS[@]}" "$TARGET" 'bash -s' <<'REMOTE'
set -e
sudo install -m755 /tmp/relay.py /opt/helmdeck-relay.py
sudo mkdir -p /opt/helmdeck-apk
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

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now helmdeck-relay
sleep 1
systemctl is-active helmdeck-relay
curl -s -m5 http://127.0.0.1:6790/health && echo
which cloudflared >/dev/null || { echo "installing cloudflared"; \
  curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /tmp/cloudflared \
  && sudo install -m755 /tmp/cloudflared /usr/local/bin/cloudflared; }
REMOTE

if ! ssh "${SSH_OPTS[@]}" "$TARGET" 'test -f ~/.cloudflared/cert.pem'; then
  echo
  echo "==> Cloudflare account authorization needed (one-time, interactive)."
  echo "    Run this and open the printed URL in a browser; pick the zone"
  echo "    that owns $RELAY_DOMAIN and click Authorize:"
  echo
  echo "    ssh ${SSH_OPTS[*]} $TARGET 'cloudflared tunnel login'"
  echo
  exit 1
fi

echo "==> creating tunnel '$TUNNEL_NAME' (idempotent - reuses if it exists)"
TUNNEL_ID=$(ssh "${SSH_OPTS[@]}" "$TARGET" \
  "cloudflared tunnel list -o json 2>/dev/null | grep -o '\"id\":\"[a-f0-9-]*\",\"name\":\"$TUNNEL_NAME\"' | head -1 | grep -o '[a-f0-9-]\{36\}'")
if [ -z "$TUNNEL_ID" ]; then
  ssh "${SSH_OPTS[@]}" "$TARGET" "cloudflared tunnel create $TUNNEL_NAME"
  TUNNEL_ID=$(ssh "${SSH_OPTS[@]}" "$TARGET" \
    "cloudflared tunnel list -o json 2>/dev/null | grep -o '\"id\":\"[a-f0-9-]*\",\"name\":\"$TUNNEL_NAME\"' | head -1 | grep -o '[a-f0-9-]\{36\}'")
fi
: "${TUNNEL_ID:?could not determine tunnel id - check 'cloudflared tunnel list' on the box}"
echo "    tunnel id: $TUNNEL_ID"

echo "==> routing DNS: $RELAY_DOMAIN -> tunnel $TUNNEL_NAME"
ssh "${SSH_OPTS[@]}" "$TARGET" "cloudflared tunnel route dns $TUNNEL_NAME $RELAY_DOMAIN" || true

echo "==> installing cloudflared as a systemd service"
ssh "${SSH_OPTS[@]}" "$TARGET" TUNNEL_ID="$TUNNEL_ID" RELAY_DOMAIN="$RELAY_DOMAIN" 'bash -s' <<'REMOTE'
set -e
sudo mkdir -p /etc/cloudflared
sudo cp "$HOME/.cloudflared/$TUNNEL_ID.json" /etc/cloudflared/
sudo tee /etc/cloudflared/config.yml >/dev/null <<CFG
tunnel: $TUNNEL_ID
credentials-file: /etc/cloudflared/$TUNNEL_ID.json

ingress:
  - hostname: $RELAY_DOMAIN
    service: http://127.0.0.1:6790
  - service: http_status:404
CFG
sudo cloudflared service install 2>/dev/null || true
sudo systemctl enable --now cloudflared
sleep 2
systemctl is-active cloudflared
REMOTE

echo
echo "==> verifying https://$RELAY_DOMAIN/health"
sleep 3
curl -s -m 20 "https://$RELAY_DOMAIN/health" && echo
echo
echo "Box provisioned. From now on, ship relay updates with:"
echo "  bash ops/deploy/push_relay.sh"
