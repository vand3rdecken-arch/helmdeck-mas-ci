#!/usr/bin/env bash
# RETIRED 2026-08-26 - read before using.
#
# This script's entire premise (owner's decision 2026-08-14: "one repo" -
# filter+push SOURCE into the SAME repo the public release builds live in,
# because that repo was public and CI needed something to check out) no
# longer holds. The repo has since been split:
#   - Tienduyvo/helmdeck (PRIVATE) now holds the FULL, UNFILTERED source via
#     a plain `git push` (no .attachments/ or ops/docs/ stripping needed -
#     there is no public reader to protect it from anymore).
#   - Tienduyvo/helmdeck-release (PUBLIC) holds ONLY release binaries -
#     running THIS script against it (e.g. via HELMDECK_GH_REPO) would push
#     full source into a repo meant to carry release assets only.
# The macOS CI runner (.github/workflows/desktop-mac.yml) now checks out the
# PRIVATE repo directly - normal `git push origin expo-migration` already
# gets it there, same as every other commit. If Actions on a private repo
# ever needs *filtered* history again for some other reason, revive this;
# until then it fails loudly below rather than silently doing something that
# made sense under the old topology but not this one.
set -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"
if [ -z "${HELMDECK_PUBLISH_SOURCE_ACKNOWLEDGE_RETIRED:-}" ]; then
  echo "!!! publish_source.sh is retired (repo split 2026-08-26) - see the header comment."
  echo "!!! Source now goes to the PRIVATE Tienduyvo/helmdeck via a plain 'git push'."
  echo "!!! Set HELMDECK_PUBLISH_SOURCE_ACKNOWLEDGE_RETIRED=1 to run this anyway."
  exit 1
fi
REPO="${HELMDECK_GH_REPO:-Tienduyvo/helmdeck}"
# The local trunk is NOT called main. main is a stale 2026-08-12 branch with no
# .github/ at all; the branch that actually carries the source (and the mac
# workflow) is expo-migration - `git log main` vs the checked-out branch is the
# one-line proof. Publishing "main" therefore published a tree the macOS runner
# could not build, which is the whole point of this script.
BRANCH="${HELMDECK_PUBLISH_BRANCH:-expo-migration}"
# ...but it must LAND on the remote's default branch. GitHub only offers
# workflow_dispatch for workflows present on the default branch, and
# desktop-mac.yml's own `push: branches: [main]` trigger never fires from a
# branch by another name. So source and target are separate knobs.
TARGET="${HELMDECK_PUBLISH_TARGET:-main}"
REMOTE="${HELMDECK_PUBLISH_REMOTE:-origin}"
LIMIT_HARD=104857600      # GitHub rejects any file above this
LIMIT_WARN=52428800       # GitHub warns above this

DRY=0
FILTER=0
for a in "$@"; do
  case "$a" in
    --dry-run)        DRY=1 ;;
    --filter-private) FILTER=1 ;;
    *) echo "unknown arg: $a"; exit 2 ;;
  esac
done
# --filter-private is how the repo was ACTUALLY published on 2026-08-15, so it
# lives here rather than in somebody's shell history. It publishes a FILTERED
# MIRROR: clone the trunk to a temp dir, drop .attachments/ from that copy's
# history with git_filter_repo, push the result. The owner's real repo is never
# rewritten - which matters, because ~20 live card branches and worktrees hang
# off the trunk and a filter-repo run on it would strand every one of them.
#
# Verified before relying on it: the rewrite is DETERMINISTIC. Filtering the
# same input commit twice produced the identical sha (a10d9454), so the public
# lineage stays stable and later publishes FAST-FORWARD instead of needing a
# force every time. (Measured by filtering 2349475 in two separate clones - an
# earlier attempt seemed nondeterministic purely because another card had
# landed 2 commits on the trunk between the two runs.)

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

# ---- 2b. PRIVATE-BUT-NOT-SECRET paths (the gap check 2 does not close) -----
# A credential scanner asks "can this be used to log in", and answers "no" for
# a photo. But `.attachments/` is where the daemon parks what the OWNER uploads
# into chat - phone screenshots of his own board: unreleased card titles, due
# dates, distribution decisions. Nothing there is a credential, so checks 2 and
# 3 wave it through, and the push publishes it forever.
#
# That these are user data and not source is not a judgement call made here -
# the repo already says so twice: their siblings daemon/recordings/ and
# daemon/checkpoints/ are git-ignored, and electron-builder.yml refuses to ship
# .attachments/** into the desktop bundle. Only git itself never got the memo,
# so five of them were committed before .gitignore covered the path.
#
# Fails CLOSED, because the cost is asymmetric: a needless stop costs one env
# var, publishing the owner's private board costs a history rewrite of a public
# repo. HELMDECK_PUBLISH_ALLOW_PRIVATE=1 is the deliberate "yes, I looked at
# them, publish anyway" - it must be a decision, never a default.
# docs/ is the same class from a different direction, and the whole tree is out
# by OWNER DECISION (2026-08-16): "you work local so just don't publish docs".
#
# It is TRACKED on purpose - a card's worktree holds only TRACKED files, so an
# internal reference that isn't in git is invisible exactly where it is needed
# (docs/glasses-reference.md is mandatory reading for every glasses card). The
# `docs` line in .gitignore keeps NEW docs out by default; this keeps the ones
# that must be tracked out of the PUBLIC mirror. Two different jobs.
#
# The tree is private-but-not-secret in exactly the way check 2 cannot see:
# glasses-reference.md carries the owner's absolute home paths, his WhatsApp-
# bridge setup and the LID identity mechanics; docs/store/screenshots/ are
# pictures of his real board (card titles, dates). No credential in any of it,
# so the scanner waves it all through - the same gap .attachments/ falls
# through, and the reason that gap is worth a second net at all.
say "checking for private user-content paths in $BRANCH history"
PRIVPATHS="$(git log "$BRANCH" --pretty=format: --name-only --diff-filter=A \
  | sort -u \
  | grep -iE '(^|/)\.attachments/|(^|/)\.copilot_attachments/|(^|/)daemon/recordings/|(^|/)daemon/checkpoints/|(^|/)docs/' \
  || true)"
