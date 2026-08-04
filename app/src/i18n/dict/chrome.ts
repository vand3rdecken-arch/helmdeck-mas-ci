import type { Dict } from "../index";

/** Navigation, lanes, statuses, priorities - the vocabulary that appears on
 *  every screen. This is where the old mix was most visible: German prose under
 *  English tabs ("Needs you") and English lane/status words. */
export const chrome: Dict = {
  // tabs / navigation
  "nav.board": { de: "Board", en: "Board" },
  "nav.needsYou": { de: "Wartet auf dich", en: "Needs you" },
  "nav.dashboard": { de: "Übersicht", en: "Dashboard" },
  "nav.more": { de: "Mehr", en: "More" },
  "nav.processes": { de: "Prozesse", en: "Processes" },
  "nav.recordings": { de: "Aufnahmen", en: "Recordings" },
  "nav.sessions": { de: "Sitzungen", en: "Sessions" },
  "nav.history": { de: "Verlauf", en: "History" },
  "nav.connectors": { de: "Connectoren", en: "Connectors" },
  "nav.automation": { de: "Automatik", en: "Automation" },
  "nav.settings": { de: "Einstellungen", en: "Settings" },
  "nav.chat": { de: "Chat", en: "Chat" },

  // lanes (defaults; policy.lane_labels still overrides per workspace)
  "lane.backlog": { de: "Backlog", en: "Backlog" },
  "lane.working": { de: "In Arbeit", en: "Working" },
  "lane.review": { de: "Review", en: "Review" },
  "lane.done": { de: "Fertig", en: "Done" },

  // card status
  "status.queued": { de: "wartet", en: "queued" },
  "status.running": { de: "läuft", en: "running" },
  "status.gating": { de: "Gate läuft…", en: "gate running…" },
  "status.needsYou": { de: "wartet auf dich", en: "needs you" },
  "status.bounced": { de: "abgelehnt", en: "bounced" },
  "status.submitted": { de: "eingereicht", en: "submitted" },
  "status.accepted": { de: "abgenommen", en: "accepted" },

  // priority
  "prio.urgent": { de: "dringend", en: "urgent" },
  "prio.high": { de: "hoch", en: "high" },
  "prio.medium": { de: "mittel", en: "medium" },
  "prio.low": { de: "niedrig", en: "low" },

  // shared verbs / generic UI
  "ui.cancel": { de: "Abbrechen", en: "Cancel" },
  "ui.save": { de: "Speichern", en: "Save" },
  "ui.delete": { de: "Löschen", en: "Delete" },
  "ui.remove": { de: "Entfernen", en: "Remove" },
  "ui.open": { de: "Öffnen", en: "Open" },
  "ui.close": { de: "Schließen", en: "Close" },
  "ui.back": { de: "Zurück", en: "Back" },
  "ui.retry": { de: "Nochmal", en: "Retry" },
  "ui.error": { de: "Fehler", en: "Error" },
  "ui.empty": { de: "leer", en: "empty" },
  "ui.loading": { de: "lädt…", en: "loading…" },
  "ui.create": { de: "Anlegen", en: "Create" },
  "ui.language": { de: "Sprache", en: "Language" },
  "ui.offline": { de: "Desktop nicht erreichbar – läuft HelmDeck?",
                  en: "Desktop unreachable – is HelmDeck running?" },

  // Render-crash boundary (app/_layout.tsx). It renders ABOVE the providers, so
  // it must translate through the hook-free t() from i18n/core - useT() would
  // need the QueryClient that is not mounted yet at that point.
  "err.updateNeeded": { de: "App-Update nötig", en: "App update required" },
  "err.generic": { de: "Etwas ist schiefgelaufen", en: "Something went wrong" },
  "err.updateBody": {
    de: "Diese App-Version ist älter als das aktuelle Update. Bitte installiere die neueste HelmDeck-App (Google Drive / Store) und öffne sie neu.",
    en: "This app version is older than the current update. Please install the latest HelmDeck app (Google Drive / Store) and open it again.",
  },
  "err.unknown": { de: "Unbekannter Fehler", en: "Unknown error" },
  "err.retry": { de: "Erneut versuchen", en: "Try again" },
};
