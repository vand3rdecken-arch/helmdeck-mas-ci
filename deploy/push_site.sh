#!/usr/bin/env bash
# Ship helmdeck.de (the Cloudflare Worker in deploy/waitlist) and PROVE it landed.
#
# Why this exists: the site is the one surface the repo's card deploy hook does
# not touch. Card proc-20260814-s7 merged the full landing page on 2026-08-15 and
# helmdeck.de kept serving the 2026-08-13 waitlist-only build, because "merged"
# was read as "shipped" and `wrangler deploy` never ran. So this script does not
# stop at a successful upload - it re-reads the live origin and diffs the <title>
# against the source, and exits non-zero if they disagree.
#
# Usage:  bash deploy/push_site.sh [--check]
#           (no args)  deploy, then verify the live origin
#           --check    verify only - no deploy (safe to run any time)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/deploy/waitlist/src/index.js"
ORIGIN="https://helmdeck.de"

# The title is a good canary: it is server-rendered, cheap to fetch, and every
# content change so far has moved it. It is NOT a version stamp, so treat a
# match as "the current source is live", not as "nothing else drifted".
want_title() { sed -n 's|.*<title>\(.*\)</title>.*|\1|p' "$SRC" | head -1; }
live_title() { curl -fsS "$ORIGIN/" | sed -n 's|.*<title>\([^<]*\)</title>.*|\1|p' | head -1; }

verify() {
  local want live svc
  want="$(want_title)"
  # /health names the worker, which is what proves the domain is still bound to
  # THIS worker and not something else that happens to answer on 443.
  svc="$(curl -fsS "$ORIGIN/health")"
  case "$svc" in
    *helmdeck-waitlist*) ;;
    *) echo "FAIL: $ORIGIN/health is not the site worker: $svc" >&2; return 1 ;;
  esac
  live="$(live_title)"
  echo "  source title: $want"
  echo "  live   title: $live"
  if [ "$want" != "$live" ]; then
    echo "FAIL: $ORIGIN is serving a different build than deploy/waitlist/src." >&2
    echo "      Run 'bash deploy/push_site.sh' (without --check) to ship it." >&2
    return 1
  fi
  echo "OK: $ORIGIN serves the current source."
}

if [ "${1:-}" = "--check" ]; then
  echo "== checking $ORIGIN (no deploy) =="
  verify
  exit $?
fi

echo "== deploying deploy/waitlist -> $ORIGIN =="
( cd "$ROOT/deploy/waitlist" && npx wrangler deploy )

# Cloudflare's global propagation is fast but not instant; give it a few tries
# rather than declaring failure on the first stale edge response.
echo "== verifying the live origin =="
for attempt in 1 2 3 4 5; do
  if verify; then exit 0; fi
  echo "  (attempt $attempt: not live yet, retrying in 6s)"
  sleep 6
done

echo "FAIL: deploy reported success but $ORIGIN never served the new build." >&2
exit 1
