# helmdeck-desktop (Tauri prototype of the Electron shell)

A native window around the HelmDeck web app, in Tauri 2. It does what `surfaces/desktop/main.js`
does for the Electron shell, minus the parts the tray took over:

- serves the exported web app (`surfaces/app/dist`) on `http://localhost:3300`, with the Electron
  server's rules: unknown paths fall back to `index.html`, entry documents are never cached, hashed
  assets are immutable, `..` is refused (`src/ui_server.rs`, 4 tests);
- opens ONE window on it and hands the app the daemon URL in the `#cfg` hash, no token;
- exposes `window.helmdeckNative` with the shapes the web app already reads from the Electron
  preload: `getAppInfo`, `pickFolder`, `getLoginItem` / `setLoginItem`, update status ("current");
- opens external links in the real browser; one instance at a time.

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
2. **The first-run setup wizard** (`setup.js`, 920 lines): Python / `claude` CLI checks, the loopback
   control endpoint the onboarding screen uses while the daemon is down.
3. **The full-app updater** (`native-updater.js`, electron-updater). Tauri has its own updater plugin
   with a signing key; the release feed (`helmdeck-release`) would need `latest.json` in its format.
   The UI bundle itself is refreshed by the tray's update thread, not by the shell.
4. **Packaging and signing.** Electron has three pipelines: NSIS (`electron-builder.yml`), MSIX
   (`electron-builder.appx.yml`, `build_msix.ps1`) and Mac App Store (`electron-builder.mas.yml`,
   notarization). `bundle.active` is `false` here: this builds an exe, not an installer.
5. **macOS menu / re-open window** (the App Store rejection fix of 2026-09-27).
6. **Linux / macOS runs.** The code is portable (WebKitGTK / WKWebView; `open_external` and the
   login item have non-Windows branches) but nothing here was built or run off Windows.

Both shells coexist: nothing in `surfaces/desktop/main.js` was touched.
