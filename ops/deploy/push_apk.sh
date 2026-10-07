#!/usr/bin/env bash
# Distribute the signed sideload APK - the ONE route since the relay moved to the
# Cloudflare worker (2026-09-22): the worker answers GET <relay>/apk/helmdeck.apk
# with a 302 to APK_URL (wrangler.jsonc: the helmdeck-release repo's latest
# release asset helmdeck.apk; too big for a static asset), and version.json is a
# static asset of the worker. So distributing = (1) put helmdeck.apk on the
# LATEST release of that repo and prove the asset landed, (2) write version.json
# into HELMDECK_APK_DIR, which push_update.sh's worker deploy
# (publish_relay_worker.sh) then publishes. version.json is written only AFTER
# the upload is proven, so a failed upload can never advertise a version no
# phone can download.
#
# Replaces push_relay.sh (SSH to the dead trooper VM; its failure was swallowed
# by build_apk.sh, so a native ship reported success with no APK anywhere).
# EVERY failure here exits non-zero; the caller (ship.sh / the ship card) must
# treat that as a failed native ship (revert the bump, push no OTA).
#
#   bash ops/deploy/push_apk.sh
# Test seams (env): HELMDECK_APK_FILE, HELMDECK_APP_JSON, HELMDECK_APK_DIR,
# HELMDECK_GH_REPO; `gh` is whatever is first on PATH.
set -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
APK="${HELMDECK_APK_FILE:-surfaces/app/android/app/build/outputs/apk/release/app-release.apk}"
APPJSON="${HELMDECK_APP_JSON:-surfaces/app/app.json}"
OUT="${HELMDECK_APK_DIR:-/c/opt/helmdeck-apk}"
REPO="${HELMDECK_GH_REPO:-Tienduyvo/helmdeck-release}"

[ -f "$APK" ] || { echo "[push_apk] FAILED: no APK at $APK"; exit 1; }
VCODE=$(sed -n 's/.*"versionCode"[^0-9]*\([0-9]*\).*/\1/p' "$APPJSON" | head -1)
VNAME=$(sed -n 's/.*"version"[^"]*"\([^"]*\)".*/\1/p' "$APPJSON" | head -1)
[ -n "$VCODE" ] && [ -n "$VNAME" ] || { echo "[push_apk] FAILED: no version in $APPJSON"; exit 1; }
SHA=$(sha256sum < "$APK" | cut -d' ' -f1)   # stdin: a backslash path would prefix the hash with '\'
SIZE=$(wc -c < "$APK" | tr -d ' ')

TAG="$(gh release view -R "$REPO" --json tagName -q .tagName 2>/dev/null)"
[ -n "$TAG" ] || { echo "[push_apk] FAILED: no latest release on $REPO (gh not logged in?)"; exit 1; }

STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
cp "$APK" "$STAGE/helmdeck.apk" || { echo "[push_apk] FAILED: cannot stage the APK"; exit 1; }
echo "[push_apk] uploading APK v$VNAME ($VCODE, $SIZE bytes) to $REPO $TAG"
gh release upload "$TAG" "$STAGE/helmdeck.apk" -R "$REPO" --clobber \
  || { echo "[push_apk] FAILED: upload to $REPO $TAG"; exit 1; }

# Prove the artifact the phone's redirect will serve, not the upload's exit code.
GOT="$(gh release view "$TAG" -R "$REPO" --json assets \
  -q '.assets[] | select(.name=="helmdeck.apk") | (.size|tostring)+" "+(.digest // "")' 2>/dev/null)"
[ "${GOT%% *}" = "$SIZE" ] \
  || { echo "[push_apk] FAILED: release asset is '${GOT:-missing}', built $SIZE bytes"; exit 1; }
case "$GOT" in *sha256:*) [ "${GOT##*sha256:}" = "$SHA" ] \
  || { echo "[push_apk] FAILED: release asset digest ${GOT##*sha256:} differs from built $SHA"; exit 1; };; esac

mkdir -p "$OUT" || { echo "[push_apk] FAILED: cannot create $OUT"; exit 1; }
printf '{"versionCode": %s, "versionName": "%s", "url": "/apk/helmdeck.apk?v=%s-%s"}\n' \
  "$VCODE" "$VNAME" "$VCODE" "${SHA:0:12}" > "$OUT/version.json" \
  || { echo "[push_apk] FAILED: cannot write $OUT/version.json"; exit 1; }
echo "[push_apk] APK on $REPO $TAG; version.json staged for the worker deploy (push_update.sh)"
