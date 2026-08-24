#!/usr/bin/env bash
# adb helpers for the release smoke. Sourced by the step scripts, or called
# directly:  bash .smoke/drive.sh <fn> [args]
#
# The PID assertions matter: this card must prove check-on-RESUME, not
# check-on-launch (the build also has EXPO_UPDATES_CHECK_ON_LAUNCH=ALWAYS, so a
# cold start would check too and prove nothing). MainActivity is singleTask, so
# `am start` on a live process delivers onResume without recreating it - if the
# PID is unchanged across a background/foreground cycle, the check that ran was
# the AppState "active" handler in app/src/data/ota.ts, not a fresh launch.
ADB="$HOME/AppData/Local/Android/Sdk/platform-tools/adb.exe"
PKG=app.helmdeck
SHOTS="$(cd "$(dirname "$0")" && pwd)/shots"
mkdir -p "$SHOTS"

pid()   { "$ADB" shell pidof $PKG 2>/dev/null | tr -d '\r\n'; }
shot()  { "$ADB" exec-out screencap -p > "$SHOTS/$1.png"; echo "shot -> $SHOTS/$1.png"; }
home()  { "$ADB" shell input keyevent KEYCODE_HOME; }
fg()    { "$ADB" shell am start -a android.intent.action.MAIN \
                 -c android.intent.category.LAUNCHER -n $PKG/.MainActivity >/dev/null; }
tap()   { "$ADB" shell input tap "$1" "$2"; }

# background -> wait -> foreground, asserting the process survived (= a real
# resume). $1 = seconds to stay backgrounded (default 3).
cycle() {
  local before after
  before="$(pid)"
  [ -z "$before" ] && { echo "cycle: app NOT running"; return 1; }
  home; sleep "${1:-3}"; fg; sleep "${2:-4}"
  after="$(pid)"
  if [ "$before" = "$after" ]; then
    echo "cycle ok: RESUME (pid $before unchanged)"
  else
    echo "cycle WARN: process changed ($before -> $after) = cold start, not a resume"
  fi
}

"$@"
