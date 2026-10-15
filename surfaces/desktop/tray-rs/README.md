# helmdeck-tray (the production tray supervisor since 2026-10-15)

Rust port of `tray.py`. Supervises the daemon from the system tray: starts it when
the port goes quiet, adopts one that already serves, shows Daemon/Relay status,
opens the web UI, restarts the daemon, toggles autostart.

    cargo build --release                      # target/release/helmdeck-tray.exe
    helmdeck-tray [--root DIR] [--port N]      # supervise for real
    helmdeck-tray --watch-only                 # beside another tray / a live daemon: observes, never spawns or stops
    helmdeck-tray --once                       # state as JSON (debug build prints; release is a GUI binary)
    helmdeck-tray --dump-icon DIR              # icon-up.png / icon-down.png
    helmdeck-tray --run-for N                  # leave through the quit path after N s (tests, benchmarks)
    cargo test                                 # 11 unit tests, incl. spawn/adopt/respawn against a real process

Same contract as tray.py: health by ANY http reply on `/system/health` (never `/`,
which redirects to the web UI - the 2026-08-29 eviction war), adopt before spawn,
daemon log appended to `daemon.out.log`. The relay row is read from `helmdeck.db`
(`workspace_config.relay`). The daemon's data directory follows
`HELMDECK_DATA_ROOT`, like `daemon/paths.py`. One tray per daemon port (named
mutex, exit code 4 for a second one).

## Operating it

    py -3.12 ops/tools/tray_switch.py status    # who owns autostart, who runs, daemon pid
    py -3.12 ops/tools/tray_switch.py rust      # copy exe to %LOCALAPPDATA%\HelmDeck\tray, set the Run value, swap the running tray
    py -3.12 ops/tools/tray_switch.py python    # the way back: Python tray + its Run value
    python ops/tests/test_rust_tray_e2e.py      # real supervision against a SANDBOX daemon (port 8191, throw-away data root)

Switching never stops the daemon; the new tray adopts it by health. Re-run `rust`
after a rebuild: the exe is COPIED so `cargo clean` cannot empty the autostart.
Starting the Python tray by hand takes autostart back (tray.py repairs the Run value).

## Deliberately NOT ported (debt `rust-tray-no-desktop-update`)

- Desktop-shell auto-update (`desktop_update.py`): the Electron shell is switched off.
- Local relay.py + cloudflared supervision: the Cloudflare Worker serves the relay.
- Autostart REPAIR at start: only the menu item and `tray_switch.py` write the Run key.

## Measured (2026-10-15, side by side against the live daemon, 60 s)

| | Python tray | Rust tray |
|---|---|---|
| private memory | 16.4 MB | 1.9 MB |
| CPU, idle beats | 0.029 % | 0.026 % |
| start to first answer | 0.21 s for the imports alone | 0.02 s |
| on disk | Pillow 15.9 MB plus pystray | 1.6 MB |
| respawn after daemon death | one 4 s beat | 3.5 s (sandbox end to end) |

CPU is a wash. The icon was rendered to PNG and judged and Windows registered the
tray icon; menu and tooltip were not looked at on screen.
