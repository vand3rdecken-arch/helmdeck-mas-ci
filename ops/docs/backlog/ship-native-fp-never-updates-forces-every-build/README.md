# Every single card accept triggers a full native APK build, even docs-only ones

**STATUS 2026-08-31 21:0x: primary fix SHIPPED (commit pending in this
session) - `ops/deploy/.native_fp` replaced with a shared git ref
(`refs/helmdeck/last-native-fp`), fixing the case that hit today (`direct`
cards on the live tree, and the general worktree-file-isolation bug). A
SEPARATE residual gap was found while verifying the fix and is NOT yet
fixed - see "Residual gap" section at the end.**

**Filed 2026-08-31**, found while diagnosing "warum kaputt Henry" ->
"desktop+phone verbinden konstant neu" -> traced to a relay-restart pattern
on trooper going back to 2026-08-28 -> traced further to `ops/deploy/ship.sh`
running a full native build on every accept. Owner's own words once the
picture was clear: "Es will immer APK bauen, immer...".

## Root cause (measured)

`ship.sh`'s hash-fallback path (`SHIP_KIND` unset - the ship-advisor
described in the script's own comments, `ops/harness/agents/ship-advisor.md`
+ `ops/tools/ship_facts.py`, is never actually wired into the deploy hook
invocation; every observed hook call is the bare
`"C:\Program Files\Git\bin\bash.exe" ops/deploy/ship.sh` with no env var)
compares a freshly computed `native_fp()` against `ops/deploy/.native_fp`.

That stored file is only written at the very end of the native branch
(`ship.sh:258`), AFTER `build_apk.sh` succeeds. Checked 2026-08-31 20:2x:
`ops/deploy/.native_fp` is timestamped **2026-08-30 17:48** and does not
match a freshly recomputed fingerprint. The last commit matching the
auto-commit `ship.sh` makes on a successful native ship
("chore(release): version X ... versionCode Y") is older still
(`6c45457`, "version 1.0.35 / versionCode 77").

Conclusion: no native build has run to completion in over a day. Every
single accept since then - including a card explicitly named
"ANALYSE ONLY, KEIN CODE" that touched zero files - re-triggers
`bump_version` + a full `npm ci + gradle assembleRelease + emulator smoke`
cycle (~15-20 min), because the comparison can never come out equal while
`.native_fp` stays frozen at a stale value.

Each of these attempts also calls `push_relay.sh` (from inside
`build_apk.sh`) with byte-identical content every time, restarting the
live relay service on trooper for ~2s each time - this is the direct cause
of the "Handy/Desktop verbinden konstant neu" symptom investigated earlier
today (relay journal on trooper shows `systemctl restart helmdeck-relay`
every ~20-35 min since 2026-08-28, always via `install /tmp/relay.py` with
identical MD5).

## Why builds don't complete (secondary, not yet root-caused)

`daemon/recordings/20260831-191942-.../actions.jsonl` shows, mid-build:
`wartet: Box ausgelastet durch unbekannt/extern (nicht von HelmDeck
verfolgt) (CPU 100%) - warte bis zu 1800s` - something OUTSIDE HelmDeck's
own tracking is pegging the CPU, plausibly starving/timing out the Gradle
build before it reaches the fingerprint-write line. Not confirmed which
process; worth a fresh `Get-CimInstance Win32_Process` sweep next time this
fires live.

## Fix

- Primary: make `ship.sh` resilient to repeated failure - e.g. write
  `.native_fp` (or a distinct "last attempted" marker) even on a failed
  build IF the failure is confirmed unrelated to the native diff itself
  (timeout/resource contention), so a transient failure doesn't force every
  subsequent unrelated accept to retry the same doomed build. Needs care:
  must not silently swallow a REAL native change that failed to build (the
  false-negative direction is explicitly the one this script must never
  produce, per its own comments).
- Alternative/complementary: wire up the ship-advisor (`SHIP_KIND`) that the
  script's own comments say should already be deciding this - it would let
  a docs-only card like the one that triggered this correctly resolve to
  `SHIP_KIND=none` instead of falling to the hash heuristic at all.
- Root-cause the CPU-100%-external contention so builds actually finish
  instead of timing out.
- `push_relay.sh` should skip the redeploy when the relay script's hash is
  unchanged (independently useful even after the above is fixed - no reason
  to restart a live service for a byte-identical file).

## Non-goals

- Touching `cfg_fp()`/`kt_fp()`'s exclusion logic - already correctly
  excludes version/versionCode/ios/extra per a documented 2026-08-15/08-23
  incident history. Not the bug here.

## Fix applied 2026-08-31 (primary)

Replaced the working-tree file with a git ref:
- `ops/deploy/.native_fp` (gitignored - the actual bug, `git worktree add`
  never copies gitignored files, so every worktree checkout started with an
  empty `LAST` and false-positived "native change" on its first ship no
  matter how trivial) -> `refs/helmdeck/last-native-fp`, a ref pointing at
  a blob holding the hash string. Refs live in the shared `.git` object
  database every worktree already points at, so `git cat-file -p
  refs/helmdeck/last-native-fp` returns the same value regardless of which
  checkout runs `ship.sh`. Verified from a throwaway `git worktree add`.
- `.native_fp`'s stale 2026-08-30 value was corrected before the swap (git
  history confirmed no native-relevant file changed since the last
  successful ship, `6c45457`) and seeded into the new ref.
- Also fixed the accompanying symptom: `ops/deploy/push_relay.sh` was
  unconditionally `systemctl restart`-ing the live trooper relay on every
  call, even with byte-identical content - confirmed via trooper's own
  auth.log (same md5, every ~20-35 min since 2026-08-28). Now compares
  against the remote's installed copy first and only restarts on an actual
  change. This is what was surfacing as "Handy/Desktop verbindet konstant
  neu".

## Residual gap found while verifying the fix (NOT fixed yet)

`surfaces/app/android/` (the native project dir `expo prebuild` generates)
is itself gitignored and does not exist at all in a freshly created
worktree until a build runs `expo prebuild` inside THAT checkout.
`cfg_fp()` fingerprints `AndroidManifest.xml` from that folder - so its mere
presence/absence (not its content) still swings the fingerprint,
independent of any real native change. Verified: a throwaway `git worktree
add` computed a DIFFERENT `cfg_fp()` than the live tree purely because it
had no `android/` folder yet (`FileNotFoundError` -> skipped) while the live
tree's `android/` was present (partially regenerated by today's aborted
build). This means a worktree-based card's FIRST ship in a brand-new
checkout can still false-positive as "native", even with the ref fix -
`direct` cards (default per owner decree 2026-08-29, and the class that
actually failed today) are unaffected since they always run against the
one persistent live tree, which already has `android/`.

Not fixed here because the manifest fingerprinting looks deliberate (own
comment block references incident history for the EXPO_RUNTIME_VERSION
line specifically) and I don't have full context for why it fingerprints a
GENERATED artifact rather than relying on its sources (app.json + plugin
.kt/.java, both already fingerprinted separately) - ripping it out blind
risks reintroducing the false-negative class this script is most guarded
against. Needs a scoped look at the manifest-fingerprinting history before
touching it.
