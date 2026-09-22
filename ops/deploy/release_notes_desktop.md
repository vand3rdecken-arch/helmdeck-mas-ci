# HelmDeck Desktop 0.2.24 (Windows)

## What's new since 0.2.23

- **New: the shell exposes its own version.** Settings > System > App & Updates
  can now tell the installed 0.2.x shell apart from the 1.0.x JS bundle, via a
  small IPC call (`native:app-info`) added to the main process and preload.
- **Fixed: the tray's relay stand-down only stopped processes it spawned
  itself.** Once the public relay is served by the Cloudflare Worker, the
  tray now also sweeps a `relay.py` / `cloudflared` it only *adopted* (left
  running by an earlier tray instance or the legacy `relay_local.cmd`
  autostart) - so nothing on this PC keeps listening for the phone after the
  worker takes over.
- **Packaging fix carried over from today's 0.2.23 re-release:** the daemon
  bundle now copies only top-level `.py`/`.md` files, not every nested one -
  closes a leak where local runtime state (memory exports, checkpoints,
  outreach logs) could ride along in the installer.

## Do I need to update manually?

Only for this one - it changes the shell (`main.js`, `tray.py`, the packaging
config), which auto-update cannot apply to itself. Every later 1.0.x-only
change keeps riding the silent auto-update as before.
