# Desktop + macOS: only urgent installer updates

Owner 2026-10-21: prepare the desktop and macOS apps so a new installer is needed
only for urgent things. Sibling of native-release-diet (phone/watch).

## Measured state (2026-10-21)

Shell = Tauri since 2026-10-20 (surfaces/desktop/tauri-app). One installer carries:
the window (Rust), the web app (app-dist), the DAEMON PYTHON SOURCES (spine/cells,
181 files), the tray exe and the relay bridge.

| What changes                    | How it reaches users today                        | Installer needed? |
|---------------------------------|---------------------------------------------------|-------------------|
| UI / web app (app-dist)         | relay OTA channel `desktop` (desktop.json), tray update thread, sha256-verified swap, app-dist.old kept | no |
| Daemon Python (spine/cells)     | NOTHING - only inside the installer               | YES |
| Window / tray / bridge (Rust)   | Tauri full-app updater, `latest.json` on tag `tauri-feed` (helmdeck-release), minisign-verified | new build, but silent for direct installs |
| Microsoft Store (MSIX)          | store.rs derives "package identity" -> no self-update | certification per release |
| Mac App Store (.pkg)            | no self-update                                    | App Review per release |
| macOS Developer ID DMG          | Tauri updater (universal, signed, notarized)       | notarize per release (CI) |

## The gap

Every daemon fix is an installer release, although only the Python changed. For the
direct installs (NSIS, Developer ID DMG) that is a silent full-app update; for the
two Store variants it is a submission. That is what drives desktop releases.

## Plan

1. DAEMON CODE OTA for the direct installs: ship the allowlisted daemon sources as a
   signed archive next to the web bundle. The tray stages it, verifies, swaps
   when the daemon is quiet (existing rule for app-dist), keeps `.old`, restarts the
   daemon. Same stage/verify/swap discipline as desktop_update.py, one owner.
   AUTHENTICITY IS NOT OPTIONAL here: a sha256 list served by the relay proves
   integrity, not origin; a compromised relay or feed would push code to every
   machine. Sign the archive with the existing Tauri updater key (minisign,
   private key outside the repo, signing happens on this PC like
   release_tauri_mac.py) and verify against the public key already pinned in
   tauri.conf.json.
2. STORE VARIANTS stay frozen: Apple 2.5.2 / Microsoft policy forbid
   downloading executable code, so the OTA is OFF whenever store.rs says "Store
   mode" (derived, never configured). Store builds are cut only for urgent fixes
   and the yearly forced dates (Xcode/SDK for MAS, Windows SDK policy).
3. KEEP THE SHELL THIN so the full-app updater is rare: window, tray, bridge only
   carry mechanics; wording, layout, thresholds stay in web/daemon (same rule as
   the phone and the watch).
4. Release rhythm: direct installs via the Tauri updater whenever the Rust shell
   changes (rare); Store variants quarterly at most plus urgent.

## DECISION 2026-10-21: leave desktop as is

Owner: "lassen wir Desktop so". No daemon-code OTA, no Windows Authenticode, no change
to the channels. Both store listings (Microsoft Store, Mac App Store) are KEPT; their
updates are urgent-only plus the yearly forced dates. Kept for later, not scheduled:
signed daemon-code OTA for direct installs (plan above), Windows Authenticode for the
direct download (certificate or cloud signing, cost not checked). Python stays the
daemon language (measured problems were design, not language; rewrite refused).

## Open / decisions (historical, superseded by the decision above)

- Build step 1 (signed daemon-code OTA)? It touches the update path of a
  load-bearing process and the signing flow; needs the key on this PC.
- Whether the two Store variants are still wanted (each is a recurring review).
- Nothing here changes the running app until a release carries it: the OTA
  client itself ships in the installer.
