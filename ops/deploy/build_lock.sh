#!/usr/bin/env bash
# ANDROID BUILD MUTEX - machine-global, sourced by every Gradle entrypoint.
#
# WHY THIS EXISTS (measured 2026-08-30, owner report): two Android builds ran
# at once and blocked each other. The box was NOT out of CPU, so the load-aware
# admission (lanemachine._admit_heavy) admitted both - by design: that seam is
# mutual AWARENESS (is there headroom?), never mutual EXCLUSION. And ship.sh's
# ship.lock did not catch it either, for two reasons that are the whole point
# of this file:
#   1. ship.lock is $ROOT-scoped ("$ROOT/.loop/ship.lock"), so it only ever
#      serializes ships that resolve the SAME tree. The contended resources are
#      machine-global, not tree-local: the Gradle daemon + its ~/.gradle caches,
#      the single surfaces/app/android tree, adb/the emulator, node_modules.
#   2. ship.lock guards the SHIP path only. DEPLOY.md tells an agent to run
#      ops/deploy/build_apk.sh directly, and ops/tools/release.sh builds too -
#      both took no lock whatsoever.
# The aggravating mechanism, why they didn't just run slowly but actually broke
# each other: build_apk.sh opens with `./gradlew --stop`, which stops EVERY
# Gradle daemon of this user - including one that is ten minutes into another
# build. The loser then dies on the EPERM/EBUSY unlink over node_modules that
# build_apk.sh's own header already documents. So the lock MUST be taken before
# that --stop, which is what build_apk.sh now does.
#
# THE PRIMITIVE is deliberately the one ship.sh already proved on this box:
# `mkdir` (atomic create, works over MSYS/Windows where flock does not) plus a
# LIVE-PID observation. State is DERIVED from the runtime's own signal - a lock
# whose holder pid is dead is stale and gets taken over - never trusted as a
# stored flag (the Paseo rule, CLAUDE.md "NO MONKEY PATCHES"). That is what
# makes an unbounded wait safe: we only ever wait on a holder we just PROVED is
# alive, so a crashed build can never wedge the next one forever.
#
# WHY A FILE LOCK AND NOT AN IN-PROCESS ONE: the daemon does not run gradle. It
# spawns an agent, which spawns a shell, which runs the script - and the owner
# can start a build from a terminal with no daemon involved at all. An
# in-process lock in spine/git/locks.py cannot see any of that. The file is the
# only seam every trigger passes through.
#
# Usage (from a script whose cwd is the repo root):
#   . "$(dirname "$0")/build_lock.sh"
#   android_build_lock "build_apk :app:assembleRelease"
# Release is automatic on EXIT. Safe to call once per process; a second call in
# the same process is a no-op (we already hold it), so a wrapper that sources
# this and then calls another wrapper that does too cannot self-deadlock.

# Machine-global, and deliberately OUTSIDE any repo/worktree: two different
# checkouts of this repo still share one Gradle daemon and one ~/.gradle, so a
# tree-relative path would reintroduce exactly the hole this file closes.
# Overridable for tests only.
: "${HELMDECK_LOCK_DIR:=$HOME/.helmdeck/locks}"
ANDROID_BUILD_LOCK="$HELMDECK_LOCK_DIR/android-build"
_ANDROID_LOCK_HELD=0

_abl_pid_line() {
  # Line 1 = $$ (the MSYS pid, what a sibling bash's `kill -0` can see).
  # Line 2 = the real Windows pid. MEASURED TRAP (2026-08-23, ship.lock): a
  # live 40-minute gradle build read as "dead" to the daemon's Python-side
  # os.kill(pid, 0) because only the MSYS pid had ever been recorded and the
  # Windows process table has no such pid. Both, always.
  sed -n "${1}p" "$ANDROID_BUILD_LOCK/pid" 2>/dev/null | tr -d '\r' | tr -d ' '
}

_abl_holder_desc() {
  local label; label="$(cat "$ANDROID_BUILD_LOCK/label" 2>/dev/null)"
  echo "${label:-unbekannter Android-Build}"
}

_abl_lock_age_s() {
  local born now
  born="$(stat -c %Y "$ANDROID_BUILD_LOCK" 2>/dev/null)" || return 1
  now="$(date +%s)"
  echo $(( now - born ))
}