if [ -n "$PRIVPATHS" ]; then
  printf '    %s\n' $PRIVPATHS
  if [ "$FILTER" = "1" ]; then
    say "--filter-private: the above will be REMOVED from the published mirror"
  elif [ "${HELMDECK_PUBLISH_ALLOW_PRIVATE:-0}" = "1" ]; then
    say "HELMDECK_PUBLISH_ALLOW_PRIVATE=1 - publishing the above ANYWAY"
  else
    fail "private user content in history - these are chat uploads, not source.
    Like any blob, deleting them in a NEW commit does NOT unpublish them; the
    push publishes history. Your options:
      - --filter-private   publish a filtered MIRROR (clone + git_filter_repo in
                           a temp dir; your real repo is never rewritten). This
                           is how the repo was published on 2026-08-15.
      - HELMDECK_PUBLISH_ALLOW_PRIVATE=1 if you have LOOKED at them and are
        content for them to be public forever.
    Look first: git show $BRANCH:<path> > /tmp/x.jpg"
  fi
fi

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
if [ "$FILTER" = "1" ]; then
  # Never filter in place: the trunk is the base of ~20 live card branches and
  # worktrees, and git_filter_repo rewrites every sha it touches.
  command -v py >/dev/null 2>&1 && PY=py || PY=python3
  "$PY" -3.12 -c "import git_filter_repo" 2>/dev/null \
    || $PY -c "import git_filter_repo" 2>/dev/null \
    || fail "git_filter_repo not importable - pip install git-filter-repo"
  TMP="${HELMDECK_PUBLISH_TMP:-/c/hd/publish-mirror}"
  say "building a filtered mirror in $TMP (your repo is NOT touched)"
  rm -rf "$TMP" || fail "could not clear $TMP"
  git clone -q --single-branch --branch "$BRANCH" --no-local "file://$ROOT" "$TMP" \
    || fail "clone failed"
  ( cd "$TMP" && "$PY" -3.12 -m git_filter_repo \
      --path .attachments --path .copilot_attachments --invert-paths --force ) \
    || fail "filter-repo failed"
  # prove it, do not trust it: the mirror must contain ZERO private paths and
  # must still carry the workflow the whole exercise exists to run.
  LEFT="$( cd "$TMP" && git log --all --pretty=format: --name-only | sort -u \
           | grep -cE '^\.attachments/|^\.copilot_attachments/' )"
  [ "$LEFT" = "0" ] || fail "mirror STILL contains $LEFT private path(s) - not pushing"
  ( cd "$TMP" && git ls-tree -r --name-only HEAD -- .github/workflows | grep -q . ) \
    || fail "mirror has no .github/workflows - the runner would have nothing to do"
  say "mirror clean (0 private paths, workflows present) - pushing to $REMOTE/$TARGET"
  ( cd "$TMP" && git remote add origin "git@github.com:$REPO.git" \
      && git push origin "HEAD:$TARGET" ) || fail "push failed
    A non-fast-forward here is expected ONLY the first time (the remote's main
    was a single unrelated 'HelmDeck public releases' commit). Re-run with an
    explicit lease once you have checked what is on the remote:
      cd $TMP && git push --force-with-lease=$TARGET:<sha> origin HEAD:$TARGET
    Force is safe for the download shelf - all release tags pin their own
    commit and assets live in the releases API, not in git - but verify first."
else
  say "pushing $BRANCH -> $REMOTE/$TARGET (single branch, never --all)"
  git push "$REMOTE" "$BRANCH:$TARGET" || fail "push failed"
fi

say "done: https://github.com/$REPO"
echo "    Next: Actions tab -> 'desktop-mac' -> Run workflow. With no secrets"
echo "    set it produces an UNSIGNED dmg/zip - that unsigned run is the honest"
echo "    smoke test for debt item mac-build-never-executed."
