# HelmDeck Desktop 0.2.22 (Windows)

## What's new since 0.2.21

- **Fixed: "Relay nicht erreichbar" / "Desktop antwortet nicht" under load.**
  Two causes in the daemon, both measured and fixed: the dashboard re-read
  and re-parsed the whole event log on every poll (now derived once and
  cached on the store's own change signal), and the relay bridge paused for
  up to 12 s every minute while it re-checked the tunnel (now checked in the
  background, the phone path never waits for it).
- **New: the phone path has a visible budget.** Settings > System > Daemon
  shows how often a request breached it in the last 15 minutes, and the
  worst case.
- **Fixed: finished cards left dev servers running for days.** A card's dev
  port is reclaimed when the card is accepted or archived.
- **Clearer error:** a chat message that the desktop could not answer in
  time now says so, instead of blaming network/DNS.

## Do I need to update manually?

No - if you're on 0.2.2 or newer, this installs itself silently on your
next restart (auto-update). This installer is for a first install, or if
you want it immediately.
