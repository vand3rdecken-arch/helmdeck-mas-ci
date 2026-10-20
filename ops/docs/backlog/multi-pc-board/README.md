# Card: one board across several paired PCs

**Origin** 2026-10-20, owner "clear debt" on `daemon-switch-reloads`
(spine/registry/debt.py). The SHORTCUT part of that debt is paid; what is
left is a feature, filed here instead of kept as debt.

## Where it stands

- The app keeps every pairing (`surfaces/app/src/data/config.ts` `saved` /
  `activeId`). Mehr shows the active PC, the others, "Wechseln" and
  "Weiteren PC koppeln".
- Switching reloads the app (`switchDaemon`), the account-switch pattern of
  Slack/Discord: sockets, the LAN direct path and every cached query start
  clean for the chosen PC. Not a shortcut - one daemon per session is the
  model.
- Pushes from a PC that is NOT active are decrypted with that pairing's key
  (`data/push.ts decryptPush` tries every saved `daemonPub`), shown, and a tap
  switches to that PC and lands on the card/room after the reload
  (`setPendingRoute` / `takePendingRoute`).

## What this card would add

A combined view: cards from several PCs on one board, without switching.

1. Query keys namespaced per daemon (`[daemonId, ...]`) - today they are
   global, which is why a switch must clear everything.
2. One relay socket (and LAN probe) per saved daemon instead of one.
3. A board column/filter "PC" and per-card routing of every action to the
   card's own daemon.

## Open question for the owner

Is a combined board wanted at all, or is "switch + pushes from every PC"
enough? Paseo has no multi-host board either.
