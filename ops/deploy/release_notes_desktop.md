# HelmDeck Desktop 0.2.6 (Windows)

**First release delivered by the new auto-updater itself.** If you're
reading this from inside the app without having downloaded anything, it
worked - 0.2.5's electron-updater picked this up silently.

## What's new since 0.2.5

- **Fixed: cascading console windows during a slow daemon boot.** The
  connect screen polled for Python/Claude every few seconds while the
  daemon was starting; each poll re-probed by shelling out, and a
  shell-fallback bug made it worse - together these could pop a fresh
  empty console window every ~3 seconds during a long boot (a worktree
  sweep), stacking dozens across the desktop. Probes are now cached once
  successful, and the shell fallback only fires on a genuinely missing
  executable, never a normal nonzero exit.

## Do I need to update manually?

No - if you're on 0.2.5 or newer, this installs itself silently on your
next app quit. `HelmDeck-Setup-0.2.6-x64.exe` below is only for anyone
still on an older build.
