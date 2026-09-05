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

## Provisioning - measured, not assumed (4 red CI runs, 2026-09-05)

The original plan - `xcodebuild -allowProvisioningUpdates` + the ASC API key,
automatic signing all the way - DOES NOT WORK on ephemeral CI, and the reason
is structural, not a flag:

- `xcodebuild archive` under Automatic signing requests an **Apple
  Development** identity (Xcode's model: the archive signs with Development,
  the *export* step re-signs with Distribution).
- A Development identity's private key is minted into the build Mac's
  keychain - a GitHub runner is destroyed after every run, so the key is
  gone forever ("...but its private key is not installed in your keychain"),
  and Apple caps Development certs at 2/account, so retries wedge the
  account. Manually pinning `CODE_SIGN_IDENTITY: Apple Distribution` under
  Automatic style is rejected outright ("conflicting provisioning
  settings"). All measured in runs 33958823586..33963881033.

What `5eb6a5b` actually proved still stands: the **Admin** ASC API key
(`AZQRY4K34W`) mints certs/profiles with no Apple ID login and no 2FA. But
the working mechanism there was **EAS' credential store** - the Distribution
cert's private key lives on Expo's servers, never on a throwaway Mac. So CI
here reuses exactly that: export the existing team Distribution cert from
EAS once as a `.p12`, keep it as a GitHub secret, and every run imports it
into a throwaway keychain + signs Release **manually** (identity and profile
names pinned in `project.yml`; App Store profiles created/fetched by the
runner's preinstalled `fastlane sigh` via the same API key - App Store
profiles need no device UDIDs).

### The one-time credential step - DONE 2026-09-05

Executed via the desktop (eas-cli menu -> "Download credentials from EAS to
credentials.json"): `APPLE_CERT_P12` (base64 of dist-cert.p12) and
`APPLE_CERT_PASSWORD` are live GitHub secrets; local credential files were
deleted after upload. TRAP for a future re-export: EAS encrypts every
export with a FRESH password - both secrets must come from the SAME
download (a p12 from one export + a password from another fails with "MAC
verification failed during PKCS12 import").

Proven end-to-end by run 33966012602: both App IDs registered, both App
Store profiles embedded, both apps signed by "iPhone Distribution: Tien Duy
Vo", .xcarchive uploaded as the `helmdeck-watch` artifact. A green run
alone does NOT mean signing ran - check the Build step for "signing: ON"
(secret-less forks fall back to the unsigned compile-only build).

Two fastlane/XcodeGen traps burned into build-watch.sh/project.yml on the
way (see their comments): `fastlane produce`/`create_app_online` has NO
API-key auth at all (App IDs are registered via the ASC REST API directly,
node-minted JWT), and XcodeGen's application preset injects an
sdk-conditional target-level CODE_SIGN_IDENTITY that must be overridden
target-level, sdk-conditional included.

**Cleanup worth doing once:** developer.apple.com -> Certificates - revoke
the stale "Apple Development" certificates the early failed runs minted
(they belong to already-destroyed CI Macs; revoking breaks nothing and
frees the 2-per-account quota).

**Deferred on purpose:** the watch target currently declares NO push
entitlement, so plain App Store profiles suffice and the PUSH_NOTIFICATIONS
capability-sync trap (`5eb6a5b`, DEPLOY.md) cannot fire yet. The card that
wires the watch's APNs token re-adds `aps-environment` and handles that one
portal checkbox then.

What this scaffold does **not** need: no `.p8` files, no `.env`, no path
under `C:/hd/secrets` - none of that is reachable from (or belongs in) this
worktree. The actual signed run happens in GitHub Actions, reading repository
secrets.

## Board/chat/voice + relay client - DONE 2026-09-05 (this card)

The scaffold's placeholder screens are replaced with the real thing, per
`watchos-ui-ux-entwurf/README.md`'s designs and mirroring the already-shipped
Wear OS module (`surfaces/app/plugins/wear/*.kt`) file-for-file where the
platforms agree, and diverging deliberately where they don't:

- **Crypto** (`Watch/Data/HelmDeckBox.swift`) - NaCl box via
  [swift-sodium](https://github.com/jedisct1/swift-sodium) (pinned
  `exactVersion: 0.11.0` in `project.yml`'s new `packages:` block), not a
  hand-rolled port: its `Package.swift` vendors a prebuilt
  `Clibsodium.xcframework` with watchOS as an explicit platform, so
  `xcodebuild` links a binary instead of compiling C sources on the runner -
  the same "verify via CI, not a local device" posture as the rest of this
  target. Confirmed against the package's own `Box.swift` source this
  session, not assumed.
- **Transport** (`Watch/Data/RelayClient.swift`) - `URLSession` async/await,
  the exact sealed-envelope protocol `RelayClient.kt`/`client.ts` use. **Not
  a WebSocket and not a hanging GET**: `ops/docs/backlog/watchos-technik-machbarkeit/README.md`
  §2.2 measured that watchOS has no ambient-mode equivalent to Wear OS's
  throttled-but-alive background state - a third-party process suspends
  within seconds of leaving the foreground, so there is no safe place to hold
  a long-poll open. Every screen loads fresh on `.task`/foreground-return
  instead (`ChatView`/`BoardView`'s own doc comments call this out) - no
  `WearStream` equivalent exists here, by design, not by omission.
- **Screens** (`Watch/Views/*.swift`) - `PairingView` (device-code entry,
  dictation for free via watchOS's own `TextField` input controller, no
  manual speech-recognizer intent needed the way Wear OS required one),
  `ChatView` (Henry, the landing screen, day-separated bubbles, per-question
  option buttons, a voice toggle riding on `AppState` so it is ONE switch for
  every screen - the exact bug class `wear-os-paritaets-audit/README.md`
  found and this build avoids from the start), `BoardView` (needs_you/yours/
  working/backlog sections, reload button), `CardView` (the worker's own
  question answered via `/tracks/<id>/answer`, "Henry fragen" navigating into
  the SAME chat with the card as context rather than a second local dialog).
- **Voice** (`Watch/Data/VoicePlayer.swift`) - `AVAudioPlayer` over a decoded
  temp file, server-rendered MP3 only (`ops/docs/glasses-reference.md` §4) -
  no on-device synthesis anywhere in this target.

**Deliberately still out of scope, same reasoning as the scaffold:**
- No push-token registration (`daemon/notify.py`) - still gated on the
  Expo-Push-Service decision (`ios-watch-feasibility.md` §1.3) and the watch
  target still declares no `aps-environment` entitlement.
- No local verification - this card's worktree has no Mac/simulator. The
  first real signal for BOTH compile correctness and runtime crypto/UI
  behaviour is a `watchos-app.yml` CI run (compile-only) followed by a real
  TestFlight install once signing is exercised - nothing in this diff has
  been round-tripped against the daemon.
