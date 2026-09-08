#!/usr/bin/env bash
# Update the relay on the VM: ship surfaces/relay/relay.py, the app-update channel
# (version.json + signed APK), and restart the service. Does NOT touch the
# web server or TLS - nginx + certbot were set up once and stay as they are
# (the old first-install version of this script wrote a Caddyfile; running
# that against the nginx VM would have two servers fighting over :443).
# Idempotent - safe to re-run after every relay change or APK release.
#
#   bash ops/deploy/push_relay.sh
set -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
[ -f .env ] && set -a && . ./.env && set +a

# LOCAL FALLBACK (2026-09-08: trooper, the VM RELAY_HOST used to point at, is
# dead) - same probe push_update.sh uses. A live relay on this box already
# runs surfaces/relay/relay.py straight from the repo (ops/deploy/relay_local.cmd),
# so there is nothing to scp for the relay code itself - a relay.py edit needs
# a restart of that process to take effect, which this script deliberately
# does NOT do on every push (it would drop the live tunnel's in-flight
# long-polls on every APK ship, not just on a real relay.py change). What
# LOCAL mode still does: drop version.json + the signed APK straight into the
# dir relay.py serves /apk/ from - no SSH, no VM.
RELAY_PORT="${HELMDECK_RELAY_PORT:-6790}"
RELAY_LOCAL=0
if curl -s -m3 "http://127.0.0.1:$RELAY_PORT/health" 2>/dev/null | grep -q '"ok": *true'; then
  RELAY_LOCAL=1
  LOCAL_APK_DIR="${HELMDECK_APK_DIR:-/c/opt/helmdeck-apk}"
  RELAY_DOMAIN="${RELAY_DOMAIN:-relay.helmdeck.de}"
  echo "==> local relay answering on 127.0.0.1:$RELAY_PORT - publishing to $LOCAL_APK_DIR (no SSH)"
  echo "==> relay.py itself already runs live from this repo - restart relay_local.cmd by hand if it changed"
else
  : "${RELAY_HOST:?set RELAY_HOST (VM public IP) in .env, or start the local relay (ops/deploy/relay_local.cmd)}"
  RELAY_DOMAIN="${RELAY_DOMAIN:-${RELAY_HOST}.sslip.io}"
  SSH_USER="${RELAY_SSH_USER:-ubuntu}"
  # array keeps a key path containing spaces ("Tien Duy Vo") in one piece
  SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
  [ -n "${RELAY_SSH_KEY:-}" ] && SSH_OPTS+=(-i "$RELAY_SSH_KEY")
  TARGET="$SSH_USER@$RELAY_HOST"

  echo "==> shipping relay.py to $TARGET"
  scp "${SSH_OPTS[@]}" surfaces/relay/relay.py "$TARGET:/tmp/relay.py" || exit 1
fi

# Expo APK (post-cutover path). versionCode/Name come from surfaces/app/app.json.
APK="surfaces/app/android/app/build/outputs/apk/release/app-release.apk"
if [ -f "$APK" ]; then
  VCODE=$(sed -n 's/.*"versionCode"[^0-9]*\([0-9]*\).*/\1/p' surfaces/app/app.json | head -1)
  VNAME=$(sed -n 's/.*"version"[^"]*"\([^"]*\)".*/\1/p' surfaces/app/app.json | head -1)
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
  #
  # ?v= carries versionCode AND a content-hash prefix (2026-08-26): versionCode
  # alone collided the day a build was re-cut at the SAME version - the signing
  # hotfix re-shipped v62 under the identical ?v=62 key, so every phone pulled
  # the previous (debug-signed) body from edge cache and install died on
  # INSTALL_FAILED_UPDATE_INCOMPATIBLE, while this script's length check even
  # passed (both builds were coincidentally byte-identical in SIZE). The hash
  # makes the cache key track the BYTES, which is the only thing that never lies.
  APK_SHA=$(sha256sum "$APK" | cut -c1-12)
  printf '{"versionCode": %s, "versionName": "%s", "url": "/apk/helmdeck.apk?v=%s-%s"}\n' \
         "$VCODE" "$VNAME" "$VCODE" "$APK_SHA" > /tmp/sd_version.json
  echo "==> shipping APK v$VNAME ($VCODE) + version.json"
  if [ "$RELAY_LOCAL" != "1" ]; then
    scp "${SSH_OPTS[@]}" "$APK" "$TARGET:/tmp/helmdeck.apk" || exit 1
    scp "${SSH_OPTS[@]}" /tmp/sd_version.json "$TARGET:/tmp/version.json" || exit 1
  fi
