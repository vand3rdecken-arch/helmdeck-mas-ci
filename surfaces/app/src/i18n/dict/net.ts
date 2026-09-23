import type { Dict } from "../core";

/** Transport + pairing. These live in data/client.ts and data/config.ts, which
 *  run outside React, so they translate through the plain `t()` from ../core.
 *  Every failure mode keeps its own message - "offline", "timeout", "wrong
 *  keys" and "no network" need different actions from the owner. */
export const net: Dict = {
  // ---- connection check (data/connection_check.ts, ui/connection_check.tsx) --
  // Owner 2026-09-23: "Haupt problem ist fehlender Diagnose". One line per leg,
  // each naming WHO is broken and WHAT the owner can do - the old single
  // "Relay unreachable" covered three different causes in one day.
  "check.title": { de: "Verbindung testen", en: "Test connection" },
  "check.run": { de: "Testen", en: "Run test" },
  "check.running": { de: "Teste…", en: "Testing…" },
  "check.leg.network": { de: "Netz des Handys", en: "Phone network" },
  "check.leg.relay": { de: "Relay", en: "Relay" },
  "check.leg.daemon": { de: "Daemon am Raum", en: "Daemon on the room" },
  "check.leg.e2e": { de: "Verschlüsselte Anfrage", en: "Sealed request" },
  "check.networkOk": { de: "erreicht {0}", en: "reaches {0}" },
  "check.networkFail": {
    de: "Das Handy erreicht den Relay nicht. WLAN/Mobilfunk, DNS oder eine veraltete Relay-Adresse.",
    en: "The phone cannot reach the relay: WiFi/cellular, DNS, or a stale relay address.",
  },
  "check.relayOk": { de: "antwortet", en: "answering" },
  "check.relayFail": {
    de: "Der Relay antwortet, aber fehlerhaft. Das ist nichts, was du am Handy lösen kannst.",
    en: "The relay answers, but with an error. Nothing you can fix from the phone.",
  },
  "check.daemonOk": { de: "holt Anfragen ab", en: "is pulling requests" },
  "check.daemonOffline": {
    de: "Kein Daemon an deinem Raum. Läuft HelmDeck am PC? (Neustart dauert ~1 Minute.)",
    en: "No daemon on your room. Is HelmDeck running on the PC? (A restart takes ~1 minute.)",
  },
  "check.daemonProbeFail": { de: "Prüfung fehlgeschlagen", en: "probe failed" },
  "check.e2eOk": { de: "beantwortet", en: "answered" },
  "check.e2eFail": {
    de: "Der Daemon ist da, aber die Anfrage scheitert - meist passen die Schlüssel nicht mehr. Neu koppeln.",
    en: "The daemon is there but the request fails - usually stale keys. Pair again.",
  },
  "check.skipped": { de: "übersprungen", en: "skipped" },
  "check.notPaired": {
    de: "Kein Relay eingerichtet - dieses Gerät ist nicht gekoppelt.",
    en: "No relay configured - this device is not paired.",
  },
  "check.verdict.ok": { de: "Alles in Ordnung.", en: "All good." },
  "check.verdict.network": { de: "Es liegt am Netz dieses Handys.", en: "It is this phone's network." },
  "check.verdict.relay": { de: "Es liegt am Relay.", en: "It is the relay." },
  "check.verdict.daemon": { de: "Es liegt am PC - dort läuft kein Daemon.", en: "It is the PC - no daemon is running." },
  "check.verdict.e2e": { de: "Es liegt an der Kopplung dieses Geräts.", en: "It is this device's pairing." },

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
  // OUR client-side abort before the relay itself answered - distinct from
  // desktopTimeout (a 504 the relay sent us after ITS OWN wait) so the owner
  // can tell "relay is stuck" from "relay says the desktop is stuck".
  "net.relayTimeout": {
    de: "Relay antwortet nicht (Timeout)",
    en: "Relay is not answering (timeout)",
  },

  // ---- outbox (ui/outbox_strip.tsx): messages that never reached the daemon.
  // They are kept on disk instead of vanishing with the screen, so "offline"
  // costs a tap, not the message. ----
  "outbox.notSent": { de: "Nicht gesendet", en: "Not sent" },
  "outbox.tries": { de: "{n} Versuche", en: "{n} attempts" },
  "outbox.retry": { de: "Erneut senden", en: "Send again" },
  "outbox.discard": { de: "Verwerfen", en: "Discard" },
  "outbox.more": { de: "+{n} weitere nicht gesendet", en: "+{n} more not sent" },

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
