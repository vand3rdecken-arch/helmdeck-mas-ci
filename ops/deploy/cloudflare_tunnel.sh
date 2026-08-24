#!/usr/bin/env bash
# Path A: publish the local daemon over HTTPS with a free Cloudflare Tunnel.
# No relay, no VM, no credit card. cloudflared dials OUT from this PC, so no
# port-forwarding and nothing inbound on your router.
#
#   bash ops/deploy/cloudflare_tunnel.sh              # quick tunnel (ephemeral URL)
#   bash ops/deploy/cloudflare_tunnel.sh example.com  # named tunnel (stable URL)
#
# You must be signed in to a free Cloudflare account for the named variant
# (the script opens the browser login for you).
set -o pipefail
PORT="${HELMDECK_PORT:-8140}"
DOMAIN="${1:-}"

have() { command -v "$1" >/dev/null 2>&1; }

install_cloudflared() {
  have cloudflared && { echo "cloudflared: already installed"; return 0; }
  echo "==> installing cloudflared"
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*)
      if have winget; then winget install --id Cloudflare.cloudflared -e --silent
      else echo "Install cloudflared manually: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"; return 1; fi ;;
    Linux)  curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /tmp/cloudflared \
              && sudo install -m755 /tmp/cloudflared /usr/local/bin/cloudflared ;;
    Darwin) have brew && brew install cloudflared ;;
  esac
}

install_cloudflared || exit 1

# the daemon must be up, or the tunnel publishes a dead port
curl -s -m3 "http://localhost:$PORT/auth/state" >/dev/null 2>&1 \
  || echo "WARNING: no daemon answering on :$PORT - start it first (cd daemon && py -3.12 swarm.py serve)"

if [ -z "$DOMAIN" ]; then
  echo "==> quick tunnel -> http://localhost:$PORT"
  echo "    (URL changes each restart; fine for testing and a store review)"
  exec cloudflared tunnel --url "http://localhost:$PORT"
fi

echo "==> named tunnel for $DOMAIN (stable URL)"
cloudflared tunnel login                                    # opens the browser: you approve
cloudflared tunnel create helmdeck 2>/dev/null || true
cloudflared tunnel route dns helmdeck "helmdeck.$DOMAIN"
exec cloudflared tunnel run --url "http://localhost:$PORT" helmdeck
