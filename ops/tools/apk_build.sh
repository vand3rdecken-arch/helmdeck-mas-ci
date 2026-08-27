#!/usr/bin/env bash
# Build the Android app with the right JDK/SDK. Usage:
#   bash ops/tools/apk_build.sh [gradle tasks...]     (default: assembleDebug)
set -o pipefail
cd "$(dirname "$0")/../apk" || exit 1
export JAVA_HOME="/c/Program Files/Android/Android Studio1/jbr"
export ANDROID_HOME="/c/Users/Tien Duy Vo/AppData/Local/Android/Sdk"
export PATH="$JAVA_HOME/bin:$PATH"
exec ./gradlew "${@:-assembleDebug}" --no-daemon --console=plain
