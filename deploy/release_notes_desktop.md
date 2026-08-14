# HelmDeck Desktop 0.2.4 (Windows)

**Fixes reinstalls breaking pairing.** Installing 0.2.3 over an existing
install reset the app's resources folder and wiped the hand-set redirect to
the real daemon - the app silently fell back to a fresh, unpaired sandbox
daemon ("Desktop nicht erreichbar" on phone and web, no error shown). This
build closes that for good.

## What's new since 0.2.3

- **The daemon-dir pointer now survives reinstalls.** It lives in Electron's
  userData folder (untouched by the installer) instead of the resources
  folder (replaced on every install). A pointer from a prior install
  migrates automatically on first launch of this build - no manual fix
  needed again after this.
- **Crash-log capture no longer goes dark on a stuck handle.** If the
  daemon's log file is held by a lingering process in a way that denies new
  opens, the app now logs to a PID-suffixed file instead of silently losing
  all output until a reboot.

## Do I need to update manually?

**Yes, once** - download and run `HelmDeck-Setup-0.2.4-x64.exe` below. This
is also the LAST time a reinstall risks breaking pairing - from this build
on, the pointer survives every future install.

## Install

| File | What |
|---|---|
| `HelmDeck-Setup-0.2.4-x64.exe` | Windows desktop installer |

**Windows + SmartScreen:** the installer is not code-signed yet, so Windows will
warn. *More info → Run anyway.* Verify the download against `SHA256SUMS.txt`.
