import type { Dict } from "../index";

/** Keys for the card surface. Owned by that area - keep additions here so the
 *  dict never becomes a merge bottleneck. Every key needs BOTH languages.
 *
 *  NOT here on purpose: anything the daemon writes at runtime - the description
 *  body and its ALL-CAPS section heads (NUTZERGESCHICHTE / FERTIG, WENN / …),
 *  gate and merge reports, lifecycle notes, tool output, attachment filenames,
 *  branch/repo/session ids. That is the record, not the chrome. */
export const card: Dict = {
  // screen chrome
  "card.card": { de: "Karte", en: "Card" },
  "card.tab.overview": { de: "Übersicht", en: "Overview" },
  "card.changeStatus": { de: "Status ändern", en: "Change status" },

  // section labels (rendered upper-cased by SectionLabel)
  "card.sec.task": { de: "aufgabe", en: "task" },
  "card.sec.description": { de: "beschreibung", en: "description" },
  "card.sec.attachments": { de: "anhänge", en: "attachments" },
  "card.sec.properties": { de: "eigenschaften", en: "properties" },
  "card.sec.economics": { de: "wirtschaftlichkeit", en: "economics" },
  "card.sec.technical": { de: "technisch", en: "technical" },
  "card.sec.aiTurns": { de: "ki-runden", en: "ai turns" },
  "card.sec.rewind": { de: "zurücksetzen (nur dateien, reversibel)",
                       en: "rewind (files only, reversible)" },

  // task / description editors
  "card.descPlaceholder": { de: "Kontext, Akzeptanzkriterien, Links… (der Worker liest es)",
                            en: "Context, acceptance criteria, links… (the worker reads it)" },
  "card.editDescription": { de: "Beschreibung bearbeiten", en: "Edit description" },

  // attachments
  "card.attachment": { de: "Anhang", en: "Attachment" },
  "card.removeAttachment": { de: "{name} entfernen", en: "Remove {name}" },

  // properties
  "card.prop.priority": { de: "Priorität", en: "Priority" },
  "card.prop.due": { de: "Fällig (YYYY-MM-DD)", en: "Due (YYYY-MM-DD)" },
  "card.prop.billing": { de: "Abrechnung", en: "Billing" },
  "card.prop.price": { de: "Preis", en: "Price" },
  "card.prop.rate": { de: "Satz /h", en: "Rate /h" },
  "card.prop.client": { de: "Kunde", en: "Client" },
  "card.billing.fixed": { de: "Festpreis", en: "Fixed price" },
  "card.billing.tm": { de: "Zeit & Material", en: "Time & material" },
  "card.billing.none": { de: "Intern", en: "Internal" },

  // economics
  "card.econ.billed": { de: "Abgerechnet", en: "Billed" },
  "card.econ.aiCost": { de: "KI-Kosten", en: "AI cost" },
  // flat plan (Max-Abo): consumption, not cash - never render it as $-cost
  "card.econ.aiUse": { de: "KI-Verbrauch", en: "AI usage" },
  "card.econ.aiUseVal": { de: "{tok} Tok · im Max-Abo inkl. (Flat)", en: "{tok} tok · incl. in Max plan (flat)" },
  // the unit that answers "was this card expensive?": share of the allowance
  "card.econ.aiUsePlan": { de: "{pct} vom Wochenkontingent · {tok} Tok", en: "{pct} of the weekly allowance · {tok} tok" },
  "card.econ.margin": { de: "Marge", en: "Margin" },
  "card.econ.touches": { de: "Eingriffe", en: "Touches" },
  "card.econ.touchOne": { de: "{n} Eingriff", en: "{n} touch" },
  "card.econ.touchMany": { de: "{n} Eingriffe", en: "{n} touches" },
  "card.econ.mode": { de: "Modus", en: "Mode" },
  "card.mode.auto": { de: "auto", en: "auto" },
  "card.mode.assisted": { de: "begleitet", en: "assisted" },

  // technical
  "card.tech.branch": { de: "Branch", en: "Branch" },
  "card.tech.repo": { de: "Repo", en: "Repo" },
  "card.tech.session": { de: "Sitzung", en: "Session" },
  "card.tech.turns": { de: "Runden", en: "Turns" },
  "card.tech.tokens": { de: "Tokens", en: "Tokens" },
  "card.tech.models": { de: "Modelle", en: "Models" },
  "card.notStarted": { de: "nicht gestartet", en: "not started" },

  // rewind (files only)
  "card.rewind.title": { de: "Dateien zurücksetzen?", en: "Restore files?" },
  "card.rewind.body": { de: "Die aktuellen Dateien werden zuerst gesichert (reversibel). Der Verlauf bleibt.",
                        en: "The current files are backed up first (reversible). The history stays." },
  "card.rewind.restore": { de: "Wiederherstellen", en: "Restore" },
  "card.rewind.turn": { de: "Runde {n}", en: "turn {n}" },

  // chat column
  "card.chat.noMessages": { de: "Noch keine Nachrichten.", en: "No messages yet." },
  "card.chat.historyLost": { de: "Verlauf nicht verfügbar - {n} Runden liefen, aber die Aufzeichnung dazu ist verloren gegangen (nicht diese Karte kaputt: die Daten fehlen).",
                             en: "History unavailable - {n} turns ran, but the recording of them is gone (not this card breaking: the data is missing)." },
  "card.chat.latest": { de: "Neueste", en: "Latest" },
  "card.chat.mentionHenry": { de: "verschieben/löschen/steuern (Board-Kontext)",
                              en: "move/delete/steer (board context)" },
  "card.chat.mentionWorker": { de: "steuert die Karten-Session", en: "steers the card's own session" },
  "card.chat.henryThinking": { de: "Henry denkt…", en: "Henry is thinking…" },
  "card.chat.context": { de: "Kontext {k}k · {pct}%", en: "Context {k}k · {pct}%" },
  "card.chat.contextFull": { de: "Kontext fast voll — bei Überlauf startet eine frische Session, der Verlauf bleibt sichtbar", en: "Context nearly full — on overflow a fresh session starts, the history stays visible" },
  "card.chat.awaitingBackground": { de: "Worker wartet auf {n} Hintergrund-Task — nicht auf dich.",
                                    en: "The worker is waiting on {n} background task — not on you." },
  "card.bg.line": { de: "Hintergrund-Tasks: {n}", en: "Background tasks: {n}" },
  "card.bg.lineLive": { de: "Hintergrund-Tasks: {n} · {m} läuft", en: "Background tasks: {n} · {m} running" },
  "card.bg.lineWaiting": { de: "Worker wartet auf {m} Hintergrund-Task — nicht auf dich",
                           en: "The worker is waiting on {m} background task — not on you" },
  "card.bg.status.running": { de: "läuft", en: "running" },
  "card.bg.status.completed": { de: "fertig", en: "done" },
  "card.bg.status.failed": { de: "fehlgeschlagen", en: "failed" },
  "card.bg.status.canceled": { de: "abgebrochen", en: "canceled" },
  "card.q.title": { de: "ENTSCHEIDUNG NÖTIG", en: "DECISION NEEDED" },
  "card.q.hint": { de: "Deine Wahl geht direkt an den Worker — er macht dort weiter, wo er aufgehört hat.",
                   en: "Your choice goes straight to the worker — it carries on where it stopped." },
  // Henry's OWN question has no parked worker behind it: the choice is simply
  // the next thing the owner says to him. Promising it "goes to the worker" was
  // wrong the moment the panel started serving both doors — caught by judging
  // the screenshot, not by tsc.
  "card.q.hintChat": { de: "Deine Wahl geht als deine nächste Nachricht an Henry.",
                       en: "Your choice goes to Henry as your next message." },
  "card.q.progress": { de: "Frage {n}/{total}", en: "Question {n}/{total}" },
  "card.q.count": { de: "{n} Optionen", en: "{n} options" },
  "card.q.next": { de: "Weiter", en: "Next" },
  "card.q.back": { de: "Zurück", en: "Back" },
  "card.q.send": { de: "Antworten", en: "Answer" },
  "card.q.otherPh": { de: "Eigene Antwort eingeben…", en: "Type your own answer…" },
  "card.q.otherLabel": { de: "Oder eigene Antwort", en: "Or your own answer" },
  "card.q.collapse": { de: "Frage einklappen", en: "Collapse question" },
  "card.q.expand": { de: "Frage ausklappen", en: "Expand question" },
  "card.q.tapAnswer": { de: "Tippen zum Antworten", en: "Tap to answer" },
  "card.q.tapExpand": { de: "Tippen zum Ausklappen & Antworten", en: "Tap to expand & answer" },
  "card.q.failedTitle": { de: "Antwort fehlgeschlagen", en: "Answer failed" },
  "card.chat.phWorkerLive": { de: "Worker steuern – Kontext läuft weiter · @Henry, /commands",
                              en: "Steer the worker – context carries on · @Henry, /commands" },
  "card.chat.phWorkerIdle": { de: "Worker starten… · @Henry, /commands", en: "Start the worker… · @Henry, /commands" },
  "card.chat.sendFailed": { de: "Senden an Henry fehlgeschlagen", en: "Sending to Henry failed" },

  // slash commands (the hint the owner reads, and the text it types for them)
  "card.slash.planHint": { de: "erst planen, dann handeln", en: "plan before acting" },
  "card.slash.planInsert": { de: "Mach einen Plan für: ", en: "Make a plan for: " },
  "card.slash.testHint": { de: "Tests laufen lassen, Fehler melden", en: "run tests, report failures" },
  "card.slash.testInsert": { de: "Lass die Tests laufen und melde alle Fehler.",
                             en: "Run the tests and report any failures." },
  "card.slash.diffHint": { de: "aktuelle Änderungen zusammenfassen", en: "summarize current changes" },
  "card.slash.diffInsert": { de: "Fasse den aktuellen Diff auf diesem Branch zusammen.",
                             en: "Summarize the current diff on this branch." },
  "card.slash.commitHint": { de: "die Arbeit committen", en: "commit the work" },
  "card.slash.commitInsert": { de: "Committe die aktuelle Arbeit mit einer klaren Nachricht.",
                               en: "Commit the current work with a clear message." },

  // move sheet / card menu
  "card.move.to": { de: "Verschieben nach…", en: "Move to…" },
  "card.move.nextStep": { de: "nächster Schritt", en: "next step" },
  "card.move.advance": { de: "Weiterschieben", en: "Advance" },
  "card.fastTrack.enable": { de: "⚡ Fast-Track aktivieren", en: "⚡ Enable fast-track" },
  "card.fastTrack.disable": { de: "⚡ Fast-Track deaktivieren", en: "⚡ Disable fast-track" },
  "card.fastTrack.hint": { de: "  (grün → auto-merge + deploy)",
                           en: "  (green → auto-merge + deploy)" },
  "card.fastTrack.off": { de: "Fast-Track aus", en: "Turn fast-track off" },
  "card.desktop.enable": { de: "🖥️ Desktop-Zugriff aktivieren", en: "🖥️ Enable desktop control" },
  "card.desktop.disable": { de: "🖥️ Desktop-Zugriff deaktivieren", en: "🖥️ Disable desktop control" },
  "card.desktop.hint": { de: "  (Agent steuert Maus/Tastatur/Bildschirm)",
                         en: "  (agent drives mouse/keyboard/screen)" },
  // Feedback after flipping the driver: the tool grant is bound at process
  // spawn, so it takes hold on the NEXT turn, not the running one (see
  // drivers.build_argv / drop_session).
  "card.desktop.toastOn": { de: "🖥️ Desktop-Zugriff aktiviert — wirkt ab deiner nächsten Nachricht",
                            en: "🖥️ Desktop control on — takes effect on your next message" },
  "card.desktop.toastOff": { de: "🖥️ Desktop-Zugriff deaktiviert — wirkt ab deiner nächsten Nachricht",
                             en: "🖥️ Desktop control off — takes effect on your next message" },
  "card.menu.fork": { de: "Code forken", en: "Fork code" },
  "card.menu.forkChat": { de: "Konversation forken", en: "Fork conversation" },
  "card.menu.archive": { de: "Archivieren", en: "Archive" },
  // shown instead of the above once the card IS archived - the round trip back
  // out of the archive (api.archive(id, false)).
  "card.menu.unarchive": { de: "Aus dem Archiv holen", en: "Restore from archive" },
  "card.menu.unarchived": { de: "Karte ist zurück auf dem Board",
                            en: "Card is back on the board" },

  // move toasts
  "card.toast.gateMerge": { de: "Gate + Merge laufen… Ergebnis erscheint hier",
                            en: "Gate + merge running… the result appears here" },
  "card.toast.gate": { de: "Gate läuft… Ergebnis erscheint hier",
                       en: "Gate running… the result appears here" },
  "card.toast.started": { de: "Gestartet → {lane} · Agent arbeitet",
                          en: "Started → {lane} · agent working" },
  "card.toast.bounced": { de: "Abgelehnt → {lane} (Gate/Review)", en: "Bounced → {lane} (gate/review)" },
  "card.toast.moved": { de: "Verschoben → {lane}", en: "Moved → {lane}" },
  "card.toast.moveFailed": { de: "Verschieben fehlgeschlagen: {err}", en: "Move failed: {err}" },

  // permission modes offered to the composer
  "card.perm.edit": { de: "Bearbeiten", en: "Edit" },
  "card.perm.plan": { de: "Plan", en: "Plan" },
  "card.perm.full": { de: "Voll", en: "Full" },

  // transcript / markdown rendering
  "transcript.showMore": { de: "Mehr anzeigen", en: "Show more" },
  "transcript.showLess": { de: "Weniger anzeigen", en: "Show less" },
  // 4-state tool calls + turn lifecycle (Phase 3: running|completed|failed|canceled)
  "transcript.toolCanceled": { de: "abgebrochen", en: "canceled" },
  "transcript.toolFailed": { de: "fehlgeschlagen", en: "failed" },
  "transcript.turnFailed": { de: "Turn fehlgeschlagen", en: "Turn failed" },
  "transcript.turnCanceled": { de: "Turn abgebrochen", en: "Turn canceled" },
  "transcript.turnDone": { de: "Turn abgeschlossen", en: "Turn done" },
  "transcript.thinking": { de: "Gedanken", en: "Thinking" },
  "transcript.todos": { de: "PLAN / TO-DOS", en: "PLAN / TO-DOS" },
  "transcript.plan": { de: "PLAN", en: "PLAN" },
  "transcript.boardAgent": { de: "Henry", en: "Henry" },
  "transcript.worker": { de: "Worker", en: "Worker" },
  // Chain-break divider. Since /compact injection was removed (a0853d4) a
  // session_chain break is always a ROTATION (new session, context not carried
  // in full) - never an in-place compaction, which keeps its session id. The
  // old "Kontext verdichtet" label claimed a summarisation that never happened.
  "transcript.compacted": { de: "Frühere Session — Verlauf wird unten fortgesetzt", en: "Earlier session — history continues below" },
  "transcript.code": { de: "Code", en: "code" },
};
