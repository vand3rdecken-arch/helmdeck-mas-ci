# Token-Burn-Hardening — nie wieder ein 190-Mio-Token-Turn

**Anlass (gemessen, 2026-09-10/11):** Karte 20260910-155445-machine (Wear-OS
Play-Produktionsfreigabe) verbrannte ~190,4 Mio Tokens (~137,7M in / 188k out,
$86+ Events-Summe, ein Einzelturn $37.77) in EINEM 94-Minuten-Turn und starb am
Session-Limit. Forensik (Transkript `96dfda7f`, 210 MB):

- windows-mcp `Snapshot` liefert auf der Play Console ~600–700 KB UIA-Baum
  PRO AUFRUF; 122 Snapshots + 61 Screenshots = 104 MB Tool-Results.
- Jede API-Iteration zahlt den GESAMTEN akkumulierten Kontext erneut
  (Cache-Read): der finale Turn allein 105,5M Cache-Read bei ~604k Kontext
  pro Iteration. Kostenwachstum ~quadratisch.
- KEIN Mechanismus greift mid-turn: Auto-Compact ist ein Post-Turn-Hook
  (lief nie, weil der Turn RAISTE), die 150k-Bloat-Eskalation ist idle-only,
  und Kontext blieb bei ~75% eines 1M-Fensters — Compaction war die falsche
  Achse. Henry flaggte 4x, hatte aber keinen Hebel auf einen LIVE-Turn.
- Paseo-Vergleich: dort SDK-in-stream-Compaction (mid-turn möglich), aber
  ebenfalls NULL Kosten-Tripwire — derselbe Burn wäre dort unbemerkt gelaufen.

Vier Karten, Risiko-Reihenfolge. A+B parallel dispatchbar, C nach A
(teilt den mcp-config-Seam), D unabhängig. A+B allein deckeln eine
Wiederholung auf ~5% der Kosten; B generalisiert auf UNBEKANNTE künftige
Burn-Muster.

---

## Karte A — MCP-Result-Capper (klein, Worktree-Worker)

Stdio-Proxy `ops/tools/mcp_capper.py` VOR windows-mcp (und künftige MCP-
Server): Tool-Results > N Zeichen (Default 50k, per-Tool-Override in policy)
werden gekürzt mit Marker-Tail "…[gekürzt — Query verengen]". Verdrahtung:
`build_argv`s `--mcp-config` (spine/agent/drivers.py) zeigt für Machine-Karten
auf den Proxy statt direkt auf `uvx windows-mcp`.

WICHTIG (Round-1-Fehlanalyse, nicht wiederholen): Daemon-seitiges Kürzen im
Stream-Fold spart NULL Tokens — `fold_timeline_event` beobachtet nur, das
Result ist da schon im Modellkontext. Der Cap MUSS upstream im MCP-Kanal
sitzen.

Traps: uvx-Cold-Start ~20–25s (MCP_TIMEOUT=60000 beibehalten, Memory
windows-mcp-cli-cold-start-timeout); MCP-Ghost-Regression 9cb229d darf nicht
brechen.
Verify: Play-Console-Snapshot durch den Proxy replayen → Kürzung + Marker im
CLI-Stream; bestehender mcp-config-Pfad weiter grün.

## Karte B — Turn-Burn-Tripwire (mittel, Worktree-Worker)

Pro-Turn-Akkumulator im Driver-Pump: `fold_timeline_event` sieht jeden
usage-Block live (drivers.py:661ff, inkl. cacheRead) — Summe pro Turn ist
"derived from the runtime's own signal, folded at event time, one owner"
(gesetzeskonform, kein Monkey-Patch). Schwellen in policy als **%-Anteil der
Wochen-Quota** (plan_calibration, Dekret costs-are-plan-share — NICHT € oder
absolute Tokens). Seed aus dem Vorfall: der $37-Turn war ~8.8% Quota; Default
soft=2%, hard=5% hätte nach ~20 bzw. ~50 Minuten gegriffen.

- soft → Henry-Eskalation neue Art `turn-burn` MIT Evidenz (kumulative
  Tokens, Iterationszahl, Top-3-Result-Produzenten) — anders als
  context-bloat ist sie mid-turn actionable.
- hard → kooperativer Interrupt über bestehendes `cancel(tid)`/Steer-Replace,
  Karte → needs_you + Burn-Report. Session überlebt (resumable).

EXPLIZITES NICHT-ZIEL: kein Wall-Clock-Cap (Memory turn-idle-watchdog:
nie wieder einführen), Silence-Watchdog unangetastet. Stale-Result-Race
0160647 nicht reintroduzieren.
Verify: Unit-Test synthetischer Stream über beide Schwellen (Muster
test_cost_watch.py): soft feuert genau 1x, hard cancelt über den
Cancel-Intent-Pfad.

## Karte C — Browser-Verben für Machine-Karten (groß, Worktree-Worker)

Fünf BEGRENZTE Verben über `spine/media/browsercap.py` (CDP-Attach an den
persistenten eingeloggten HelmDeck-Chrome), exponiert über denselben
mcp-config-Seam wie Karte A:
`navigate` / `read` (viewport-scoped Markdown, hart gedeckelt) / `find`
(Selector-Query, max 20 interaktive Elemente) / `click(selector)` /
`type(selector, text)`. Output-Shaping IST das Deliverable (<5k Zeichen
pro Aktion, gemessen vs. ~700k Snapshot). Referenz für CDP-Härtung:
netdance (`Documents/Private Project/netdance` — Chrome-147+ WS-Discovery,
Port-Token, Anti-Automation); ERSTER Commit = Lese-Notiz der netdance-
CDP-Schicht (Aufwand ist bis dahin unsicher).

Brief-Update machine-worker: Web-Seiten → Browser-Verben oder `Scrape`,
NIE Full-`Snapshot` (Snapshot nur für Nicht-Browser-Desktop-UI). TRAP:
Byte-Mirror machine-worker.md ↔ `harness._DEFAULT_MACHINE` (gated).
Debt-Pflicht: jedes nicht-viewport-gescopte Output = Shortcut → debt.py.
Verify: echte Play-Console-Dev-Seite über die Verben fahren, Result-Größen
messen; adversarial-test auf den Selector-Miss-Pfad.

## Karte D — Compaction-Hygiene (klein)

Zwei gemessene Defekte, NICHT kostenkausal im Vorfall (deshalb kleine Karte,
kein Redesign):
1. `compact_pending` überlebt eine `ctx_window`-Neuableitung nicht
   (sessions.py:668 cleart bedingungslos beim Unterschreiten der NEUEN
   0.8×Fenster-Marke — Karte 20260910-134430: Queue verdampfte durch
   1M-Reklassifikation bei 604k Kontext). Fix: gegen die neue Schwelle
   re-evaluieren statt clearen.
2. Owner-Steer schneidet laufende Compaction nach 25s (`_COMPACT_WAIT_S`) —
   Paseo-Semantik übernehmen: Steer wartet Compaction aus
   (steerActiveTurn → unavailable while compacting) bzw. Wait deutlich
   erhöhen, Re-Queue als Fallback behalten.
Verify: test_card_compact_interrupt.py + test_compact_mark.py erweitern.
