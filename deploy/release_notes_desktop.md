# HelmDeck Desktop 0.2.2 (Windows)

**The desktop app now auto-updates.** This is the change that closes the gap
the 0.2.1 notes flagged ("the desktop app has no auto-update channel"). From
this build on, HelmDeck desktop follows the same relay update channel the phone
already uses — so you install this **once by hand**, and every future UI update
arrives silently.

## What's new since 0.2.1

- **Silent auto-update (Paseo mechanism).** On launch and every 30 minutes the
  app quietly checks the relay for a newer UI bundle, downloads and verifies it
  (per-file SHA-256), and applies it on the next quit — no reinstall. The
  always-on tray supervisor does the same even when the window is closed, and
  shows a passive **Update: …** line in its menu.
- **Safe by construction.** An update is applied only after every file matches
  the signed manifest; the previous bundle is kept as `app-dist.old` as a
  manual rollback reserve. A failed check is silent and simply retried.

## Do I need to update manually?

- **On 0.2.1 or older:** yes, once — download and run `HelmDeck-Setup-0.2.2-x64.exe`
  below. The auto-updater lives in the app shell, which an update channel can't
  replace (same reason a phone needs a new APK for native changes).
- **On 0.2.2 or newer:** no — future UI updates install themselves. You only
  re-download when the app *shell* itself changes (a new installer release).

## Install

| File | What |
|---|---|
| `HelmDeck-Setup-0.2.2-x64.exe` | Windows desktop installer |

**Windows + SmartScreen:** the installer is not code-signed yet, so Windows will
warn. *More info → Run anyway.* Verify the download against `SHA256SUMS.txt`.
