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
  "nav.escalations": { de: "Eskalationen", en: "Escalations" },
  "nav.audit": { de: "Audit-Log", en: "Audit log" },
  "esc.sub": { de: "Was Henry entschieden hat - und was noch offen ist.", en: "What Henry decided - and what is still open." },
  "esc.empty": { de: "Keine Eskalationen - der Harness kam allein zurecht.", en: "No escalations - the harness coped on its own." },
  "esc.open": { de: "offen · Versuch {n}/2", en: "open · attempt {n}/2" },
  "esc.decided": { de: "entschieden: {action}", en: "decided: {action}" },
  "esc.demoWhy": { de: "Deploy starb mit dem Daemon-Neustart", en: "Deploy died with the daemon restart" },
  "nav.feedback": { de: "Feedback geben", en: "Give feedback" },

  // "More" tab: group headers + one-line subtitles so every row says what is
  // behind it (the labels alone proved opaque even to the owner).
  "more.grp.control": { de: "Steuerung", en: "Control" },
  "more.grp.logs": { de: "Protokolle", en: "Activity" },
  "more.grp.system": { de: "App & System", en: "App & system" },
  "more.sub.automation": { de: "Regeln & Freigaben: was allein laufen darf", en: "Rules & approvals: what may run on its own" },
  "more.sub.processes": { de: "Mehrstufige Abläufe anlegen und starten", en: "Create and run multi-step workflows" },
  "more.sub.connectors": { de: "Externe Dienste anbinden", en: "Connect external services" },
  "more.sub.history": { de: "Alles, was passiert ist – chronologisch", en: "Everything that happened, in order" },
  "more.sub.escalations": { de: "Was Henry entschieden hat, was offen ist", en: "What Henry decided, what is still open" },
  "more.sub.audit": { de: "Wer was wann getan hat - unveränderlich", en: "Who did what, when - immutable" },
  "more.sub.sessions": { de: "Chat-Verläufe der Agenten", en: "Agent chat transcripts" },
  "more.sub.recordings": { de: "Mitschnitte erledigter Arbeit", en: "Recordings of finished work" },
  "more.sub.settings": { de: "Team, Geräte, Import, Nachtschicht", en: "Team, devices, import, night shift" },
  "more.sub.repo": { de: "Repo-Typ wählen — die Vorlage belegt den Rest vor", en: "Choose the repo type — the template presets the rest" },
  "more.sub.loopmap": { de: "Schaubild: wie Karten durch Gate & Review laufen", en: "Diagram: how cards flow through gate & review" },
  "more.sub.feedback": { de: "Wunsch oder Problem melden", en: "Report a wish or a problem" },
  // The two language OPTIONS, for the generic chip renderer - a schema knob
  // ships option VALUES ("de"), never prose, so the labels live here.
  //
  // NATIVE names, identical in both columns, deliberately: a language picker
  // is the one control a reader may not be able to read, so "English" must say
  // English even to somebody whose UI is German. It also keeps this chip row
  // identical to the workspace-default row right below it in door 1 (which
  // renders from i18n's own LANGS) and to the login screen - judged on a
  // screenshot, where "Deutsch/Englisch" above "Deutsch/English" read as two
  // different controls.
  "lang.de": { de: "Deutsch", en: "Deutsch" },
  "lang.en": { de: "English", en: "English" },
  "more.conn.connectedRelay": { de: "Mit dem Desktop gekoppelt (über Relay)", en: "Paired with the desktop (via relay)" },
  "more.conn.edit": { de: "Ändern", en: "Change" },
  "more.conn.hide": { de: "Fertig", en: "Done" },

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
