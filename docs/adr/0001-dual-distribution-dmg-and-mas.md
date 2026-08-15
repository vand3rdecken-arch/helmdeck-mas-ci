# ADR 0001 — Distribution: Direct-Download DMG **and** Mac App Store

- **Status:** Direct-DMG **shipped**; Mac App Store **blocked on architecture** — see Consequence 2. The owner's "both channels" decision stands as intent, but MAS is not reachable without re-architecting the daemon.
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

The stack is **Electron + electron-builder** (confirmed: `desktop/electron-builder.yml`, `desktop/native-updater.js` wrapping `electron-updater`, `@electron/notarize` and `dmg-builder` in the lockfile).

The **Direct-DMG channel already exists and ships** — `electron-builder.yml` on the integration branch carries a `mac:` section with `dmg` + `zip` targets, `hardenedRuntime: true`, a custom entitlements pair, and notarization wired up. Nothing in this ADR asks for that to change; the DMG side is done.

For a MAS target, the updater must be **absent from the built bundle**, not feature-flagged off at runtime — a runtime toggle still leaves the self-update code in the bundle and is a review-rejection risk. `electron-builder` models this natively with a `mas` target alongside `mac`, and `electron-updater` would be dropped from it via per-target `files`/`asar` config plus a build-time define.

That part is straightforward. It is also, per Consequence 2, not the binding constraint — so it should not be built until the daemon question is settled.

### 2. The sandbox audit is DONE, and it blocks MAS

The audit has now been performed against the real `desktop/` Electron app. It does not report a list of costs to weigh — it reports a hard stop.

**HelmDeck's core function is spawning executables the user installed.** `desktop/main.js` resolves a Python interpreter off the user's machine (`py -3.12` on Windows, `python3` on macOS) and `spawn()`s it detached to run `swarm.py serve <port>` — the Python daemon shipped as `extraResources`. It also spawns the `claude` CLI, and will *adopt* a daemon it finds already listening on the port rather than start its own.

**App Sandbox forbids exactly this.** A sandboxed app may not execute arbitrary non-bundled binaries; a bundled interpreter executing arbitrary `.py` source is dynamic code execution, which is what MAS review exists to reject. Worse, the mitigation the app already relies on — `com.apple.security.cs.disable-library-validation`, present in `desktop/build/entitlements.mac.plist` precisely so a hardened process can load code signed by somebody else or not signed at all — **is a Developer ID / hardened-runtime entitlement and is not available to MAS builds.**

The repository already recorded this conclusion before the decision was taken. From the header comment of `desktop/build/entitlements.mac.plist`:

> Kept deliberately narrow: **NO App Sandbox (this is direct distribution, not the Mac App Store)**

So the blocker is not the OTA updater, which was the trade-off the decision was weighed on. The updater is a build-config problem and genuinely solvable. The daemon spawn is an architecture problem: sandboxing removes the app's reason to exist.

#### "Can't we just bundle it all together?"

Asked directly, and it is the right instinct — but it rescues only the half that was never the hard part.

**Bundling the Python daemon genuinely works.** A sandboxed app may spawn a helper that lives inside its own bundle and is signed with the same Team ID (the child gets `com.apple.security.inherit`); this is how Electron's own helper processes ship on the Store today. Embedding an interpreter is likewise fine — bundled `.py` files ship with the app and are reviewed with it, so Guideline 2.5.2 (no downloading or executing code that changes the app's functionality) is not triggered. Bundle CPython plus its native extension modules, sign them all with our Team ID, and library validation passes on its own — meaning `disable-library-validation` would no longer be needed either.

**What cannot be bundled is the toolchain HelmDeck exists to drive.** `daemon/drivers.py:50` resolves the agent CLI off the user's `PATH`:

```python
CLAUDE = (os.environ.get("HELMDECK_CLAUDE") or shutil.which("claude") ...
```

alongside `git` (11 call sites in `daemon/`), `node`, and OS utilities. `claude` is a third-party CLI carrying the user's own authentication and its own update cadence; it cannot be redistributed inside our bundle, and it in turn spawns further arbitrary tools and reads and writes the user's filesystem at will. A sandboxed process may not execute binaries outside its bundle, full stop.

Two smaller consequences point the same way. HelmDeck runs `git worktree add` into sibling directories outside any folder the user could plausibly have granted, whereas a sandboxed app reaches non-container paths only through user-selected paths plus security-scoped bookmarks. And `taskkill`/`netstat`-style process inspection is not available to a sandboxed process either.

So the sequence is: bundling removes the interpreter objection, and the `claude` spawn remains — which is not an incidental feature but the product. **An App Store build that spawns nothing is not HelmDeck**; it is at most a companion to a HelmDeck running elsewhere. That is route 3 below, and it is a product decision rather than a packaging one.

**Reaching MAS therefore requires one of:**

