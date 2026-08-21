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

# Expo APK (post-cutover path). versionCode/Name come from app/app.json.
APK="app/android/app/build/outputs/apk/release/app-release.apk"
if [ -f "$APK" ]; then
  VCODE=$(sed -n 's/.*"versionCode"[^0-9]*\([0-9]*\).*/\1/p' app/app.json | head -1)
  VNAME=$(sed -n 's/.*"version"[^"]*"\([^"]*\)".*/\1/p' app/app.json | head -1)
  # ?v=<versionCode> IS LOAD-BEARING, not decoration. relay.helmdeck.de is
  # proxied through CLOUDFLARE, which caches /apk/helmdeck.apk for 4 hours
  # (`cache-control: max-age=14400`). The file on the origin is replaced in
  # place under a CONSTANT path, so the edge keeps serving the PREVIOUS release
  # to every phone for up to four hours while this script exits 0 and the
  # closing curl below reports the new version.json - the artifact is stale and
  # every signal says shipped. Measured 2026-08-21: after a good push, a HEAD on
  # the bare URL returned `cf-cache-status: HIT, age: 3812, content-length:
  # 146058606` (the OLD APK) while the same URL with any query string returned
  # `MISS` and the new 162213126 bytes.
  #
  # The query string makes the cache KEY carry the version, so a new release can
  # never collide with its predecessor's cached body - a purge fixes one
  # release, this fixes all of them, and it needs no Cloudflare credential (the
  # box's wrangler OAuth token has no `cache_purge` scope). version.json itself
  # is `cf-cache-status: DYNAMIC` - never cached - so phones read the new URL
  # immediately. Verified: relay.py routes on the path and ignores the query.
  printf '{"versionCode": %s, "versionName": "%s", "url": "/apk/helmdeck.apk?v=%s"}\n' \
         "$VCODE" "$VNAME" "$VCODE" > /tmp/sd_version.json
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
# The ssh block above had NO error check for its whole life, so a remote that
# died on `install` still let this script exit 0 with a green-looking tail.
[ $? -eq 0 ] || { echo "==> REMOTE INSTALL FAILED"; exit 1; }

echo
echo "==> verifying https://$RELAY_DOMAIN"
curl -s -m 20 "https://$RELAY_DOMAIN/health" && echo
curl -s -m 20 "https://$RELAY_DOMAIN/apk/version.json" && echo

# VERIFY THE ARTIFACT THE PHONE WILL ACTUALLY RECEIVE, not the manifest that
# describes it. Same discipline push_site.sh already enforces ("never verify a
# deploy from git log"): everything above this line was green on 2026-08-21
# while Cloudflare served the previous release's 146 MB body from edge cache.
# So re-read the download URL out of the version.json we just published and
# compare its length to the local file, byte for byte.
if [ -f "$APK" ]; then
  URL=$(sed -n 's/.*"url": *"\([^"]*\)".*/\1/p' /tmp/sd_version.json)
  WANT=$(wc -c < "$APK" | tr -d ' ')
  GOT=$(curl -s -m 60 -I "https://$RELAY_DOMAIN$URL" \
        | tr -d '\r' | sed -n 's/^[Cc]ontent-[Ll]ength: *//p' | tail -1)
  if [ "$GOT" = "$WANT" ]; then
    echo "==> APK verified at $URL ($GOT bytes)"
  else
    echo "==> APK MISMATCH at $URL: serving ${GOT:-?} bytes, built $WANT"
    echo "==> the phone would install a DIFFERENT build than the one just made"
    exit 1
  fi
fi
