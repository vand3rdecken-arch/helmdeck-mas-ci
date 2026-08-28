#!/usr/bin/env bash
# Path A: publish the local daemon over HTTPS with a free Cloudflare Tunnel.
# No relay, no VM, no credit card. cloudflared dials OUT from this PC, so no
# port-forwarding and nothing inbound on your router.
#
#   bash ops/deploy/cloudflare_tunnel.sh                          # quick tunnel (ephemeral URL)
#   bash ops/deploy/cloudflare_tunnel.sh example.com              # named tunnel -> helmdeck.example.com
#   bash ops/deploy/cloudflare_tunnel.sh example.com sub.example.com  # named tunnel -> EXACT hostname (2nd arg)
#
# The 2nd arg exists because the DEFAULT naming (helmdeck.$1) is not always
# the hostname you want to route (e.g. a fixed pairing subdomain for a
# second device - ops/docs/backlog/wear-os-integration/README.md §4.11):
# `cloudflare_tunnel.sh helmdeck.de pair.helmdeck.de` routes exactly
# pair.helmdeck.de, not the double-prefixed helmdeck.helmdeck.de a bare
# `cloudflare_tunnel.sh pair.helmdeck.de` would have silently produced -
# $1 is still the ZONE Cloudflare manages (needed for `tunnel route dns`
# regardless of which hostname within it you're routing), $2 is the exact
# hostname, only overriding the DEFAULT of helmdeck.$1 when given.
#
# You must be signed in to a free Cloudflare account for the named variant
# (the script opens the browser login for you).
set -o pipefail
PORT="${HELMDECK_PORT:-8140}"
DOMAIN="${1:-}"
HOSTNAME_OVERRIDE="${2:-}"

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

HOST="${HOSTNAME_OVERRIDE:-helmdeck.$DOMAIN}"
echo "==> named tunnel for $HOST (stable URL, zone $DOMAIN)"
cloudflared tunnel login                                    # opens the browser: you approve
cloudflared tunnel create helmdeck 2>/dev/null || true
cloudflared tunnel route dns helmdeck "$HOST"
exec cloudflared tunnel run --url "http://localhost:$PORT" helmdeck
