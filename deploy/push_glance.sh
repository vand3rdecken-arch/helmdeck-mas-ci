#!/usr/bin/env bash
# Ship the GLASSES webapp: sync glasses/*.{html,css,js} into the Glance worker
# and deploy it, then prove the live origin actually serves the new build.
#
# WHY A WORKER AND NOT A ZIP SOMEWHERE. Putting a webapp permanently on the
# Ray-Ban Display is self-serve - Meta AI app -> Developer Mode -> App
# Connections -> Web Apps -> Add a Web App - and needs exactly one thing: a
# public HTTPS URL. (The partner-only gate is on the STORE LISTING, a different
# thing; docs/glasses-reference.md 11.9.) This script produces that URL.
#
# THE POINT OF THE ONE URL. You register it ONCE, on the glasses, forever. Every
# later change ships by re-running this script - never by touching the glasses
# again. That is lifted from glass-crud-harness ("New apps appear inside the
# launcher later - no new URL"), and it is the same relationship
# deploy/push_update.sh has with the phone.
#
# ONE-TIME SETUP
#   1. Expose the daemon. A Worker runs at Cloudflare's edge and cannot see
#      localhost:8140:
#          bash deploy/cloudflare_tunnel.sh          # prints an https URL
#   2. Tell the Worker where that is (a SECRET - it is a door to the flat):
#          cd glasses/worker && npx wrangler secret put DAEMON_URL
#   3. Turn the endpoint on in HelmDeck Settings: settings.glance_token
#      (plus glance_talk / glance_decide if you want to talk and decide).
#   4. Deploy, then register the URL on the glasses - carrying the token in the
#      fragment so nothing is ever typed on the device:
#          https://helmdeck-glance.<subdomain>.workers.dev/#t=<glance_token>
#      python tools/qr.py-style QR: the fragment is never sent to a server, so
#      the token does not land in Cloudflare's logs on the way in.
#
# Usage:  bash deploy/push_glance.sh [--check]
#           (no args)  sync + deploy + verify
#           --check    verify the live origin only (safe any time)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKER="$ROOT/glasses/worker"
PUBLIC="$WORKER/public"
NAME="helmdeck-glance"

# The three files that ARE the app. Kept explicit rather than copying the whole
# directory: glasses/ also holds README.md, dist/ and the worker itself, none of
# which belong on a public origin.
ASSETS=(index.html styles.css app.js)

sync_public() {
  rm -rf "$PUBLIC"
  mkdir -p "$PUBLIC"
  local f
  for f in "${ASSETS[@]}"; do
    if [ ! -f "$ROOT/glasses/$f" ]; then
      echo "FAIL: glasses/$f is missing" >&2
      return 1
    fi
    cp "$ROOT/glasses/$f" "$PUBLIC/$f"
  done
  echo "  synced ${#ASSETS[@]} files -> glasses/worker/public/"
}

# app.js changes on nearly every edit and is served verbatim, so its byte length
# is a cheap, honest canary that the live origin is running THIS source. It is
# not a version stamp - a match means "this file is live", not "nothing drifted".
want_len() { wc -c < "$ROOT/glasses/app.js" | tr -d ' '; }
live_len() { curl -fsS "$1/app.js" | wc -c | tr -d ' '; }

origin_url() {
  # wrangler prints the deployed URL; fall back to asking the user if we cannot
  # parse it rather than guessing a subdomain that may not be theirs.
  if [ -n "${GLANCE_ORIGIN:-}" ]; then echo "$GLANCE_ORIGIN"; return; fi
  echo ""
}

verify() {
  local origin="$1" health want live
  health="$(curl -fsS "$origin/health")" || {
    echo "FAIL: $origin/health did not answer" >&2; return 1; }
  case "$health" in
    *"$NAME"*) ;;
    *) echo "FAIL: $origin/health is not the glance worker: $health" >&2; return 1 ;;
  esac
  # The Worker is useless without a daemon behind it, and this is the failure
  # that otherwise shows up as an empty screen on the glasses with no clue why.
  case "$health" in
    *'"daemon":true'*) ;;
    *) echo "WARN: DAEMON_URL is not set on the worker - the app will load but" >&2
       echo "      every /glance call will 503. Fix:" >&2
       echo "      cd glasses/worker && npx wrangler secret put DAEMON_URL" >&2 ;;
  esac
  want="$(want_len)"; live="$(live_len "$origin")"
  echo "  source app.js: $want bytes"
  echo "  live   app.js: $live bytes"
  if [ "$want" != "$live" ]; then
    echo "FAIL: $origin serves a different build than glasses/." >&2
    return 1
  fi
  echo "OK: $origin serves the current source."
}

ORIGIN="$(origin_url)"

if [ "${1:-}" = "--check" ]; then
  if [ -z "$ORIGIN" ]; then
    echo "Set GLANCE_ORIGIN=https://... to verify (the deployed worker URL)." >&2
    exit 2
  fi
  echo "== checking $ORIGIN (no deploy) =="
  verify "$ORIGIN"
  exit $?
fi

echo "== syncing glasses/ -> glasses/worker/public =="
sync_public

echo "== deploying $NAME =="
( cd "$WORKER" && npx wrangler deploy )

if [ -z "$ORIGIN" ]; then
  echo
  echo "Deployed. wrangler printed the URL above."
  echo "To let this script verify future deploys automatically:"
  echo "    export GLANCE_ORIGIN=https://$NAME.<your-subdomain>.workers.dev"
  echo
  echo "Then register it on the glasses ONCE (Meta AI app -> Developer Mode ->"
  echo "App Connections -> Web Apps -> Add a Web App):"
  echo "    \$GLANCE_ORIGIN/#t=<your glance_token>"
  exit 0
fi

echo "== verifying $ORIGIN =="
for attempt in 1 2 3 4 5; do
  if verify "$ORIGIN"; then exit 0; fi
  echo "  (attempt $attempt: not live yet, retrying in 6s)"
  sleep 6
done

echo "FAIL: deploy reported success but $ORIGIN never served the new build." >&2
exit 1
