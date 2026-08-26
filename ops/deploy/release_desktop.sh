#!/usr/bin/env bash
# Build the HelmDeck Windows desktop installer and publish it to the GitHub
# "Downloads" release (github.com/Tienduyvo/helmdeck) - the desktop analog of
# push_relay.sh / push_update.sh, turning the "build the installer, checksum
# it, upload it, keep SHA256SUMS.txt correct" chore into one command.
#
# This build carries BOTH auto-updaters: the relay OTA (surfaces/desktop/updater.js +
# surfaces/desktop/tray.py, UI bundle only) and electron-updater (surfaces/desktop/native-
# updater.js, the WHOLE app - main.js included). So it is the LAST build a
# user installs by hand for real - after it, future changes of any kind
# arrive silently, UI or shell. Uploads latest.yml + the NSIS blockmap
# alongside the .exe (electron-updater's own feed format), not just the
# checksum this script already tracked.
#
#   bash ops/deploy/release_desktop.sh --version 0.2.2 --latest
#       build 0.2.2, upload the .exe + refreshed SHA256SUMS.txt to the newest
#       release (clobbering the old desktop asset; the APK line is preserved)
#   bash ops/deploy/release_desktop.sh --version 0.2.2 --tag v1.0.8
#       target/create a specific tag (a fresh release if the tag is new)
#   bash ops/deploy/release_desktop.sh --version 0.2.2 --no-build --latest
#       reuse an already-built surfaces/desktop/release/*.exe
#   bash ops/deploy/release_desktop.sh --version 0.2.2 --dry-run
#       build + checksum only, print the plan, upload nothing
#
# gh must be authenticated (gh auth status). Repo override: HELMDECK_GH_REPO.
set -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
REPO="${HELMDECK_GH_REPO:-Tienduyvo/helmdeck}"
export PATH="/c/Program Files/nodejs:$PATH"

VERSION=""; TAG=""; USE_LATEST=0; NO_BUILD=0; DRY_RUN=0; NOTES_FILE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --version)   VERSION="${2:-}"; shift ;;
    --tag)       TAG="${2:-}"; shift ;;
    --latest)    USE_LATEST=1 ;;
    --no-build)  NO_BUILD=1 ;;
    --dry-run)   DRY_RUN=1 ;;
    --notes)     NOTES_FILE="${2:-}"; shift ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
  shift
done

# Version: explicit, else package.json. A real release should pass --version
# ABOVE the last published one (the committed version can lag - see build-win.ps1).
if [ -z "$VERSION" ]; then
  VERSION="$(py -3.12 -c "import json;print(json.load(open('surfaces/desktop/package.json',encoding='utf-8'))['version'],end='')" 2>/dev/null)"
fi
[ -n "$VERSION" ] || { echo "no version - pass --version X.Y.Z"; exit 2; }
EXE="HelmDeck-Setup-${VERSION}-x64.exe"
EXE_PATH="surfaces/desktop/release/${EXE}"
YML_PATH="surfaces/desktop/release/latest.yml"          # electron-updater's feed manifest
BLOCKMAP_PATH="${EXE_PATH}.blockmap"           # differential-update data
echo "==> HelmDeck desktop release: version $VERSION -> $REPO"

# ---- build ----------------------------------------------------------------
if [ "$NO_BUILD" != "1" ]; then
  echo "==> building the installer (electron-builder, version-stamped $VERSION)"
  BUILT=0
  # Prefer the maintained one-command build (does the winCodeSign workaround).
  for ps in powershell.exe pwsh; do
    if command -v "$ps" >/dev/null 2>&1; then
      "$ps" -ExecutionPolicy Bypass -File surfaces/desktop/build-win.ps1 -Version "$VERSION" && BUILT=1
      break
    fi
  done
  if [ "$BUILT" != "1" ]; then
    # powershell absent (it can be off the PATH on this box) - build inline with
    # the same steps: icon, deps, winCodeSign-without-darwin, web export, build.
    echo "==> powershell not found - inline bash build"
    ( cd surfaces/desktop
      # icon.ico is git-ignored (generated from icon-1024.png); NSIS needs it.
      [ -f assets/icon.ico ] || py -3.12 ../../ops/tools/make_icon.py || exit 1
      [ -d node_modules/electron-builder ] || npm install || exit 1
      cache="$LOCALAPPDATA/electron-builder/Cache/winCodeSign"
      z="node_modules/7zip-bin/win/x64/7za.exe"
      arc="$(ls "$cache"/*.7z 2>/dev/null | head -1)"
      if [ -n "$arc" ] && [ -x "$z" ]; then
        rm -rf "$cache/winCodeSign-2.6.0"
        "$z" x "$arc" "-o$cache/winCodeSign-2.6.0" "-xr!darwin" -y >/dev/null || true
      fi
      npm run build:web || exit 1
      # electron-builder rewrites package.json in place for extraMetadata (drops
      # scripts/devDeps) - snapshot + restore so the source tree stays intact.
      cp package.json .package.json.bak
      # --publish never: still WRITES latest.yml + the NSIS blockmap locally
      # (electron-builder.yml carries a publish: block) without uploading -
      # this script uploads them itself below, same as SHA256SUMS.txt.
      npx electron-builder --win --config electron-builder.yml --publish never \
        -c.extraMetadata.version="$VERSION"; rc=$?
      mv .package.json.bak package.json
      [ "$rc" = "0" ] || exit 1
    ) || { echo "!!! build failed"; exit 1; }
  fi
