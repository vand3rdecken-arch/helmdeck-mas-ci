# HelmDeck — deploy & dev runbook

How to ship a change to the phone/desktop, and the traps that cost us hours.
An agent on a deploy/fast-track card should follow THIS, not guess.

## First decision: OTA or native rebuild?

- **JS / React / assets only** (a screen, logic, styling, a new expo-router
  route) → **OTA**. Seconds, no rebuild.
- **Native** (a new native module like `expo-camera`, an Android permission, an
  `app.json` plugin, a `runtimeVersion` bump) → **APK rebuild**. ~10 min. You
  CANNOT ship native code over OTA.

---

## 1) OTA update (JS-only) — the fast path

```bash
bash deploy/push_update.sh
```

Runs `expo export --platform android` and uploads the JS bundle to the relay's
`/updates` channel (runtimeVersion `1.0.0`). The phone applies it over the next
**two** launches (1st downloads, 2nd applies). Verify on the phone: **More tab
footer** shows the new `OTA <id>`.

### Desktop OTA rides the same push (Paseo auto-update)
`push_update.sh` also exports the **web** bundle and publishes it + a
`desktop.json` manifest to the relay's `desktop` channel dir
(`/opt/helmdeck-updates-desktop`, served by the existing `/updates/assets`
route - no relay change). The desktop follows it silently with Paseo's exact
mechanism (verified in `_paseo_src`, constants cited in
`desktop/desktop_update.py`): **check at start + every 30 min, 10 s retry
while a download is pending, silent apply on quit** (revalidated, 5 s
deadline) - plus the always-on `desktop/tray.py` supervisor checks on the same
cadence and swaps the installed app's `resources/app-dist` whenever the
Electron shell isn't running, so the owner never reinstalls. Every file is
sha256-verified against the manifest before a swap; the previous bundle stays
as `app-dist.old` (manual rollback: swap it back). A desktop publish failure
warns loudly but never blocks the phone OTA. Verify: tray menu shows
`Update: aktuell/angewendet`, or check `desktop.json` id vs
`<install>/resources/app-dist/.hd-update.json`.

### ⚠ CRITICAL: after a native APK, push a matching OTA
The **relay is the source of truth**: on launch the app pulls the relay's bundle
for its runtimeVersion **even if that bundle is older**, and it overwrites the
APK's embedded JS. So if you build a native APK with new JS but forget to push a
matching OTA, the old relay bundle reverts the JS on next launch — the native
module stays, but its UI vanishes ("OTA works but the update is gone"). Always
`push_update.sh` right after a native release.

