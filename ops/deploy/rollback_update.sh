#!/usr/bin/env bash
# Roll back a bad OTA update - two ladders, both silent on the phone (applied
# on the next check-on-resume / launch, no user prompt):
#
#   bash ops/deploy/rollback_update.sh                    # re-publish the PREVIOUS
#       update (the .old dir push_update.sh keeps). Fails if none exists.
#   bash ops/deploy/rollback_update.sh --embedded         # serve a rollBackToEmbedded
#       directive: every client reverts to the APK's built-in bundle.
#   bash ops/deploy/rollback_update.sh --clear            # remove the --embedded
#       marker and resume serving whatever update dir is live.
#   ... --channel beta                                # any of the above, per channel
#
# --embedded stamps rollback.json with the current UTC time as commitTime; the
# client only honours a commitTime newer than the last rollback it applied, so
# re-running it after a fresh bad publish rolls phones back again. The marker
# (and the whole state) is replaced by the next push_update.sh.
#
# Needs .env with RELAY_HOST / RELAY_SSH_* (same as push_update.sh).
set -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
[ -f .env ] && set -a && . ./.env && set +a
: "${RELAY_HOST:?set RELAY_HOST (VM public IP) in .env}"
RELAY_DOMAIN="${RELAY_DOMAIN:-${RELAY_HOST}.sslip.io}"
SSH_USER="${RELAY_SSH_USER:-ubuntu}"
SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
[ -n "${RELAY_SSH_KEY:-}" ] && SSH_OPTS+=(-i "$RELAY_SSH_KEY")
TARGET="$SSH_USER@$RELAY_HOST"

MODE="previous"; CHANNEL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --embedded) MODE="embedded" ;;
    --clear)    MODE="clear" ;;
    --channel)  CHANNEL="${2:-}"; shift ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
  shift
done
case "$CHANNEL" in production) CHANNEL="" ;; *[!A-Za-z0-9._-]*) echo "bad channel name"; exit 2 ;; esac

echo "==> rollback ($MODE) on ${CHANNEL:-production}"
ssh "${SSH_OPTS[@]}" "$TARGET" 'bash -s' -- "$MODE" "$CHANNEL" <<'REMOTE'
set -e
MODE="$1"
DEST="/opt/helmdeck-updates${2:+-$2}"
case "$MODE" in
  previous)
    [ -d "$DEST.old" ] || { echo "no $DEST.old - nothing to roll back to (use --embedded)"; exit 1; }
    # keep the bad build around as .bad for a post-mortem; atomic swap as usual
    sudo rm -rf "$DEST.bad"
    [ -d "$DEST" ] && sudo mv "$DEST" "$DEST.bad" || true
    sudo mv "$DEST.old" "$DEST"
    sudo rm -f "$DEST/rollback.json"
    echo "restored previous update: $(sudo test -f "$DEST/metadata.json" && echo ok)"
    ;;
  embedded)
    sudo mkdir -p "$DEST"
    printf '{"commitTime":"%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%S.000Z)" | sudo tee "$DEST/rollback.json" >/dev/null
    sudo chmod a+r "$DEST/rollback.json"
    echo "rollBackToEmbedded directive live (commitTime = now)"
    ;;
  clear)
    sudo rm -f "$DEST/rollback.json"
    echo "marker cleared - serving the live update dir again"
    ;;
esac
REMOTE
[ $? -eq 0 ] || exit 1

echo "==> verify live manifest"
curl -s -m20 -H "expo-platform: android" -H "expo-runtime-version: 1.0.0" \
     -H "expo-protocol-version: 1" ${CHANNEL:+-H "expo-channel-name: $CHANNEL"} \
     "https://$RELAY_DOMAIN/updates/manifest" \
  | head -c 240
echo
