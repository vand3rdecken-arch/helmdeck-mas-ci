#!/usr/bin/env bash
# Manual replay tool for the Android build mutex (ops/deploy/build_lock.sh).
# NOT part of the gate - the gate is LIGHT by owner decree and stays that way;
# this is the "prove it once, replay it when you touch it" tool the rest of
# ops/tests already is.
#
# SELF-SANDBOXING: every case runs against a throwaway HELMDECK_LOCK_DIR under
# a temp dir, so this can never observe - let alone release - the real
# ~/.helmdeck/locks/android-build of a build running on this box. (The
# recordings-wipe incident is the standing reason that rule is absolute.)
#
#   bash ops/tests/test_android_build_lock.sh
set -o pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"; cd "$ROOT"

SANDBOX="$(mktemp -d)"
export HELMDECK_LOCK_DIR="$SANDBOX/locks"
trap 'rm -rf "$SANDBOX"' EXIT
pass=0; fail=0
ok()   { echo "  PASS: $1"; pass=$((pass+1)); }
bad()  { echo "  FAIL: $1"; fail=$((fail+1)); }

echo "== sandbox: $HELMDECK_LOCK_DIR"

# --- 1. acquire + release -------------------------------------------------
echo "[1] acquire and release"
# BASHPID, not $$: inside this subshell $$ is still the TEST script's pid, so
# asserting against it would pass even if the lock recorded the wrong process.
( . ops/deploy/build_lock.sh; android_build_lock "test-one" >/dev/null
  [ -d "$HELMDECK_LOCK_DIR/android-build" ] || exit 1
  [ "$(sed -n 1p "$HELMDECK_LOCK_DIR/android-build/pid")" = "$BASHPID" ] || exit 2
  [ "$(cat "$HELMDECK_LOCK_DIR/android-build/label")" = "test-one" ] || exit 3 )
rc=$?
[ $rc = 0 ] && ok "acquired, pid+label written" || bad "acquire returned $rc"
[ -d "$HELMDECK_LOCK_DIR/android-build" ] && bad "lock NOT released on exit" || ok "released on EXIT trap"

# --- 2. the real thing: a second build WAITS, it does not run -------------
echo "[2] second build waits for a LIVE holder (this is the whole point)"
( . ops/deploy/build_lock.sh; android_build_lock "holder-sleeps" >/dev/null
  sleep 12 ) &
holder=$!
sleep 2
[ -d "$HELMDECK_LOCK_DIR/android-build" ] || bad "holder never took the lock"
start=$(date +%s)
( . ops/deploy/build_lock.sh; android_build_lock "second-build" >/dev/null ) &
second=$!
sleep 3
if kill -0 $second 2>/dev/null; then ok "second build is BLOCKED while holder runs"
else bad "second build did NOT wait - ran in parallel (the 30.08 bug)"; fi
wait $holder 2>/dev/null
wait $second 2>/dev/null
waited=$(( $(date +%s) - start ))
[ "$waited" -ge 9 ] && ok "second build waited ${waited}s for the holder to finish" \
                    || bad "second build only waited ${waited}s - did not queue"

# --- 3. a dead holder must never wedge the next build ---------------------
echo "[3] stale takeover: dead pid is not a deadlock"
mkdir -p "$HELMDECK_LOCK_DIR/android-build"
printf '999999\n999999\n' > "$HELMDECK_LOCK_DIR/android-build/pid"
printf 'crashed-build' > "$HELMDECK_LOCK_DIR/android-build/label"
start=$(date +%s)
( . ops/deploy/build_lock.sh; android_build_lock "after-crash" >/dev/null )
rc=$?; took=$(( $(date +%s) - start ))
[ $rc = 0 ] && [ "$took" -lt 20 ] && ok "took over dead lock in ${took}s" \
                                  || bad "stale takeover failed (rc=$rc, ${took}s)"

# --- 4. reentrancy: nested sourcing must not self-deadlock ----------------
echo "[4] reentrant acquire is a no-op"
( . ops/deploy/build_lock.sh
  android_build_lock "outer" >/dev/null
  timeout 10 bash -c 'true'
  android_build_lock "outer-again" >/dev/null )
[ $? = 0 ] && ok "second acquire in same process returned immediately" \
           || bad "reentrant acquire deadlocked or failed"

# --- 5. a lock we no longer own must not be released by us ---------------
echo "[5] never release a lock that was taken over from us"
out=$( . ops/deploy/build_lock.sh
       android_build_lock "victim" >/dev/null
       printf '999998\n999998\n' > "$HELMDECK_LOCK_DIR/android-build/pid"   # someone else owns it now
       android_build_unlock )
if echo "$out" | grep -q "NOT releasing"; then ok "declined to release a foreign lock"
else bad "released a lock owned by another build"; fi
rm -rf "$HELMDECK_LOCK_DIR/android-build"

echo
echo "== $pass passed, $fail failed"
[ "$fail" = 0 ]
