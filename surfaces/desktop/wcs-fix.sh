#!/usr/bin/env bash
# Pre-populate the electron-builder winCodeSign cache WITHOUT the macOS symlinks
# (darwin/*.dylib) that fail to extract on Windows without the symlink privilege.
# app-builder then finds the extracted dir and skips its own (failing) extraction.
set -u
CACHE="$HOME/AppData/Local/electron-builder/Cache/winCodeSign"
Z="$HOME/Downloads/helmdeck/surfaces/desktop/node_modules/7zip-bin/win/x64/7za.exe"
mkdir -p "$CACHE"
ARC="$(ls "$CACHE"/*.7z 2>/dev/null | head -1)"
if [ -z "$ARC" ]; then
  echo "NO_ARCHIVE"   # nothing downloaded yet; the build will fetch it
  exit 0
fi
echo "archive: $ARC"
DEST="$CACHE/winCodeSign-2.6.0"
rm -rf "$DEST"
"$Z" x "$ARC" -o"$DEST" -xr'!'darwin -y >/tmp/wcs.log 2>&1
echo "exit=$?"
tail -3 /tmp/wcs.log
echo "--- dest content ---"
ls "$DEST" 2>/dev/null
