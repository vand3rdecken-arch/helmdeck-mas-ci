#!/usr/bin/env bash
# WEAR BUILD PROVENANCE GUARD - sourced by build_wear_aab.sh / build_wear_apk.sh.
#
# WHY (measured 2026-09-23): Play rejected Wear production vc1000006 for the
# font-size policy even though the fix was already written. The AAB was built
# 2026-09-17 23:27 from the working tree; the commit that removed the truncating
# maxLines/Ellipsis (a0d88137) landed at 23:29. The upload therefore carried the
# OLD code while git history said "fixed", and nothing could tell the two apart.
# A build has to be reproducible from a commit, so:
#   1. refuse to build while the Wear sources have uncommitted changes, and
#   2. stamp every artifact with the exact commit it was built from.
# Escape hatch for a deliberate local experiment: WEAR_ALLOW_DIRTY=1 (the
# artifact is then stamped DIRTY and must never be uploaded).

WEAR_GUARD_PATHS="surfaces/app/plugins/wear surfaces/app/plugins/withWearApp.js surfaces/app/plugins/withWearReleaseSigning.js"

wear_guard_check() {
  local dirty
  dirty="$(git status --porcelain -- $WEAR_GUARD_PATHS 2>/dev/null)"
  WEAR_SRC_SHA="$(git rev-parse --short=10 HEAD 2>/dev/null || echo unknown)"
  WEAR_SRC_STATE="clean"
  if [ -n "$dirty" ]; then
    if [ "${WEAR_ALLOW_DIRTY:-0}" = "1" ]; then
      WEAR_SRC_STATE="DIRTY"
      echo "[wear-guard] WARNING: building from UNCOMMITTED wear changes (WEAR_ALLOW_DIRTY=1) - artifact is stamped DIRTY, do NOT upload it:"
      echo "$dirty"
    else
      echo "[wear-guard] REFUSING to build: uncommitted changes in the Wear sources."
      echo "[wear-guard] vc1000006 was uploaded from such a tree (built 2 min before its fix was committed) and Play rejected it."
      echo "$dirty"
      echo "[wear-guard] Commit first, then build. (Local experiment only: WEAR_ALLOW_DIRTY=1.)"
      exit 1
    fi
  fi
  export WEAR_SRC_SHA WEAR_SRC_STATE
  echo "[wear-guard] building from commit $WEAR_SRC_SHA ($WEAR_SRC_STATE)"
}

# wear_guard_stamp <artifact> : writes <artifact>.src beside it.
wear_guard_stamp() {
  local art="$1"
  [ -f "$art" ] || return 0
  printf 'commit=%s\nstate=%s\nbuilt=%s\nsha256=%s\n' \
    "$WEAR_SRC_SHA" "$WEAR_SRC_STATE" "$(date '+%Y-%m-%d %H:%M:%S')" \
    "$(sha256sum "$art" | cut -d' ' -f1)" > "$art.src"
  echo "[wear-guard] stamped $art.src (commit $WEAR_SRC_SHA, $WEAR_SRC_STATE)"
}
