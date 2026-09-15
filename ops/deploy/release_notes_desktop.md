# HelmDeck Desktop 0.2.21 (Windows)

## What's new since 0.2.18

- **Fixed: fresh installs since 0.2.20 failed to start the daemon**
  (`No module named nacl`) - `daemon/requirements.txt` never declared
  `pynacl`, which the relay's end-to-end encryption needs.
- **Fixed: preload.js was missing from the packaged app**, which could
  show a black window on a fresh install with no explanation. The
  packaged build now ships it, and a failed preload now shows a
  diagnostic page instead of a blank screen.
- **New: native folder picker for the onboarding "repo path" step.**
  Browse for your project folder instead of typing the path by hand.

## Do I need to update manually?

No - if you're on 0.2.2 or newer, this installs itself silently on your
next restart (auto-update). This installer is for a first install, or if
you want it immediately.