fi
[ -f "$EXE_PATH" ] || { echo "!!! no $EXE_PATH - build first (drop --no-build)"; exit 1; }
[ -f "$YML_PATH" ] || echo "!!! no $YML_PATH - electron-updater's feed won't see this release (check electron-builder.yml's publish: block is present)"
[ -f "$BLOCKMAP_PATH" ] || echo "!!! no $BLOCKMAP_PATH - differential updates degrade to a full download (not fatal)"

# ---- checksum ('<hash> *<file>', the shape the published SHA256SUMS uses) ---
SUM="$(cd surfaces/desktop/release && printf '%s *%s' "$(sha256sum "$EXE" | awk '{print $1}')" "$EXE")"
echo "==> $SUM"

if [ "$DRY_RUN" = "1" ]; then
  echo "==> dry run: built + checksummed, uploading nothing."
  exit 0
fi

# ---- resolve the target release -------------------------------------------
if [ -z "$TAG" ] && [ "$USE_LATEST" = "1" ]; then
  TAG="$(gh release view -R "$REPO" --json tagName -q .tagName 2>/dev/null)"
  [ -n "$TAG" ] || { echo "!!! no latest release found on $REPO"; exit 1; }
fi
[ -n "$TAG" ] || { echo "!!! choose a target: --latest or --tag <tag>"; exit 2; }
echo "==> target release: $TAG"

if ! gh release view "$TAG" -R "$REPO" >/dev/null 2>&1; then
  echo "==> creating release $TAG"
  NF=(); [ -n "$NOTES_FILE" ] && NF=(--notes-file "$NOTES_FILE")
  gh release create "$TAG" -R "$REPO" --title "HelmDeck Desktop $VERSION" \
    "${NF[@]:---generate-notes}" || { echo "!!! release create failed"; exit 1; }
fi

# ---- refresh SHA256SUMS.txt (keep the APK line, replace the desktop line) --
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
gh release download "$TAG" -R "$REPO" -p SHA256SUMS.txt -D "$TMP" 2>/dev/null || true
SUMS="$TMP/SHA256SUMS.txt"; [ -f "$SUMS" ] || : > "$SUMS"
grep -v 'HelmDeck-Setup-.*-x64\.exe' "$SUMS" > "$SUMS.new" 2>/dev/null || : > "$SUMS.new"
printf '%s\n' "$SUM" >> "$SUMS.new"
mv "$SUMS.new" "$SUMS"

# latest.yml + blockmap are optional (electron-builder.yml might be building
# without the publish: block in some older checkout) - upload whatever exists.
UPLOAD_FILES=("$EXE_PATH" "$SUMS")
[ -f "$YML_PATH" ] && UPLOAD_FILES+=("$YML_PATH")
[ -f "$BLOCKMAP_PATH" ] && UPLOAD_FILES+=("$BLOCKMAP_PATH")

echo "==> uploading ${UPLOAD_FILES[*]##*/} to $TAG"
gh release upload "$TAG" -R "$REPO" --clobber "${UPLOAD_FILES[@]}" \
  || { echo "!!! upload failed"; exit 1; }

# --clobber only replaces a same-named asset; an OLDER desktop installer (or
# its version-specific blockmap) has a different filename and would linger.
# latest.yml is version-generic (always the same name) so --clobber alone
# keeps it current - no cleanup needed for it.
for a in $(gh release view "$TAG" -R "$REPO" --json assets -q '.assets[].name' 2>/dev/null); do
  case "$a" in
    HelmDeck-Setup-*-x64.exe)
      [ "$a" = "$EXE" ] || { echo "==> removing stale asset $a"; \
        gh release delete-asset "$TAG" -R "$REPO" "$a" -y 2>/dev/null || true; } ;;
    HelmDeck-Setup-*-x64.exe.blockmap)
      [ "$a" = "$(basename "$BLOCKMAP_PATH")" ] || { echo "==> removing stale asset $a"; \
        gh release delete-asset "$TAG" -R "$REPO" "$a" -y 2>/dev/null || true; } ;;
  esac
done

[ -n "$NOTES_FILE" ] && {
  echo "==> updating release notes from $NOTES_FILE"
  gh release edit "$TAG" -R "$REPO" --notes-file "$NOTES_FILE" \
    || echo "!!! notes update failed (asset upload already succeeded)"
}

echo "==> done: https://github.com/$REPO/releases/tag/$TAG"
echo "    Existing desktop installs on $VERSION-capable builds auto-update over the"
echo "    relay; users on an OLDER build install this .exe ONCE to gain auto-update."