### runtimeVersion bump on native change (automated in ship.sh)
`runtimeVersion` policy is `appVersion`, so the runtimeVersion == `expo.version`.
`deploy/ship.sh` now **bumps `version` + `android.versionCode` on every native
change** before building the APK. Effect: an OLD APK (old version) *rejects* the
new JS (rtv mismatch) instead of loading it and crashing on a native module it
doesn't ship — the `Cannot find native module 'ExpoDocumentPicker'` crash-loop.
JS-only ships keep the version, so phones still receive those OTAs. Belt-and-
suspenders: `app/src/app/_layout.tsx` `ErrorBoundary` turns any such missing-
native-module error into a clear "App-Update nötig" screen instead of a crash.
Recovery if a bad bundle already shipped: `deploy/rollback_update.sh --embedded`
(reverts every phone to its APK's own bundle), then distribute the matching APK.

---

## 1b) Desktop installer → GitHub release

The Windows desktop app is distributed as an NSIS installer on the GitHub
"Downloads" release (`github.com/Tienduyvo/helmdeck`). OTA now covers the UI
bundle (§1), but the app *shell* (main.js, the auto-updater, electron-builder
config) can only ship as a new installer — the desktop's native-vs-OTA line.
So whenever the shell changes (like adding the auto-updater), cut a new
installer and update the release:

```bash
bash deploy/release_desktop.sh --version 0.2.2 --latest \
     --notes deploy/release_notes_desktop.md
```

What it does (one command; `gh` must be authed — `gh auth status`):
- builds `HelmDeck-Setup-<version>-x64.exe` via `build-win.ps1 -Version` (the
  winCodeSign workaround; falls back to an inline bash build if `powershell` is
  off the PATH),
- uploads it to the target release (`--latest` = newest tag, or `--tag vX`,
  creating it if new), **clobbering** the old desktop `.exe`,
- refreshes `SHA256SUMS.txt` in place — keeps the APK line, replaces the
  desktop line,
- with `--notes`, sets the release body.

Pick `--version` **above the last published one** (the committed
`desktop/package.json` version can lag — 0.2.1 was built from a committed
0.2.0; `-Version` stamps the installer without a package.json bump). Rehearse
with `--dry-run` (build + checksum, no upload) or `--no-build` (reuse an
existing `desktop/release/*.exe`). Since 0.2.2 the installed app auto-updates
its UI, so this manual step is only for shell releases — the once-per-user
install that grants auto-update, then never again for JS-only changes.

## 1c) macOS desktop build → a macOS runner, never this box

The Mac app is the same Electron shell, same daemon, same `app/dist` — only the
packaging differs. What does **not** transfer is the toolchain: `codesign`,
`hdiutil` and `notarytool` exist only on macOS, so there is **no cross-build
from Windows**. electron-builder says so itself and stops immediately:

```
⨯ Build for macOS is supported only on macOS
```

So the Mac artifact is built by GitHub's macOS runner:
`.github/workflows/desktop-mac.yml` (`runs-on: macos-14`, Apple silicon, which
cross-compiles the x64 slice too). Trigger it from the Actions tab
(**workflow_dispatch** — optional `version` to stamp, optional `release_tag` to
attach the artifacts to a release) or let it run on a push touching
`desktop/**`, `app/**` or `daemon/**`. On a Mac, the same build is one command:

```bash
bash desktop/build-mac.sh --version 0.2.3        # dmg + zip, arm64 + x64
```

Output in `desktop/release/`: `HelmDeck-<v>-{arm64,x64}.dmg` for humans,
`HelmDeck-<v>-{arm64,x64}.zip` **for the auto-updater** — Squirrel.Mac (what
`native-updater.js` drives via electron-updater) can only apply a zipped `.app`,
it cannot read a `.dmg` — plus `latest-mac.yml`, the feed pointing at the zip.

### ✅ EXECUTED 2026-08-15 — signed, notarized, Gatekeeper-accepted

Run [`31877006863`](https://github.com/Tienduyvo/helmdeck/actions/runs/31877006863)
on `macos-14`, **32m10s, every step green**. This is the first Mac build that
has ever run, and it closed debt `mac-build-never-executed`. What the log
proves, quoted rather than paraphrased:

| stage | evidence |
| --- | --- |
| decision | `==> signing: Developer ID identity supplied` → `==> notarization: ON` |
| Apple | `• notarization successful` — **twice**, once per arch |
| signature | `codesign --verify --deep --strict` → *valid on disk* + *satisfies its Designated Requirement* |
| **Gatekeeper** | `spctl --assess --type execute` → **`accepted`**, `source=Notarized Developer ID` |
| artifacts | `HelmDeck-0.2.0-{arm64,x64}.{dmg,zip}` + blockmaps + `latest-mac.yml`; `hdiutil imageinfo` passed on both dmgs |

So the entitlement set really is the right one — that was the one thing only a
notarized run on real hardware could establish. Budget note: ~32 min of macOS
runner time per build, free because the repo is public.

⚠ **Benign warning, do NOT "fix" it.** electron-builder prints *"Please specify
notarization Team ID in the `APPLE_TEAM_ID` env var instead of
`notarize.teamId`"*. Ignore it. The `-c.mac.notarize.teamId` override is what
**turns notarization on at all** (the committed config deliberately keeps
`notarize: false` so a secret-less build still succeeds); the warning is only
about where the team id is read from, and notarization demonstrably worked.

**The build succeeds with no secrets at all** — it just produces an *unsigned*
app: Gatekeeper quarantines it and the auto-updater cannot apply updates to it
(Squirrel.Mac requires a valid signature). Add the repo secrets and the same
workflow starts signing, then notarizing, with no file changing:

| secret | effect |
| --- | --- |
| `MAC_CSC_LINK` + `MAC_CSC_KEY_PASSWORD` | Developer ID `.p12` → signed build |
| `ASC_API_KEY_P8`, `ASC_KEY_ID`, `ASC_ISSUER_ID`, `APPLE_TEAM_ID` | → notarized (**all four**, on top of signing) |

The ASC key is the *same* App Store Connect key `deploy/ios_credentials.sh`
already uses (§2b) — one key notarizes macOS and signs iOS.

`MAC_CSC_LINK` / `MAC_CSC_KEY_PASSWORD` come from `deploy/mac_credentials.py`.
No Xcode/Keychain needed for the CSR — it's plain PKCS#10, openssl builds one
on Windows — but **creating the certificate itself is not reachable by any
API key**: VERIFIED 2026-08-15, the ASC API returns 403 "This operation can
only be performed by the Account Holder" for `DEVELOPER_ID_APPLICATION`, for
the same Admin-role key that mints iOS distribution certs fine. This is not
a key-role problem (retrying with a different role key changes nothing) —
Apple walls this operation off from all API-key auth, the same bucket
`deploy/ios_credentials.sh` already documents for ASC-key management and
push keys. So the flow is CSR-by-script, cert-by-human, bundle-by-script:

```
py -3.12 deploy/mac_credentials.py --check                  # read-only, run first
py -3.12 deploy/mac_credentials.py --create [--out DIR]     # writes key+CSR; POST 403s -
                                                              # prints the manual step below
# --- one human, in a browser, as the Account Holder, with 2FA ---
#   https://developer.apple.com/account/resources/certificates/add
#   -> "Developer ID" -> "Developer ID Application" -> Continue
#   -> intermediary: pick "G2 Sub-CA (Xcode 11.4.1 or later)", NOT the
#      pre-selected "Previous Sub-CA" - that one hard-expires 2027-02-01
#      regardless of when it was issued; G2 gives the full 5 years
#   -> upload the CSR --create wrote -> download the resulting .cer
py -3.12 deploy/mac_credentials.py --finish DOWNLOADED.cer   # bundles key+cert -> .p12
py -3.12 deploy/mac_credentials.py --secrets FILE.p12 --password PW
```

**DONE 2026-08-15** — walked end to end. The cert exists
(`Developer ID Application: Tien Duy Vo (92WJZQ2WWH)`, issuer *Developer ID
Certification Authority G2*, valid to **2031-08-16**), the `.p12` is at
`C:/hd/secrets/mac_developer_id.p12`, and `MAC_CSC_LINK` +
`MAC_CSC_KEY_PASSWORD` are live on `Tienduyvo/helmdeck` (`gh secret list`
confirms both). Verified before upload, not assumed: the `.p12` carries a
private key, and its modulus matches the signed cert's. Signing is no longer
the blocker — §1d (source push) is: the release repo still has no
`.github/workflows`, so no runner can check the build out.

**NOTARIZATION SECRETS LIVE 2026-08-15** — all six repo secrets are now set on
`Tienduyvo/helmdeck`, so the workflow's signed **and notarized** path is armed:
`MAC_CSC_LINK`, `MAC_CSC_KEY_PASSWORD` (from the cert above) plus
`ASC_API_KEY_P8`, `ASC_KEY_ID`, `ASC_ISSUER_ID`, `APPLE_TEAM_ID`. The `.p8` was
piped straight into `gh secret set` from `C:/hd/secrets/` — never read, never
echoed, never copied into the repo. Verified rather than assumed, twice:
- the key **authenticates against Apple right now**:
  `ASC_KEY_ID=… ASC_ISSUER_ID=… ASC_API_KEY_PATH=… py -3.12
  deploy/mac_credentials.py --check` mints a JWT and gets a 200. A wrong key id
  or issuer 401s *here*, which is 20 minutes and a whole Mac build cheaper than
  finding out during notarization. It reports *"no existing Developer ID
  Application certificate"* — that is the **same API-key wall** that 403s cert
  creation, **not** a missing cert; Apple does not list Developer ID certs to
  API keys at all. Do not "fix" that by minting a second cert.
- the certificate itself is real, read locally with openssl:
  `CN = Developer ID Application: Tien Duy Vo (92WJZQ2WWH)`, issuer *Developer
  ID Certification Authority G2*, EKU **Code Signing**, valid to 2031-08-16 —
  and its team `92WJZQ2WWH` matches the `APPLE_TEAM_ID` secret, which is the
  pairing `-c.mac.notarize.teamId` actually depends on.

So nothing in the signing/notarization *wiring* is outstanding: hardened
runtime, both entitlements files, the notarize-object override and the
workflow's `codesign --verify` + `spctl --assess` gate were all already in
place and re-read line by line on 2026-08-15. §1d is the only thing left.

`--check` lists any Developer ID Application certs the account already holds
— re-submitting a CSR against an account that already has one just burns
another slot of Apple's quota, so check before minting. `--create`/`--finish`
write the private key + `.p12` **outside** the repo (refuses an `--out`
under it, same guard `ios_credentials.sh` puts on the `.p8`) and print the
`.p12` password once — Apple-style secrets are not re-servable, save it
before running `--secrets`. `--secrets` is a deliberate separate step: it is
the one that actually writes to the real repo via `gh secret set`.

Traps already paid for here:
- `notarize` stays `false` in `electron-builder.yml`; `build-mac.sh` turns it on
  with `-c.mac.notarize.teamId=<team>`. The **object** form is deliberate —
  `-c.mac.notarize=true` reaches electron-builder as the *string* `"true"`,
  truthy but carrying no team id.
- Custom `entitlements` **replace** electron-builder's defaults, so
  `desktop/build/entitlements.mac.plist` restates the three JIT ones Electron
  needs *plus* `disable-library-validation` — without it a hardened HelmDeck
  cannot spawn the Python daemon or the `claude` CLI (code it did not sign).
- The Mac icon is a **tracked** PNG (`desktop/assets/icon-mac-1024.png`, on
  Apple's inset 824/1024 grid) that electron-builder converts to `.icns`, so a
  clean CI checkout needs neither Pillow nor `iconutil` — unlike `icon.ico`,
  which is git-ignored and must be regenerated before every Windows build.
- No signing identity ⇒ `build-mac.sh` exports `CSC_IDENTITY_AUTO_DISCOVERY=false`.
  Without it electron-builder hunts an empty keychain and *fails* the build
  instead of producing a clean unsigned one.

### ✅ PUBLISHED 2026-08-15 — the OTA channel is connected

A signed, notarized build sitting in `desktop-mac.yml`'s workflow-artifact
storage is not reachable by any installed app — `native-updater.js`
(electron-updater's `GithubProvider`) only ever reads **release assets**, and
CI's own artifact zip expires in 14 days. `deploy/release_desktop_mac.sh` is
the macOS twin of `release_desktop.sh`: it never builds (there is no macOS on
this box), it publishes a set that either `desktop/build-mac.sh` on real
macOS or `gh run download <run> -n helmdeck-macos -D DIR` already produced —
uploading the dmgs, the zips (**Squirrel.Mac's actual update payload**),
`latest-mac.yml` (the feed `native-updater.js` polls), and the blockmaps to
the release, refreshing `SHA256SUMS.txt` in place with the same discipline
the Windows script uses.

```bash
gh run download 31877006863 --repo Tienduyvo/helmdeck -n helmdeck-macos -D /tmp/mac-artifacts
bash deploy/release_desktop_mac.sh --dir /tmp/mac-artifacts --latest
```

Run against the notarized `31877006863` build: `v1.0.7` on
`github.com/Tienduyvo/helmdeck` now carries
`HelmDeck-0.2.0-{arm64,x64}.{dmg,zip}` + blockmaps + `latest-mac.yml`,
verified byte-identical to CI's copy after upload (not just a successful exit
code) and cross-checked against the refreshed `SHA256SUMS.txt`. That is the
whole channel: a new Mac user downloads the `.dmg`; an installed 0.2.0+ Mac
app finds `latest-mac.yml` on the same release electron-updater already
checks for Windows and applies the matching zip silently on quit — no code
change was needed in `native-updater.js`, since electron-updater's
`GithubProvider` was always platform-generic, only the mac artifacts were
missing from the release.

## 1d) Publishing the source — what the macOS runner needs

CI can only build what it can check out, and until 2026-08-14 the local clone
had **no git remote at all**: `github.com/Tienduyvo/helmdeck` was a download
shelf holding `README.md` plus release assets, everything uploaded by `gh`.
Owner's decision: **one repo** — the source goes into that same public repo,
next to the builds. Not a second source repo.

```bash
bash deploy/publish_source.sh --dry-run     # audit only, pushes nothing
bash deploy/publish_source.sh               # audit, then push the trunk -> remote main
```

⚠ **Two traps found on 2026-08-15, both now handled by the script — read this
before running it, because one of them is irreversible.**

**a) The local trunk is not called `main`.** `main` is a stale 2026-08-12
branch (`2aaa4d4`, "mobile: glass on BOTH bars") that contains **no `.github/`
at all**. The branch actually carrying the source *and* `desktop-mac.yml` is
**`expo-migration`** — that is what the main working copy has checked out and
what accept-commits land on. The script's old default would therefore have
published a tree the macOS runner cannot build, which is the one job it has.
Source and target are now separate knobs, defaulting to the right pair:
```bash
HELMDECK_PUBLISH_BRANCH=expo-migration   # what gets audited + pushed
HELMDECK_PUBLISH_TARGET=main             # where it LANDS on the remote
```
The target must stay the remote's **default branch**: GitHub only offers
*Run workflow* (`workflow_dispatch`) for workflows present on the default
branch, and `desktop-mac.yml`'s own `push: branches: [main]` trigger never
fires from a branch by another name.

**b) A green audit is not a safe audit — `.attachments/`.** The old checks ask
"is this a credential", so a **photo** answers *no* and sails through. Five
files in `.attachments/` are chat uploads: the owner's **phone screenshots of
his own board**, showing unreleased card titles, due dates and distribution
decisions. A push publishes *history*, so those would have been public forever
— and, as the script says about every blob, deleting them in a later commit
does **not** unpublish them. That they are user data and not source was already
settled twice in this repo (`daemon/recordings/` + `daemon/checkpoints/` are
git-ignored; `electron-builder.yml` refuses to ship `.attachments/**`); only
git never got the memo. There is now a privacy check that **fails closed**:
```bash
git show expo-migration:.attachments/0_1000029273.jpg > /tmp/x.jpg   # LOOK first
HELMDECK_PUBLISH_ALLOW_PRIVATE=1 bash deploy/publish_source.sh       # publish anyway
```
The alternative — and **what was actually done** — is `--filter-private`.

### PUBLISHED 2026-08-15 — how, and the two things that surprised it

```bash
bash deploy/publish_source.sh --filter-private     # this is the command
```
It publishes a **filtered mirror**: clone the trunk to a temp dir, drop
`.attachments/` from *that copy's* history, push the result. Filtering the trunk
in place was rejected deliberately — ~20 live card branches and worktrees hang
off it and `git_filter_repo` rewrites every sha it touches, stranding all of
them. The owner's repo is never rewritten. Result: 572 commits, 585 files,
tree byte-identical to the trunk minus the 5 jpgs (`git archive | tar -t` diff:
only those 5 + the dir entry missing, **nothing added**). The 5 commits that
vanished were attachment-only "finalize" commits, correctly pruned as empty.

The mirror lineage is **deterministic**, which is what makes it sustainable:
filtering the same input commit twice gave the identical sha (`a10d9454`), so
later publishes **fast-forward** and never need a force again. (It briefly
looked nondeterministic — that was another card landing 2 commits on the trunk
between the two test clones, not the filter.)

⚠ **The first push is a non-fast-forward, and forcing it is safe.** The remote
`main` was a single *unrelated* commit (`1dc31bb6` "HelmDeck public releases"),
so a plain push is rejected exactly once. Verified **before** forcing, not
after: all four release tags (`v1.0.4`–`v1.0.7`) pin `1dc31bb6` themselves, and
release **assets live in the releases API, not in git** — so a force-push of
`main` cannot break the download shelf or the desktop auto-updater. Confirmed
after the push: all 4 releases still listed, `1dc31bb6` still resolvable. The
push used `--force-with-lease=main:1dc31bb6…` so it would have aborted if the
remote had moved.

⚠ **The push did NOT auto-trigger the workflow.** `desktop-mac.yml` has
`push: branches: [main]`, Actions was enabled and the workflow registered
`state=active` — and `gh run list` was still empty. A first-ever workflow file
arriving by force-push of an unrelated history does not fire its own push
trigger. Dispatch it explicitly and don't wait on a run that will never start:
```bash
gh workflow run desktop-mac.yml --repo Tienduyvo/helmdeck --ref main
gh run list --repo Tienduyvo/helmdeck --limit 3
```

It is an audit that ends in a push, re-run in full every time — `.gitignore`
only ever protected the *present*, and a push publishes *history*. Audit as of
this commit: 2244 blobs, **zero** credential matches; no `settings.json` /
`users.json` / `*.db` / `*.jks` / `*.p8` ever committed; the one interesting
literal is a `*.trycloudflare.com` quick-tunnel URL from 26 old blobs, verified
**dead** (no DNS).

Three traps it guards, each one load-bearing:

- **Never `--all` / `--mirror`.** Branch `wip-expo-migration-20260812-223553`
  parks a 136 MB APK, an 81 MB `.exe` and a 78 MB `.aab` under
  `deploy/release_v1.0.7/`. GitHub **hard-rejects any file over 100 MB**, so
  that push fails outright — and it would publish ~20 stale card branches too.
  `main` is clean (largest blob 14.8 MB), which is the whole point of pushing a
  single branch.
- **The root `README.md` is the public product page**, not the dev map: Play
  links, the SmartScreen note, the privacy policy. Pushing the old internal
  README would have silently replaced a live page. So the landing text now *is*
  `README.md` (byte-identical to what was published — verified by blob hash,
  plus an appended `## Development` pointer) and the internal map moved to
  `docs/repo-map.md`. The script refuses to push a `README.md` with no
  `## Downloads` section. (Plain reference, not a link: `docs/` is stripped from
  the mirror — next bullet — so a link there would 404 for a public reader.)
- **`docs/` never reaches the mirror** (owner decision 2026-08-16: *"you work
  local so just don't publish docs"*). `publish_source.sh`'s private-path check
  strips the whole tree under `--filter-private`. Two different mechanisms, two
  different jobs: the `docs` line in `.gitignore` keeps NEW docs untracked by
  default, this keeps the ones that MUST be tracked out of the public mirror.
  Some must be tracked — a card's worktree contains only tracked files, so
  `docs/glasses-reference.md` (mandatory reading for every glasses card) would
  be invisible to the cards that need it if it were merely ignored. The tree is
  private-but-not-secret in the way the credential scanner cannot see: home
  paths and bridge setup in the glasses reference, and real board screenshots
  (card titles, dates) under `docs/store/screenshots/`.
- **Use SSH, not HTTPS.** The owner's `gh` token scopes are
  `admin:public_key, gist, read:org, read:packages, repo` — **no `workflow`**,
  so an HTTPS push touching `.github/workflows/` is rejected with *"refusing to
  allow an OAuth App to create or update workflow"*. The script wires
  `git@github.com:…` for exactly this reason.

Public repo ⇒ **macOS runner minutes are free and unmetered** (private would
bill 10×, ~200 free minutes/month ≈ 10 Mac builds). After the push: Actions →
`desktop-mac` → *Run workflow*. With no secrets set that produces an unsigned
`.dmg`/`.zip` — and that unsigned run is the honest smoke test that closes debt
item `mac-build-never-executed`.

## 1e) Shipping the website (helmdeck.de) — merging is NOT shipping

`helmdeck.de` is a single Cloudflare Worker (`deploy/waitlist/`, worker name
`helmdeck-waitlist`). It is the **one shipping surface the card deploy hook does
not cover** — accepting a card runs the repo's `deploy` hook (OTA / installer),
and nothing in that path runs `wrangler deploy`. A merged commit changes
nothing on the live domain until someone runs the deploy by hand.

That gap has already cost a release: card `proc-20260814-s7` merged the full
landing page on 2026-08-15 (commit `39bf69a`) and the live site kept serving the
**2026-08-13 waitlist-only build** — the owner saw "nur die Waitlist" while the
commit log said the page had shipped days ago. The card had verified against
`wrangler dev`, not against the origin.

```bash
bash deploy/push_site.sh            # deploy, then re-read the live origin
bash deploy/push_site.sh --check    # verify only; safe any time, exits 1 if stale
```

⚠ **Never verify a site deploy from `git log`.** The commit history is not the
deploy state. Two origin-truth probes, both cheap:

```bash
curl -s https://helmdeck.de/health                       # {"ok":true,"service":"helmdeck-waitlist"}
curl -s https://helmdeck.de/ | grep -o '<title>[^<]*</title>'
cd deploy/waitlist && npx wrangler deployments list | tail -8   # newest deploy timestamp
```

`push_site.sh` does exactly this after uploading and **exits non-zero if the
origin still serves the old build**, so a silent no-op deploy can't pass again.

- **Auth**: `wrangler` uses the owner's OAuth token on this box
  (`npx wrangler whoami`). There is no Cloudflare secret in the repo.
- **Download links are live-fetched**, so shipping a *new app release* needs no
  site deploy — the Worker re-reads `releases/latest` (1h KV cache). Only
  *page* changes need `push_site.sh`.
- **Recommended**: add `bash deploy/push_site.sh` to the repo `deploy` hook in
  `settings.json` (`repo_hooks.<repo>.deploy`) so the site can never again be
  left behind by an accept. Registered as debt `site-deploy-outside-hook`.

## 2) Native APK build

Prereqs (once per machine):
- **JDK 17** — RN 0.86 / Expo 57 need it; Java 8 fails. `winget install Microsoft.OpenJDK.17`
- Android SDK + NDK 27 (already installed here).
- `app/android/local.properties` must use **forward slashes**:
  `sdk.dir=C:/Users/.../AppData/Local/Android/Sdk`. Backslashes are eaten by the
  Java properties parser → build dies with "The filename, directory name, or
  volume label syntax is incorrect".

Build (release = signed + JS bundled = standalone APK):
```bash
cd app/android
export JAVA_HOME="/c/Program Files/Microsoft/jdk-17.0.20.8-hotspot"
export ANDROID_HOME="$HOME/AppData/Local/Android/Sdk"
export PATH="/c/Program Files/nodejs:$JAVA_HOME/bin:$PATH"
./gradlew assembleRelease -x lint --console=plain
# -> app/build/outputs/apk/release/app-release.apk  (~140MB, signed w/ daemon/certs/apk-signing/swarmdeck-release.jks)
```

⚠ **Those raw gradle lines are for DEBUGGING a build, not for producing a
shippable APK — use `deploy/build_apk.sh`.** Calling gradle directly skips
everything the script does first, and the skips are SILENT: the build goes
green and the artifact is wrong. Measured on 2026-08-17 by doing exactly this:
a 52-minute build produced an APK stamped **versionName 1.0.2 / versionCode
38** while `app.json` already said **1.0.8 / 44**, because the version-sync
step below never ran — precisely the drift the comment there warns about. The
config plugins (`withLanCleartext`, `withGlassVoice`) are skipped the same way,
so a permission can be missing from a perfectly successful build. If you do run
gradle by hand, run the plugin + version-sync steps from `build_apk.sh` first,
and verify the result rather than trusting it:
```bash
AAPT=$(ls -t "$ANDROID_HOME/build-tools/"*/aapt2.exe | head -1)
"$AAPT" dump badging app-release.apk | grep versionName   # must match app.json
"$AAPT" dump permissions app-release.apk                  # must list what you added
```

⚠ **Building from a worktree: `ninja: manifest 'build.ninja' still dirty after
100 tries`.** react-native-screens / -worklets / expo-modules-core die in the
CMake step, right after CMake warns "object file path cannot be safely placed
under this directory". Cause is path length: `helmdeck-worktrees/<repo-hash>/
<branch>/app/node_modules/...` is ~50 chars deeper than the main repo, so NDK object paths
blow past the Windows limit. **`subst`-ing a drive letter does NOT help** —
gradle/CMake canonicalise it straight back to the long path. What works: build
from a real short path, e.g. mirror `app/` to `C:\hd\app` and run gradle there.
When mirroring with robocopy, exclude `dist`/`build` **fully qualified** —
bare `-XD dist build` drops those dirs out of every npm package too and breaks
autolinking (`Cannot find module '@jridgewell/gen-mapping/dist/…'`).

Other Git-Bash traps when driving the emulator: `adb shell … /sdcard/x` gets
rewritten to `/Files/Git/sdcard/x` — prefix `MSYS_NO_PATHCONV=1`. And the
emulator is shared: `deploy/build_apk.sh` does `adb uninstall` + `adb install`
as its smoke, so a concurrent build can silently replace the APK you are
testing — check `dumpsys package app.helmdeck | grep version` before trusting a
measurement.

Native config note: `app/android/` is **git-ignored / hand-managed**. A native
permission (e.g. CAMERA) must go in BOTH `app/app.json` `plugins` (so a future
`expo prebuild` reproduces it) AND the hand-managed
`app/android/app/src/main/AndroidManifest.xml` (what THIS build uses).

Cleartext / direct-LAN: cleartext HTTP is **scoped, not global** — a
network-security-config allows it only for `10.0.2.2`/loopback plus the hosts
in the `./plugins/withLanCleartext` entry in `app.json` (Android can't express
IP ranges). `deploy/build_apk.sh` re-applies it to the hand-managed
`app/android` before every gradle build (`node app/plugins/withLanCleartext.js
app/android`), and the same file is the expo config plugin for a future
prebuild. Direct-LAN from a real phone ⇒ add the PC's IP to that host list and
rebuild the APK; relay/HTTPS need nothing.

---

## 2b) iOS signing & credentials (EAS)

iOS has no local path on this box — there is no Xcode and no macOS, so the build
runs on EAS and the **signing assets live in EAS, not in the repo**. Nothing here
is a secret you may commit; the certificate and profile stay on Expo's servers.

State as of this section: the project is **linked** —
`@tienduyvo/helmdeck`, projectId `a0ea8905-52a1-4223-b102-1dfd9e98d561`, recorded
in `app/app.json` as `extra.eas.projectId` + `owner`. `eas.json` already carries an
`internal` (ad-hoc/device) and a `production` (App Store) profile. A paid **Apple
Developer Program** membership is the hard floor — without it Apple issues no
distribution certificate and every route below dies at the identical step
(confirmed active by the owner on 2026-08-14).

Decided route (owner, 2026-08-14): **App Store Connect API key**, not an Apple ID
login. Everything below is driven by `deploy/ios_credentials.sh` — read its header,
it carries the source citations for the claims here.

**DONE on 2026-08-14 — this is the record, not a to-do.** Signing is wired and the
assets exist; the steps are kept because they are what you repeat when the key is
rotated or the certificate expires.

1. App Store Connect → *Users and Access* → *Integrations* → *Keys* → **+**,
   role **Admin**. *App Manager is not enough for certificate creation, and a
   Developer-role key cannot create certificates or profiles at all.* The role is
   fixed at creation — Apple's own page says keys "can not be changed after they
   are created", so a wrong role means a **new key**, not an edit. (The first key
   here was minted as Developer and had to be replaced; the superseded one is
   parked as `C:/hd/secrets/AuthKey_3PF7T489J8.p8.superseded` and can be revoked
   in App Store Connect whenever you like.)
   EAS cannot bootstrap this itself — `createAscApiKeyAsync` is one of the few
   calls that hard-forces a user session.
2. Download the `.p8`. Apple serves it **exactly once**, no re-download.
   Store it **outside the repo** (`C:/hd/secrets/` is what this box uses) — the
   script refuses to run otherwise, and `*.p8` is git-ignored as a second net.
3. Put the values in `.env` (git-ignored). Live values on this box:
   ```
   ASC_API_KEY_PATH=C:/hd/secrets/AuthKey_AZQRY4K34W.p8
   ASC_KEY_ID=AZQRY4K34W
   ASC_ISSUER_ID=1b630099-8d46-41b6-b69f-9e41c4662b41   # per team, stays the same
   APPLE_TEAM_ID=92WJZQ2WWH        # developer.apple.com → Membership details
   APPLE_TEAM_TYPE=INDIVIDUAL      # "Registriert als: Einzelperson"
   ```
   Write that block with a plain editor. PowerShell's `Set-Content -Encoding UTF8`
   prepends a **BOM**, and bash then reports `.env: line 1: <U+FEFF>: command not
   found` — harmless on a blank first line, but it eats the variable name if the
   BOM lands on one. `Add-Content` onto an existing file does not add one.
4. ```bash
   bash deploy/ios_credentials.sh --check   # validates everything, changes nothing
   bash deploy/ios_credentials.sh           # creates cert + profile
   ```
   **Run step 4 from `cmd.exe`/Windows Terminal, not from Git Bash.** MinTTY pipes
   stdin through named pipes, so `node` sees no TTY there and eas-cli aborts with
   *"Input is required, but stdin is not readable"* at its first Y/n prompt — the
   same error you get with `</dev/null`, which is why it looks like a script bug
   and is not. Piping `y` in does not help either; eas-cli wants a real terminal.
   ```cmd
   "C:\Program Files\Git\bin\bash.exe" -lc "cd /c/.../helmdeck && bash deploy/ios_credentials.sh"
   ```

⚠ **The capability-sync trap.** On the very first run, `configure-build` registers
the bundle ID and then tries to switch on the capabilities implied by `app.json`.
For HelmDeck that is `PUSH_NOTIFICATIONS` (from `expo-notifications`), and Apple's
API rejects eas-cli's patch payload outright:
*"Unexpected or invalid value at `data.relationships.bundleIdCapabilities.data.[0].attributes`"*.
eas-cli offers `EXPO_NO_CAPABILITY_SYNC=1` — **don't**: that silences the check
instead of fixing the state, and the capability stays off. Tick *Push Notifications*
by hand on the App ID (developer.apple.com → Identifiers → `app.helmdeck` →
Capabilities → Save → Confirm) and re-run; the sync then reports *"No updates"* and
walks straight through. Note Apple's confirm dialog warns that changing capabilities
invalidates existing provisioning profiles — irrelevant the first time, but if you
add a capability later you must regenerate the profile.

**What exists now** (created by the run above, both read back from EAS, not assumed):

| asset | value |
|---|---|
| Apple team | `92WJZQ2WWH` (Individual) |
| Bundle ID | `app.helmdeck` (explicit), registered via the API key |
| Distribution Certificate | serial `6871F101B7F3B831D88FBF82A0A977DF`, expires 2027-08-14 |
| Provisioning Profile | portal ID `6A8R2K67SV`, active, expires 2027-08-14 |

eas-cli's closing line was *"All credentials are ready to build @tienduyvo/helmdeck
(app.helmdeck)"*. **No Apple ID and no 2FA were used at any point** — the API key
carried the whole flow, which is the claim this section was written to prove.

**Why step 4 wants a real terminal — and why that is not a 2FA prompt.** Verified
in eas-cli's source, because the docs do not say it:
`credentials/ios/appstore/AppStoreApi.js` sets
`defaultAuthenticationMode = hasAscEnvVars() ? API_KEY : USER`. With the three
`EXPO_ASC_*` vars exported, certificate creation, profile creation, ad-hoc profiles
and bundle-ID registration all authenticate by JWT, and `credentials/context.js`
skips the *"Do you want to log in to your Apple account?"* prompt entirely. What
still needs a TTY is `SetUpDistributionCertificate.js`:
`runNonInteractiveAsync` throws `MissingCredentialsNonInteractiveError` when no
certificate exists yet — non-interactive mode **reuses** a certificate, it never
mints the first one. Confirmed on the real run: the only question asked was
*"Generate a new Apple Distribution Certificate? (Y/n)"*. Apple never appeared.
`APPLE_TEAM_ID` + `APPLE_TEAM_TYPE` pre-answer the two team prompts that would
otherwise come first.

**Afterwards it is unattended** — an agent card can run:
```bash
bash deploy/ios_credentials.sh --build                    # production .ipa
bash deploy/ios_credentials.sh --build --profile internal # ad-hoc, needs UDIDs
```
`internal` installs only on devices registered with `npx eas-cli device:create`;
`production` needs no UDIDs. If `--build` ever reports
`MissingCredentialsNonInteractiveError`, the certificate did not persist and step 4
must be repeated.

**Exercised 2026-08-14 (card `proc-20260814-s5`, from a different worktree than
setup ran in — proof the credentials really live on EAS, not locally):**
`bash deploy/ios_credentials.sh --build` succeeded unattended, build `e67d1247`,
clean log. Artifact:
`https://expo.dev/artifacts/eas/HuTPOLX77F1-MJkIbcK7HKKceWfy8wUwIR7jAl-3jBw.ipa`.
Prerequisite done first: `app.json → ios.runtimeVersion` set to a fixed literal,
decoupled from the shared `expo.version` `ship.sh` bumps for Android (§5 R5 in
`docs/ios-requirements.md`, "vor dem ersten iOS-Build umsetzen").

**Still requires a human Apple ID + 2FA** (these ignore the API key —
`AppStoreApi.js` routes them through `ensureUserAuthenticatedAsync`):
ASC API key management itself, and **push notification keys**. HelmDeck ships
`expo-notifications`, so iOS push will need one interactive session later. It is
not needed for signing or building.

**[NEU] A THIRD thing needs it too, discovered running `eas submit` for the
first time: "ensuring your app exists on App Store Connect".** Even with the
ASC API key exported, `eas submit --platform ios --latest --non-interactive`
dies with *"Set ascAppId in the submit profile (eas.json) or re-run this
command in interactive mode"*; dropping `--non-interactive` doesn't help from
a card either — it prints *"Log in to your Apple Developer account to
continue"* and then the same TTY-less `Input is required, but stdin is not
readable. Failed to display prompt: Apple ID:` as the credential setup's first
run. Unlike certificate/profile creation, this step is **not** unattended-safe
even after a one-time bootstrap — `ensureAscAppAsync` hard-routes through user
auth every time an `ascAppId` isn't already pinned in `eas.json`. Fix once a
human has created the app record in App Store Connect (or logged in
interactively to let eas-cli create it): copy the app's numeric ASC ID into
`app/eas.json → submit.production.ios.ascAppId`, and every later
`eas submit --non-interactive` skips this step entirely.

Both halves of that are verified in eas-cli source, not guessed:
- `submit/ios/AppProduce.js` `createAppStoreConnectAppAsync` calls
  `ensureUserAuthenticatedAsync(...)` **unconditionally** — that is why no
  amount of API-key env gets you past app creation.
- `submit/ios/IosSubmitCommand.js` `resolveAscAppIdentifierAsync`: if
  `profile.ascAppId` is set it returns immediately, never reaching AppProduce.
  The one thing it still runs, `ensureTestFlightSetupForExistingAppAsync`,
  takes the `AuthenticationMode.API_KEY` branch when `hasAscEnvVars()` and
  `EXPO_APPLE_TEAM_ID` are present (and is best-effort/try-catch anyway).

**CDP co-pilot for the human half:** `deploy/asc_guide.py` attaches to the
persistent HelmDeck Chrome (same standard as `daemon/browsercap.py`) so the
owner does only password + 2FA, and the numeric app ID is **read back out of
the live DOM** instead of transcribed by hand:
```bash
py -3.12 deploy/asc_guide.py open    # launch/attach + open App Store Connect
py -3.12 deploy/asc_guide.py where   # url + title + headings (login? app list?)
py -3.12 deploy/asc_guide.py shot    # -> docs/shots/asc.png
py -3.12 deploy/asc_guide.py appid   # the ascAppId for app.helmdeck
```
Creating the record by hand: My Apps → **+** → New App → Platform *iOS*,
Bundle ID `app.helmdeck` (already registered, so it is in the dropdown), a
**globally unique** App Store name, any unique SKU, Full Access.

⚠ **Do not read the result off the Apps page.** Right after the record was
created here, that list still rendered **"No Apps"** — a stale SPA view — while
`GET /v1/apps` already returned the app. Trusting the screen would have meant
re-creating an app that existed. `asc_guide.py apps|appid` therefore query the
App Store Connect **API** with the same `.p8`; the browser verbs exist only to
carry the human through password + 2FA.

### 2c) TestFlight submit — DONE 2026-08-14

```bash
cd app && npx eas-cli submit --platform ios --latest --non-interactive --wait
```
Result: build `e67d1247` → submission `da233c48`, *"Submitted your app to Apple
App Store Connect!"*. Live state:
```bash
py -3.12 deploy/asc_build_state.py --wait   # Apple's own processing verdict
```
That verdict matters: `eas submit` returning only proves the .ipa *reached*
Apple. Processing is a real gate (bad slice / entitlement / Info.plist ⇒
`INVALID`), and with no macOS on this box it is the strongest automated
statement available about the artifact — R2 in
`docs/ios-watch-feasibility.md` still stands, the final "does it launch" is a
human tap on the phone.

**Live values:** ASC app id `6801637667`, bundle `app.helmdeck`, SKU
`helmdeck-001`, primary language German, TestFlight group *Team (Expo)*
(auto-created by eas-cli).

⚠ **The submit key is a THIRD credential slot**, separate from the build
credentials, and it surprised this card: after the app-exists step passes,
eas-cli says *"App Store Connect API Keys cannot be set up in --non-interactive
mode"*. The exported `EXPO_ASC_*` env is **not** consulted here —
`AscApiKeySource.js` only accepts (a) all three of
`ascApiKeyPath`/`ascApiKeyId`/`ascApiKeyIssuerId` in the submit profile, or
(b) a key stored on EAS via `SetUpAscApiKey`, which needs a TTY. Route (a) is
what `eas.json` currently uses, which makes submit **work on this box only** —
registered as debt `ios-submit-local-asc-key`. Route (b) is the portable fix:
one interactive `npx eas-cli credentials -p ios` from cmd.exe, then delete the
three fields.

⚠ `eas init` rewrites `app/app.json` through the expo-config normalizer and adds
hunks you did not ask for — it added an `android.permissions: [CAMERA]` array and
an empty `extra.router` here. Diff `app/app.json` after any `eas` command and keep
only what you meant to change; the CAMERA permission is already delivered by the
`expo-camera` plugin entry.

⚠ Running `eas` from a worktree needs `app/node_modules` — the worktrees never get
their own install. Junction it first (`docs/shots/link.py` is the pattern:
`_winapi.CreateJunction(r"C:\hd\app\node_modules", "<worktree>/app/node_modules")`),
otherwise every `eas` command dies with *"Failed to resolve plugin for module
expo-router"*.

### 2d) TestFlight metadata — Beta App Review Detail, localizations, "What to Test"

Internal testing (this app's fixed scope) needs none of this to distribute a
build, but leaving it empty means a later switch to external testing starts
from zero. Content lives in `docs/store/ASC_METADATA.md` — read section 1
first (export compliance is a legal call, deliberately left to the owner,
not automated) — and is applied via:

```bash
py -3.12 deploy/asc_metadata_draft.py show          # read-only
py -3.12 deploy/asc_metadata_draft.py apply --yes   # writes the draft (PATCH/POST, never submits for review)
```

Same `.env` requirement as `asc_build_state.py`/`asc_guide.py`. Fill in
`contactPhone` in the doc before running `apply` — no phone number is
invented.

---

## 3) Get the APK onto the phone

- **Relay** (served at `https://<relay>/apk/helmdeck.apk`):
  `bash deploy/push_relay.sh` (also ships relay.py + restarts the service), or
  minimal file-only (no restart): scp the apk to the VM and
  `sudo install -m644 helmdeck.apk /opt/helmdeck-apk/helmdeck.apk`.
- **Google Drive**: copy to `G:\My Drive\HelmDeck.apk` (Drive-for-Desktop syncs).

Signature: our APK is signed with `swarmdeck-release.jks`. If that differs from
the currently-installed app, Android says "app not installed" → **uninstall the
old app first** (you re-pair anyway; the relay/pairing keys may have rotated).

---

## 4) Emulator test — verify before shipping (TEST = judged, not assumed)

```bash
adb install -r app-release.apk          # uninstall old first if the signature differs
adb exec-out screencap -p > shot.png    # NOT `adb shell screencap /sdcard/x.png` — Git Bash mangles the /sdcard path
adb shell pm grant app.helmdeck android.permission.CAMERA   # grant a runtime perm directly
adb shell input tap X Y                 # coordinates are ACTUAL device px (1080x2400)
```
The emulator gets ANR-heavy ("Pixel Launcher isn't responding") while the dev
daemon is hammering the CPU — dismiss with the "Wait" button and retry.

---

## 5) Pairing / relay (how the phone reaches the desktop)

- The "desktop" IS your PC's daemon (`swarm.py serve 8140`), fronted by the
  Electron app (`desktop/main.js` — runs the daemon + UI + injects an owner
  token via `#cfg`). Don't run a second supervisor against :8140.
- Phone → zero-knowledge relay (NaCl-sealed frames) → daemon. **"Desktop nicht
  erreichbar" = relay HTTP 503 = the daemon isn't polling the relay** (i.e. the
  daemon/desktop isn't running). Not a pairing problem.
- **Multi-device**: up to 8 devices (`relay.phone_pubs` allowlist); pairing is an
  explicit 15-min single-use window (Settings → Mobile app → "Telefon koppeln" →
  QR / link / code). `unpair` rotates room + keypair (kill switch → every device
  must re-pair).
- Pair from the app: **More → "QR-Code scannen"**, or paste the code, or tap the
  link. The desktop web UI needs a token too; the Electron app injects it, or in
  a browser open `http://localhost:8140/#cfg=<base64{baseUrl,token}>`.
- Gotcha we hit: after pairing, queries that ran BEFORE pairing don't auto-refetch
  → "paired but empty board". The app now invalidates all queries on a successful
  pair; on an old build, just restart the app.

---

## Fast-track policy (make agent cards flow without babysitting)
The gate is fixed (always runs — your safety net), but the human steps are policy:
- `policy.auto_accept_green: true` → green-gated cards auto-accept + merge.
- `policy.auto_dispatch_priority: "high"` → high-prio backlog self-dispatches.
- a deploy hook that runs `deploy/push_update.sh` on accept → auto-OTA on merge.
With all three: file a card → agent works → gate green → auto-merge → auto-deploy,
same as a hand deploy, gate still guarding.

## Fast-track deploy (deploy/ship.sh)
The repo `deploy` hook runs `deploy/ship.sh`: it fingerprints the native-affecting
files and ships JS-only changes via OTA, or on a native change **bumps the
version/runtimeVersion** (so old APKs can't pull incompatible JS), builds the APK
(deploy/build_apk.sh: JDK17 + gradle + emulator smoke + relay distribute) AND
pushes a matching OTA, then commits the version bump. So a fast-track card just
works whether the change is JS or native, and a native change never crash-loops
an un-updated phone.
