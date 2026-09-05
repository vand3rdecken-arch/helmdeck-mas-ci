# HelmDeck Watch - Apple Watch companion target

**Status: scaffold, unverified beyond CI.** Registers the watchOS target
skeleton this repo did not have before (`ops/docs/backlog/watchos-ui-ux-entwurf/README.md`
SS6 point 4). No network/crypto/board code yet - two empty SwiftUI screens,
built to prove the target compiles, signs and can reach TestFlight.

Grounded in three prior cards, not re-litigated here:
- `ops/docs/ios-watch-feasibility.md` (2026-08-12) - Phase W1 vs W2 scope call.
- `ops/docs/backlog/watchos-technik-machbarkeit/README.md` (2026-09-05) - the
  watch talks **directly to the relay** with its own APNs token; no
  `WatchConnectivity`/companion-phone relay path.
- `ops/docs/backlog/watchos-ui-ux-entwurf/README.md` (2026-09-05) SS5 - build
  path is a `macos-14` GitHub Actions runner + `xcodebuild`, the same pattern
  already proven for `.github/workflows/desktop-mac.yml`. No local Mac needed
  for build/verify, only for fast UI iteration (out of scope here).

## What exists here

- `project.yml` - an [XcodeGen](https://github.com/yonaskolb/XcodeGen) spec,
  not a hand-authored `.xcodeproj`. Chosen deliberately: this worktree has no
  Mac/Xcode to author or sanity-check a `project.pbxproj` by hand, and a
  malformed one fails silently or corrupts on next Xcode open. A YAML spec
  regenerates the project deterministically on the CI runner every time -
  mistakes fail loud and fast (`xcodegen generate` / `xcodebuild -list`) as
  the actual verification, matching this repo's need to verify via CI instead
  of a local device.
- Two targets:
  - `HelmDeckWatchCompanion` (iOS, bundle `app.helmdeck.watchcompanion`) - a
    near-empty host app. Its only job is Apple's App Store embedding
    requirement; it has and will have no business logic, because the watch
    app does not talk to it (see the technik-machbarkeit doc above).
  - `HelmDeckWatch` (watchOS, bundle `app.helmdeck.watchcompanion.watchkitapp`)
    - the real target. `aps-environment: production` entitlement pre-declared
    for its own push token; everything else is a placeholder `Text("HelmDeck")`.
  - **Deliberately separate bundle-ID root from `app.helmdeck`** (the live,
    working iOS app) - this scaffold must not be able to collide with or
    destabilize the already-signed, already-shipping main app pipeline.
- `build-watch.sh` / `.github/workflows/watchos-app.yml` - mirrors
  `surfaces/desktop/build-mac.sh` / `desktop-mac.yml` exactly: succeeds
  **unsigned** with zero secrets (proves the target compiles), archives only
  once the same four `ASC_*`/`APPLE_TEAM_ID` GitHub secrets `desktop-mac.yml`
  already uses are present.

## Provisioning - what to expect, not new research

Registering `app.helmdeck` itself (commit `5eb6a5b`) already proved an
App Store Connect **Admin** API key can mint a Distribution Certificate and a
Provisioning Profile with **no Apple ID login and no 2FA at any point** -
`xcodebuild -allowProvisioningUpdates -authenticationKeyPath/-ID/-IssuerID`
is Apple's CI-native equivalent of the `eas credentials` flow that did it.
Two knowns carry over directly, already solved once:

1. **The capability-sync trap will very likely repeat.** `5eb6a5b` hit Apple
   rejecting the automatic `PUSH_NOTIFICATIONS` capability patch on first
   registration of a bundle ID; the fix was a single manual toggle
   (developer.apple.com -> Identifiers -> the new App ID -> Capabilities ->
   Push Notifications -> Save) after which the next run reports "No updates."
   Expect the same for `app.helmdeck.watchcompanion.watchkitapp` the first
   time `--archive` runs with secrets present. **This is the
   "Account-Holder-Zugriff" this card's title anticipated** - one checkbox,
   not a research problem.
2. **The API key's role is fixed at creation** (Developer-role keys cannot
   create certs/profiles at all) - already an Admin key on file
   (`AZQRY4K34W`, see `surfaces/app/eas.json` / `DEPLOY.md`), so this should
   not need a new key.

What this scaffold does **not** need: no `.p8` files, no `.env`, no path
under `C:/hd/secrets` - none of that is reachable from (or belongs in) this
worktree. The actual signed run happens in GitHub Actions, reading the same
repository secrets `desktop-mac.yml` already reads.

## Explicitly not done here

- No board/chat/voice screens (`watchos-ui-ux-entwurf/README.md`'s designs) -
  next card, once this target is proven to build and sign.
- No push-token registration wiring in `daemon/notify.py` - depends on the
  Expo-Push-Service decision in `ios-watch-feasibility.md` SS1.3, unrelated to
  getting the target itself to compile and sign.
- No local verification - this card's worktree has no Mac. The first real
  signal is the `watchos-app.yml` run.
