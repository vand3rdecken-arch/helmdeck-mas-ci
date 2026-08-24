import type { Dict } from "../index";

/** Demo mode — the "try it without your own machine" path. HelmDeck is a
 *  companion app, so an unpaired visitor otherwise only ever sees a pairing
 *  wall and cannot judge the product. See data/demo.ts.
 *
 *  The SAMPLE BOARD lives here too, not as literals in the fixture: it is copy
 *  the user reads, so it follows the language switch like everything else. */
export const demo: Dict = {
  // ---- chrome ---------------------------------------------------------------
  "demo.cta": { de: "Ohne eigenen Rechner ausprobieren",
                en: "Try it without your own computer" },
  "demo.ctaHint": {
    de: "HelmDeck steuert deine eigene Installation. Noch keine da? Sieh dir das Board mit Beispieldaten an.",
    en: "HelmDeck drives your own installation. Don't have one yet? Explore the board with sample data.",
  },
  "demo.banner": { de: "Demo-Modus · Beispieldaten, kein echter Rechner",
                   en: "Demo mode · sample data, no real machine" },
  "demo.exit": { de: "Beenden", en: "Exit" },
  "demo.pairInstead": { de: "Jetzt koppeln", en: "Pair now" },

  // ---- sample board ---------------------------------------------------------
  "demo.client": { de: "Demo GmbH", en: "Demo Ltd" },
  "demo.project": { de: "Demo-Projekt", en: "Demo project" },

  "demo.c1.task": { de: "Rechnungs-PDF pro Kunde automatisch erzeugen",
                    en: "Generate an invoice PDF per client automatically" },
  "demo.c1.reply": { de: "Abgenommen. PDF-Export läuft, Gate grün.",
                     en: "Accepted. PDF export works, gate green." },
  "demo.c2.task": { de: "Login: Passwort-Reset per E-Mail",
                    en: "Login: password reset by email" },
  "demo.c2.reply": { de: "Fertig zur Abnahme — Reset-Flow inkl. Ablauf nach 30 Minuten.",
                     en: "Ready for review — reset flow with a 30-minute expiry." },
  "demo.c3.task": { de: "Dashboard: Umsatz nach Monat als Balken",
                    en: "Dashboard: revenue per month as bars" },
  "demo.c3.reply": { de: "Baue die Aggregation, danach die Chart-Komponente.",
                     en: "Building the aggregation, then the chart component." },
  "demo.c4.task": { de: "Soll ich die alten Exporte migrieren?",
                    en: "Should I migrate the old exports?" },
  "demo.c4.reply": {
    de: "Rückfrage: Die Altdaten haben zwei Formate (v1 CSV, v2 JSON). Soll ich beide migrieren oder nur v2?",
    en: "Question: the legacy data has two formats (v1 CSV, v2 JSON). Migrate both, or only v2?",
  },
  "demo.c5.task": { de: "Onboarding-Mail an neue Nutzer",
                    en: "Onboarding email for new users" },
  "demo.c6.task": { de: "Fehler: Suche ignoriert Umlaute",
                    en: "Bug: search ignores accented characters" },

  "demo.gate.tests": { de: "Tests {n}/{n} grün", en: "tests {n}/{n} green" },
  "demo.gate.lint": { de: "Lint sauber", en: "lint clean" },
  "demo.gate.types": { de: "Typen sauber", en: "types clean" },
  "demo.merge.report": { de: "in main gemerged, deployed", en: "merged into main, deployed" },

  // ---- sample transcript ----------------------------------------------------
  "demo.step.started": { de: "Karte gestartet · Worktree angelegt",
                         en: "Card started · worktree created" },
  "demo.step.startedShort": { de: "Karte gestartet", en: "Card started" },
  "demo.c3.s1": { de: "Ich schaue mir erst das Datenmodell an, bevor ich die Aggregation schreibe.",
                  en: "Let me read the data model before writing the aggregation." },
  "demo.c3.s2": {
    de: "Die Monatsaggregation gibt es schon in metrics.py. Ich baue darauf auf, statt sie zu duplizieren, und ergänze nur die Gruppierung nach Monat.",
    en: "The monthly aggregation already exists in metrics.py. I'll build on it instead of duplicating it and only add the per-month grouping.",
  },
  "demo.c3.s3": { de: "Balken rendern. Als Nächstes die Achsenbeschriftung und ein Test.",
                  en: "Bars render. Next the axis labels and a test." },
  "demo.c2.s1": { de: "Reset-Token mit 30-Minuten-Ablauf, einmalig einlösbar.",
                  en: "Reset token with a 30-minute expiry, single use." },
  "demo.c2.s2": { de: "Fertig zur Abnahme.", en: "Ready for review." },
  "demo.c2.gate": { de: "Gate grün · Tests 18/18 · Lint sauber · Typen sauber",
                    en: "Gate green · tests 18/18 · lint clean · types clean" },
  "demo.readResult": { de: "{n} Zeilen gelesen", en: "{n} lines read" },
  "demo.hitsResult": { de: "{n} Treffer in {f} Dateien", en: "{n} hits in {f} files" },
  "demo.filesResult": { de: "{n} Dateien", en: "{n} files" },
  "demo.testsResult": { de: "18 bestanden", en: "18 passed" },

  // ---- sample PM plan (the triage-first dashboard) --------------------------
  "demo.pm.goal": { de: "MVP in den Play Store: Board, Chat und Abnahme rund",
                    en: "MVP into the Play Store: board, chat and review polished" },
  "demo.pm.m1": { de: "Passwort-Reset abnehmen", en: "Accept the password reset" },
  "demo.pm.m2": { de: "Umsatz-Dashboard fertigstellen", en: "Finish the revenue dashboard" },
  "demo.pm.m3": { de: "Play-Store-Release", en: "Play Store release" },
  "demo.pm.n1": { de: "Passwort-Reset reviewen & abnehmen", en: "Review & accept the password reset" },
  "demo.pm.n2": { de: "Rückfrage zur Migration beantworten", en: "Answer the migration question" },
  "demo.pm.n3": { de: "Store-Listing-Texte schreiben", en: "Write the store listing copy" },
  "demo.pm.feasNote": { de: "Kalendergebunden: Abnahme-Slots nur werktags.",
                        en: "Calendar-bound: review slots on weekdays only." },

  // ---- sample chat / replies ------------------------------------------------
  "demo.chat.q": { de: "Wie stehen wir diese Woche?", en: "How are we doing this week?" },
  "demo.chat.a": {
    de: "Zwei Karten sind durch (1.200 € Wert, 3,42 € KI-Kosten). Eine wartet auf deine Abnahme, eine auf deine Antwort. Kapazität ist frei.",
    en: "Two cards are done (€1,200 of value, €3.42 of AI cost). One waits for your review, one for your answer. Capacity is free.",
  },
  "demo.chat.reply": {
    de: "Das ist die Demo — ich antworte aus einem festen Datensatz, ohne echten Rechner. Mit gekoppelter HelmDeck-Installation würde hier dein Agent antworten, Karten anlegen und Rückfragen stellen.",
    en: "This is the demo — I answer from a fixed data set, with no real machine. Paired with your own HelmDeck installation, your agent would reply here, file cards and ask you questions.",
  },
  "demo.steer.reply": { de: "Verstanden — in der Demo arbeite ich nicht wirklich weiter.",
                        en: "Got it — in the demo I don't actually continue the work." },
  "demo.steer.step": {
    de: "Angekommen. In der Demo führe ich keine echten Schritte aus — gekoppelt würde ich jetzt im Worktree arbeiten.",
    en: "Received. The demo runs no real steps — paired, I would now work in the worktree.",
  },
  "demo.newCard": { de: "Neue Anfrage", en: "New request" },
};
