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
  "automation.now": { de: "jetzt: {state}", en: "now: {state}" },
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
  "automation.openMap": { de: "Loop-Map ansehen", en: "View loop map" },
  "automation.configPolicy": { de: "Policy (konfigurierbar)", en: "Policy (configurable)" },
  "automation.nightSection": { de: "Nachtschicht", en: "Night shift" },
  "automation.save": { de: "Speichern", en: "Save" },
  // config_schema knob labels (rendered generically from the daemon schema)
  "cfg.autoAccept": { de: "Grün automatisch abnehmen & mergen", en: "Auto-accept & merge green" },
  "cfg.autoModes": { de: "Auto-Dispatch-Modi", en: "Auto-dispatch modes" },
  "cfg.autoPrio": { de: "Auto-Dispatch ab Priorität", en: "Auto-dispatch from priority" },
  "cfg.chatRoles": { de: "Wer die Policy per Chat ändern darf", en: "Who may change policy via chat" },
  "cfg.laneLabels": { de: "Spalten-Beschriftungen", en: "Lane labels" },
  "cfg.nightEnabled": { de: "Nachtschicht an", en: "Night shift on" },
  "cfg.nightWindow": { de: "Zeitfenster", en: "Window" },
  "cfg.nightMax": { de: "Max. Karten/Nacht", en: "Max cards/night" },
  "cfg.nightIdle": { de: "Idle-Gate (Min)", en: "Idle gate (min)" },
  "automation.movedHint": {
    de: "Loop, Harness & Automatik-Policy sind jetzt hier gebündelt.",
    en: "Loop, harness & automation policy now live here.",
  },

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
  "processes.acceptCard": { de: "Übernehmen → Card", en: "Accept → card" },
  "processes.acceptAll": { de: "Alle übernehmen → Cards", en: "Accept all → cards" },
  "processes.addStep": { de: "+ Schritt", en: "+ add step" },
  "processes.done": { de: "Erledigt", en: "Done" },
  "processes.cardCreated": { de: "Card auf dem Board erstellt.", en: "Card created on the board." },
  "processes.cardsCreated": { de: "Cards auf dem Board erstellt.", en: "Cards created on the board." },
  "processes.stepTitlePrompt": { de: "Schritt-Titel:", en: "Step title:" },
  "processes.newStep": { de: "Neuer Schritt", en: "New step" },
  "processes.titleLabel": { de: "Titel:", en: "Title:" },
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
  "sessions.onBoard": { de: "→ Karte öffnen (bereits auf dem Board)", en: "→ open card (already on the board)" },
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
  "loopmap.title": { de: "Loop & Harness", en: "Loop & harness" },
  "loopmap.hint": {
    de: "Tippe einen Schritt oder das Schild, um die Regel dahinter zu sehen.",
    en: "Tap a step or the shield to see the rule behind it.",
  },
  "loopmap.laws": { de: "Harness-Gesetze (fix)", en: "Harness laws (fixed)" },
  "loopmap.charter": {
    de: "Capability-Charter (Code, read-only)",
    en: "Capability charter (code, read-only)",
  },
  "loopmap.kindFixed": { de: "FIX (Harness)", en: "FIXED (harness)" },
  "loopmap.kindPolicy": { de: "POLICY (justierbar)", en: "POLICY (adjustable)" },

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
  "scan.allow": { de: "Kamera erlauben", en: "Allow camera" },
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
};
