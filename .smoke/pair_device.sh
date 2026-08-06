#!/usr/bin/env bash
# Open a fresh 15-min pairing window on the sandbox daemon and fire the deep
# link at the emulator. Uses the helmdeck:// custom scheme, NOT the https App
# Link: assetlinks binds the https /pair route to the PRODUCTION relay host,
# so a quick-tunnel host would not verify. Same payload either way.
#
#   bash .smoke/pair_device.sh <owner-device-token>
set -o pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ADB="$HOME/AppData/Local/Android/Sdk/platform-tools/adb.exe"
TOK="${1:?usage: pair_device.sh <owner-device-token>}"

RESP="$(curl -s -m 15 -X POST http://127.0.0.1:8145/relay/pair \
        -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" -d '{}')"
echo "pair window: $RESP"
case "$RESP" in *device_token*) ;; *) echo "PAIR WINDOW FAILED"; exit 1 ;; esac

LINK="$(/c/Windows/py.exe -3.12 -c "
import base64, json, sys, urllib.parse
r = json.loads(sys.argv[1])
code = base64.urlsafe_b64encode(json.dumps(
    {'u': r['url'], 'r': r['room'], 'k': r['daemon_pub'], 't': r['device_token']}
).encode()).decode()
print('helmdeck://pair?c=' + urllib.parse.quote(code, safe='-_'))
" "$RESP")"
echo "link: ${LINK:0:80}..."

"$ADB" shell am start -a android.intent.action.VIEW -d "$LINK" app.helmdeck
