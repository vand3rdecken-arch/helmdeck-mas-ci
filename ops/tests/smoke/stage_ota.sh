#!/usr/bin/env bash
# Stage a marked OTA bundle for the release smoke. Run AFTER the APK build has
# finished (both bundle JS from a node_modules tree - don't run them at once).
#
# Adds a visible " · OTA-SMOKE" marker to the version line that More/Settings
# render, exports the JS bundle, stages it into the relay's updates dir
# (.smoke/updates, served at /updates/manifest through the cloudflared tunnel),
# then reverts the marker so the git tree stays pristine. The marker is the
# whole point: silent OTA has no prompt, so a visible string is how a human
# proves on-screen which bundle is running.
#
#   bash .smoke/stage_ota.sh [MARKER]     # default marker: OTA-SMOKE
#
# Pass a distinct MARKER per round: proving check-on-RESUME needs a SECOND
# update staged while the app is already running, and the footer has to show
# which of the two is live.
set -o pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT/surfaces/app" || exit 1
export PATH="/c/Program Files/nodejs:$PATH"

MARKER="${1:-OTA-SMOKE}"
F=src/ui/updates_info.tsx
revert() { sed -i "s/ · $MARKER//" "$F"; }
grep -q "$MARKER" "$F" || sed -i "s/HelmDeck v{version}/HelmDeck v{version} · $MARKER/" "$F"
grep -q "$MARKER" "$F" || { echo "marker edit FAILED"; exit 1; }

rm -rf dist
if ! npx expo export --platform android; then
  revert; echo "export FAILED"; exit 1
fi
revert
grep -q "$MARKER" "$F" && { echo "marker revert FAILED"; exit 1; }
[ -f dist/metadata.json ] || { echo "no dist/metadata.json"; exit 1; }

U="$ROOT/ops/tests/smoke/updates"
rm -rf "$U.new"; mkdir -p "$U.new"
cp -r dist/. "$U.new/"
rm -rf "$U.old"; [ -d "$U" ] && mv "$U" "$U.old"
mv "$U.new" "$U"
echo "staged -> $U"
ls "$U"
