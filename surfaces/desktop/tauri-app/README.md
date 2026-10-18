# helmdeck-desktop (Tauri prototype of the Electron shell)

A native window around the HelmDeck web app, in Tauri 2. It does what `surfaces/desktop/main.js`
does for the Electron shell, minus the parts the tray took over:

- serves the exported web app (`surfaces/app/dist`) on `http://localhost:3300`, with the Electron
  server's rules: unknown paths fall back to `index.html`, entry documents are never cached, hashed
  assets are immutable, `..` is refused (`src/ui_server.rs`, 4 tests);
- opens ONE window on it and hands the app the daemon URL in the `#cfg` hash, no token;
- exposes `window.helmdeckNative` with the shapes the web app already reads from the Electron
  preload: `getAppInfo`, `pickFolder`, `getLoginItem` / `setLoginItem`, update status ("current");
- opens external links in the real browser; one instance at a time;
- runs the first-run setup control plane (`src/setup.rs`, port 8141, per-launch nonce in the `#cfg` hash):
  `/setup/state`, `/log`, `/engines`, `/provision` with the shapes the web app reads from `setup.js`.
  Provisions Claude Code (npm install -g, winget Node, hidden `claude auth login` with a 5-min poll),
  detects Python, starts the daemon. 12 tests, incl. nonce refusal and probe caching.

    cd surfaces/desktop/tauri-app
    cargo build --release                         # target/release/helmdeck-desktop.exe, 7 MB
    cargo test                                    # 8 tests
    py -3.12 ops/tests/test_tauri_desktop_e2e.py  # a REAL WebView2 window, no mocks

`HELMDECK_APP_DIST` points it at another web bundle; otherwise it looks for `app-dist` next to the
exe, then `surfaces/app/dist` of the checkout, then the folder an installed Electron shell keeps.

## Measured (2026-10-16)

| | Electron shell | Tauri window |
|---|---|---|
| program file | ~170 MB installed | 7 MB |
| private memory, window open, incl. all child processes | ~430 MB (measured earlier when it ran) | 129 MB (7 processes) |

The saving is real but not the 1 : 10 it sounds like: WebView2 is Chromium too, so the page still
costs a renderer (49 MB) and a GPU process (19 MB). What disappears is the second copy of
Chromium and Node.

## Security: least privilege, tested

The page may call exactly four commands, and only from `localhost:3300`
(`build.rs` declares them, `capabilities/default.json` grants them, nothing else: no core
permissions, no plugin permissions). The end-to-end test tries seven other commands from the page
(dialog open/save, window close, create webview, event listen, app hide, an unknown one) and
requires every one to be refused. Found by that test: without the per-command permission Tauri 2
refuses even the four bridge calls ("not allowed by ACL").

## NOT ported (what an Electron replacement still needs)

1. **Starting/supervising the daemon.** The tray owns that. The window only adopts.
2. **The rest of the setup wizard.** Ported: endpoints, probes, Claude install + login, daemon start.
   Python: bundled runtime first, else the embeddable CPython is fetched + unpacked (real download tested)
   and its `_pth` pinned to the daemon root. NOT ported: the `claude -p` hand-offs (Python fallback,
   daemon diagnosis), optional engine installs (status only), the Microsoft Store variant, the
   mac/linux login terminal. The e2e check of the control plane needs ports 8141/3300 free (it skips
   while the Electron app runs).
3. **The full-app updater: built** (`src/updater.rs`, tauri-plugin-updater). States are the ones the web
   app renders; a check at start and every 30 min downloads in the background, "restart now" installs.
   Every update is verified against the public key in `tauri.conf.json`; the private key is OUTSIDE the repo
   (`%USERPROFILE%\.helmdeck-keys`, password DPAPI-protected). Status is pushed into the page, not polled.
   Feed: `latest.json` on the fixed `tauri-feed` tag of `helmdeck-release` (below).
   `py -3.12 ops/deploy/release_tauri.py --version x.y.z [--publish]` builds the signed NSIS installer
   (4.8 MB). The UI bundle itself is refreshed by the tray's update thread, not by the shell.
4. **Packaging and signing.** NSIS is built now (see 3). Not done: Windows code signing (SmartScreen warns on a
   fresh install), MSIX and the Mac App Store. Electron has three pipelines: NSIS (`electron-builder.yml`), MSIX
   (`electron-builder.appx.yml`, `build_msix.ps1`) and Mac App Store (`electron-builder.mas.yml`,
   notarization). `bundle.active` is `false` here: this builds an exe, not an installer.
5. **macOS menu / re-open window** (the App Store rejection fix of 2026-09-27).
6. **Linux / macOS runs.** The code is portable (WebKitGTK / WKWebView; `open_external` and the
   login item have non-Windows branches) but nothing here was built or run off Windows.

Both shells coexist: nothing in `surfaces/desktop/main.js` was touched.

## Update feed (decided 2026-10-18: a fixed tag)

`tauri.conf.json` points at `.../releases/download/tauri-feed/latest.json`: a FIXED tag of `helmdeck-release`, not
"latest". The Electron feed follows the newest release of the same repo, so Tauri installers go to their own
`v<version>` releases (`--latest=false`) and only `latest.json` on `tauri-feed` is replaced each time
(`ops/deploy/release_tauri.py --publish`; not run yet).

## Microsoft Store build (2026-10-18)

    py -3.12 ops/deploy/build_msix_tauri.py --version 0.3.0      # unsigned .msix, 10.5 MB; never submits

Store mode is DERIVED from the runtime (`store.rs`: the process has a package identity), never configured:
no self-update (the Store updates the package), setup only DETECTS prerequisites (policy 10.2.4: no npm,
winget or Python download), the daemon's data lives in `%LOCALAPPDATA%\HelmDeck\daemon-data` (the package is
read-only), and the window starts the daemon itself (adopt if one answers, else spawn it detached with
pythonw). The package carries the electron-builder ALLOWLIST (209 source files + the web app) and the
build refuses to package if a secret-shaped file is staged (`ops/tests/test_msix_tauri_allowlist.py`).
Identity comes from the git-ignored `surfaces/desktop/build/appx-identity.json`.

Not verified yet: a packaged run on a real install (needs Developer Mode for `Add-AppxPackage -Register`, or a
signed package); the "start at login" toggle in a Store install (debt `tauri-store-startuptask`).
