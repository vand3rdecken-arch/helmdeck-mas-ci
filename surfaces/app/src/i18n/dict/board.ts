import type { Dict } from "../index";

/** Keys for the board surface. Owned by that area - keep additions here so the
 *  dict never becomes a merge bottleneck. Every key needs BOTH languages. */
export const board: Dict = {
  // ---- lane-move verdicts (board.tsx laneVerdict) -------------------------
  // {why} / {verdict} carry the daemon's own technical report, untranslated.
  "board.verdict.gatingDone": {
    de: "Gate lÃ¤uft, dann Merge nach main â€“ Ergebnis kommt auf die Karte und in den Chat",
    en: "Gate is running, then merge into main â€“ the result lands on the card and in the chat",
  },
  "board.verdict.gating": {
    de: "Gate lÃ¤uft â€“ Ergebnis kommt auf die Karte und in den Chat",
    en: "Gate is running â€“ the result lands on the card and in the chat",
  },
  "board.verdict.gateRed": {
    de: "Gate rot â€“ bleibt auf Review: {why}",
    en: "Gate red â€“ stays in Review: {why}",
  },
  "board.verdict.gateOpen": {
    de: "GATE offen â€“ bleibt auf Review: {why}",
    en: "GATE open â€“ stays in Review: {why}",
  },
  "board.verdict.mergeConflict": {
    de: "MERGE-KONFLIKT â€“ bleibt auf Review: {why}",
    en: "MERGE CONFLICT â€“ stays in Review: {why}",
  },
  "board.verdict.cannotLand": {
    de: "Kann nicht landen â€“ bleibt auf Review: {why}",
    en: "Can't land â€“ stays in Review: {why}",
  },
  "board.verdict.review": {
    de: "Review: {verdict} â€” zum Landen auf Done ziehen",
    en: "Review: {verdict} â€” drag to Done to land it",
  },
  "board.verdict.merged": {
    de: "Fertig â†’ committet & nach main gemergt",
    en: "Done â†’ committed & merged into main",
  },
  "board.verdict.redundant": {
    de: "Redundant â€“ war schon in main, Karte geschlossen",
    en: "Redundant â€“ was already in main, card closed",
  },
  "board.verdict.dispatched": { de: "Dispatched â€“ Session startet", en: "Dispatched â€“ session starting" },
  "board.verdict.queued": { de: "Queued", en: "Queued" },

  "board.merge.mergeable": { de: "âœ“ bereit zu mergen", en: "âœ“ ready to merge" },
  "board.merge.redundant": { de: "redundant â€“ schon in main", en: "redundant â€“ already in main" },
  "board.merge.conflict": { de: "âš  Konflikt mit main", en: "âš  conflict with main" },
  "board.merge.checked": { de: "geprÃ¼ft", en: "checked" },

  "board.accepted": { de: "Abgenommen", en: "Accepted" },

  // ---- card ---------------------------------------------------------------
  "board.card.gating": {
    de: "Der Harness prÃ¼ft und merged â€“ das kann ein paar Minuten dauern.",
    en: "The harness is gating and merging â€“ this can take a few minutes.",
  },
  "board.card.delivered": { de: "Geliefert: {text}", en: "Delivered: {text}" },
  "board.card.replyReady": { de: "â— Antwort da â€“ tippen", en: "â— reply is in â€“ tap" },
  "board.card.waitsOnTask": { de: "wartet auf eigenen Task", en: "waiting on its own task" },
  "board.card.menu": { de: "KartenmenÃ¼", en: "Card menu" },
  "board.card.bounced": { de: "â— abgelehnt â€“ ansehen", en: "â— bounced â€“ take a look" },
  "board.noGit": { de: "(kein Git)", en: "(no git)" },
  "board.step": { de: "Schritt {n}", en: "step {n}" },
  "board.process": { de: "Prozess", en: "process" },
  "board.due": { de: "fÃ¤llig {d}", en: "due {d}" },
  "board.onDevice": { de: "auf GerÃ¤t", en: "on device" },
  "board.deviceStale": { de: "GerÃ¤t offline?", en: "device offline?" },
  // flat plan (Max-Abo): a card's AI figure is its SHARE OF THE SUBSCRIPTION.
  // aiTok stays as the fallback for when the quota can't be calibrated.
  "board.aiPlan": { de: "KI {pct} vom Abo", en: "AI {pct} of plan" },
  "board.aiTok": { de: "KI {tok} Tok", en: "AI {tok} tok" },
  "board.mode.auto": { de: "auto Â· KI", en: "auto Â· AI" },
  "board.mode.assisted": { de: "begleitet Â· Mensch", en: "assisted Â· human" },

  // ---- next up ------------------------------------------------------------
  "board.nextUp": { de: "ALS NÃ„CHSTES", en: "NEXT UP" },
  "board.why.bounced": { de: "gate abgelehnt - fixen", en: "gate bounced - fix it" },
  "board.why.needsYou": { de: "Agent braucht dich", en: "agent needs you" },
  "board.why.human": { de: "dein Schritt", en: "your move" },
  "board.why.cowork": { de: "cowork", en: "cowork" },
  "board.why.next": { de: "als NÃ¤chstes", en: "up next" },
  "board.markDone": { de: "erledigt", en: "done" },
  "board.more": { de: "+{n} weitere", en: "+{n} more" },

  // ---- scope bar (board.tsx ScopeBar) --------------------------------------
  "board.scope.all": { de: "Alle", en: "All" },
  "board.scope.archived": { de: "Archiv", en: "Archive" },

  // ---- done column window + quick filters (board overview, stage 1) ---------
  "board.done.today": { de: "Heute", en: "Today" },
  "board.done.week": { de: "Diese Woche", en: "This week" },
  "board.done.older": { de: "Ã„lter", en: "Older" },
  "board.done.hidden": { de: "Archiviert", en: "Archived" },
  "board.done.olderLink": { de: "{n} Ã¤ltere", en: "{n} older" },
  "board.doneAt": { de: "Fertig Â· {when}", en: "Done Â· {when}" },

  // ---- layout toggle --------------------------------------------------------
  "board.layout.board": { de: "Board", en: "Board" },
  "board.layout.timeline": { de: "Timeline", en: "Timeline" },
  "board.moveTo": { de: "Verschieben nachâ€¦", en: "Move toâ€¦" },
  "board.stale": { de: "Offline â€“ letzter bekannter Stand", en: "Offline â€“ showing the last known board" },
  "board.stepDone": { de: "Step erledigt â€“ die Kette rÃ¼ckt vor", en: "Step done â€“ the chain moves on" },
  "board.emptyNeedsYou": { de: "Nichts wartet gerade auf dich.", en: "Nothing is waiting on you right now." },

  // ---- timeline / gantt ---------------------------------------------------
  "gantt.zoom.weeks": { de: "Wochen", en: "Weeks" },
  "gantt.zoom.months": { de: "Monate", en: "Months" },
  "gantt.zoom.quarters": { de: "Quartale", en: "Quarters" },
  "gantt.empty": { de: "Noch keine Arbeit.", en: "No work yet." },
  "gantt.emptyHideDone": { de: "Nichts Offenes - alles fertig.", en: "Nothing open - all done." },
  "gantt.vertical": { de: "Vertikal", en: "Vertical" },
  "gantt.hideDone": { de: "Fertige ausblenden", en: "Hide finished" },
  "gantt.rotate": { de: "Drehen", en: "Rotate" },
  "gantt.card": { de: "KARTE", en: "CARD" },
  "gantt.overdue": { de: "Ã¼berfÃ¤llig", en: "overdue" },
  "gantt.process": { de: "Prozess", en: "Process" },
  "gantt.steps": { de: "Schritte", en: "steps" },
  "gantt.legend": {
    de: "Balken = angelegt â†’ letzte AktivitÃ¤t (Done friert bei Abnahme ein) Â· blaue Linie = jetzt Â· â—† = fÃ¤llig",
    en: "Bar = created â†’ last activity (Done freezes at acceptance) Â· blue line = now Â· â—† = due",
  },
  "gantt.mon.jan": { de: "Jan", en: "Jan" },
  "gantt.mon.feb": { de: "Feb", en: "Feb" },
  "gantt.mon.mar": { de: "MÃ¤r", en: "Mar" },
  "gantt.mon.apr": { de: "Apr", en: "Apr" },
  "gantt.mon.may": { de: "Mai", en: "May" },
  "gantt.mon.jun": { de: "Jun", en: "Jun" },
  "gantt.mon.jul": { de: "Jul", en: "Jul" },
  "gantt.mon.aug": { de: "Aug", en: "Aug" },
  "gantt.mon.sep": { de: "Sep", en: "Sep" },
  "gantt.mon.oct": { de: "Okt", en: "Oct" },
  "gantt.mon.nov": { de: "Nov", en: "Nov" },
  "gantt.mon.dec": { de: "Dez", en: "Dec" },

  // ---- dashboard tiles ----------------------------------------------------
  "dash.tile.valueDelivered": { de: "Wert geliefert", en: "value delivered" },
  "dash.tile.aiSpend": { de: "KI-Ausgaben", en: "AI spend" },
  // flat (Max-Abo): consumption in tokens, never a $ figure - the subscription
  // is a flatrate, so per-card dollars would misread as pay-per-token spend.
  "dash.tile.aiSpendFlat": { de: "KI-Verbrauch â€” Flat, im Abo inkl.", en: "AI usage â€” flat, incl. in plan" },
  // the flat plan's real cost unit: how much of the subscription the board ate.
  "dash.tile.aiPlanShare": { de: "KI-Verbrauch â€” Anteil am Abo (Woche)", en: "AI usage â€” share of plan (week)" },
  "dash.tile.margin": { de: "Marge (Wert âˆ’ KI)", en: "margin (value âˆ’ AI)" },
  "dash.tile.marginFlat": { de: "Marge (KI im Abo inkl.)", en: "margin (AI incl. in plan)" },
  "dash.tile.yield": { de: "First-Pass-Quote ({a}/{b})", en: "first-pass yield ({a}/{b})" },
  "dash.tile.automation": { de: "Automatisierungsgrad ({a}/{b} auto)", en: "automation rate ({a}/{b} auto)" },
  "dash.tile.leverage": { de: "Wert pro Touch-Einheit", en: "value per touch unit" },
  // ai_spend's flat-plan label, folded-in reset-projection hint (dash_panels.
  // aiSpendLabel) - only appended when the pace is heading somewhere notable.
  "dash.tile.aiPlanShareOverrun": { de: "droht zu Ã¼berziehen", en: "heading to overrun" },
  "dash.tile.aiPlanShareSurplus": { de: "nur {proj}% projiziert - Rest verfÃ¤llt", en: "only {proj}% projected - rest expires" },

  // ---- dashboard customizer ----------------------------------------------
  "dash.tileName.valueDelivered": { de: "Wert geliefert", en: "Value delivered" },
  "dash.tileName.aiSpend": { de: "KI-Ausgaben", en: "AI spend" },
  "dash.tileName.margin": { de: "Marge", en: "Margin" },
  "dash.tileName.yield": { de: "First-Pass-Quote", en: "First-pass yield" },
  "dash.tileName.automation": { de: "Automatisierungsgrad", en: "Automation rate" },
  "dash.tileName.leverage": { de: "Hebel pro Touch", en: "Leverage per touch" },
  "dash.panelName.sows": { de: "SoW-Marge", en: "SoW margin" },
  "dash.panelName.capacity": { de: "KapazitÃ¤tsanzeige", en: "Capacity gauge" },
  "dash.panelName.gates": { de: "Gate-Fehler", en: "Gate failures" },
  "dash.panelName.models": { de: "KI-Nutzung nach Modell", en: "AI usage by model" },
  "dash.panelName.work": { de: "Arbeitstabelle", en: "Work table" },
  "dash.customizeDone": { de: "Fertig", en: "Done" },
  "dash.customize": { de: "âš™ Anpassen", en: "âš™ Customize" },
  "dash.customizeTitle": { de: "Auf diesem Dashboard anzeigen", en: "Show on this dashboard" },
  "dash.customizeNote": {
    de: "Auch per Chat: â€žzeige nur Marge und Automatisierungâ€œ. Die Ã–konomie bleibt immer gemessen.",
    en: "Also via chat: â€œshow only margin and automationâ€. The economics stay measured either way.",
  },

  // ---- SoW panel ----------------------------------------------------------
  "dash.sow.title": {
    de: "SoW-Marge â€” ein Prozess = ein Statement of Work",
    en: "SoW margin â€” one process = one statement of work",
  },
  "dash.sow.note": {
    de: "abgerechnet = anerkannter Umsatz (Festpreis bei Lieferung Â· T&M wÃ¤chst mit den Stunden Â· keins = intern). Marge = abgerechnet âˆ’ KI-Kosten.",
    en: "billed = recognized revenue (fixed price on delivery Â· T&M accrues with hours Â· none = internal). margin = billed âˆ’ AI cost.",
  },
  "dash.sow.noteFlat": {
    de: "abgerechnet = anerkannter Umsatz (Festpreis bei Lieferung Â· T&M wÃ¤chst mit den Stunden Â· keins = intern). KI lÃ¤uft im Max-Abo (Flatrate): kein Geld pro Karte, Marge = abgerechnet. Die KI-Spalte zeigt den Anteil am Wochenkontingent (~ = aus dem laufenden Fenster geschÃ¤tzt).",
    en: "billed = recognized revenue (fixed price on delivery Â· T&M accrues with hours Â· none = internal). AI runs on the flat Max plan: no cash per card, margin = billed. The AI column shows the share of the weekly allowance (~ = estimated from the live window).",
  },
  "dash.sow.empty": {
    de: "Noch keine prozessgruppierte Arbeit. Ein Prozess bÃ¼ndelt seine Karten zu einem SoW; die Abrechnung pro Karte rollt hier auf.",
    en: "No process-grouped work yet. A process groups its cards into one SoW; per-card billing rolls up here.",
  },
  "dash.sow.col.name": { de: "statement of work", en: "statement of work" },
  "dash.sow.col.client": { de: "Kunde", en: "client" },
  "dash.sow.col.status": { de: "Status", en: "status" },
  "dash.sow.col.cards": { de: "Karten", en: "cards" },
  "dash.sow.col.hours": { de: "Stunden", en: "hours" },
  "dash.sow.col.billed": { de: "abgerechnet", en: "billed" },
  "dash.sow.col.aiCost": { de: "KI $", en: "AI $" },
  "dash.sow.col.aiPlan": { de: "KI (% Abo)", en: "AI (% plan)" },
  "dash.sow.col.margin": { de: "Marge", en: "margin" },
  "dash.flatIncl": { de: "inkl.", en: "incl." },
  "dash.sow.delivered": { de: "geliefert", en: "delivered" },
  "dash.sow.progress": { de: "{done}/{cards} fertig", en: "{done}/{cards} done" },
  "dash.sow.totalOne": { de: "gesamt (1 SoW)", en: "total (1 SoW)" },
  "dash.sow.totalMany": { de: "gesamt ({n} SoWs)", en: "total ({n} SoWs)" },

  // ---- capacity panel -----------------------------------------------------
  "dash.triangle.budget": { de: "Budget", en: "Budget" },
  "dash.triangle.timeline": { de: "Timeline", en: "Timeline" },
  "dash.triangle.scope": { de: "Scope", en: "Scope" },
  "dash.triangle.ok": { de: "grÃ¼n", en: "green" },
  "dash.triangle.red": { de: "blockiert", en: "blocked" },
  "dash.triangle.unknown": { de: "offen", en: "open" },
  // Standard PM vocabulary, owner-requested (2026-09-04: "man hat da eher
  // Velocity und Burnchart - kenne diese Sprache nicht" about the internal
  // word "Turns"): Restaufwand/Velocity are the terms a PM-literate owner
  // already knows; "Turns" never reaches this surface.
  "dash.triangle.etaOne": { de: "Restaufwand: ~{n} Tag(e)", en: "remaining: ~{n} day(s)" },
  "dash.triangle.etaRange": { de: "Restaufwand: ~{min}â€“{max} Tage", en: "remaining: ~{min}â€“{max} days" },
  "dash.triangle.msTurns": { de: "~{n} Schritte", en: "~{n} steps" },
  "dash.triangle.checkedAt": { de: "zuletzt geprÃ¼ft {when}", en: "last checked {when}" },
  "dash.triangle.msDone": { de: "fertig", en: "done" },
  "dash.triangle.msWait": { de: "wartet auf extern", en: "external wait" },
  // ---- the senior-PM one-pager (StatusPanel) ------------------------------
  // Conclusion first, in report language: a verdict, the ask, the roadmap as
  // states. The analysis corners live behind "Details".
  "dash.status.title": { de: "Status", en: "Status" },
  "dash.status.onTrack": { de: "Auf Kurs", en: "On track" },
  "dash.status.needsYou": { de: "Wartet auf dich", en: "Waiting on you" },
  "dash.status.atRisk": { de: "In Gefahr", en: "At risk" },
  "dash.status.progress": { de: "{pct}% geschafft", en: "{pct}% done" },
  "dash.status.needTitle": { de: "Ich brauche von dir", en: "I need from you" },
  "dash.status.answerHint": { de: "Antworten â€” Ã¶ffnet den Chat", en: "Answer â€” opens the chat" },
  "dash.status.roadmap": { de: "Roadmap", en: "Roadmap" },
  // "Der Weg" (pm-lean-advisor phase 3.1, 2026-09-04): the dependency chain,
  // not the parallel milestone list - who/du/agent/extern say whose move.
  "dash.status.path": { de: "Der Weg", en: "The path" },
  "dash.status.whoDu": { de: "Du", en: "You" },
  "dash.status.whoAgent": { de: "Agent", en: "Agent" },
  "dash.status.whoExtern": { de: "wartet extern", en: "external wait" },
  "dash.status.msRunning": { de: "lÃ¤uft", en: "running" },
  "dash.status.msPlanned": { de: "geplant", en: "planned" },
  "dash.status.msProposal": { de: "Vorschlag", en: "proposed" },
  "dash.status.capOk": { de: "KapazitÃ¤t reicht locker bis zum Wochen-Reset.", en: "Capacity comfortably lasts until the weekly reset." },
  "dash.status.capWarn": { de: "KapazitÃ¤t wird knapp vor dem Wochen-Reset.", en: "Capacity is getting tight before the weekly reset." },
  "dash.status.details": { de: "Details", en: "Details" },
  // ---- triage follow-up: the three corners own every deep-dive -------------
  "dash.corner.spentToDate": { de: "bisher {v}", en: "{v} spent" },
  "dash.corner.usageNote": {
    de: "Max-Abo: Budget = Plan-KapazitÃ¤t (Auslastung â†’ Projektion bis Reset), kein Geld.",
    en: "Max plan: budget = plan capacity (usage â†’ projection until reset), not money.",
  },
  "dash.corner.aiSpend": { de: "KI ${v}", en: "AI ${v}" },
  "dash.corner.aiUse": { de: "KI {v} Tok (Flat)", en: "AI {v} tok (flat)" },
  "dash.corner.aiPlan": { de: "KI {v} vom Abo", en: "AI {v} of plan" },
  "dash.corner.margin": { de: "Marge {v}", en: "margin {v}" },
  "dash.corner.wip": { de: "Laufende Arbeit {wip}/{limit} Â· {n} PlÃ¤tze frei", en: "Work in progress {wip}/{limit} Â· {n} slots free" },
  // Budget SURPLUS note (pm_triangle._budget_surplus) - the mirror of the red
  // overrun GateReason above, same corner, same spot, opposite direction.
  "dash.corner.surplusTitle": { de: "Budget Ã¼brig", en: "Budget headroom" },
  "dash.corner.surplusBody": {
    de: "Projektion nur {proj}% zum Reset â€” Kontingent verfÃ¤llt sonst ungenutzt.",
    en: "Projected only {proj}% by reset â€” the quota otherwise expires unused.",
  },
  "dash.usage.title": { de: "Nutzung â€” Claude-Abo", en: "Usage â€” Claude plan" },
  "dash.usage.unavailable": {
    de: "Nutzungsdaten nicht verfÃ¼gbar (kein Claude-Login gefunden).",
    en: "Usage data unavailable (no Claude login found).",
  },
  "dash.usage.used": { de: "{pct}% genutzt", en: "{pct}% used" },
  // window names by id - the daemon's label is German-only (spine/ops/usage.py)
  "dash.usage.win.five_hour": { de: "5 Stunden", en: "5 hours" },
  "dash.usage.win.weekly": { de: "Woche", en: "Week" },
  "dash.usage.win.weekly_opus": { de: "Woche Â· Opus", en: "Week Â· Opus" },
  "dash.usage.reset": { de: "Reset {when}", en: "resets {when}" },
  "dash.usage.pace": {
    de: "âš  Bei diesem Tempo ~{proj}% zum Reset â€” Limit ~{when} erschÃ¶pft, vor dem Reset.",
    en: "âš  At this pace ~{proj}% by reset â€” limit exhausted ~{when}, before it resets.",
  },
  "dash.capacity.title": {
    de: "KapazitÃ¤t â€” mehr Arbeit annehmen oder automatisieren?",
    en: "Capacity â€” take more work, or automate?",
  },
  "dash.capacity.note": {
    de: "WIP = laufende Agenten, die du betreuen kannst Â· Touch-Einheiten = deine Aufmerksamkeit als WÃ¤hrung gegen ein Tagesbudget Â· Headroom = freie WIP-PlÃ¤tze. Alle Schwellen sind Policy.",
    en: "WIP = running agents you can supervise Â· touch units = your attention as currency vs a daily budget Â· headroom = WIP slots left. All thresholds are policy.",
  },
  "dash.capacity.line": {
    de: "heute {a}/{b} Touch-Einheiten ({pct}%) Â· WIP {wip}/{limit} Â· Headroom",
    en: "today {a}/{b} touch units ({pct}%) Â· WIP {wip}/{limit} Â· headroom",
  },
  "dash.capacity.headroom": { de: "{n} Karten", en: "{n} cards" },
  "dash.capacity.below": {
    de: "Unter KapazitÃ¤t â†’ mehr annehmen: die Grenzkosten einer weiteren Karte sind nur Tokens.",
    en: "Below capacity â†’ intake more: marginal cost of one more card is tokens only.",
  },
  "dash.capacity.at": {
    de: "Auf Anschlag â†’ automatisieren: den hÃ¤ufigsten Gate-Fehler unten zu fixen schafft den meisten Headroom.",
    en: "At capacity â†’ automate: fixing the top gate failure below frees the most headroom.",
  },

  // ---- gate failures panel ------------------------------------------------
  "dash.gates.title": {
    de: "Gate-Fehler â€” was als NÃ¤chstes im Harness zu fixen ist",
    en: "Gate failures â€” what to fix in the harness next",
  },
  "dash.gates.empty": { de: "noch nichts erfasst", en: "none recorded yet" },

  // ---- models panel -------------------------------------------------------
  "dash.models.title": {
    de: "KI-Nutzung nach Modell â€” was eine Einheit Agentenarbeit kostet",
    en: "AI usage by model â€” what a unit of agent work costs",
  },
  "dash.models.note": {
    de: "Ã˜ $/Turn ist deine Angebotszahl: geschÃ¤tzte Turns Ã— Ã˜ Kosten â‰ˆ der KI-Preis einer kÃ¼nftigen Karte.",
    en: "avg $/turn is your quoting number: estimated turns Ã— avg cost â‰ˆ the AI price of a future card.",
  },
  "dash.models.col.model": { de: "Modell", en: "model" },
  "dash.models.col.turns": { de: "Turns", en: "turns" },
  "dash.models.col.tokIn": { de: "Tok rein", en: "tok in" },
  "dash.models.col.tokOut": { de: "Tok raus", en: "tok out" },
  "dash.models.col.cost": { de: "gesamt $", en: "total $" },
  "dash.models.col.avg": { de: "$/Turn", en: "$/turn" },
  "dash.models.col.tokPerTurn": { de: "Tok/Turn", en: "tok/turn" },
  "dash.models.col.planPerTurn": { de: "% Abo/Turn", en: "% plan/turn" },
  "dash.models.noteFlat": {
    de: "Max-Abo (Flatrate): Verbrauch zÃ¤hlt gegen das Kontingent, nicht in $. â€ž% Abo/Turnâ€œ ist deine Angebotszahl â€” was ein Turn dieses Modells vom Wochenkontingent frisst (~ = aus dem laufenden Fenster geschÃ¤tzt).",
    en: "Max plan (flat): usage counts against the quota, not in $. â€œ% plan/turnâ€ is your quoting number â€” what one turn of this model eats of the weekly allowance (~ = estimated from the live window).",
  },

  // ---- work panel ---------------------------------------------------------
  "dash.work.title": { de: "Erledigte Arbeit", en: "Work done" },
  "dash.work.legendAi": { de: "KI ($)", en: "AI ($)" },
  "dash.work.legendAiFlat": { de: "KI (Anteil am Abo)", en: "AI (share of plan)" },
  "dash.work.legendHuman": { de: "Mensch (Touch-Einheiten)", en: "human (touch units)" },
  "dash.work.col.card": { de: "Karte", en: "card" },
  "dash.work.col.lane": { de: "Lane", en: "lane" },
  "dash.work.col.model": { de: "Modell", en: "model" },
  "dash.work.col.tok": { de: "Tok rein/raus", en: "tok in/out" },
  "dash.work.col.aiCost": { de: "KI $", en: "AI $" },
  "dash.work.col.aiFlat": { de: "KI (% Abo)", en: "AI (% plan)" },
  "dash.work.col.touch": { de: "Touch", en: "touch" },
  "dash.work.col.split": { de: "Split", en: "split" },
  "dash.work.col.value": { de: "Wert", en: "value" },
  "dash.work.col.margin": { de: "Marge", en: "margin" },
  "dash.work.col.mode": { de: "Modus", en: "mode" },
  "dash.work.empty": { de: "noch keine Karten", en: "no cards yet" },
  "board.wip": { de: "in Arbeit", en: "WIP" },
  "board.touches": { de: "Eingriffe", en: "Touches" },
  "board.headroom": { de: "Luft", en: "Headroom" },

  // ---- boards (accounts-boards-prd phase 2) -------------------------------
  // The overflow hint is the one string that has to explain a column the user
  // did NOT create - see data/boards.ts renderColumns for why it exists.
  "board.overflowHint": {
    de: "Nicht auf diesem Board â€“ erscheint nur, solange hier Karten liegen",
    en: "Not on this board â€“ shown only while cards are sitting here" },
  "boards.title": { de: "Boards", en: "Boards" },
  "boards.intro": {
    de: "Ein Board ist eine gespeicherte Ansicht: Karten gibt es nur einmal, das Board entscheidet nur, welche Spalten du siehst. Der Ablauf selbst â€“ Gate vor Review, Merge â€“ bleibt derselbe.",
    en: "A board is a saved view: cards exist once, the board only decides which columns you see. The workflow itself â€“ gate before review, merge â€“ stays the same." },
  "boards.switch": { de: "Board wechseln", en: "Switch board" },
  "boards.manage": { de: "Boards verwaltenâ€¦", en: "Manage boardsâ€¦" },
  "boards.new": { de: "Neues Board", en: "New board" },
  "boards.newName": { de: "Mein Board", en: "My board" },
  "boards.shared": { de: "geteilt", en: "shared" },
  "boards.readonly": {
    de: "Das geteilte Board gehÃ¶rt dem Workspace â€“ nur der Owner kann es Ã¤ndern.",
    en: "The shared board belongs to the workspace â€“ only the owner can change it." },
  "boards.pick": { de: "WÃ¤hle ein Board zum Bearbeiten.", en: "Pick a board to edit." },
  "boards.name": { de: "Name", en: "Name" },
  "boards.columns": { de: "Spalten", en: "Columns" },
  "boards.addColumn": { de: "Spalte hinzufÃ¼gen", en: "Add column" },
  "boards.save": { de: "Speichern", en: "Save" },
  "boards.delete": { de: "Board lÃ¶schen", en: "Delete board" },
  // Henry's context chip on this screen's chat entry - the WORKFLOW a board's
  // cards run (gate before review, deploy) is his, even though the column
  // layout on this screen is edited by hand (boards.intro says as much).
  "boards.askContext": {
    de: "Es geht um das Board â€ž{name}â€œ (Spalten sind hier bearbeitbar, der Ablauf ist Henrys).",
    en: "This is about the \"{name}\" board (columns are edited here, the workflow is Henry's).",
  },
};
