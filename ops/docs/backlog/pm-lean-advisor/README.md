# PM-Lean-Advisor — den Briefing-Kern durch messbaren Rat ersetzen

Owner-Beschwerde (2026-09-04, mehrfach in einer Session): "Neu planen" dauert
7 Minuten, danach sieht das Board exakt gleich aus, und der Output ist
"Infos, womit ich nichts anfangen kann". Owner-Steering für den Umbau:
"Ideal soll es wirklichen Mehrwert bringen - user informieren: hey, wenn das
dein Ziel ist, musst du mehr oder weniger X machen. Das jetzige System ist
viel, aber wenig sinnvoller Output."

## Befund (gemessen, nicht vermutet)

1. **Ein "Neu planen"-Tap = bis zu 4 sequenzielle Modell-Turns** in
   `cells/copilot/planning/pm.py brief()`: Planer (Riesen-Prompt: Charter +
   Policy + Ökonomie + Quota + Systemzustand + letzter Plan + Board-Snapshot)
   → `_verify_plan` (2. Turn) → Reparatur (3. Turn) → Re-Verify (4. Turn).
   Gemessen 2026-09-04: Läufe um 13:06 und 13:15, je ~7 Minuten.
2. **Rotes Gate = stilles Nichts.** `plan_status: blocked` (Scope) →
   `make_plan` dispatcht nichts, Board unverändert, und die UI erklärt das
   nirgends. Der 7-Minuten-Lauf endet für den Owner in exakt null sichtbarer
   Wirkung.
3. **Der Prüfer streitet mit dem Planer in Endlosschleife.** Seit 07:14
   blockiert derselbe Befund (festes Datum auf externem Google-Review-Wait)
   jede Runde neu; die Selbstreparatur kriegt den Fall trotz expliziter
   Repair-Rules und existierendem `calendar_wait`-Mechanismus nicht
   zuverlässig hin. Der Owner sieht den Roh-Prüfertext (teils englisch).
4. **Der Ziel-Abgleich urteilt falsch über Karten.** Der Plan von 13:15
   markierte Play-Store-Karten als "stale" - der Owner stellte klar: nicht
   Duplikat, nicht veraltet, die Karte trägt ein Update. Vom Titel auf den
   Wert einer Karte zu schließen ist unzuverlässig.

## Externe Evidenz (Recherche 2026-09-04, zwei unabhängige Sweeps)

