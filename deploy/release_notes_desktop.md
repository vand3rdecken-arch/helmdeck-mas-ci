# HelmDeck Desktop 0.2.3 (Windows)

**Fixes the auto-update chain.** The previous installed build was missing the
auto-updater from its packaged app shell (a stale build predating that
feature), so the desktop silently fell behind the phone's UI — a manual sync
was needed to catch it up. This build carries the updater for real.

## What's new since 0.2.2

- **Auto-update chain restored.** Same silent relay-polling mechanism as
  designed for 0.2.2 (check on launch + every 30 min, per-file SHA-256
  verify, apply on quit) - this build actually ships it.
- **Crash-log capture hardened.** The daemon's stdout/stderr log file open
  now retries on a transient sharing violation instead of silently falling
  back to no capture - a healthy daemon could previously run its whole life
  with zero captured output if the very first open attempt lost a race.

## Do I need to update manually?

- **Yes, once** - download and run `HelmDeck-Setup-0.2.3-x64.exe` below.
  After this, future UI updates install themselves; you only re-download
  when the app *shell* itself changes again.

## Install

| File | What |
|---|---|
| `HelmDeck-Setup-0.2.3-x64.exe` | Windows desktop installer |

**Windows + SmartScreen:** the installer is not code-signed yet, so Windows will
warn. *More info → Run anyway.* Verify the download against `SHA256SUMS.txt`.
