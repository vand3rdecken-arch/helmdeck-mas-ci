#!/usr/bin/env bash
# Deploy the Pair worker (surfaces/relay/pair_worker) - the narrow public door to
# GET /relay/pair/claim. Mirrors push_glance.sh's shape, simplified: no static
# assets to sync (this worker has no webapp), so it is deploy + verify only.
#
# Usage:  bash ops/deploy/push_pair_worker.sh [--check]
#           (no args)  deploy + verify
#           --check    verify the live origin only (safe any time)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKER="$ROOT/surfaces/relay/pair_worker"
NAME="helmdeck-pair"

# Same PATH fix build_apk.sh already documents for this box: npm's postinstall
# scripts shell out via cmd.exe, which does not inherit node's own directory
# even though THIS script's own `node`/`npm` calls resolve fine - measured
# 2026-08-29, not assumed (esbuild's postinstall failed with "'node' is not
# recognized" until this was added).
export PATH="/c/Program Files/nodejs:$PATH"

verify() {
  local origin="$1" health
  health="$(curl -fsS "$origin/health")" || {
    echo "FAIL: $origin/health did not answer" >&2; return 1; }
  case "$health" in
    *"$NAME"*) ;;
    *) echo "FAIL: $origin/health is not the pair worker: $health" >&2; return 1 ;;
  esac
  case "$health" in
    *'"daemon":true'*) ;;
    *) echo "WARN: DAEMON_URL is not set on the worker - claim requests will 503." >&2
       echo "      Fix: cd surfaces/relay/pair_worker && npx wrangler secret put DAEMON_URL" >&2 ;;
  esac
  echo "OK: $origin answers as $NAME."
}

ORIGIN="${PAIR_WORKER_ORIGIN:-}"

if [ "${1:-}" = "--check" ]; then
  if [ -z "$ORIGIN" ]; then
    echo "Set PAIR_WORKER_ORIGIN=https://... to verify (the deployed worker URL)." >&2
    exit 2
  fi
  echo "== checking $ORIGIN (no deploy) =="
  verify "$ORIGIN"
  exit $?
fi

echo "== deploying $NAME =="
( cd "$WORKER" && npx wrangler deploy )

if [ -z "$ORIGIN" ]; then
  echo
  echo "Deployed. wrangler printed the URL above."
  echo "To let this script verify future deploys automatically:"
  echo "    export PAIR_WORKER_ORIGIN=https://$NAME.<your-subdomain>.workers.dev"
  exit 0
fi

echo "== verifying $ORIGIN =="
for attempt in 1 2 3 4 5; do
  if verify "$ORIGIN"; then exit 0; fi
  echo "  (attempt $attempt: not live yet, retrying in 6s)"
  sleep 6
done

echo "FAIL: deploy reported success but $ORIGIN never answered." >&2
exit 1