1. **Reimplement the daemon in-process** — port `swarm.py` into the Electron main process (JS/TS), so nothing is spawned. Largest change; also strands the Python codebase that the CLI and other surfaces share.
2. **Ship a bundled, same-team-signed helper** — a compiled binary inside the bundle, no user-installed interpreter, no `claude` CLI spawn. Still forfeits the "drive the tools you already installed" premise.
3. **A reduced-feature MAS build** — a viewer/companion that talks to a daemon running elsewhere (another machine, or the phone app), spawning nothing locally.

Options 1 and 2 are projects, not build targets. Option 3 is the only one that is a *product* decision rather than a rewrite.

Cheap items, listed only for completeness once the blocker above is resolved: the local HTTP server needs `com.apple.security.network.server`, outbound needs `.client`, and any access outside the container needs user-selected paths plus security-scoped bookmarks.

### 3. Release process becomes two-track

- MAS releases pass App Review (commonly under 48h, but variable and occasionally much longer). MAS users will lag DMG users unless releases are deliberately staged: submit to MAS first, hold the DMG until approval, then publish both.
- Version numbers (`CFBundleShortVersionString` / `CFBundleVersion`) must stay in lockstep across channels to keep support and crash reports sane.
- CI needs both credential sets: Developer ID cert + notarization API key (`notarytool`), and Apple Distribution cert + MAS provisioning profile.

### 4. Bundle identifier — open decision

Same bundle ID across channels lets preferences and license state carry over if a user switches, but permits two copies of the app to coexist confusingly on disk. Different IDs are cleaner to reason about but orphan the user's existing settings on a channel switch. Recommend **same bundle ID** with a build-time channel marker in `Info.plist` for telemetry, unless licensing requires otherwise.

### 5. If the app is paid

MAS forces StoreKit and takes 30% (15% under the Small Business Program, for revenue under $1M/year). Direct sales keep your own payment and license-key flow. The licensing layer must therefore be pluggable, with receipt validation on MAS and key validation on direct.

## What comparable apps actually do

Asked directly: how do Paseo and similar tools get into the App Store? Checked rather than assumed — **they don't.** Every comparable ships exactly the shape this ADR arrives at.

- **Paseo** — the closest analogue, and its source is on this machine. `packages/desktop/electron-builder.yml` declares `mac.target: [dmg, zip]`, `hardenedRuntime: true`, `notarize: true`, and a GitHub `publish` feed for electron-updater. There is **no `mas` target**, and `build/entitlements.mac.plist` declares no `com.apple.security.app-sandbox` at all — so it is not sandboxed and is not eligible for the Store. It also ships its own `bin/paseo` CLI as an extra resource. Structurally identical to HelmDeck.
- **Warp** — warp.dev offers DMG and Homebrew. The App Store is not among the channels.
- **VS Code** — direct DMG download. The request to publish it on the Mac App Store (`microsoft/vscode#43947`) has sat open for years without shipping.
- **Cursor** — the desktop editor is a direct download. What *is* on the App Store is Cursor's **iOS companion**.

That last one is the pattern, and it is worth stating plainly: for developer and agent tooling, the desktop ships direct — notarized, self-updating — and the App Store presence, where there is one, is a **phone companion**, not the desktop agent. Nobody is sandboxing the toolchain driver, because it cannot be done.

**HelmDeck already follows this pattern.** The Expo app in `app/` is the phone client, iOS signing is in place, and it is the App-Store-facing surface. So the "both channels" intent is already satisfied — just not along the axis the original memo framed: **Direct-DMG for the desktop, Apple's store via the phone app.** A Mac App Store build would add no channel that HelmDeck does not already have.

## Open Items

1. ~~Sandbox feasibility audit~~ — **done**, see Consequence 2. Result: MAS is blocked by the daemon spawn, not by the updater.
2. ~~Tech stack confirmation~~ — **done**: Electron + electron-builder; Direct-DMG already shipping.
3. **Owner decision required** — given the audit, pick one of the three MAS routes in Consequence 2, or accept Direct-DMG as the only channel. This is the live question; everything below is downstream of it.
4. **Apple Developer Program account** — only if a MAS route is chosen: confirm App Store distribution capability and an App Store Connect record. (Developer ID is already in use for the DMG.)
5. **Paid vs. free** — only if a MAS route is chosen; determines whether the licensing abstraction in Consequence 5 is needed at all.

## Provenance

Authored for HelmDeck card `proc-20260814-s4` and committed on that card's branch. The audit in Consequence 2 was performed against the working tree at `fff99a1`, cross-checked against the `mac:` build config and `entitlements.mac.plist` on the integration branch (`expo-migration`), which are ahead of this branch.

Note for future edits: `.gitignore:48` ignores `docs` wholesale, so a new file here needs `git add -f` or it is silently never committed.
