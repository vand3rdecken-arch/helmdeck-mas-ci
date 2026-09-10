#!/usr/bin/env bash
# HelmDeck - Mac App Store build. The mas twin of build-mac.sh: same shell,
# same daemon, same surfaces/app/dist, DIFFERENT packaging (electron-builder.mas.yml -
# App Sandbox on, appId app.helmdeck, target mas -> .pkg, no publish feed).
#
#   bash surfaces/desktop/build-mas.sh                       # both arches
#   bash surfaces/desktop/build-mas.sh --version 0.2.17      # stamp a release version
#   bash surfaces/desktop/build-mas.sh --arch arm64          # Apple silicon only
#   bash surfaces/desktop/build-mas.sh --no-web               # reuse an existing surfaces/app/dist
#
# Produces in surfaces/desktop/release/: HelmDeck-<version>-{arm64,x64}.pkg
#
# MUST RUN ON macOS, same reason as build-mac.sh: codesign/productbuild are
# macOS-only tools.
#
# REQUIRED (a mas build is meaningless unsigned - Apple's installer refuses
# an unsigned .pkg outright, unlike the direct-distribution build which can
# produce a working unsigned artifact):
#   CSC_LINK / CSC_KEY_PASSWORD                     Mac App Distribution .p12 (signs HelmDeck.app)
#   CSC_INSTALLER_LINK / CSC_INSTALLER_KEY_PASSWORD Mac Installer Distribution .p12 (signs the .pkg)
#   surfaces/desktop/build/embedded.provisionprofile              MAC_APP_STORE provisioning profile
#
# All three come from ops/deploy/mac_credentials.py (DEPLOY.md 1f):
#   py -3.12 ops/deploy/mac_credentials.py --check  --type mas-app
#   py -3.12 ops/deploy/mac_credentials.py --create --type mas-app        # -> .p12 + password
#   py -3.12 ops/deploy/mac_credentials.py --check  --type mas-installer
#   py -3.12 ops/deploy/mac_credentials.py --create --type mas-installer  # -> .p12 + password
#   py -3.12 ops/deploy/mac_credentials.py --bundleids                    # confirm app.helmdeck's resource id
#   py -3.12 ops/deploy/mac_credentials.py --profile-create --name "HelmDeck Mac App Store" \
#       --bundle-id-resource <id from --bundleids> --cert-id <id from --check --type mas-app>
# then: base64 the two .p12s into CSC_LINK/CSC_INSTALLER_LINK (same shape as
# MAC_CSC_LINK already is for the direct build), and copy the .provisionprofile
# to surfaces/desktop/build/embedded.provisionprofile (git-ignored - a provisioning
# profile is tied to this team, not shippable source).
set -o pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/desktop" || exit 1

[ "$(uname -s)" = "Darwin" ] || {
  echo "!!! build-mas.sh must run on macOS - codesign/productbuild exist nowhere else."
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

[ -n "${CSC_LINK:-}" ] || { echo "!!! CSC_LINK not set (Mac App Distribution .p12) - a mas build cannot be unsigned"; exit 1; }
[ -n "${CSC_INSTALLER_LINK:-}" ] || { echo "!!! CSC_INSTALLER_LINK not set (Mac Installer Distribution .p12) - electron-builder cannot sign the .pkg"; exit 1; }
[ -f build/embedded.provisionprofile ] || { echo "!!! build/embedded.provisionprofile missing - see ops/deploy/mac_credentials.py --profile-create (DEPLOY.md 1f)"; exit 1; }

echo "==> installing build deps"
[ -d node_modules/electron-builder ] || npm ci || npm install || exit 1
[ "$NO_WEB" = "1" ] || [ -d ../app/node_modules ] \
  || ( cd ../app && { npm ci || npm install; } ) || exit 1

if [ "$NO_WEB" != "1" ]; then
  echo "==> building the UI (Expo web export -> surfaces/app/dist)"
  npm run build:web || { echo "!!! web export failed"; exit 1; }
fi
[ -d ../app/dist ] || { echo "!!! surfaces/app/dist missing - drop --no-web"; exit 1; }

# `--mac mas` (not bare `--mac`) - config-level mac.target:[mas] in
# electron-builder.mas.yml does NOT replace the base config's [dmg, zip]
# via `extends` as the comment there intends: electron-builder concatenates
# extended arrays instead of overriding them (measured 2026-09-10 - a mas
# run without this flag also builds unsigned direct-distribution dmg/zip/app
# it has no Developer ID cert for). CLI target selection bypasses that merge.
EB_ARGS=(--mac mas --config electron-builder.mas.yml --publish never)
case "$ARCH" in
  arm64) EB_ARGS+=(--arm64) ;;
  x64)   EB_ARGS+=(--x64) ;;
  both)  EB_ARGS+=(--arm64 --x64) ;;
  *) echo "unknown --arch '$ARCH' (arm64|x64|both)"; exit 2 ;;
esac

# electron-builder REWRITES package.json in place when extraMetadata is set -
# snapshot + restore, same trap build-mac.sh/build-win.ps1 already document.
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
echo "DONE. Artifacts -> surfaces/desktop/release/mas*/ (upload with Transporter or"
echo "'xcrun altool --upload-app', never with a git push - a .pkg is a binary, not source)."
# the mas target nests its .pkg under a per-arch appOutDir (release/mas/,
# release/mas-arm64/), unlike dmg/zip which land flat in release/ - measured
# 2026-09-10, do not "fix" this back to release/*.pkg.
ls -1 release/mas*/*.pkg 2>/dev/null | sed 's/^/  /'