fi

if [ "$RELAY_LOCAL" = "1" ]; then
  echo "==> installing into $LOCAL_APK_DIR"
  mkdir -p "$LOCAL_APK_DIR" || exit 1
  [ -f "$APK" ] && { cp "$APK" "$LOCAL_APK_DIR/helmdeck.apk" || exit 1; }
  [ -f /tmp/sd_version.json ] && { cp /tmp/sd_version.json "$LOCAL_APK_DIR/version.json" || exit 1; }
else
  ssh "${SSH_OPTS[@]}" "$TARGET" 'bash -s' <<'REMOTE'
set -e
# the systemd unit on this VM runs /opt/helmdeck-relay.py (installed that
# way originally); keep /opt/relay.py in sync for older docs.
#
# ONLY restart the live service when relay.py's content actually changed.
# A restart drops every in-flight long-poll on the phone/desktop bridge for
# ~2s - fine for a real relay.py change, but this script also runs on EVERY
# APK-only ship (native build success), and running it repeatedly (a caller
# retrying, a stale native-change detector re-triggering) was restarting a
# byte-identical relay.py every ~20-35 min for days (measured 2026-08-28
# onward via `sudo grep helmdeck-relay /var/log/auth.log` - same md5 every
# time), which is what made the phone/desktop show "verbindet neu" on a
# schedule that had nothing to do with real relay changes.
NEED_RESTART=1
if [ -f /opt/helmdeck-relay.py ] && cmp -s /tmp/relay.py /opt/helmdeck-relay.py; then
  NEED_RESTART=0
fi
sudo install -m755 /tmp/relay.py /opt/helmdeck-relay.py
sudo install -m755 /tmp/relay.py /opt/relay.py
sudo mkdir -p /opt/helmdeck-apk
[ -f /tmp/helmdeck.apk ] && sudo install -m644 /tmp/helmdeck.apk /opt/helmdeck-apk/helmdeck.apk
[ -f /tmp/version.json ] && sudo install -m644 /tmp/version.json /opt/helmdeck-apk/version.json
if [ "$NEED_RESTART" = "1" ] || ! systemctl is-active --quiet helmdeck-relay; then
  sudo systemctl restart helmdeck-relay
  sleep 2
else
  echo "relay.py unchanged - skipping restart (no reason to drop live connections)"
fi
systemctl is-active helmdeck-relay
REMOTE
  # The ssh block above had NO error check for its whole life, so a remote that
  # died on `install` still let this script exit 0 with a green-looking tail.
  [ $? -eq 0 ] || { echo "==> REMOTE INSTALL FAILED"; exit 1; }
fi

echo
echo "==> verifying https://$RELAY_DOMAIN"
curl -s -m 20 "https://$RELAY_DOMAIN/health" && echo
curl -s -m 20 "https://$RELAY_DOMAIN/apk/version.json" && echo

# VERIFY THE ARTIFACT THE PHONE WILL ACTUALLY RECEIVE, not the manifest that
# describes it. Same discipline push_site.sh already enforces ("never verify a
# deploy from git log"): everything above this line was green on 2026-08-21
# while Cloudflare served the previous release's 146 MB body from edge cache.
# So re-read the download URL out of the version.json we just published,
# DOWNLOAD the body, and compare its sha256 to the local file. Length alone
# is proven insufficient: on 2026-08-26 the edge served a stale build that
# was coincidentally byte-identical in SIZE to the new one (same code, only
# the signing cert differed) and the old length check waved it through.
if [ -f "$APK" ]; then
  URL=$(sed -n 's/.*"url": *"\([^"]*\)".*/\1/p' /tmp/sd_version.json)
  WANT=$(sha256sum "$APK" | cut -d' ' -f1)
  curl -s -m 300 -o /tmp/sd_apk_verify.apk "https://$RELAY_DOMAIN$URL" || true
  GOT=$(sha256sum /tmp/sd_apk_verify.apk 2>/dev/null | cut -d' ' -f1)
  rm -f /tmp/sd_apk_verify.apk
  if [ "$GOT" = "$WANT" ]; then
    echo "==> APK verified at $URL (sha256 ${GOT:0:12}...)"
  else
    echo "==> APK MISMATCH at $URL: serving sha256 ${GOT:-?}, built $WANT"
    echo "==> the phone would install a DIFFERENT build than the one just made"
    exit 1
  fi
fi
