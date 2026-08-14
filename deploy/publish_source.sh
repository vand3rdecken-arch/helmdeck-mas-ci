#!/usr/bin/env bash
# Push the HelmDeck SOURCE to github.com/Tienduyvo/helmdeck - the same repo
# that already hosts the releases (owner's decision 2026-08-14: one repo, not
# a second source repo), which is what finally gives the macOS CI runner
# something to check out (.github/workflows/desktop-mac.yml).
#
#   bash deploy/publish_source.sh --dry-run     # audit only, push nothing
#   bash deploy/publish_source.sh               # audit, then push main
#
# THE REPO IS PUBLIC. A push publishes HISTORY, not just the working tree, and
# .gitignore only ever protected the present. So this script is an AUDIT that
# happens to end in a push - it re-runs every check on every invocation,
# because "it was clean in August" is not a property that survives new commits.
#
# What it refuses to do, and why each one is a real failure and not paperwork:
#   - push anything but ONE branch. `--all`/`--mirror` would publish ~20 stale
#     card branches AND hit GitHub's hard 100 MB file limit: the WIP branch
#     wip-expo-migration-20260812-223553 parks a 136 MB APK, an 81 MB .exe and
#     a 78 MB .aab under deploy/release_v1.0.7/. main itself is clean (largest
#     blob 14.8 MB) - that difference is the whole reason for --single-branch.
#   - push a blob over the limit (re-measured here, not assumed).
#   - push credential-shaped content found anywhere in the pushed history.
#   - push while the working tree is dirty.
set -o pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
REPO="${HELMDECK_GH_REPO:-Tienduyvo/helmdeck}"
BRANCH="${HELMDECK_PUBLISH_BRANCH:-main}"
REMOTE="${HELMDECK_PUBLISH_REMOTE:-origin}"
LIMIT_HARD=104857600      # GitHub rejects any file above this
LIMIT_WARN=52428800       # GitHub warns above this

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

fail() { echo "!!! $*"; exit 1; }
say()  { echo "==> $*"; }

say "auditing branch '$BRANCH' before publishing to $REPO (public)"

# ---- 0. the tree must be clean ---------------------------------------------
[ -z "$(git status --porcelain)" ] || fail "working tree is dirty - commit or stash first"
git rev-parse --verify "$BRANCH" >/dev/null 2>&1 || fail "no such branch: $BRANCH"

# ---- 1. blob sizes reachable from the branch -------------------------------
say "checking blob sizes reachable from $BRANCH"
SIZES="$(git rev-list --objects "$BRANCH" \
  | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' \
  | awk '$1=="blob"{print $3" "$4}' | sort -rn)"
BIGGEST="$(printf '%s\n' "$SIZES" | head -1)"
say "largest blob: $(printf '%s' "${BIGGEST%% *}" | awk '{printf "%.1f MB", $1/1048576}') (${BIGGEST#* })"
OVER="$(printf '%s\n' "$SIZES" | awk -v L="$LIMIT_HARD" '$1>L')"
[ -z "$OVER" ] || {
  echo "$OVER" | awk '{printf "    %.1f MB  %s\n", $1/1048576, $2}'
  fail "blob(s) above GitHub's 100 MB hard limit - the push WILL be rejected.
    Fix: keep them off this branch (they belong on a release, not in git)."
}
printf '%s\n' "$SIZES" | awk -v L="$LIMIT_WARN" '$1>L{printf "    warn: %.1f MB  %s\n", $1/1048576, $2}'

# ---- 2. secret-shaped PATHS ever added on this branch ----------------------
# The dangerous JSONs are the DAEMON's runtime state (the list .gitignore
# protects: settings/users/tracks/sessions/processes/copilot_*/plane_links).
# Matching those basenames anywhere over-fires on tool config - .claude/
# settings.json (hooks + permissions, deliberately tracked), app/.vscode/
# settings.json - so the state files are anchored to a daemon/ directory while
# the genuinely-always-secret shapes (keys, keystores, DBs, .env) stay global.
say "checking for secret-shaped paths in $BRANCH history"
BADPATHS="$(git log "$BRANCH" --pretty=format: --name-only --diff-filter=A \
  | sort -u \
  | grep -iE '(^|/)daemon/(settings|users|tracks|sessions|processes|copilot_log|copilot_stats|copilot_sessions|plane_links|driver_pids|recorder_pids)\.json$|(^|/)daemon/events\.jsonl$|\.db$|\.db-(wal|shm)$|\.jks$|\.keystore$|\.p8$|\.p12$|\.mobileprovision$|(^|/)[^/]*\.env$|(^|/)id_(rsa|ed25519)$|\.pem$' \
  || true)"
