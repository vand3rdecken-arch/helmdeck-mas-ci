# Every single card accept triggers a full native APK build, even docs-only ones

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
