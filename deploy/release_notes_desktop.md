# HelmDeck Desktop 0.2.5 (Windows)

**Real auto-updates, finally.** Every previous build could only silently
update its own UI - any change to the app shell itself (like the last two
releases' fixes) needed a manual reinstall. This build adds a second,
independent updater (electron-updater, the same mechanism most desktop apps
use) that downloads and silently reinstalls the WHOLE app, main process
included. This is the **last** manual install, for real this time.

## What's new since 0.2.4

- **Full-app silent auto-update.** On launch and every 30 minutes, the app
  checks GitHub for a newer release, downloads it in the background, and
  installs it automatically the next time you quit - no dialog, no manual
  download, and it now covers shell-level fixes too, not just UI changes.
- **Fixed: the daemon's own log capture.** Root-caused live - `shell:true`
  on Windows doesn't safely quote a multi-word argument passed as an array,
  so the daemon's stdout/stderr redirection was silently corrupted. The app
  now spawns the real python.exe directly, skipping the broken shell hop.

## Do I need to update manually?

**Yes, once more** - download and run `HelmDeck-Setup-0.2.5-x64.exe` below.
After this, every future update - UI or shell - installs itself.

## Install

| File | What |
|---|---|
| `HelmDeck-Setup-0.2.5-x64.exe` | Windows desktop installer |

**Windows + SmartScreen:** the installer is not code-signed yet, so Windows will
warn. *More info → Run anyway.* Verify the download against `SHA256SUMS.txt`.