[ -z "$BADPATHS" ] || {
  printf '    %s\n' $BADPATHS
  fail "secret-shaped file(s) in history. Deleting them in a NEW commit does
    NOT help - the blob stays reachable. They must be purged (git filter-repo)
    and the credential rotated."
}

# ---- 3. credential-shaped CONTENT in every blob on this branch -------------
say "scanning blob contents for credentials"
HITS="$(git rev-list --objects "$BRANCH" \
  | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize)' \
  | awk '$1=="blob" && $3<3000000 {print $2}' \
  | git cat-file --batch 2>/dev/null \
  | grep -aoiE 'sk-ant-[A-Za-z0-9_-]{10,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----' \
  | sort -u || true)"
[ -z "$HITS" ] || {
  # print the shape, never the value
  printf '%s\n' "$HITS" | cut -c1-12 | sed 's/^/    matched prefix: /' | sort -u
  fail "credential-shaped content in history - rotate it and purge the blob."
}
say "no credential patterns found"

# ---- 4. the root README is the PRODUCT page, not the dev map ---------------
# Pushing main overwrites github.com/<repo>/README.md, which is the public
# download page (Play links, SmartScreen note, privacy policy). Swapping it for
# an internal repo map is a silent regression of a live page, so guard it.
#
# Read it from $BRANCH, NOT the working tree. Auditing a branch while checked
# out somewhere else is the normal case, and the first version of this check
# read ./README.md - so it happily green-lit a branch whose README was the
# internal map, because the WORKTREE's copy was the right one. A guard that
# inspects something other than what it is guarding is worse than none.
if ! git show "$BRANCH:README.md" 2>/dev/null | grep -q '^## Downloads'; then
  fail "README.md has no '## Downloads' section - it looks like the internal
    map, not the public landing page. Pushing it would replace the product page
    users land on (see docs/repo-map.md for where the dev map went)."
fi
say "README.md is the public landing page (Downloads section present)"

if [ "$DRY" = "1" ]; then
  say "dry run: audit passed, pushing nothing."
  exit 0
fi

# ---- 5. wire the remote (the local clone has never had one) ----------------
if ! git remote get-url "$REMOTE" >/dev/null 2>&1; then
  say "adding remote '$REMOTE' -> git@github.com:$REPO.git"
  # SSH on purpose: the owner's gh token has no `workflow` scope, so an HTTPS
  # push that touches .github/workflows/ is rejected outright. SSH is unaffected.
  git remote add "$REMOTE" "git@github.com:$REPO.git" || fail "could not add remote"
fi
say "remote: $(git remote get-url "$REMOTE")"

case "$(git remote get-url "$REMOTE")" in
  https://*) echo "!!! WARNING: HTTPS remote. If the push is rejected with"
             echo "    'refusing to allow an OAuth App to create or update workflow',"
             echo "    that is the missing \`workflow\` token scope - switch to SSH:"
             echo "    git remote set-url $REMOTE git@github.com:$REPO.git" ;;
esac

# ---- 6. push ONE branch ----------------------------------------------------
say "pushing $BRANCH -> $REMOTE (single branch, never --all)"
git push "$REMOTE" "$BRANCH:$BRANCH" || fail "push failed"

say "done: https://github.com/$REPO"
echo "    Next: Actions tab -> 'desktop-mac' -> Run workflow. With no secrets"
echo "    set it produces an UNSIGNED dmg/zip - that unsigned run is the honest"
echo "    smoke test for debt item mac-build-never-executed."
