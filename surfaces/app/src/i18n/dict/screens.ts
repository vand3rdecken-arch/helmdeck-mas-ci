import type { Dict } from "../index";

/** The secondary screens: automation, connectors, history, processes,
 *  recordings, sessions, the loop map, pairing, plus the app-wide chrome that
 *  lives outside the board (health banner, updates panel, prompt host).
 *
 *  What is deliberately NOT here: anything the daemon sends at runtime (card
 *  task text, debt register entries, connector names, event/timeline lines,
 *  branch names, charter text). That is the audit trail and stays as it comes. */
export const screens: Dict = {
  // ---- automation & loop --------------------------------------------------
  "automation.title": { de: "Automatik & Loop", en: "Automation & loop" },
  "automation.errorOwner": {
    de: "Nur für Owner / Desktop nicht erreichbar.",
    en: "Owner only / desktop unreachable.",
  },
  "automation.on": { de: "an", en: "on" },
  "automation.off": { de: "aus", en: "off" },
  "automation.window": { de: "Fenster", en: "Window" },
  "automation.always": { de: "immer", en: "always" },
  "automation.idleGate": { de: "Idle-Gate", en: "Idle gate" },
  "automation.idleMinutes": { de: "{n} Min", en: "{n} min" },
  "automation.maxPerNight": { de: "Max/Nacht", en: "Max/night" },
  "automation.startedToday": { de: "Heute gestartet", en: "Started today" },
  "automation.autoAcceptGreen": { de: "Auto-accept grün", en: "Auto-accept green" },
  "automation.autoDispatch": { de: "Auto-dispatch", en: "Auto-dispatch" },
  "automation.chatAdmin": { de: "Chat-Admin", en: "Chat admin" },
  "automation.yes": { de: "ja", en: "yes" },
  "automation.no": { de: "nein", en: "no" },
  "automation.repos": { de: "Repos ({n})", en: "repos ({n})" },
  "automation.noRepos": { de: "keine", en: "none" },
  "automation.configPolicy": { de: "Policy (konfigurierbar)", en: "Policy (configurable)" },
  "automation.nightSection": { de: "Nachtschicht", en: "Night shift" },
  "automation.save": { de: "Speichern", en: "Save" },
  // config_schema knob labels (rendered generically from the daemon schema)
  "cfg.autoAccept": { de: "Grün automatisch abnehmen & mergen", en: "Auto-accept & merge green" },
  "cfg.autoAccept.desc": { de: "Karten, die die Suite bestehen, werden ohne Rückfrage abgenommen und gemergt.",
                           en: "Cards that pass the suite are accepted and merged without asking." },
  "cfg.autoModes": { de: "Auto-Dispatch-Modi", en: "Auto-dispatch modes" },
  "cfg.autoModes.desc": { de: "In welchen Ausführungsmodi Karten automatisch gestartet werden dürfen.",
                          en: "Which execution modes may auto-start a card." },
  "cfg.autoPrio": { de: "Auto-Dispatch ab Priorität", en: "Auto-dispatch from priority" },
  "cfg.autoPrio.desc": { de: "Ab welcher Priorität eine Karte ohne manuellen Start losläuft.",
                         en: "From which priority a card starts without a manual dispatch." },
  "cfg.chatRoles": { de: "Wer die Policy per Chat ändern darf", en: "Who may change policy via chat" },
  "cfg.chatRoles.desc": { de: "Welche Rollen dem Copilot im Chat Policy-Änderungen geben dürfen.",
                          en: "Which roles may hand the copilot a policy change via chat." },
  // The row is badged WORKSPACE, so it has to describe what it really changes.
  // "Eigene Namen für die vier Board-Spalten" was true when this key was the
  // only column rename there was; a board owns its column labels now, and this
  // key is what every OTHER surface calls a station - so a description still
  // promising board columns would be the same mismatch the scope badge just
  // stopped making.
  // NOT "Stationsnamen": that is already this row's SECTION header
  // (hub.grp.boardLabels), and the two stacked read as a stutter. The control
  // labels the grid of four fields, so it names what one field holds.
  "cfg.laneLabels": { de: "Name je Station", en: "Name per station" },
  "cfg.laneLabels.desc": {
    de: "Wie die vier Stationen überall außerhalb eines Boards heißen — im Verschieben-Menü, auf der Karte, im Harness. Board-Spalten ohne eigene Beschriftung zeigen ebenfalls diesen Namen.",
    en: "What the four stations are called everywhere outside a board — the move menu, the card, the harness. Board columns with no label of their own show this name too.",
  },
  "cfg.nightEnabled": { de: "Nachtschicht an", en: "Night shift on" },
  "cfg.nightEnabled.desc": { de: "Der PM darf außerhalb deiner Arbeitszeit selbstständig Karten starten.",
                             en: "The PM may dispatch cards on its own outside your working hours." },
  "cfg.nightWindow": { de: "Zeitfenster", en: "Window" },
  "cfg.nightWindow.desc": { de: "Uhrzeitfenster der Nachtschicht, z. B. 01:00-07:00, oder \"always\".",
                            en: "Time window for the night shift, e.g. 01:00-07:00, or \"always\"." },
  "cfg.nightMax": { de: "Max. Karten/Nacht", en: "Max cards/night" },
  "cfg.nightMax.desc": { de: "Obergrenze, wie viele Karten eine Nachtschicht anstößt.",
                         en: "Upper bound on how many cards one night shift dispatches." },
  "cfg.nightIdle": { de: "Idle-Gate (Min)", en: "Idle gate (min)" },
  "cfg.nightIdle.desc": { de: "So lange muss Ruhe sein, bevor die Nachtschicht die nächste Karte startet.",
                          en: "How long things must be quiet before the night shift starts the next card." },
  // ---- knobs that joined the schema in accounts-boards-prd phase 4 ----
  // The account's own two (door 1, scope "Konto"), the business panel that
  // dissolved into door 6, and the one genuinely machine-scoped key.
  "cfg.lang.desc": { de: "Deine Sprache – gilt für dein Konto auf allen Geräten.",
                     en: "Your language - applies to your account on every device." },
  "cfg.backdrop.desc": { de: "Der Hintergrund hinter dem Glas, für dein Konto.",
                         en: "The backdrop behind the glass, for your account." },
  "cfg.defaultRepo.desc": { de: "In welches Repo eine neue Karte geht, wenn keins genannt ist.",
                            en: "Which repo a new card lands in when none is named." },
  "cfg.wipLimit.desc": { de: "Wie viele Karten gleichzeitig laufen dürfen.",
                         en: "How many cards may run at the same time." },
  "cfg.valuePerCard.desc": { de: "Angenommener Wert einer gelieferten Karte – die Basis der Margen-Rechnung.",
                             en: "Assumed value of one delivered card - the basis of the margin figure." },
  "cfg.touchBudget.desc": { de: "Wie viele deiner Eingriffe pro Tag eingeplant sind.",
                            en: "How many of your touches per day are budgeted for." },
  "cfg.tariffSteer": { de: "Tarif: Steuern", en: "Tariff: steer" },
  "cfg.tariffSteer.desc": { de: "Wie viele Touches ein Zwischenruf an eine laufende Karte kostet.",
                            en: "How many touches one nudge to a running card costs." },
  "cfg.tariffReview": { de: "Tarif: Review", en: "Tariff: review" },
  "cfg.tariffReview.desc": { de: "Wie viele Touches eine Abnahme kostet.",
                             en: "How many touches one review costs." },
  "cfg.tariffBounce": { de: "Tarif: Zurückweisen", en: "Tariff: bounce" },
  "cfg.tariffBounce.desc": { de: "Wie viele Touches eine zurückgewiesene Karte kostet.",
                             en: "How many touches a bounced card costs." },
  "cfg.webUrl": { de: "Web-Oberfläche (URL)", en: "Web surface (URL)" },
  "cfg.webUrl.desc": { de: "Wohin dieser Daemon die alten Web-Pfade weiterleitet. Gilt nur für diese Maschine.",
                       en: "Where this daemon redirects the legacy web paths. This machine only." },

  // ---- harness (briefs, settings layers, spawn preview) --------------------
  "harness.section": { de: "Harness", en: "Harness" },
  "harness.intro": {
    de: "Was jede Agenten-Oberfläche über sich selbst erfährt — und was beim Start wirklich ausgeführt wird.",
    en: "What each agent surface is told about itself — and what actually runs on spawn.",
  },
  "harness.brief": { de: "Brief (editierbar)", en: "Brief (editable)" },
  "harness.briefHint": {
    de: "Der System-Prompt dieser Oberfläche. Frontmatter wird gegen das Schema geprüft; der Body ist freie Policy.",
    en: "This surface's system prompt. Frontmatter is schema-checked; the body is free policy.",
  },
  "harness.settings": { de: "Settings-Ebene (editierbar)", en: "Settings layer (editable)" },
  "harness.settingsHint": {
    de: "Die eigene Claude-Settings-Datei dieser Oberfläche. Nie Secrets — die Datei liegt in git.",
    en: "This surface's own Claude settings file. Never secrets — it is tracked in git.",
  },
  "harness.preview": { de: "Spawn-Vorschau (nur lesbar)", en: "Spawn preview (read-only)" },
  "harness.previewHint": {
    de: "Aus demselben Builder wie der echte Start — kann also nicht auseinanderlaufen.",
    en: "From the same builder the real spawn uses — so it cannot drift.",
  },
  "harness.builtBy": { de: "gebaut von {fn}", en: "built by {fn}" },
  "harness.execRewritten": {
    de: "Das ist die ECHTE Exec-Form: {from} wird vor dem Start auf die reale claude.exe aufgelöst — der .cmd-Umweg über cmd.exe zerlegt zitierte Argumente (er hat einmal --resume verschluckt).",
    en: "This is the REAL exec form: {from} is resolved to the actual claude.exe before spawn — routing a .cmd through cmd.exe mangles quoted args (it once ate --resume).",
  },
  "harness.briefSource": { de: "Brief-Quelle", en: "Brief source" },
  "harness.resolvedHash": {
    de: "aufgelöst: {n} Zeichen · sha256 {h}",
    en: "resolved: {n} chars · sha256 {h}",
  },
  "harness.askSpliced": {
    de: "+ <helmdeck-ask>-Protokoll (fest, nicht editierbar)",
    en: "+ <helmdeck-ask> protocol (fixed, not editable)",
  },
  "harness.memory": { de: "Auto-Memory (geteilt, kein Git)", en: "Auto-memory (shared, no git)" },
  "harness.memoryProtected": { de: "schreibgeschuetzt", en: "write-protected" },
  "harness.memoryWritable": { de: "SCHREIBBAR", en: "WRITABLE" },
  "harness.layers": { de: "Settings-Ebenen", en: "Settings layers" },
  "harness.hookMatrix": { de: "Hooks: {on} aktiv, {off} ausgeschlossen", en: "Hooks: {on} active, {off} excluded" },
  "harness.noHooks": { de: "keine Hooks", en: "no hooks" },
  "harness.hooksDisabled": {
    de: "disableAllHooks ist gesetzt ({files}) — welche der folgenden Hooks dadurch wirklich ausfallen, ist hier NICHT modelliert (nicht gegen die echte CLI geprüft). Diese Liste ist dann unzuverlässig.",
    en: "disableAllHooks is set ({files}) — which of the hooks below that actually kills is NOT modelled here (never probed against the real CLI). Treat this list as unreliable.",
  },
  "harness.save": { de: "Speichern", en: "Save" },
  "harness.saved": { de: "Gespeichert: {p}", en: "Saved: {p}" },
  "harness.unsaved": { de: "ungespeichert", en: "unsaved" },
  "harness.restore": { de: "Zurückrollen", en: "Roll back" },
  "harness.brokenFiles": { de: "Harness-Dateien mit Fehlern", en: "Harness files failing to load" },
  "harness.sourcesOff": { de: "(aus)", en: "(off)" },

  // ---- connectors ---------------------------------------------------------
  "connectors.everyMins": { de: "alle {n}m", en: "every {n}m" },
  "connectors.lastRun": { de: "Letzter Lauf: {when}", en: "Last run: {when}" },
  "connectors.never": { de: "nie", en: "never" },
  "connectors.runNow": { de: "Jetzt laufen", en: "Run now" },
  "connectors.started": { de: "Gestartet", en: "Started" },
  "connectors.startedCards": {
    de: "Gestartet — {n} neue Backlog-Karten",
    en: "Started — {n} new backlog cards",
  },
  "connectors.rollbackTitle": { de: "Rollback?", en: "Rollback?" },
  "connectors.rollbackBody": {
    de: "„{name}“ auf die vorherige Version zurücksetzen? Die von diesem Connector erzeugten Karten werden rückgängig gemacht.",
    en: "Roll “{name}” back to the previous version? The cards this connector created will be undone.",
  },
  "connectors.rolledBack": { de: "Zurückgerollt", en: "Rolled back" },
  "connectors.rollbackN": { de: "Rollback ({n})", en: "Rollback ({n})" },
  "connectors.every": { de: "alle", en: "every" },
  "connectors.minutes": { de: "Minuten", en: "minutes" },
  "connectors.saveSchedule": { de: "Zeitplan speichern", en: "Save schedule" },
  "connectors.scheduled": { de: "Alle {n} Min geplant", en: "Scheduled every {n} min" },
  "connectors.scheduleRemoved": { de: "Zeitplan entfernt", en: "Schedule removed" },
  "connectors.produced": { de: "ERZEUGTE KARTEN ({n})", en: "CARDS PRODUCED ({n})" },
  "connectors.noneProduced": {
    de: "Noch keine – lass ihn laufen.",
    en: "None yet – give it a run.",
  },
  "connectors.empty": { de: "Keine Connectors.", en: "No connectors." },
  // Henry's context chip on this screen's chat entry (settings-ia-redesign
  // follow-up): building a new connector (build_integration) has no button
  // here at all - it is chat-only by design (an AGENT writes the connector as
  // a card) - so this hint says so explicitly rather than leaving the owner to
  // guess why "connector build" isn't a form.
  "connectors.askContext": {
    de: "Es geht um Connectors (bauen, laufen lassen, planen, zurückrollen).",
    en: "This is about connectors (build, run, schedule, roll back).",
  },

  // ---- history (commit graph, checkpoints, debt) --------------------------
  "history.unset": { de: "(nicht gesetzt)", en: "(unset)" },
  "history.commitGraph": { de: "Commit-Graph", en: "Commit graph" },
  "history.commitGraphSub": {
    de: "Jede Zeile = der Branch einer Card (tippen → Card) · jeder Punkt = ein Commit · Zeilenfarbe = Lane.",
    en: "Each row = one card's branch (tap → card) · each dot = one commit · row colour = lane.",
  },
  "history.checkpoints": { de: "Config-Checkpoints", en: "Config checkpoints" },
  "history.checkpointsSub": {
    de: "Policy/Settings- und Connector-Änderungen (nicht Code – das ist der Graph oben). Zeile antippen für Details.",
    en: "Policy/settings and connector changes (not code – that is the graph above). Tap a row for details.",
  },
  "history.noCheckpoints": {
    de: "Noch keine – die nächste Settings-/Connector-Änderung erzeugt einen.",
    en: "None yet – the next settings/connector change creates one.",
  },
  "history.debt": { de: "Structural Debt", en: "Structural debt" },
  "history.debtSub": {
    de: "Bewusste Abkürzungen, die das Programm über sich selbst kennt.",
    en: "Deliberate shortcuts the program knows about itself.",
  },
  "history.noDebt": { de: "Keine Einträge.", en: "No entries." },
  "history.restoreShort": { de: "↺ wiederherstellen", en: "↺ restore" },
  "history.restore": { de: "Wiederherstellen", en: "Restore" },
  "history.restoreTitle": { de: "Wiederherstellen?", en: "Restore?" },
  "history.restoreBody": {
    de: "Config-Stand vor „{reason}“ wiederherstellen? (Umkehrbar – aktueller Stand wird zuerst gesichert.)",
    en: "Restore the config state from before “{reason}”? (Reversible – the current state is backed up first.)",
  },
  "history.restored": { de: "Wiederhergestellt", en: "Restored" },
  "history.restoredBody": {
    de: "Aktueller Stand wurde zuvor gesichert.",
    en: "The current state was backed up first.",
  },
  "history.diffLoading": { de: "Diff wird gelesen…", en: "Reading the diff…" },
  "history.noFieldChange": {
    de: "Keine feldweise Änderung erfasst.",
    en: "No field-level change recorded.",
  },
  "history.connectorAdded": { de: "+ Connector {name}", en: "+ connector {name}" },
  "history.connectorRemoved": { de: "− Connector {name}", en: "− connector {name}" },
  "history.fileFixCard": { de: "Fix-Card anlegen", en: "file fix card" },
  "history.fixCardCreated": { de: "Fix-Card erstellt", en: "Fix card created" },
  "history.fixCardBody": {
    de: "Fix-Card im Backlog (hohe Priorität).",
    en: "Fix card in the backlog (high priority).",
  },
  "history.bitesWhen": { de: "beißt, wenn: {trigger}", en: "bites when: {trigger}" },
  "history.fix": { de: "Fix: {fix}", en: "fix: {fix}" },
  "history.fork": { de: "Fork", en: "Fork" },
  "history.forkShort": { de: "⑂ forken", en: "⑂ fork" },
  "history.forkTitle": { de: "Branch forken?", en: "Fork branch?" },
  "history.forkBody": {
    de: "Neue Card aus dem Stand von „{branch}“ starten? (Append-only – die Quelle bleibt unberührt.)",
    en: "Start a new card from the state of “{branch}”? (Append-only – the source stays untouched.)",
  },
  "history.forked": { de: "Geforkt", en: "Forked" },
  "history.forkedBody": {
    de: "Neue Card aus diesem Branch (Quelle bleibt unberührt).",
    en: "New card from this branch (the source stays untouched).",
  },
  "history.noCommits": { de: "Noch keine Commits.", en: "No commits yet." },
  "history.branch": { de: "Branch", en: "branch" },
  "history.acceptedTruth": { de: "die abgenommene Wahrheit", en: "the accepted truth" },
  "history.hash": { de: "Hash", en: "hash" },
  "history.author": { de: "Autor", en: "author" },
  "history.date": { de: "Datum", en: "date" },
  // A 500 from the daemon is NOT "Desktop nicht erreichbar" - the desktop
  // answered. Naming the real error is what turns a wrong-and-unactionable
  // message into a debuggable one.
  "history.loadFailed": {
    de: "Konnte nicht geladen werden: {msg}",
    en: "Could not load: {msg}",
  },

  // ---- processes ----------------------------------------------------------
  "processes.stateDone": { de: "fertig", en: "done" },
  "processes.stateWorking": { de: "Agent arbeitet", en: "agent working" },
  "processes.stateReady": { de: "als Nächstes", en: "up next" },
  "processes.stateWaiting": { de: "wartet", en: "waiting" },
  "processes.stateProposed": { de: "vorgeschlagen", en: "proposed" },
  "processes.inReview": { de: "in Review", en: "in review" },
  "processes.stepTitlePlaceholder": { de: "Schritt-Titel", en: "step title" },
  "processes.duePlaceholder": { de: "fällig (YYYY-MM-DD)", en: "due (YYYY-MM-DD)" },
  "processes.cardChip": { de: "✓ Card", en: "✓ card" },
  "processes.cardChipOpen": { de: "✓ Card öffnen", en: "✓ open card" },
  "processes.editProcess": { de: "Bearbeiten", en: "Edit" },
  "processes.cancelProcess": { de: "Abbrechen", en: "Cancel" },
  "processes.clientPrompt": { de: "Client:", en: "Client:" },
  "processes.duePrompt": { de: "Fällig (YYYY-MM-DD):", en: "Due (YYYY-MM-DD):" },
  "processes.cancelConfirmTitle": { de: "Prozess abbrechen?", en: "Cancel process?" },
  "processes.cancelConfirmBody": {
    de: "Verbleibende Schritte starten nicht mehr automatisch. Bereits erstellte Cards laufen normal weiter.",
    en: "Remaining steps will no longer auto-advance. Cards already created keep running normally.",
  },
  "processes.deleteProcess": { de: "Löschen", en: "Delete" },
  "processes.deleteConfirmTitle": { de: "Prozess löschen?", en: "Delete process?" },
  "processes.deleteConfirmBody": {
    de: "Der Prozess verschwindet aus der Liste. Bereits erstellte Cards laufen normal weiter.",
    en: "The process disappears from the list. Cards already created keep running normally.",
  },
  "processes.acceptCard": { de: "Übernehmen → Card", en: "Accept → card" },
  "processes.acceptAll": { de: "Alle übernehmen → Cards", en: "Accept all → cards" },
  "processes.addStep": { de: "+ Schritt", en: "+ add step" },
  "processes.done": { de: "Erledigt", en: "Done" },
  "processes.cardCreated": { de: "Card auf dem Board erstellt.", en: "Card created on the board." },
  "processes.cardsCreated": { de: "Cards auf dem Board erstellt.", en: "Cards created on the board." },
  "processes.stepTitlePrompt": { de: "Schritt-Titel:", en: "Step title:" },
  "processes.clientChip": { de: "Client: {name}", en: "client: {name}" },
  "processes.dueChip": { de: "fällig {due}", en: "due {due}" },
  "processes.aiCost": { de: "KI ${amount}", en: "AI ${amount}" },
  "processes.aiFlat": { de: "KI im Abo inkl.", en: "AI incl. in plan" },
  "processes.proposing": { de: "Agent schlägt Schritte vor…", en: "Agent is proposing steps…" },
  "processes.proposeFailed": { de: "Vorschlag fehlgeschlagen", en: "Proposal failed" },
  "processes.newProcess": { de: "Neuer Prozess", en: "New process" },
  "processes.newProcessHint": {
    de: "Beschreibe die Anfrage in Worten – ein Agent schlägt die Schritte vor, du passt sie an, jeder angenommene Schritt wird zu einer Card und die Kette läuft der Reihe nach.",
    en: "Describe the request in words – an agent proposes the steps, you adjust them, every accepted step becomes a card and the chain runs in order.",
  },
  "processes.requestPlaceholder": {
    de: "z. B. Kunde Meier braucht den Q3-Vertrag: aus Vorlage entwerfen, rechtlich prüfen, an Kunden zur Unterschrift, unterschriebene Kopie archivieren.",
    en: "e.g. client Meier needs the Q3 contract: draft it from the template, have legal review it, send it to the client for signature, archive the signed copy.",
  },
  "processes.clientPlaceholder": { de: "Client (optional)", en: "client (optional)" },
  "processes.hint": { de: "Hinweis", en: "Note" },
  "processes.describeRequest": { de: "Beschreibe die Anfrage.", en: "Describe the request." },
  "processes.proposeSteps": { de: "Schritte vorschlagen", en: "Propose steps" },
  "processes.submitted": { de: "Eingereicht", en: "Submitted" },
  "processes.submittedBody": {
    de: "Agent schlägt die Schritte vor.",
    en: "An agent is proposing the steps.",
  },
  "processes.empty": { de: "Keine Prozesse.", en: "No processes." },

  // ---- recordings ---------------------------------------------------------
  "recordings.steps": { de: "{n} Schritte", en: "{n} steps" },
  "recordings.timelineError": { de: "Timeline nicht ladbar.", en: "Timeline could not be loaded." },
  "recordings.noSteps": { de: "Keine Schritte aufgezeichnet.", en: "No steps recorded." },
  "recordings.videoRelay": {
    de: "Video verfügbar auf dem Desktop (im Relay-Modus nicht direkt streambar).",
    en: "Video available on the desktop (not directly streamable in relay mode).",
  },
  "recordings.openVideo": { de: "▶ Video öffnen", en: "▶ Open video" },
  "recordings.installExpoVideo": {
    de: "Für eingebettete Wiedergabe expo-video installieren.",
    en: "Install expo-video for embedded playback.",
  },
  "recordings.empty": { de: "Keine Aufnahmen.", en: "No recordings." },

  // ---- claude sessions ----------------------------------------------------
  "sessions.intro": {
    de: "Deine Claude-Code-Sessions aus ~/.claude. Continue setzt eine genau dort fort, wo sie aufgehört hat; Branch öffnet eine frische Session in einem neuen Branch/Worktree mit der ursprünglichen Anfrage als Kontext. Das Übernehmen macht keinen Commit – die Card-Historie ist die Nachverfolgung.",
    en: "Your Claude Code sessions from ~/.claude. Continue picks one up exactly where it left off; Branch opens a fresh session in a new branch/worktree with the original request as context. Adopting makes no commit – the card history is the trail.",
  },
  "sessions.session": { de: "Sitzung", en: "session" },
  "sessions.noText": { de: "(kein Text)", en: "(no text)" },
  "sessions.continue": { de: "▶ Fortsetzen", en: "▶ Continue" },
  "sessions.forkChat": { de: "⑂ Konversation forken", en: "⑂ Fork conversation" },
  "sessions.branch": { de: "⑂ Verzweigen", en: "⑂ Branch" },
  "sessions.asCard": { de: "Session als Card", en: "Session as card" },
  "sessions.asCardBody": { de: "Öffne die Card, um fortzusetzen.", en: "Open the card to continue." },
  "sessions.branched": { de: "Verzweigt", en: "Branched" },
  "sessions.branchedBody": {
    de: "Eine neue Card verzweigt davon.",
    en: "A new card branches off it.",
  },
  "sessions.empty": { de: "Keine Sessions gefunden.", en: "No sessions found." },

  // ---- loop map -----------------------------------------------------------
  // Vocabulary, fixed once here and used nowhere else in three different ways:
  //   Lane       = a column on the board (where a CARD sits)
  //   Loop-Stufe = a step inside one repo checkout (how a CHANGE gets built)
  //   Brief      = the instructions an AGENT is spawned with
  // The screen mixed all three under one heading style, which is half the
  // reason it read as one undifferentiated wall of locks.
  "loopmap.title": { de: "Harness", en: "Harness" },
  "loopmap.intro": {
    de: "Diese Seite zeigt drei verschiedene Dinge. Manches ist bewusst fest verdrahtet, anderes kannst du ändern — jeder Block sagt oben, was davon gilt.",
    en: "This page shows three different things. Some of it is deliberately hard-wired, some of it you can change — every block states which up front.",
  },
  "loopmap.legend": { de: "Legende", en: "Legend" },
  "loopmap.legendFixedHint": {
    de: "Im Code verankert und absichtlich nicht änderbar. Tippen zeigt den Grund und die Codestelle.",
    en: "Anchored in code and deliberately not changeable. Tap to see the reason and the source line.",
  },
  "loopmap.legendPolicyHint": {
    de: "Das darfst du einstellen. Tippen zeigt, welcher Schalter es steuert und wo er liegt.",
    en: "This one is yours to set. Tap to see which knob governs it and where that knob lives.",
  },
  "loopmap.hint": {
    de: "Tippe eine Station für Regel, Grund und Codestelle.",
    en: "Tap a station for the rule, the reason and the source line.",
  },
  "loopmap.allRepos": { de: "Allgemein", en: "General" },
  "loopmap.repoHint": {
    de: "Die Strecke dieses Repos — gestrichelt heißt: gibt es, läuft hier aber nicht. Ändern? Sag es Henry.",
    en: "This repo's route — dashed means: it exists, but does not run here. Want it changed? Tell Henry.",
  },

  // -- the repo pipeline, shared by the loop map and repo onboarding ----------
  "pipeline.off": { de: "nicht aktiv", en: "not active" },
  "pipeline.askHenry": {
    de: "Nur Anzeige. Geändert wird im Chat: sag Henry in einem Satz, wie das Repo laufen soll.",
    en: "Display only. Changes happen in chat: tell Henry in one sentence how the repo should run.",
  },
  "pipeline.deviated": {
    de: "Vom Standard der Vorlage „{template}“ abgewichen: {keys}. Bewusst so gesetzt — die Vorlage gibt nur den Startwert vor.",
    en: "Deviates from the “{template}” template default: {keys}. Set deliberately — the template only provides the starting value.",
  },
  // THE STEP LEGEND. A step is not a lane: it runs inside a transition between
  // two of them, and the arrow is what says so. Written out because position
  // alone was not enough - the row used to draw the gate as a column and the
  // owner went looking for that lane on his board.
  "pipeline.stepOn": {
    de: "läuft im Übergang {from} → {to}",
    en: "runs inside the {from} → {to} move",
  },
  // The knob badge + the Henry track (harness-config-ui phase 4). The verbs are
  // owner language on purpose - the same jargon ban Henry's own brief holds him
  // to: "legt an", never "dispatched into the backlog lane".
  "pipeline.knobs": { de: "{n} Knöpfe", en: "{n} settings" },
  "pipeline.henry": { de: "Henry", en: "Henry" },
  // SHORT ON PURPOSE. Five stations on a 430px phone leave ~80px each, and
  // "entscheidet" measured 11 characters too wide there - it rendered as
  // "entscheid…" in the first screenshot. A truncated verb is worse than a
  // short one: it looks like a word and isn't. Same lesson, same row, as the
  // off-reasons that had to move out from under these dots.
  "harness.track.backlog": { de: "legt an", en: "files" },
  "harness.track.working": { de: "steuert", en: "steers" },
  "harness.track.gate": { de: "prüft", en: "checks" },
  "harness.track.review": { de: "nimmt ab", en: "accepts" },
  "harness.track.done": { de: "nimmt ab", en: "accepts" },
  "harness.track.deploy": { de: "gibt frei", en: "releases" },
  // The other cells' bands (apimeta._cell_tracks): each verb is declared per
  // cell in spine/registry/cells.py (Cell.board) and only WORDED here - "Henry
  // steuert, engineer baut", readable straight off the pipeline. Same length
  // budget as the Henry verbs above (~80px per station on a phone).
  "cell.track.eng.working": { de: "baut", en: "builds" },
  "cell.track.eng.gate": { de: "prüft", en: "checks" },
  "cell.track.eng.deploy": { de: "liefert aus", en: "ships" },
  "cell.track.pm.backlog": { de: "plant", en: "plans" },

  // -- repo onboarding: one choice instead of twenty switches -----------------
  "repo.title": { de: "Repo einrichten", en: "Set up repo" },
  "repo.intro": {
    de: "Wähle, was für ein Repo das ist. Die Vorlage belegt alles Weitere vor — welche Stationen laufen, wie Karten gebaut werden, ob es einen Deploy gibt. Feintuning geht danach über den Chat.",
    en: "Choose what kind of repo this is. The template presets everything else — which stations run, how cards are built, whether there is a deploy. Fine-tuning happens in chat afterwards.",
  },
  "repo.which": { de: "Welches Repo", en: "Which repo" },
  "repo.noType": { de: "kein Typ", en: "no type" },
  "repo.none": {
    de: "HelmDeck kennt noch kein Repo. Trag unten einen Pfad ein.",
    en: "HelmDeck does not know any repo yet. Enter a path below.",
  },
  "repo.pathPlaceholder": { de: "C:\\Pfad\\zum\\Repo", en: "C:\\path\\to\\repo" },
  "repo.chooseFolder": { de: "Ordner wählen", en: "Choose folder" },
  "repo.pickType": { de: "Repo-Typ", en: "Repo type" },
  "repo.pipeline": { de: "So läuft dieses Repo", en: "How this repo runs" },
  // repo.intro promises "Feintuning geht danach über den Chat" - this is the
  // context that makes that promise true from THIS screen instead of sending
  // the owner hunting for the chat elsewhere.
  "repo.askContext": {
    de: "Es geht um die Pipeline für {repo} (Stationen, Deploy, Vorlage).",
    en: "This is about the pipeline for {repo} (stations, deploy, template).",
  },
  "loopmap.laws": { de: "Harness-Gesetze", en: "Harness laws" },
  "loopmap.lawsHint": {
    de: "Die sieben Sätze, die über allem stehen. Kein Schalter, kein Chat und keine Karte kann sie aufweichen — jeder nennt das Modul, das ihn durchsetzt.",
    en: "The seven sentences that outrank everything else. No switch, no chat and no card can soften them — each names the module that enforces it.",
  },
  "loopmap.charter": {
    de: "Capability-Charter (Code, read-only)",
    en: "Capability charter (code, read-only)",
  },
  "loopmap.kindFixed": { de: "Fix per Design", en: "Fixed by design" },
  "loopmap.kindPolicy": { de: "Einstellbar", en: "Adjustable" },
  "loopmap.here": { de: "HIER", en: "HERE" },
  "loopmap.modeCard": { de: "KARTEN-MODUS", en: "CARD MODE" },
  "loopmap.modeRepo": { de: "REPO-MODUS", en: "REPO MODE" },
  "loopmap.governedBy": {
    de: "Diese Schalter steuern es:",
    en: "The knobs that govern it:",
  },
  // A `settings` path the app has no field for. It is still a real knob — it
  // just does not live on a screen, so the map names the place instead of
  // sending the owner to one that has no such field.
  "loopmap.knobEnv": {
    de: "Umgebungsvariable — beim Start des Daemons gesetzt, nicht in der App",
    en: "Environment variable — set when the daemon starts, not in the app",
  },
  "loopmap.knobFile": {
    de: "Nur in settings.json — in der App (noch) kein Feld dafür",
    en: "settings.json only — no field for it in the app (yet)",
  },
  "loopmap.whyFixedFallback": {
    de: "Teil des fixen Harness: Reihenfolge und Bedingung sind Code, damit jede Karte denselben Weg nimmt und das Ergebnis prüfbar bleibt.",
    en: "Part of the fixed harness: order and condition are code, so every card takes the same path and the result stays checkable.",
  },
  "loopmap.whyPolicyFallback": {
    de: "Verhalten ist Daten, nicht Code — du kannst es über die genannten Schalter ändern.",
    en: "Behaviour is data, not code — change it through the knobs named below.",
  },
  "loopmap.secLanes": { de: "Lanes — wie eine Karte über das Board läuft", en: "Lanes — how a card crosses the board" },
  "loopmap.secLanesHint": {
    de: "Die vier Spalten deines Boards. Die Namen darfst du frei vergeben; was beim Übergang passiert, ist teils fix.",
    en: "The four columns of your board. The names are yours to choose; what happens on a transition is partly fixed.",
  },
  "loopmap.secBuild": { de: "Loop-Stufen — wie eine Änderung gebaut wird", en: "Loop stages — how a change gets built" },
  "loopmap.secBuildHint": {
    de: "Nicht das Board: das ist die Disziplin INNERHALB eines Checkouts. Tippe eine Stufe, um Regel und Grund zu sehen.",
    en: "Not the board: this is the discipline INSIDE one checkout. Tap a stage for its rule and the reason behind it.",
  },
  // The section-level answer to "why is everything here locked?". {fixed}/{total}
  // and {policy} are filled from the payload, so the sentence cannot drift from
  // the machine it describes. Both variants exist because a mode CAN be
  // all-fixed (and claiming an exception that isn't there is the same defect in
  // the other direction).
  "loopmap.buildFixedNote": {
    de: "{fixed} der {total} Stufen sind Harness-Gesetz: Reihenfolge und Bedingung sind Code, damit jede Karte denselben Weg nimmt und der Gate exakt dasselbe nachprüfen kann. Das Schloss ist hier also richtig, nicht kaputt. Einstellbar ist nur das Timing bei: {policy}.",
    en: "{fixed} of the {total} stages are harness law: order and condition are code, so every card takes the same path and the gate can re-check exactly that. The padlock here is correct, not broken. Only the timing is adjustable, on: {policy}.",
  },
  "loopmap.buildAllFixedNote": {
    de: "Alle {total} Stufen sind Harness-Gesetz: Reihenfolge und Bedingung sind Code, damit jede Karte denselben Weg nimmt und der Gate exakt dasselbe nachprüfen kann. Das Schloss ist hier also richtig, nicht kaputt — an diesem Abschnitt gibt es bewusst nichts einzustellen.",
    en: "All {total} stages are harness law: order and condition are code, so every card takes the same path and the gate can re-check exactly that. The padlock here is correct, not broken — there is deliberately nothing to set in this section.",
  },
  "loopmap.editElsewhere": {
    de: "Was du wirklich einstellen kannst, liegt im Automatik-Hub",
    en: "The settings you can actually change live in the automation hub",
  },
  "loopmap.editElsewhereWhere": {
    de: "Einstellungen → „Automatik & Loop“: Lane-Namen, Auto-Abnahme, Auto-Dispatch, Nachtschicht",
    en: "Settings → “Automation & loop”: lane names, auto-accept, auto-dispatch, night shift",
  },
  "loopmap.secHarnessHint": {
    de: "Der Text, mit dem ein Agent gestartet wird — pro Oberfläche einer. Voll editierbar.",
    en: "The text an agent is started with — one per surface. Fully editable.",
  },
  "loopmap.renameLanes": { de: "Lane-Namen ändern", en: "Rename the lanes" },
  "loopmap.harness": { de: "Agenten-Briefs", en: "Agent briefs" },
  "loopmap.chars": { de: "{n} Zeichen", en: "{n} chars" },
  "loopmap.editHarness": {
    de: "Briefs & Settings bearbeiten",
    en: "Edit briefs & settings",
  },
  "loopmap.openAutomation": {
    de: "Im Automatik-Hub ändern",
    en: "Change it in the automation hub",
  },

  // ---- pairing ------------------------------------------------------------
  "pair.title": { de: "HelmDeck koppeln", en: "Pair HelmDeck" },
  "pair.pairing": { de: "Koppeln…", en: "Pairing…" },
  "pair.noCode": { de: "Kein Pairing-Code im Link.", en: "No pairing code in the link." },
  "pair.badCode": { de: "Ungültiger Pairing-Code.", en: "Invalid pairing code." },
  "pair.checking": { de: "Verbindung prüfen…", en: "Checking the connection…" },
  "pair.ok": { de: "Gekoppelt ✓ – Desktop erreichbar.", en: "Paired ✓ – desktop reachable." },
  "pair.tokenRejected": {
    de: "Gekoppelt, aber der Token wurde abgelehnt – am Desktop einen neuen Code erzeugen.",
    en: "Paired, but the token was rejected – generate a fresh code on the desktop.",
  },
  "pair.noAnswer": {
    de: "Code übernommen, aber der Desktop antwortet nicht:\n{err}",
    en: "Code accepted, but the desktop is not answering:\n{err}",
  },
  "pair.hint": {
    de: "Desktop: Einstellungen → Mobile app → „Telefon koppeln“ erzeugt einen frischen Code (15 Min gültig, einmal verwendbar).",
    en: "Desktop: Settings → Mobile app → “Pair phone” creates a fresh code (valid for 15 min, single use).",
  },

  // ---- QR scanner (app/scan.tsx) ------------------------------------------
  "scan.permTitle": { de: "Kamera für QR-Scan", en: "Camera for the QR scan" },
  "scan.permBody": {
    de: "HelmDeck braucht die Kamera nur, um den Pairing-QR vom Desktop zu lesen.",
    en: "HelmDeck only needs the camera to read the pairing QR from your desktop.",
  },
  "scan.continue": { de: "Weiter", en: "Continue" },
  "scan.deniedTitle": { de: "Kein Kamerazugriff", en: "No camera access" },
  "scan.deniedBody": {
    de: "Der Kamerazugriff ist ausgeschaltet. Du kannst ihn in den Einstellungen für HelmDeck einschalten oder den Pairing-Code einfügen.",
    en: "Camera access is turned off. You can turn it on in the settings for HelmDeck or paste the pairing code instead.",
  },
  "scan.openSettings": { de: "Einstellungen öffnen", en: "Open Settings" },
  "scan.hint": { de: "Pairing-QR vom Desktop scannen", en: "Scan the pairing QR from your desktop" },

  // ---- app & OTA updates --------------------------------------------------
  "updates.embedded": {
    de: "Basis-Build (eingebettet, kein OTA)",
    en: "Base build (embedded, no OTA)",
  },
  "updates.section": { de: "App & Updates", en: "app & updates" },
  "updates.version": { de: "Version", en: "Version" },
  "updates.runtime": { de: "Runtime", en: "Runtime" },
  "updates.channel": { de: "Kanal", en: "Channel" },
  "updates.bundle": { de: "Bundle", en: "Bundle" },
  "updates.checking": { de: "Prüfe…", en: "Checking…" },
  "updates.upToDateNoServer": {
    de: "Aktuell - kein Update auf dem Server.",
    en: "Up to date - no update on the server.",
  },
  "updates.downloading": { de: "Lade…", en: "Downloading…" },
  "updates.rollbackLoaded": {
    de: "Rollback geladen - zurück zum eingebetteten Build.",
    en: "Rollback downloaded - back to the embedded build.",
  },
  "updates.updateLoaded": {
    de: "Update geladen - aktiviert sich beim nächsten Wechsel in den Hintergrund.",
    en: "Update downloaded - it activates the next time the app goes to the background.",
  },
  "updates.upToDate": { de: "Aktuell.", en: "Up to date." },
  "updates.checkFailed": { de: "Check fehlgeschlagen: {err}", en: "Check failed: {err}" },
  "updates.silentNote": {
    de: "Updates installieren sich still: Check beim Start und beim Zurückkehren in die App, aktiv nach dem nächsten Hintergrund-Wechsel. Kein Dialog - dieser Abschnitt ist der Beleg.",
    en: "Updates install silently: a check on launch and when you return to the app, active after the next switch to the background. No dialog - this section is the proof.",
  },
  "updates.checkNow": { de: "Jetzt auf Update prüfen", en: "Check for an update now" },
  "updates.restartApply": { de: "Jetzt neu starten & anwenden", en: "Restart & apply now" },
  "updates.otaReleaseOnly": {
    de: "OTA ist nur im Release-Build aktiv (Dev/Expo Go: aus).",
    en: "OTA is only active in the release build (dev/Expo Go: off).",
  },
  "updates.apkAvailable": {
    de: "Neue App-Version verfügbar (Build {build}). Diese Installation ist zu alt, um sie per OTA zu erreichen - nur eine neue APK bringt dich wieder auf den aktuellen Stand.",
    en: "A new app version is available (build {build}). This install is too old for OTA to reach - only a fresh APK gets you current again.",
  },
  "updates.apkInstall": { de: "Jetzt installieren", en: "Install now" },
  // ---- native desktop-shell updates (surfaces/desktop/native-updater.js) --
  // Separate from the OTA panel above: this is the whole Electron app
  // (main.js/app.asar), not just the JS bundle - owner-reported gap
  // (2026-08-26), the phone had a banner for this, the desktop app didn't.
  "updates.native.downloading": {
    de: "Neue Desktop-Version {version} wird heruntergeladen…",
    en: "Downloading desktop app update {version}…",
  },
  "updates.native.downloaded": {
    de: "Desktop-Version {version} heruntergeladen - installiert sich beim nächsten Neustart.",
    en: "Desktop app update {version} downloaded - installs on next restart.",
  },
  "updates.native.installNow": { de: "Jetzt neu starten & installieren", en: "Restart & install now" },
  "updates.js.staged": {
    de: "App-Update {version} geladen und geprüft - liegt bereit, bis die App neu startet.",
    en: "App update {version} downloaded and verified - waiting for the app to restart.",
  },

  // ---- connection health --------------------------------------------------
  "health.reconnecting": {
    de: "Verbinde neu…",
    en: "Reconnecting…",
  },
  "health.offline": {
    de: "Keine Verbindung zum Desktop.",
    en: "No connection to the desktop.",
  },
  "health.unreachable": { de: "Desktop nicht erreichbar.", en: "Desktop unreachable." },

  // ---- modules & rules (the plugin kernel surface) ------------------------
  // app/(tabs)/modules.tsx shipped with its copy hardcoded in German - exactly
  // the mix this dict exists to prevent. NOT here: the charter laws and the
  // journal lines themselves; those arrive from the daemon and stay as they
  // come, like every other audit line.
  "modules.sub": {
    de: "Alles ist ein Modul. Regeln sind aus dem Charter geseedet — anpassbar, jede Änderung wird protokolliert.",
    en: "Everything is a module. The rules are seeded from the charter — adjustable, and every change is recorded.",
  },
  "modules.engines": { de: "Engines", en: "Engines" },
  "modules.enginesHint": {
    de: "Agent-Backends hinter einem Kontrakt (Claude / Copilot / DeepSeek).",
    en: "Agent backends behind one contract (Claude / Copilot / DeepSeek).",
  },
  "modules.engineOn": { de: "verfügbar", en: "available" },
  "modules.engineOff": { de: "aus", en: "off" },
  "modules.noKernel": { de: "Kein Kernel — Fallback aktiv.", en: "No kernel — fallback active." },
  "modules.surfaces": { de: "Surfaces", en: "Surfaces" },
  "modules.surfacesHint": {
    de: "{n} registrierte Oberflächen (Nav aus der Registry).",
    en: "{n} registered surfaces (nav comes from the registry).",
  },
  "modules.rules": { de: "Regeln (geseedet)", en: "Rules (seeded)" },
  "modules.rulesHint": {
    de: "Standard = heutiger Charter. Umschalten schreibt einen getrackten Swap.",
    en: "The default is today's charter. Toggling writes a tracked swap.",
  },
  "modules.gateBeforeReview": { de: "Gate vor Review", en: "Gate before review" },
  "modules.gateBeforeReviewSub": {
    de: "Suite muss grün sein, bevor reviewt wird",
    en: "The suite must be green before review",
  },
  "modules.auditAppendOnly": { de: "Append-only Audit", en: "Append-only audit" },
  "modules.worktreeIsolation": { de: "Worktree-Isolation", en: "Worktree isolation" },
  "modules.authRequired": { de: "Auth erforderlich", en: "Auth required" },
  "modules.measuredEconomics": { de: "Gemessene Ökonomie", en: "Measured economics" },
  "modules.agentMaySwap": { de: "Agent darf Module tauschen", en: "Agent may swap modules" },
  "modules.agentMaySwapSub": {
    de: "Aus = Human-Bestätigung nötig",
    en: "Off = a human has to confirm",
  },
  "modules.buildLoop": { de: "Build-Loop (Selbststeuerung)", en: "Build loop (self-governance)" },
  "modules.buildLoopSub": {
    de: "Der interaktive Agent folgt seinem Build-Workflow (ALIGN bis COMMIT). Aus = Stop-Hook still.",
    en: "The interactive agent follows its build workflow (ALIGN through COMMIT). Off silences the Stop hook.",
  },
  "modules.wipLimit": { de: "WIP-Limit", en: "WIP limit" },
  "modules.wipLimitSub": { de: "laufende Karten", en: "cards in flight" },
  "modules.cells": { de: "Cells", en: "Cells" },
  "modules.cellsHint": {
    de: "Agentische Systeme (Rolle + Route + UI-Surface + Enable-Flag) - cells.py. Aus schaltet die Routen UND den Tab ab. Antippen zeigt die Architektur - Logic, Storage, Harness, API-Routes, UI-Surface - mit echtem Code beim Antippen einer Datei.",
    en: "Agentic systems (role + route + UI surface + enable flag) - cells.py. Off disables the routes AND the tab. Tap one for its architecture - logic, storage, harness, API routes, UI surface - with the real code behind every file.",
  },
  "modules.noCells": { de: "Keine Cells geladen.", en: "No cells loaded." },
  "modules.charter": { de: "Charter (geseedet)", en: "Charter (seeded)" },
  "modules.charterHint": {
    de: "Quelle: {source} — selbst ein tauschbares Modul.",
    en: "Source: {source} — itself a swappable module.",
  },
  "modules.journal": { de: "Reconfig-Journal", en: "Reconfig journal" },
  "modules.journalHint": {
    de: "Jede Modul-/Regeländerung, mit Urheber (die einzige Invariante: nichts ungetrackt).",
    en: "Every module/rule change, with its author (the one invariant: nothing untracked).",
  },
  "modules.journalBy": { de: "von {actor}", en: "by {actor}" },
  "modules.journalReplaced": { de: " (ersetzt {id})", en: " (replaced {id})" },
  "modules.noJournal": { de: "Noch keine Einträge.", en: "No entries yet." },

  // ui/cell_diagram.tsx - the architecture diagram behind a tapped cell. The
  // category labels (Logic, Storage, Harness, API-Routes, UI-Surface) and the
  // leaves are file paths and route names: audit side, untranslated by design.
  "cell.noRoutes": { de: "keine Routen", en: "no routes" },
  "cell.sourceLoading": { de: "Quelle wird geladen…", en: "Loading the source…" },
};
