import type { Dict } from "../index";

/** Keys for the board surface. Owned by that area - keep additions here so the
 *  dict never becomes a merge bottleneck. Every key needs BOTH languages. */
export const board: Dict = {
  // ---- lane-move verdicts (board.tsx laneVerdict) -------------------------
  // {why} / {verdict} carry the daemon's own technical report, untranslated.
  "board.verdict.gatingDone": {
    de: "Gate läuft, dann Merge nach main – Ergebnis kommt auf die Karte und in den Chat",
    en: "Gate is running, then merge into main – the result lands on the card and in the chat",
  },
  "board.verdict.gating": {
    de: "Gate läuft – Ergebnis kommt auf die Karte und in den Chat",
    en: "Gate is running – the result lands on the card and in the chat",
  },
  "board.verdict.gateRed": {
    de: "Gate rot – bleibt auf Review: {why}",
    en: "Gate red – stays in Review: {why}",
  },
  "board.verdict.gateOpen": {
    de: "GATE offen – bleibt auf Review: {why}",
    en: "GATE open – stays in Review: {why}",
  },
  "board.verdict.mergeConflict": {
    de: "MERGE-KONFLIKT – bleibt auf Review: {why}",
    en: "MERGE CONFLICT – stays in Review: {why}",
  },
  "board.verdict.cannotLand": {
    de: "Kann nicht landen – bleibt auf Review: {why}",
    en: "Can't land – stays in Review: {why}",
  },
  "board.verdict.review": {
    de: "Review: {verdict} — zum Landen auf Done ziehen",
    en: "Review: {verdict} — drag to Done to land it",
  },
  "board.verdict.merged": {
    de: "Fertig → committet & nach main gemergt",
    en: "Done → committed & merged into main",
  },
  "board.verdict.redundant": {
    de: "Redundant – war schon in main, Karte geschlossen",
    en: "Redundant – was already in main, card closed",
  },
  "board.verdict.dispatched": { de: "Dispatched – Session startet", en: "Dispatched – session starting" },
  "board.verdict.queued": { de: "Queued", en: "Queued" },

  "board.merge.mergeable": { de: "✓ bereit zu mergen", en: "✓ ready to merge" },
  "board.merge.redundant": { de: "redundant – schon in main", en: "redundant – already in main" },
  "board.merge.conflict": { de: "⚠ Konflikt mit main", en: "⚠ conflict with main" },
  "board.merge.checked": { de: "geprüft", en: "checked" },

  "board.accepted": { de: "Abgenommen", en: "Accepted" },

  // ---- card ---------------------------------------------------------------
  "board.card.gating": {
    de: "Der Harness prüft und merged – das kann ein paar Minuten dauern.",
    en: "The harness is gating and merging – this can take a few minutes.",
  },
  "board.card.delivered": { de: "Geliefert: {text}", en: "Delivered: {text}" },
  "board.card.replyReady": { de: "● Antwort da – tippen", en: "● reply is in – tap" },
  "board.card.menu": { de: "Kartenmenü", en: "Card menu" },
  "board.card.bounced": { de: "● abgelehnt – ansehen", en: "● bounced – take a look" },
  "board.noGit": { de: "(kein Git)", en: "(no git)" },
  "board.step": { de: "Schritt {n}", en: "step {n}" },
  "board.process": { de: "Prozess", en: "process" },
  "board.due": { de: "fällig {d}", en: "due {d}" },
  "board.onDevice": { de: "auf Gerät", en: "on device" },
  "board.deviceStale": { de: "Gerät offline?", en: "device offline?" },
  // flat plan (Max-Abo): a card's AI figure is its SHARE OF THE SUBSCRIPTION.
  // aiTok stays as the fallback for when the quota can't be calibrated.
  "board.aiPlan": { de: "KI {pct} vom Abo", en: "AI {pct} of plan" },
  "board.aiTok": { de: "KI {tok} Tok", en: "AI {tok} tok" },
  "board.mode.auto": { de: "auto · KI", en: "auto · AI" },
  "board.mode.assisted": { de: "begleitet · Mensch", en: "assisted · human" },

  // ---- next up ------------------------------------------------------------
  "board.nextUp": { de: "ALS NÄCHSTES", en: "NEXT UP" },
  "board.why.bounced": { de: "gate abgelehnt - fixen", en: "gate bounced - fix it" },
  "board.why.needsYou": { de: "Agent braucht dich", en: "agent needs you" },
  "board.why.human": { de: "dein Schritt", en: "your move" },
  "board.why.cowork": { de: "cowork", en: "cowork" },
  "board.why.next": { de: "als Nächstes", en: "up next" },
  "board.markDone": { de: "erledigt", en: "done" },
  "board.more": { de: "+{n} weitere", en: "+{n} more" },

  // ---- scope bar (board.tsx ScopeBar) --------------------------------------
  "board.scope.all": { de: "Alle", en: "All" },
  "board.scope.archived": { de: "Archiv", en: "Archive" },

  // ---- layout toggle --------------------------------------------------------
  "board.layout.board": { de: "Board", en: "Board" },
  "board.layout.timeline": { de: "Timeline", en: "Timeline" },
  "board.moveTo": { de: "Verschieben nach…", en: "Move to…" },
  "board.stepDone": { de: "Step erledigt – die Kette rückt vor", en: "Step done – the chain moves on" },
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
  "gantt.overdue": { de: "überfällig", en: "overdue" },
  "gantt.process": { de: "Prozess", en: "Process" },
  "gantt.steps": { de: "Schritte", en: "steps" },
  "gantt.legend": {
    de: "Balken = angelegt → letzte Aktivität (Done friert bei Abnahme ein) · blaue Linie = jetzt · ◆ = fällig",
    en: "Bar = created → last activity (Done freezes at acceptance) · blue line = now · ◆ = due",
  },
  "gantt.mon.jan": { de: "Jan", en: "Jan" },
  "gantt.mon.feb": { de: "Feb", en: "Feb" },
  "gantt.mon.mar": { de: "Mär", en: "Mar" },
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
  "dash.tile.aiSpendFlat": { de: "KI-Verbrauch — Flat, im Abo inkl.", en: "AI usage — flat, incl. in plan" },
  // the flat plan's real cost unit: how much of the subscription the board ate.
  "dash.tile.aiPlanShare": { de: "KI-Verbrauch — Anteil am Abo (Woche)", en: "AI usage — share of plan (week)" },
  "dash.tile.margin": { de: "Marge (Wert − KI)", en: "margin (value − AI)" },
  "dash.tile.marginFlat": { de: "Marge (KI im Abo inkl.)", en: "margin (AI incl. in plan)" },
  "dash.tile.yield": { de: "First-Pass-Quote ({a}/{b})", en: "first-pass yield ({a}/{b})" },
  "dash.tile.automation": { de: "Automatisierungsgrad ({a}/{b} auto)", en: "automation rate ({a}/{b} auto)" },
  "dash.tile.leverage": { de: "Wert pro Touch-Einheit", en: "value per touch unit" },

  // ---- dashboard customizer ----------------------------------------------
  "dash.tileName.valueDelivered": { de: "Wert geliefert", en: "Value delivered" },
  "dash.tileName.aiSpend": { de: "KI-Ausgaben", en: "AI spend" },
  "dash.tileName.margin": { de: "Marge", en: "Margin" },
  "dash.tileName.yield": { de: "First-Pass-Quote", en: "First-pass yield" },
  "dash.tileName.automation": { de: "Automatisierungsgrad", en: "Automation rate" },
  "dash.tileName.leverage": { de: "Hebel pro Touch", en: "Leverage per touch" },
  "dash.panelName.sows": { de: "SoW-Marge", en: "SoW margin" },
  "dash.panelName.capacity": { de: "Kapazitätsanzeige", en: "Capacity gauge" },
  "dash.panelName.gates": { de: "Gate-Fehler", en: "Gate failures" },
  "dash.panelName.models": { de: "KI-Nutzung nach Modell", en: "AI usage by model" },
  "dash.panelName.work": { de: "Arbeitstabelle", en: "Work table" },
  "dash.customizeDone": { de: "Fertig", en: "Done" },
  "dash.customize": { de: "⚙ Anpassen", en: "⚙ Customize" },
  "dash.customizeTitle": { de: "Auf diesem Dashboard anzeigen", en: "Show on this dashboard" },
  "dash.customizeNote": {
    de: "Auch per Chat: „zeige nur Marge und Automatisierung“. Die Ökonomie bleibt immer gemessen.",
    en: "Also via chat: “show only margin and automation”. The economics stay measured either way.",
  },

  // ---- SoW panel ----------------------------------------------------------
  "dash.sow.title": {
    de: "SoW-Marge — ein Prozess = ein Statement of Work",
    en: "SoW margin — one process = one statement of work",
  },
  "dash.sow.note": {
    de: "abgerechnet = anerkannter Umsatz (Festpreis bei Lieferung · T&M wächst mit den Stunden · keins = intern). Marge = abgerechnet − KI-Kosten.",
    en: "billed = recognized revenue (fixed price on delivery · T&M accrues with hours · none = internal). margin = billed − AI cost.",
  },
  "dash.sow.noteFlat": {
    de: "abgerechnet = anerkannter Umsatz (Festpreis bei Lieferung · T&M wächst mit den Stunden · keins = intern). KI läuft im Max-Abo (Flatrate): kein Geld pro Karte, Marge = abgerechnet. Die KI-Spalte zeigt den Anteil am Wochenkontingent (~ = aus dem laufenden Fenster geschätzt).",
    en: "billed = recognized revenue (fixed price on delivery · T&M accrues with hours · none = internal). AI runs on the flat Max plan: no cash per card, margin = billed. The AI column shows the share of the weekly allowance (~ = estimated from the live window).",
  },
  "dash.sow.empty": {
    de: "Noch keine prozessgruppierte Arbeit. Ein Prozess bündelt seine Karten zu einem SoW; die Abrechnung pro Karte rollt hier auf.",
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
  "dash.triangle.title": { de: "Ziel & Dreieck", en: "Goal & triangle" },
  "dash.triangle.budget": { de: "Budget", en: "Budget" },
  "dash.triangle.timeline": { de: "Timeline", en: "Timeline" },
  "dash.triangle.scope": { de: "Scope", en: "Scope" },
  "dash.triangle.ok": { de: "grün", en: "green" },
  "dash.triangle.red": { de: "blockiert", en: "blocked" },
  "dash.triangle.unknown": { de: "offen", en: "open" },
  "dash.triangle.blocked": { de: "Plan-Gate ROT", en: "plan gate RED" },
  "dash.triangle.ready": { de: "Plan-Gate grün — bereit", en: "plan gate green — ready" },
  "dash.triangle.eta": { de: "ETA ~{n} Tage", en: "ETA ~{n} days" },
  "dash.triangle.earliest": { de: "frühestens fertig: {when}", en: "earliest done: {when}" },
  // ---- triage follow-up: the three corners own every deep-dive -------------
  "dash.corner.spentToDate": { de: "bisher {v}", en: "{v} spent" },
  "dash.corner.usageNote": {
    de: "Max-Abo: Budget = Plan-Kapazität (Auslastung → Projektion bis Reset), kein Geld.",
    en: "Max plan: budget = plan capacity (usage → projection until reset), not money.",
  },
  "dash.corner.aiSpend": { de: "KI ${v}", en: "AI ${v}" },
  "dash.corner.aiUse": { de: "KI {v} Tok (Flat)", en: "AI {v} tok (flat)" },
  "dash.corner.aiPlan": { de: "KI {v} vom Abo", en: "AI {v} of plan" },
  "dash.corner.margin": { de: "Marge {v}", en: "margin {v}" },
  "dash.corner.wip": { de: "WIP {wip}/{limit} · {n} frei", en: "WIP {wip}/{limit} · {n} free" },
  "dash.usage.title": { de: "Nutzung — Claude-Abo", en: "Usage — Claude plan" },
  "dash.usage.unavailable": {
    de: "Nutzungsdaten nicht verfügbar (kein Claude-Login gefunden).",
    en: "Usage data unavailable (no Claude login found).",
  },
  "dash.usage.used": { de: "{pct}% genutzt", en: "{pct}% used" },
  "dash.usage.reset": { de: "Reset {when}", en: "resets {when}" },
  "dash.usage.pace": {
    de: "⚠ Bei diesem Tempo ~{proj}% zum Reset — Limit ~{when} erschöpft, vor dem Reset.",
    en: "⚠ At this pace ~{proj}% by reset — limit exhausted ~{when}, before it resets.",
  },
  "dash.capacity.title": {
    de: "Kapazität — mehr Arbeit annehmen oder automatisieren?",
    en: "Capacity — take more work, or automate?",
  },
  "dash.capacity.note": {
    de: "WIP = laufende Agenten, die du betreuen kannst · Touch-Einheiten = deine Aufmerksamkeit als Währung gegen ein Tagesbudget · Headroom = freie WIP-Plätze. Alle Schwellen sind Policy.",
    en: "WIP = running agents you can supervise · touch units = your attention as currency vs a daily budget · headroom = WIP slots left. All thresholds are policy.",
  },
  "dash.capacity.line": {
    de: "heute {a}/{b} Touch-Einheiten ({pct}%) · WIP {wip}/{limit} · Headroom",
    en: "today {a}/{b} touch units ({pct}%) · WIP {wip}/{limit} · headroom",
  },
  "dash.capacity.headroom": { de: "{n} Karten", en: "{n} cards" },
  "dash.capacity.below": {
    de: "Unter Kapazität → mehr annehmen: die Grenzkosten einer weiteren Karte sind nur Tokens.",
    en: "Below capacity → intake more: marginal cost of one more card is tokens only.",
  },
  "dash.capacity.at": {
    de: "Auf Anschlag → automatisieren: den häufigsten Gate-Fehler unten zu fixen schafft den meisten Headroom.",
    en: "At capacity → automate: fixing the top gate failure below frees the most headroom.",
  },

  // ---- gate failures panel ------------------------------------------------
  "dash.gates.title": {
    de: "Gate-Fehler — was als Nächstes im Harness zu fixen ist",
    en: "Gate failures — what to fix in the harness next",
  },
  "dash.gates.empty": { de: "noch nichts erfasst", en: "none recorded yet" },

  // ---- models panel -------------------------------------------------------
  "dash.models.title": {
    de: "KI-Nutzung nach Modell — was eine Einheit Agentenarbeit kostet",
    en: "AI usage by model — what a unit of agent work costs",
  },
  "dash.models.note": {
    de: "Ø $/Turn ist deine Angebotszahl: geschätzte Turns × Ø Kosten ≈ der KI-Preis einer künftigen Karte.",
    en: "avg $/turn is your quoting number: estimated turns × avg cost ≈ the AI price of a future card.",
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
    de: "Max-Abo (Flatrate): Verbrauch zählt gegen das Kontingent, nicht in $. „% Abo/Turn“ ist deine Angebotszahl — was ein Turn dieses Modells vom Wochenkontingent frisst (~ = aus dem laufenden Fenster geschätzt).",
    en: "Max plan (flat): usage counts against the quota, not in $. “% plan/turn” is your quoting number — what one turn of this model eats of the weekly allowance (~ = estimated from the live window).",
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
};
