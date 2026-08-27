#!/usr/bin/env bash
# Release build from C:\hd\app - a REAL short path (mirror of app/, caches
# excluded). `subst S:` (build3) did NOT help: gradle/CMake canonicalize the
# drive back to the long worktree path, so object paths still blew past the
# Windows limit and ninja looped ("build.ninja still dirty after 100 tries").
# x86_64 only: the smoke target is the emulator; the ABI subset changes nothing
# about the JS bundle, signing, or the expo-updates behaviour under test.
set -o pipefail
cd /c/hd/app/android || exit 1
JAVA_HOME="$(ls -d '/c/Program Files/Microsoft/jdk-17'* 2>/dev/null | head -1)"
[ -z "$JAVA_HOME" ] && { echo "no JDK17"; exit 1; }
export JAVA_HOME
export ANDROID_HOME="$HOME/AppData/Local/Android/Sdk"
export PATH="/c/Program Files/nodejs:$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$PATH"

# forward slashes only - the Java properties parser eats backslashes
printf 'sdk.dir=%s\n' 'C:/Users/Tien Duy Vo/AppData/Local/Android/Sdk' > local.properties

# android/ is hand-managed: re-apply the source-of-truth native config
node /c/hd/app/plugins/withLanCleartext.js /c/hd/app/android \
  || { echo "withLanCleartext FAILED"; exit 1; }

exec ./gradlew assembleRelease -x lint --console=plain -PreactNativeArchitectures=x86_64