android_build_lock() {
  local label="${1:-android build}"
  local waited=0 holder age

  [ "$_ANDROID_LOCK_HELD" = "1" ] && return 0    # reentrant: we already own it

  # BASHPID, not $$. In a top-level script (how the build scripts actually
  # source this) the two are identical - but inside a subshell `$$` is still
  # the PARENT's pid, so a subshell would record a pid that outlives it and
  # its lock would read as LIVE long after the build died. Recording the pid
  # that actually owns the lock is the whole basis of the stale check.
  _ABL_PID="${BASHPID:-$$}"

  mkdir -p "$HELMDECK_LOCK_DIR"
  while ! mkdir "$ANDROID_BUILD_LOCK" 2>/dev/null; do
    holder="$(_abl_pid_line 1)"
    if [ -n "$holder" ] && kill -0 "$holder" 2>/dev/null; then
      # A PROVEN-live holder. Wait, and SAY SO on every poll: the deploy hook's
      # watchdog bounds a card by SILENCE (hook_idle_s, 900s), not wall clock,
      # so a queued build that printed nothing would eventually be killed as
      # "wedged" while it was behaving exactly as designed. HOOK-NOTE is the
      # prefix lanemachine._run_streamed mirrors into the card's chat live, so
      # the owner sees "waiting for X" on the board instead of dead air.
      if [ "$((waited % 60))" = 0 ]; then
        echo "HOOK-NOTE: Android-Build wartet - laeuft bereits: $(_abl_holder_desc) (pid $holder), seit $(_abl_lock_age_s)s"
      fi
      echo "[build-lock] another Android build holds the lock (pid $holder, $(_abl_holder_desc)) - waiting ${waited}s"
      sleep 15
      waited=$(( waited + 15 ))
    else
      # No live holder. Two shapes, and they are NOT the same:
      #   - a pid that is readable and dead  -> the build died (daemon restart,
      #     killed task). Genuinely stale, take over.
      #   - an EMPTY/unreadable pid file     -> could be a lock created
      #     microseconds ago whose owner has not written its pid yet. Racing to
      #     "stale" there would hand the lock to TWO builds, which is the bug
      #     this file exists to prevent. Give it a grace window first.
      age="$(_abl_lock_age_s 2>/dev/null || echo 999)"
      if [ -z "$holder" ] && [ "$age" -lt 60 ]; then
        echo "[build-lock] lock just created, pid not written yet (${age}s) - waiting"
        sleep 5
        waited=$(( waited + 5 ))
        continue
      fi
      echo "[build-lock] stale lock (pid ${holder:-none} dead, age ${age}s) - taking over"
      rm -rf "$ANDROID_BUILD_LOCK"
    fi
  done

  echo "$_ABL_PID" > "$ANDROID_BUILD_LOCK/pid"
  cat "/proc/$_ABL_PID/winpid" 2>/dev/null >> "$ANDROID_BUILD_LOCK/pid" \
    || echo "$_ABL_PID" >> "$ANDROID_BUILD_LOCK/pid"
  printf '%s' "$label" > "$ANDROID_BUILD_LOCK/label"
  _ANDROID_LOCK_HELD=1
  # Release only what WE own: if our lock was taken over as stale (we were
  # SIGSTOPped past the liveness check, say) the dir now belongs to someone
  # else and blowing it away would free a running build's lock.
  # The trailing `exit=<rc>` line is the completion marker for anyone tailing
  # the build log (grep '^exit='): on 2026-09-23 a card waited 2h for a marker
  # no build ever wrote, so nothing woke it when the AAB was done.
  trap '_abl_rc=$?; android_build_unlock; echo "exit=$_abl_rc"' EXIT
  if [ "$waited" -gt 0 ]; then
    echo "HOOK-NOTE: Android-Build-Sperre frei nach ${waited}s - starte jetzt"
  fi
  echo "[build-lock] acquired by $_ABL_PID ($label)$([ "$waited" -gt 0 ] && echo " after ${waited}s wait")"
}

android_build_unlock() {
  [ "$_ANDROID_LOCK_HELD" = "1" ] || return 0
  if [ "$(_abl_pid_line 1)" = "$_ABL_PID" ]; then
    rm -rf "$ANDROID_BUILD_LOCK"
    echo "[build-lock] released by $_ABL_PID"
  else
    echo "[build-lock] NOT releasing - lock now held by pid $(_abl_pid_line 1), not us ($_ABL_PID)"
  fi
  _ANDROID_LOCK_HELD=0
}
