# ADR 0001 — Distribution: Direct-Download DMG **and** Mac App Store

- **Status:** Accepted
- **Date:** 2026-08-15
- **Deciders:** Product owner (HelmDeck card `proc-20260814-s4`)
- **Supersedes:** the single-channel recommendation (Direct-DMG only) presented in the original trade-off memo

## Context

The app needs a macOS distribution channel. Two options were on the table:

- **Direct-Download DMG** — signed with Developer ID, notarized by Apple, distributed from our own site. Keeps the existing over-the-air (OTA) auto-updater.
- **Mac App Store (MAS)** — distributed by Apple, better discoverability and trust, handles payment and updates.

The blocking trade-off: **MAS requires the App Sandbox**, and sandboxed apps are not permitted to replace their own binary. Any Sparkle-style / electron-updater-style OTA mechanism is therefore not merely disabled but *disallowed* in a MAS build — Apple review rejects apps that ship self-update code, even dormant.

The original recommendation was Direct-DMG only, to avoid that conflict. The owner has instead chosen to ship **both**.

## Decision

Ship **two builds from one codebase**:

| | Direct-DMG | Mac App Store |
|---|---|---|
| Sandbox | off | **on** (mandatory) |
| Updates | existing OTA updater | Apple / App Store only |
| Signing identity | Developer ID Application | Apple Distribution |
| Provisioning profile | none | Mac App Store profile |
| Notarization | **required** | n/a (Apple handles review) |
| Hardened Runtime | **required** (for notarization) | not required |
| Release latency | immediate | gated on App Review |
| Payment (if paid) | own licensing | StoreKit, Apple commission |

This is a well-trodden pattern for macOS apps, not an exotic one. The cost is a second build+release pipeline and whatever sandbox rework the feature set demands — **not** a fork of the codebase.

## Consequences

### 1. Build separation must be compile-time, not runtime

The updater must be **absent from the MAS binary**, not feature-flagged off at runtime. A runtime toggle still leaves the self-update code in the bundle and is a review-rejection risk.

- Native (Swift/Obj-C): separate target/scheme + `SWIFT_ACTIVE_COMPILATION_CONDITIONS = MAS_BUILD`, updater sources excluded from the MAS target's *Compile Sources*.
- Electron: `electron-builder` already models this — a `mac` target (`dmg`/`zip`) and a `mas` target. Strip `electron-updater` from the MAS build via build-time define + per-target `files`/`asar` config.

Everything channel-specific should funnel through one thin abstraction (e.g. `UpdateChannel`, `LicensingProvider`) so the rest of the app stays channel-agnostic.

### 2. A sandbox audit is the real cost driver — and is not yet done

Whether "both" is cheap or expensive depends entirely on which features the sandbox blocks. **This audit has not been performed** (see Open Items). Known hazards, in rough order of how often they sink a MAS build:

- **Accessibility API** (`AXIsProcessTrusted`, sending synthetic events, reading other apps' UI) — effectively incompatible with MAS. This is the single most common reason an app stays direct-only. If the app relies on it, MAS may be off the table for the full feature set and a reduced-feature MAS build becomes the question.
- **Arbitrary filesystem access** — must move to user-selected paths plus **security-scoped bookmarks** to persist access across launches.
- **Launching helper processes / daemons** — must become `XPC` services or `SMAppService` login items bundled inside the app; arbitrary `exec` of external binaries is out.
- **Apple Events / AppleScript to other apps** — needs a `scripting-targets` or `temporary-exception.apple-events` entitlement; temporary exceptions require written justification at review and are frequently refused.
- **Enumerating running processes / other installed apps** — restricted.
- **Network** — needs `com.apple.security.network.client` and/or `.server`. Cheap, but must be declared.

### 3. Release process becomes two-track

- MAS releases pass App Review (commonly under 48h, but variable and occasionally much longer). MAS users will lag DMG users unless releases are deliberately staged: submit to MAS first, hold the DMG until approval, then publish both.
- Version numbers (`CFBundleShortVersionString` / `CFBundleVersion`) must stay in lockstep across channels to keep support and crash reports sane.
- CI needs both credential sets: Developer ID cert + notarization API key (`notarytool`), and Apple Distribution cert + MAS provisioning profile.

### 4. Bundle identifier — open decision

Same bundle ID across channels lets preferences and license state carry over if a user switches, but permits two copies of the app to coexist confusingly on disk. Different IDs are cleaner to reason about but orphan the user's existing settings on a channel switch. Recommend **same bundle ID** with a build-time channel marker in `Info.plist` for telemetry, unless licensing requires otherwise.

### 5. If the app is paid

MAS forces StoreKit and takes 30% (15% under the Small Business Program, for revenue under $1M/year). Direct sales keep your own payment and license-key flow. The licensing layer must therefore be pluggable, with receipt validation on MAS and key validation on direct.

## Open Items (blocking implementation, not this decision)

1. **Sandbox feasibility audit** — enumerate every capability the app uses against the entitlement list above. This determines whether MAS ships at full parity, reduced parity, or not at all. Must happen before any build-config work.
2. **Tech stack confirmation** — this worktree contains no source (see Note), so the concrete build-config recipe (Xcode targets vs. `electron-builder` config) cannot be written yet.
3. **Apple Developer Program account** — confirm the team has both Developer ID and App Store distribution capability, and that App Store Connect has an app record.
4. **Paid vs. free** — determines whether the licensing abstraction in Consequence 5 is needed at all.

## Note on this document's location

This ADR was authored in the HelmDeck worktree for card `proc-20260814-s4`, which contains **no repository and no source code** (`app/` is empty and there is no git repo, so nothing could be committed here). The file needs to be transplanted into the real application repository — conventionally at `docs/adr/` — as part of the follow-up implementation card.
