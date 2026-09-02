#!/usr/bin/env bash
# Publish already-built macOS desktop artifacts (dmg+zip+latest-mac.yml) to
# the GitHub "Downloads" release - the macOS twin of release_desktop.sh.
#
# This box is Windows: codesign/hdiutil/notarytool are macOS-only, so unlike
# release_desktop.sh this script NEVER builds - it only publishes a set that
# surfaces/desktop/build-mac.sh (on real macOS) or .github/workflows/desktop-mac.yml
# (macos-14 runner; `gh run download <run> -n helmdeck-macos -D DIR`) already
# produced. Without this script those artifacts sit in CI's 14-day artifact
# storage or a local dir, invisible to electron-updater's GithubProvider
# (surfaces/desktop/native-updater.js), which only ever looks at RELEASE assets - so
# skipping this step leaves the Mac build signed and notarized but not
# actually reachable by an installed app. Same checksum/SHA256SUMS.txt/
# stale-asset discipline as release_desktop.sh, kept as one file per platform
# because the build step itself has nothing in common (no --version stamping
# here - the version comes from latest-mac.yml, which build-mac.sh already
# wrote from surfaces/desktop/package.json or its own --version flag).
#
#   bash ops/deploy/release_desktop_mac.sh --dir surfaces/desktop/release --latest
#   bash ops/deploy/release_desktop_mac.sh --dir /path/to/ci-artifacts --tag v1.0.7
#   bash ops/deploy/release_desktop_mac.sh --dir surfaces/desktop/release --dry-run
#
# gh must be authenticated (gh auth status). Repo override: HELMDECK_GH_REPO.
set -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
REPO="${HELMDECK_GH_REPO:-Tienduyvo/helmdeck-release}"

DIR="surfaces/desktop/release"; TAG=""; USE_LATEST=0; DRY_RUN=0; NOTES_FILE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dir)     DIR="${2:-}"; shift ;;
    --tag)     TAG="${2:-}"; shift ;;
    --latest)  USE_LATEST=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --notes)   NOTES_FILE="${2:-}"; shift ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
  shift
done

YML="$DIR/latest-mac.yml"
[ -f "$YML" ] || { echo "!!! no $YML in $DIR - build on macOS first (surfaces/desktop/build-mac.sh) or point --dir at a downloaded CI artifact set (gh run download <run> -n helmdeck-macos -D DIR)"; exit 1; }

VERSION="$(grep -m1 '^version:' "$YML" | sed 's/^version: *//; s/[[:space:]]*$//')"
[ -n "$VERSION" ] || { echo "!!! could not read 'version:' from $YML"; exit 1; }
echo "==> HelmDeck macOS desktop release: version $VERSION -> $REPO"

MAIN_FILES=()
for f in "HelmDeck-${VERSION}-arm64.dmg" "HelmDeck-${VERSION}-x64.dmg" \
         "HelmDeck-${VERSION}-arm64.zip" "HelmDeck-${VERSION}-x64.zip"; do
  [ -f "$DIR/$f" ] || { echo "!!! missing $DIR/$f"; exit 1; }
  MAIN_FILES+=("$DIR/$f")
done

UPLOAD_FILES=("${MAIN_FILES[@]}" "$YML")
for f in "${MAIN_FILES[@]}"; do
  [ -f "$f.blockmap" ] && UPLOAD_FILES+=("$f.blockmap")
done

# ---- checksums (same '<hash> *<file>' shape release_desktop.sh writes) -----
SUMLINES=()
for f in "${MAIN_FILES[@]}"; do
  SUMLINES+=("$(sha256sum "$f" | awk -v n="$(basename "$f")" '{print $1" *"n}')")
done
printf '%s\n' "${SUMLINES[@]}"

if [ "$DRY_RUN" = "1" ]; then
  echo "==> dry run: checksummed only, uploading nothing."
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

# ---- refresh SHA256SUMS.txt (keep every non-mac line, replace the mac ones)
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
gh release download "$TAG" -R "$REPO" -p SHA256SUMS.txt -D "$TMP" 2>/dev/null || true
SUMS="$TMP/SHA256SUMS.txt"; [ -f "$SUMS" ] || : > "$SUMS"
grep -v -E 'HelmDeck-[0-9.]+-(arm64|x64)\.(dmg|zip)$' "$SUMS" > "$SUMS.new" 2>/dev/null || : > "$SUMS.new"
printf '%s\n' "${SUMLINES[@]}" >> "$SUMS.new"
mv "$SUMS.new" "$SUMS"

echo "==> uploading ${UPLOAD_FILES[*]##*/} + SHA256SUMS.txt to $TAG"
gh release upload "$TAG" -R "$REPO" --clobber "${UPLOAD_FILES[@]}" "$SUMS" \
  || { echo "!!! upload failed"; exit 1; }

# --clobber only replaces same-named assets; an older mac version has
# different filenames and would linger (latest-mac.yml is version-generic,
# so --clobber alone keeps it current - no cleanup needed for it).
for a in $(gh release view "$TAG" -R "$REPO" --json assets -q '.assets[].name' 2>/dev/null); do
  case "$a" in
    HelmDeck-*-arm64.dmg|HelmDeck-*-x64.dmg|HelmDeck-*-arm64.zip|HelmDeck-*-x64.zip| \
    HelmDeck-*-arm64.dmg.blockmap|HelmDeck-*-x64.dmg.blockmap| \
    HelmDeck-*-arm64.zip.blockmap|HelmDeck-*-x64.zip.blockmap)
      case "$a" in
        *"$VERSION"*) : ;;
        *) echo "==> removing stale asset $a"
           gh release delete-asset "$TAG" -R "$REPO" "$a" -y 2>/dev/null || true ;;
      esac ;;
  esac
done

[ -n "$NOTES_FILE" ] && {
  echo "==> updating release notes from $NOTES_FILE"
  gh release edit "$TAG" -R "$REPO" --notes-file "$NOTES_FILE" \
    || echo "!!! notes update failed (asset upload already succeeded)"
}

echo "==> done: https://github.com/$REPO/releases/tag/$TAG"
echo "    New Mac installs: download the .dmg. Existing ${VERSION}+ Mac installs pick"
echo "    up newer zips silently via Squirrel.Mac (electron-updater) on next quit."
