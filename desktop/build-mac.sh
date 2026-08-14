#!/usr/bin/env bash
# HelmDeck - macOS build (one command). The mac twin of build-win.ps1.
#
#   bash desktop/build-mac.sh                       # unsigned, both arches
#   bash desktop/build-mac.sh --version 0.2.3       # stamp a release version
#   bash desktop/build-mac.sh --arch arm64          # Apple silicon only
#   bash desktop/build-mac.sh --no-web              # reuse an existing app/dist
#
# Produces in desktop/release/:
#   HelmDeck-<version>-arm64.dmg   HelmDeck-<version>-x64.dmg    (for humans)
#   HelmDeck-<version>-arm64.zip   HelmDeck-<version>-x64.zip    (Squirrel.Mac)
#   latest-mac.yml                                               (update feed)
#
# MUST RUN ON macOS. This is not a limitation of the script - codesign,
# hdiutil and notarytool are macOS-only, so there is no cross-build to fall
# back to. That is exactly why .github/workflows/desktop-mac.yml exists: the
# owner's box is Windows, so the Mac artifact is built by a macOS runner.
#
# SIGNING (all optional - a run with no secrets produces a working UNSIGNED
# build, which is what CI does by default):
#   CSC_LINK             base64 (or path) of the Developer ID Application .p12
#   CSC_KEY_PASSWORD     its password
# NOTARIZATION (only attempted when signing is on AND all of these are set;
# the same App Store Connect API key deploy/ios_credentials.sh already uses,
# so one key covers iOS and macOS):
#   ASC_API_KEY_PATH     path to AuthKey_XXXXXXXXXX.p8
#   ASC_KEY_ID           the key id
#   ASC_ISSUER_ID        the issuer uuid
#   APPLE_TEAM_ID        developer.apple.com -> Membership details
set -o pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/desktop" || exit 1

[ "$(uname -s)" = "Darwin" ] || {
  echo "!!! build-mac.sh must run on macOS - codesign/hdiutil/notarytool exist"
  echo "    nowhere else. Use the macos runner: .github/workflows/desktop-mac.yml"
  exit 2
}

VERSION=""; ARCH="both"; NO_WEB=0
while [ $# -gt 0 ]; do
  case "$1" in
    --version) VERSION="${2:-}"; shift ;;
    --arch)    ARCH="${2:-both}"; shift ;;
    --no-web)  NO_WEB=1 ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
  shift
done

echo "==> installing build deps"
# npm ci when the lockfile is authoritative (CI, clean checkout); npm install
# only as the fallback for a tree someone has been editing by hand.
[ -d node_modules/electron-builder ] || npm ci || npm install || exit 1
[ "$NO_WEB" = "1" ] || [ -d ../app/node_modules ] \
  || ( cd ../app && { npm ci || npm install; } ) || exit 1

if [ "$NO_WEB" != "1" ]; then
  echo "==> building the UI (Expo web export -> app/dist)"
  npm run build:web || { echo "!!! web export failed"; exit 1; }
fi
[ -d ../app/dist ] || { echo "!!! app/dist missing - drop --no-web"; exit 1; }

# --- signing / notarization decision ----------------------------------------
EB_ARGS=(--mac --config electron-builder.yml --publish never)
case "$ARCH" in
  arm64) EB_ARGS+=(--arm64) ;;
  x64)   EB_ARGS+=(--x64) ;;
  both)  EB_ARGS+=(--arm64 --x64) ;;
  *) echo "unknown --arch '$ARCH' (arm64|x64|both)"; exit 2 ;;
esac

if [ -n "${CSC_LINK:-}${CSC_NAME:-}" ]; then
  echo "==> signing: Developer ID identity supplied"
  if [ -n "${ASC_API_KEY_PATH:-}" ] && [ -n "${ASC_KEY_ID:-}" ] \
     && [ -n "${ASC_ISSUER_ID:-}" ] && [ -n "${APPLE_TEAM_ID:-}" ]; then
    # electron-builder reads notarytool creds from APPLE_API_*; the repo's own
    # convention (deploy/ios_credentials.sh, .env) is ASC_* - map one to the other
    # so a single key serves both pipelines.
    export APPLE_API_KEY="$ASC_API_KEY_PATH"
    export APPLE_API_KEY_ID="$ASC_KEY_ID"
    export APPLE_API_ISSUER="$ASC_ISSUER_ID"
    # the OBJECT form on purpose: `-c.mac.notarize=true` reaches electron-builder
    # as the string "true" - truthy, but with no team id attached.
    EB_ARGS+=("-c.mac.notarize.teamId=$APPLE_TEAM_ID")
    echo "==> notarization: ON (ASC key $ASC_KEY_ID, team $APPLE_TEAM_ID)"
  else
    echo "==> notarization: OFF (no complete ASC key + APPLE_TEAM_ID)"
    echo "    The .dmg will be signed but NOT notarized - Gatekeeper still warns."
  fi
else
  # Without this electron-builder hunts the keychain, finds nothing on a fresh
  # runner and fails the build. Being explicit turns that into a clean unsigned
  # build instead - the state every first CI run is in.
  export CSC_IDENTITY_AUTO_DISCOVERY=false
  echo "==> signing: OFF (no CSC_LINK/CSC_NAME) - UNSIGNED build"
  echo "    Gatekeeper will quarantine it; the auto-updater (Squirrel.Mac needs"
  echo "    a valid signature) will NOT be able to apply updates to this build."
fi

# electron-builder REWRITES package.json in place when extraMetadata is set
# (it drops scripts/devDependencies) - snapshot + restore so a release build
# never corrupts the source tree. Same trap build-win.ps1 documents.
PKG_BAK=""
if [ -n "$VERSION" ]; then
  EB_ARGS+=("-c.extraMetadata.version=$VERSION")
  PKG_BAK="$(mktemp)"; cp package.json "$PKG_BAK"
fi

echo "==> electron-builder ${EB_ARGS[*]}"
npx electron-builder "${EB_ARGS[@]}"; rc=$?
[ -n "$PKG_BAK" ] && { cp "$PKG_BAK" package.json; rm -f "$PKG_BAK"; }
[ "$rc" = "0" ] || { echo "!!! electron-builder failed"; exit 1; }

echo ""
echo "DONE. Artifacts -> desktop/release/"
ls -1 release/*.dmg release/*.zip release/latest-mac.yml 2>/dev/null | sed 's/^/  /'
