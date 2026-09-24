# HelmDeck Desktop 0.2.25 (Windows + macOS)

## What's new since 0.2.24

- **The phone connection no longer polls.** The daemon keeps ONE hibernating
  WebSocket to its relay room, and the phone joins the same room with its own.
  Board and chat changes are pushed the moment they happen instead of being
  asked for on a timer, requests travel the socket instead of costing one
  relay request each, and an idle PC costs the relay nothing - measured: zero
  relay invocations for keepalives. This is what cut the phone off on
  2026-09-23, when polling tripped the relay's request limit with a single
  user. HTTP and long-poll stay as automatic fallbacks.
- **Exactly one daemon per machine, enforced by Windows itself.** Two
  supervisors could each start a daemon in the same second and both would
  serve the same port, each with its own relay bridge. A named system lock
  now decides, and the second one exits cleanly. Only an explicit restart may
  replace a running daemon.
- **Builds no longer starve the phone.** Agent work (and every build it
  starts) runs at below-normal priority, so an Android build can no longer
  make the daemon too slow to answer your phone.
- **Henry's safety snapshot no longer commits over your work.** The rollback
  point before a hands-on turn is now a detached snapshot; your uncommitted
  changes stay uncommitted and keep their own commit messages.
- **Connection check on the phone.** Settings > Mobile app > Test connection
  names which part is down - the phone's network, the relay, the PC, or the
  pairing - instead of one generic "relay unreachable".
- **Henry pushes stalled work.** Once a day he asks what to start or drop
  when filed work is not moving, goal first, instead of a nightly plan.

## Do I need to update manually?

Yes, for this one - the daemon that ships inside the installer changed
(relay bridge, single-daemon lock, priorities), and auto-update only swaps
the UI. If your desktop app points at a source checkout (developer setup),
it already runs this code.
