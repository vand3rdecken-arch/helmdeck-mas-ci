# helmdeck-tray (Rust prototype of tray.py)

Supervises the daemon from the system tray: starts it when the port goes quiet,
adopts one that already serves, shows Daemon/Relay status, opens the web UI,
restarts the daemon, toggles autostart. 1.6 MB exe, ~1.5 MB private memory
(the Python tray: ~11 MB private + pystray/Pillow).

    cargo build --release                      # surfaces/desktop/tray-rs/target/release/helmdeck-tray.exe
    helmdeck-tray --watch-only                 # beside the Python tray / a live daemon: observes, never spawns or stops
    helmdeck-tray                              # supervises for real (starts the daemon when :8140 is quiet)
    helmdeck-tray --once                       # state as JSON (debug build prints; release is a GUI binary)
    helmdeck-tray --dump-icon DIR              # icon-up.png / icon-down.png
    cargo test                                 # 9 tests, incl. spawn/adopt/respawn against a real process

Same contract as tray.py: health by ANY http reply on `/system/health` (never `/`,
which redirects to the web UI - the 2026-08-29 eviction war), adopt before spawn,
daemon log appended to daemon/daemon.out.log. The relay row is read from
helmdeck.db (`workspace_config.relay`), like tray.py does via the daemon's loader.

## Deliberately NOT ported (prototype)

- Desktop-shell auto-update (`desktop_update.py`): the Electron shell is switched off.
- Local relay.py + cloudflared supervision: the Cloudflare Worker serves the relay.
- Autostart REPAIR at start: only the menu item writes the Run key, so merely
  starting the prototype cannot replace the production `HelmDeck` entry.
- Single-instance guard (tray.py has none either).

## Not yet judged

Menu and tooltip were not looked at on screen (the owner was working on the
machine). The icon was rendered to PNG and judged; Windows registered the tray
icon (HKCU\Control Panel\NotifyIconSettings).
