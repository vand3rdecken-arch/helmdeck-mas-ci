# HelmDeck desktop (Windows program)

An Electron wrapper that turns HelmDeck into a single Windows program - the same
shape as Paseo's desktop app (`electron` + `electron-builder`, NSIS installer).
Launching it starts the local services and shows the UI in a native window:

- the **Python daemon** (`swarm.py serve`) on `:8140` - the brain + runner
- the **Next.js UI** on `:3300` (proxies `/backend/*` to the daemon)

On quit it kills both. No browser, no terminal - one app.

## Requirements on the target PC

Same as HelmDeck itself (this wrapper doesn't remove them):

- **Python 3.12** - the `py -3.12` launcher (Windows) or `python3`
- the **`claude` CLI** (Claude Code) - the agent runtime cards execute in

(Node is *not* required on the target: the packaged app runs the UI with
Electron's own bundled Node.)

## Run in dev

```
cd desktop
npm install          # downloads Electron (~150 MB, one time)
npm start            # spawns the repo's daemon + `next dev`, opens the window
```

## Build the Windows installer

One command (recommended - handles the winCodeSign workaround automatically):

```
cd desktop
powershell -ExecutionPolicy Bypass -File build-win.ps1
```

Or the raw steps:

```
cd desktop
npm install
npm run dist:win     # 1) next build (standalone)  2) electron-builder --win
```

Output: `desktop/release/HelmDeck-Setup-0.2.0-x64.exe` (NSIS installer -
per-user, lets the user choose the install dir) plus an unpacked app under
`release/win-unpacked/`.

### If the build fails on "Cannot create symbolic link"

electron-builder's `winCodeSign` cache contains macOS symlinks that Windows
won't extract without the symlink privilege. `build-win.ps1` pre-extracts that
cache **without** those symlinks, so it just works. If you build with the raw
`npm run dist:win` instead and hit that error, either turn on **Windows
Developer Mode** (Settings -> Privacy & security -> For developers), run the
build in an **elevated** PowerShell, or just use `build-win.ps1`.

## Auto-update (Paseo mechanism)

The packaged app follows the relay's `desktop` OTA channel silently - Paseo's
desktop auto-update behaviour, taken from the real Paseo source (the referenced
files are cited in `desktop_update.py`): silent check at start + every 30 min,
10 s retry while a download is pending, download + per-file sha256 verify in
the background, silent swap of `resources/app-dist` on quit (revalidated
against the feed, 5 s deadline, no forced relaunch) or at next launch. The
tray supervisor (`tray.py`) runs the same check on the same cadence and swaps
while the window app isn't running, so updates land even if the window is
never opened. Publishing happens automatically in `deploy/push_update.sh`
(so every accept/ship reaches the desktop like it reaches the phone). The
previous bundle is kept as `app-dist.old`; there is no automatic rollback
(Paseo has none either) - swap `.old` back by hand to recover. Dev runs
(`npm start`) never auto-update, exactly like Paseo. Scope is the OTA scope:
the UI bundle. A change to the shell itself (`main.js`, `setup.js`,
electron-builder config) still needs the installer - the same line the phone
draws between an OTA and a native APK.

## Notes

- **Icon**: drop a `assets/icon.ico` (>=256px) and uncomment `win.icon` in
  `electron-builder.yml` to brand the installer; until then the default Electron
  icon is used.
- **Secrets/data are never bundled** - `settings.json`, `users.json`, the DB,
  recordings, checkpoints, chat logs and attachments are all excluded; they are
  created fresh on the user's machine at first run.
- **Fully self-contained Python** (removing the Python-3.12 requirement) would
  mean freezing the daemon with PyInstaller into a `swarmd.exe` and bundling that
  instead of the source - a follow-up, not needed while the target already has
  Claude Code + Python.
