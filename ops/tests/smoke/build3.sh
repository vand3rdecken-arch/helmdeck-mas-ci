#!/usr/bin/env bash
# Release APK build via the S: subst drive. Attempts 1+2 (build.log/build2.log)
# died with `ninja: manifest 'build.ninja' still dirty after 100 tries` right
# after CMake's "object file path cannot be safely placed under this directory"
# warning - the worktree path is ~40 chars longer than the main repo where the
# same build passes. Short drive + fresh .cxx fixes both.
set -o pipefail
cd /s || exit 1
JAVA_HOME="$(ls -d '/c/Program Files/Microsoft/jdk-17'* 2>/dev/null | head -1)"
[ -z "$JAVA_HOME" ] && { echo "no JDK17"; exit 1; }
export JAVA_HOME
export ANDROID_HOME="$HOME/AppData/Local/Android/Sdk"
export PATH="/c/Program Files/nodejs:$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$PATH"

printf 'sdk.dir=%s\n' 'C:/Users/Tien Duy Vo/AppData/Local/Android/Sdk' > surfaces/app/android/local.properties
node surfaces/app/plugins/withLanCleartext.js surfaces/app/android || { echo "withLanCleartext FAILED"; exit 1; }

echo "== drop stale .cxx caches (they reference the long C:\\ path)"
find surfaces/app/node_modules -maxdepth 4 -type d -name .cxx -prune -exec rm -rf {} + 2>/dev/null
rm -rf surfaces/app/android/app/.cxx surfaces/app/android/.cxx

cd surfaces/app/android || exit 1
./gradlew --stop >/dev/null 2>&1
exec ./gradlew assembleRelease -x lint --console=plain
