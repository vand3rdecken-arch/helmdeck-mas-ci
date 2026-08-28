import type { Dict } from "../core";

/** Transport + pairing. These live in data/client.ts and data/config.ts, which
 *  run outside React, so they translate through the plain `t()` from ../core.
 *  Every failure mode keeps its own message - "offline", "timeout", "wrong
 *  keys" and "no network" need different actions from the owner. */
export const net: Dict = {
  "net.relayUnreachable": {
    de: "Relay nicht erreichbar (Netzwerk/DNS)",
    en: "Relay unreachable (network/DNS)",
  },
  "net.desktopOffline": {
    de: "Desktop offline – das Relay erreicht den Daemon nicht",
    en: "Desktop offline – the relay cannot reach the daemon",
  },
  "net.desktopTimeout": {
    de: "Desktop antwortet nicht (Timeout)",
    en: "Desktop is not answering (timeout)",
  },
  "net.desktopSilent": { de: "Desktop antwortet nicht", en: "Desktop is not answering" },
  "net.relayError": { de: "Relay-Fehler {status}", en: "Relay error {status}" },
  "net.httpError": { de: "Fehler {status} ({method} {path})",
                     en: "Error {status} ({method} {path})" },
  "net.badKeys": {
    de: "Verschlüsselung passt nicht – Telefon neu koppeln (Desktop: Settings → Mobile app)",
    en: "Encryption mismatch – pair the phone again (desktop: Settings → Mobile app)",
  },
  "net.lanFailed": {
    de: "Direktverbindung (LAN) fehlgeschlagen – läuft HelmDeck am Desktop?",
    en: "Direct (LAN) connection failed – is HelmDeck running on the desktop?",
  },
  // ---- push notification actions (data/push.ts's reportActionFailure -
  // a tap on a notification action runs opensAppToForeground:false, so a
  // failure has NO OTHER surface than raising it as its own notification) ----
  "push.actionFailedGeneric": { de: "Konnte nicht gesendet werden.", en: "Could not be sent." },
  "push.actionFailedTitle": { de: "HelmDeck – nicht ausgeführt", en: "HelmDeck – not carried out" },
  "net.lanTimeout": {
    de: "Direktverbindung antwortet nicht (Timeout) – läuft HelmDeck am Desktop?",
    en: "Direct connection is not answering (timeout) – is HelmDeck running on the desktop?",
  },

  // pairing codes
  "pair.empty": { de: "Kein Code eingegeben.", en: "No code entered." },
  "pair.badFormat": {
    de: "Das ist kein Pairing-Code (Format ungültig) – Code/Link vollständig kopieren.",
    en: "That is not a pairing code (invalid format) – copy the whole code/link.",
  },
  "pair.incomplete": {
    de: "Code unvollständig ({missing} fehlt) – am Desktop neu erzeugen.",
    en: "Code incomplete ({missing} missing) – generate a new one on the desktop.",
  },
  "pair.partRelayUrl": { de: "Relay-URL", en: "relay URL" },
  "pair.partRoom": { de: "Room", en: "room" },
  "pair.partKey": { de: "Schlüssel", en: "key" },
};
