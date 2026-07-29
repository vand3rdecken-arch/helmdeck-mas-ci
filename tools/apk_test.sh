#!/usr/bin/env bash
# Run the instrumented Android E2E suite against a booted emulator/device.
#
#   bash tools/apk_test.sh
#
# The suite needs a LIVE pairing, and the daemon pins the first device key it
# sees (trust-on-first-use). A pin left over from a previous run makes every
# daemon-backed test fail with 409 "another phone is paired", so this script
# mints a fresh pairing each time - a test harness should set up its own
# preconditions rather than depend on what the last run happened to leave.
set -o pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/apk" || exit 1
export JAVA_HOME="/c/Program Files/Android/Android Studio1/jbr"
export ANDROID_HOME="/c/Users/Tien Duy Vo/AppData/Local/Android/Sdk"
export PATH="$JAVA_HOME/bin:$PATH"

API="${SWARM_API:-http://localhost:8140}"
OWNER="${SWARM_OWNER:-owner}"
CODE=""

if [ -n "${SWARM_PW:-}" ]; then
  CJ=$(mktemp)
  if curl -s -m10 -c "$CJ" -X POST -H "Content-Type: application/json" \
        -d "{\"name\":\"$OWNER\",\"password\":\"$SWARM_PW\"}" "$API/auth/login" -o /dev/null; then
    # /relay/pair also clears any previously pinned device, so the emulator can
    # claim the room cleanly on its first encrypted call
    CODE=$(curl -s -m10 -b "$CJ" -X POST -H "Content-Type: application/json" -d '{}' \
             "$API/relay/pair" | py -3.12 -c "
import sys, json, base64
try:
    d = json.load(sys.stdin)
    print(base64.b64encode(json.dumps({'u': d['url'], 'r': d['room'],
        'k': d['daemon_pub'], 't': d['device_token']}).encode()).decode())
except Exception:
    print('')")
  fi
  rm -f "$CJ"
  [ -n "$CODE" ] && echo "fresh pairing minted for this run" \
                 || echo "WARNING: no pairing - daemon-backed tests will be skipped"
else
  echo "SWARM_PW not set - running only the offline tests"
fi

exec ./gradlew connectedDebugAndroidTest --no-daemon --console=plain \
  -Pandroid.testInstrumentationRunnerArguments.pairCode="$CODE"
