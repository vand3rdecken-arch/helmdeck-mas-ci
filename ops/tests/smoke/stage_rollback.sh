#!/usr/bin/env bash
# Serve a rollBackToEmbedded directive from the smoke updates dir - the same
# marker ops/deploy/rollback_update.sh --embedded writes on the real relay, so this
# exercises the production rollback path, not a test-only shortcut.
#
#   bash .smoke/stage_rollback.sh          # arm the rollback
#   bash .smoke/stage_rollback.sh --clear  # remove it again
#
# commitTime is stamped NOW: the client only honours a directive newer than the
# last rollback it applied, so a fresh stamp is what makes it take effect.
set -o pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
U="$ROOT/.smoke/updates"
[ -d "$U" ] || { echo "no $U"; exit 1; }

if [ "${1:-}" = "--clear" ]; then
  rm -f "$U/rollback.json"; echo "rollback marker cleared"; exit 0
fi

/c/Windows/py.exe -3.12 -c "
import json, time, sys
p = sys.argv[1]
ct = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())
json.dump({'commitTime': ct}, open(p, 'w'))
print('rollback.json commitTime =', ct)
" "$U/rollback.json"