**Markt:** Kein überlebendes Produkt lässt ein LLM autonome PM-Entscheidungen
oder Kalenderdaten setzen. Height ("world's first autonomous project
collaboration tool", Okt 2024) wurde Sept 2025 abgeschaltet - 5 Monate nach
Launch, trotz $18M. Linear/Jira-Rovo/Asana/ClickUp/Shortcut liefern alle
denselben Zuschnitt: Triage-Vorschläge, Status-Zusammenfassungen,
Task-Breakdown aus Prosa - immer draft-and-suggest, nie Vollzug. Termine
prognostizieren nur Constraint-Solver über menschliche Schätzungen (Motion,
LiquidPlanner: probabilistische Spannen, kein LLM-Urteil).

**Forschung:**
- LLMs schätzen Dauern schwach (r=0.35-0.55 zu Ist-Zeiten; auf harten Paaren
  unter Zufallsniveau) - https://openreview.net/pdf?id=x8nL1qVPD0
- Intrinsische Selbstkorrektur VERSCHLECHTERT Reasoning (der Prüfer erbt die
  Fehlermuster des Generators) - https://arxiv.org/abs/2310.01798 . Unser
  4-Turn-Loop ist exakt dieses Anti-Pattern; das ewige rote Gate ist sein
  vorhergesagtes Symptom.
- LLM-Modulo / "LLM proposes, code disposes" als tragfähiges Muster -
  https://arxiv.org/abs/2402.01817 ; Anthropic Building Effective Agents;
  LangChain Ambient Agents (notify/ask/act - unsere Autonomie-Leiter IST
  dieses Muster); Horvitz mixed-initiative (CHI 1999).

**Konsequenz:** Das System hat die richtigen Organe (gemessene Ökonomie,
Autonomie-Leiter, Henry als Broker) um das falsche Herz: einen
Dokument-Generator, der genau die zwei Dinge tut, die nachweislich nicht
funktionieren (Termine erfinden, sich selbst prüfen).

## Zielbild: User Story

Ziel gesetzt: "HelmDeck aufräumen, testen, stabilisieren und launchen."

- **Morgens, Übersicht** (aktualisiert sich selbst, kein Knopf):
  "● Auf Kurs - bei deinem Tempo (~20 Turns/Tag) ist der Zielpfad in
  **1-3 Tagen** durch. Budget trägt das: Woche 39%, projiziert 59% zum
  Reset." Gemessene Spanne, nie ein erfundenes Datum.
- **Ziel geändert** → Save ist sofort (Settings-Write, keine KI). Im
  Hintergrund ein kleiner Turn; Ergebnis landet in "Wartet auf dich":
  "Neues Ziel geprüft. 2 Karten zahlen ein. Es fehlen: A, B, C - anlegen?
  [Anlegen] [Bearbeiten] [Nein]".
- **Unentscheidbares** → Henry-Frage mit Optionen statt Prüfer-Prosa:
  "Google-Review-Dauer unbekannt: Spanne offen lassen oder +5 Tage Puffer?
  [Offen lassen] [+5 Tage]".
- **Nichts los** → "● Auf Kurs · zuletzt geprüft 18:40 · nichts zu ändern."
  Ein Satz, dann Stille.

## UX-Regeln (bindend)

1. **Kein Warte-Knopf.** Abgleich läuft ereignisgesteuert (Karte fertig,
   Ziel geändert, Budget-Schwelle, max. alle X Stunden). Nichts in der UI
   wartet auf einen Modell-Turn.
2. **Jeder PM-Output hat eine von drei Formen:** (a) Ampel + gemessene
   Spanne (Code), (b) Vorschlag mit Tap-Aktionen und SICHTBARER Begründung,
   (c) Henry-Frage mit Optionen. Nie Fließtext-Analyse, nie ein erfundenes
   Datum.
3. **Vorschläge landen in "Wartet auf dich"**, nicht in einem PM-Reich.
4. **Abgelehnt = gemerkt.** Ein ignorierter/abgelehnter Vorschlag zur selben
   Karte kommt nicht wieder (persistiert, kein Re-Nag).
5. **Die Triage fragt, sie urteilt nicht.** Konservative Schwelle; bei
   Unklarheit schweigen statt raten. Drei dumme Vorschläge und der Owner
   ignoriert das Panel für immer.
6. **Karten sind für die KI undurchsichtig** (Play-Store-Lektion): eine
   Karte kann Informationsträger sein, nicht nur Task. Board-Hygiene-
   Vorschläge nur bei harten Belegen - und in Phase 1 GAR NICHT.

## Umbau

**Behalten (arbeitet bereits richtig):**
- `pm_triangle` / `economics()` / `_quota_signal` / `_pace` - gemessene
  Ampeln, Code, kein LLM. Ausbauen: ETA als Spanne (Rest-Turns / Tempo,
  optimistisch-pessimistisch) statt LLM-`target_date`.
- Nachtschicht-Ticker + Autonomie-Leiter (notify/ask/act) + Henry-Broker.
- `set_goal` als reiner Settings-Write (seit 7722873 auch in der UI so).

**Löschen:**
- Der 4-Turn-`brief()`-Kern: `_verify_plan`, Reparatur-Runde, Gate,
  LLM-Meilensteine mit `target_date`/`est_turns`-Datierung.
- Der "Neu planen"-Warteknopf (Dashboard-Pille + Settings-Button samt
  `usePmReplan`-Polling); ersatzlos, siehe UX-Regel 1.
- Das Plan-Dokument als Owner-Artefakt (Datei darf als internes Log bleiben).

**Neu (je ein kleiner, schneller Turn, günstiges Modell per Routing-Policy):**
- `goal_check`: Ziel + Board-Titel + Messwerte rein; raus: passt/fehlt-Liste
  als Vorschlag mit Begründung (Phase 2).
- `goal_breakdown`: bei Zieländerung fehlende Karten VORSCHLAGEN (Phase 2).
- Eskalations-Formulierung: aus einem Mess-Trigger (Budget-Riss,
  Kurs-Verlust) eine Henry-Frage mit 2 Optionen bauen (Phase 1).

**Phasen:**
1. **Ehrlich + still:** Brief-Kern und Knopf raus; Übersicht-Panel zeigt
   gemessene Ampeln + ETA-Spanne + "zuletzt geprüft"; Mess-Trigger →
   Henry-Fragen. Danach existiert "7 Minuten und nichts passiert" nicht mehr.
2. **Rat:** goal_check + goal_breakdown als Vorschläge in "Wartet auf dich",
   mit Begründung, Ablehnungs-Gedächtnis, konservativer Schwelle.
3. **Optional, nur nach bewährter Trefferquote:** Board-Hygiene-Vorschläge
   (Duplikat/erledigt) - weiterhin nie autonom.

## Akzeptanz

- Kein UI-Element wartet auf einen Modell-Turn > 5s.
- `grep`-beweisbar: kein LLM-generiertes Kalenderdatum erreicht die UI.
- Ein Zieländerungs-Flow endet in < 3 Min in einem beantwortbaren Vorschlag
  in "Wartet auf dich" (oder in Stille, wenn nichts fehlt).
- Ein abgelehnter Vorschlag zur selben Karte taucht nicht wieder auf
  (Test mit persistiertem Dismissal).
- Das rote-Gate-Konstrukt existiert nicht mehr; sein einziger Nachfolger
  ist die Henry-Frage mit Optionen.

Status: **backlog** · Priorität: hoch · Angelegt 2026-09-04 nach
Owner-Diskussion (Research-Sweeps: Markt + Forschung, IDs in Session).
