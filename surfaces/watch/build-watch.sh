#!/usr/bin/env bash
# HelmDeck Watch - build (XcodeGen -> xcodebuild). Mirrors
# surfaces/desktop/build-mac.sh's shape on purpose: MUST run on macOS
# (xcodebuild is Xcode-only), succeeds UNSIGNED with no secrets so a fresh CI
# run always proves the target compiles, and only archives/signs when Apple
# credentials are present.
#
#   bash surfaces/watch/build-watch.sh              # compile-only check, unsigned
#   bash surfaces/watch/build-watch.sh --archive    # full archive (needs signing env)
#
# SIGNING (optional - a run with none of these produces an unsigned,
# compile-only build; no Apple-account involvement at all):
#   ASC_KEY_ID / ASC_ISSUER_ID / ASC_API_KEY_PATH   App Store Connect API key
#                                                    (same key ops/deploy/ios_credentials.sh
#                                                    and surfaces/desktop/build-mac.sh use)
#   APPLE_TEAM_ID                                   developer.apple.com -> Membership details
#
# First signed run will very likely need ONE manual step from the Account
# Holder: enabling the Push Notifications capability on the new
# app.helmdeck.watchcompanion.watchkitapp App ID. This is not new territory -
# DEPLOY.md already documents the identical trap (and its one-click fix) from
# registering app.helmdeck itself (commit 5eb6a5b).
set -o pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT" || exit 1

[ "$(uname -s)" = "Darwin" ] || {
  echo "!!! build-watch.sh must run on macOS - xcodebuild exists nowhere else."
  echo "    Use the macos runner: .github/workflows/watchos-app.yml"
  exit 2
}

ARCHIVE=0
[ "${1:-}" = "--archive" ] && ARCHIVE=1

echo "==> installing XcodeGen"
command -v xcodegen >/dev/null || brew install xcodegen || exit 1

echo "==> generating HelmDeckWatch.xcodeproj from project.yml"
xcodegen generate || exit 1

if [ -n "${ASC_KEY_ID:-}" ] && [ -n "${ASC_ISSUER_ID:-}" ] && [ -n "${ASC_API_KEY_PATH:-}" ] && [ -n "${APPLE_TEAM_ID:-}" ]; then
  echo "==> signing: ON (ASC key $ASC_KEY_ID, team $APPLE_TEAM_ID)"
  SIGN_ARGS=(-allowProvisioningUpdates \
    -authenticationKeyPath "$ASC_API_KEY_PATH" \
    -authenticationKeyID "$ASC_KEY_ID" \
    -authenticationKeyIssuerID "$ASC_ISSUER_ID" \
    "DEVELOPMENT_TEAM=$APPLE_TEAM_ID")
else
  echo "==> signing: OFF (no complete ASC key + APPLE_TEAM_ID) - unsigned compile-only build"
  SIGN_ARGS=(CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO)
  if [ "$ARCHIVE" = "1" ]; then
    echo "    --archive requested but nothing to sign it with - falling back to compile-only"
    ARCHIVE=0
  fi
fi

if [ "$ARCHIVE" = "1" ]; then
  echo "==> xcodebuild archive (HelmDeckWatchCompanion, embeds HelmDeckWatch)"
  xcodebuild archive \
    -project HelmDeckWatch.xcodeproj \
    -scheme HelmDeckWatchCompanion \
    -archivePath build/HelmDeckWatchCompanion.xcarchive \
    "${SIGN_ARGS[@]}" || { echo "!!! archive failed"; exit 1; }
  echo "DONE. Archive -> surfaces/watch/build/HelmDeckWatchCompanion.xcarchive"
else
  echo "==> xcodebuild build (compile-only check; embedding proves both targets)"
  xcodebuild build \
    -project HelmDeckWatch.xcodeproj \
    -scheme HelmDeckWatchCompanion \
    -destination "generic/platform=iOS" \
    "${SIGN_ARGS[@]}" || { echo "!!! build failed"; exit 1; }
  echo "DONE. Target compiles."
fi
