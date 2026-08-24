# Burn-Guard: Loop-Erkennung mit PM-Eskalation — Dev-Plan

**Problem.** Seit der Turn nur noch durch STILLE begrenzt ist (1921fcd, korrekt),
gibt es keinen Schutz gegen einen Worker, der *aktiv* in einer Schleife hängt:
er streamt Frames (resettet den Watchdog) und brennt unbegrenzt Token, bis der
Owner Stop drückt. Der alte 1800s-Wall-Clock-Kill deckte das zufällig mit ab —
brutal und falsch (er killte auch produktive Läufe), aber die Lücke ist real.

**Ansatz (Owner-Entscheid).** Nicht der Driver urteilt und nicht der Owner ist
die erste Instanz — der **PM** ist es. Der Driver liefert nur das *mechanische
Signal* (er allein sieht die Frames), der PM beurteilt mit Kontext („legitimer
Retry mit Backoff" vs. „sinnlose Schleife"), korrigiert per Steer und eskaliert
an den Owner erst, wenn seine Korrekturen nicht greifen — exakt die bestehende
RESOLVE-Leiter (classify → act → re-check, max. Versuche, Eskalation nur mit
Unblock-Vorschlag).

**Gesetzes-Check (CLAUDE.md).** NO-MONKEY-PATCH: das Signal wird am
EVENT-ZEITPUNKT aus den Stream-Frames gefaltet (ein Fold in `_on_event`, neben
`_scan_bg`), als First-Class-Zustand über den EINEN Owner (`sessions._mutate`)
persistiert — kein Transcript-Re-Scan, kein geratener Flag. Measured economics:
jeder PM-Urteilsturn wird wie jeder Plan-Turn verbucht. Kein Shortcut → kein
Debt-Eintrag geplant.

---

## Phase 1 — Mechanik: der Fold im Driver (Signal, kein Urteil)

`drivers._on_event` faltet pro Turn (`cur`):
- `tool_calls` — Zähler aller `tool_use`-Frames.
- `repeat` — `{sig, n, sample}`: `sig = name + sha1(kanonisiertes input)[:12]`;
  identischer Folge-Call → `n += 1`, sonst Reset auf den neuen sig. `sample` =
  gekürzter Input (≤200 Z.) für die spätere PM-Evidenz.
- Schwellen aus `settings.policy` (Defaults): `burn_repeats: 5`,
  `burn_toolcalls: 75`. Re-Fire nur bei Verdopplung (5, 10, 20 … / 75, 150 …),
  damit ein laufender Loop nicht pro Frame ein Signal spammt.
- Schwellenübertritt → `sessions.flag_burn(tid, evidence)` (lazy import wie
  überall): `_mutate` setzt `t["burn"] = {kind, n, sig, sample, ts, fired}` und
  `events.emit("burn", …)`. Actionlog-Note in die Karte („⚠ Worker wiederholt
  denselben Befehl (5×) — PM prüft"). KEIN Modellaufruf im Driver.

Aufwand: ~1h. Risiko: keins (reiner Beobachter; Fehler im Fold sind
best-effort-gekapselt wie `_scan_bg`).

## Phase 2 — Urteil: `pm.review_burn(tid)` (die RESOLVE-Leiter, live)

Auslöser: `sessions.flag_burn` startet einen Thread → `pm.review_burn(tid)`
(analog `resolve_card_now`: `_resolving`-Lock, Tagesbudget teilt sich
`_RESOLVE_MAX`, „busy/exhausted" identisch).

1. **Evidenz bauen** — aus dem persistierten `t["burn"]` + Karten-Task +
   letzter Reply-Auszug. KEIN Transcript-Re-Scan (die Evidenz wurde am
   Event-Zeitpunkt mitgeschrieben).
2. **Ein `_ask()`-Urteil** (Plan-Mode, wie jeder PM-Call, verbucht):
   Verdikt `legit | loop | unsure` + bei `loop` ein konkreter Korrektur-Text
   („derselbe adb-Befehl schlägt 5× mit demselben Fehler fehl — brich den
   Ansatz ab, lies die Fehlermeldung wörtlich, …").
3. **Handeln nach `pm.autonomy`:**
   - `notify` → nur Owner-Push mit Evidenz (der PM fasst nichts an).
   - `ask`/`act` → `sessions.steer(tid, korrektur, actor="pm",
     source="pm-burn")` — Steer-während-läuft macht bereits
     Interrupt-and-Replace (a36d962), der Loop wird also unterbrochen und
     derselbe Kontext läuft mit Kurskorrektur weiter. `legit` → nichts tun,
     `fired`-Marke bleibt (Re-Fire erst bei Verdopplung).
4. **Eskalation:** feuert das Signal nach 2 PM-Korrekturen erneut →
   `_give_up`-Pfad: Owner-Push mit Unblock-Vorschlag (bestehende
   `_unblock_proposal`-Schiene), keine weiteren Auto-Korrekturen heute.

Aufwand: ~2h. Risiko: PM-Fehlurteil unterbricht einen legitimen Lauf → durch
Interrupt-and-Replace verliert er nichts (gleiche Session, Arbeit auf Platte),
der Schaden ist ein Umweg-Turn.

## Phase 3 — Sichtbarkeit (App)

- Karte: kleines Burn-Badge solange `t["burn"].active` (⟳ „wiederholt sich"),
  verschwindet mit dem nächsten sauberen Turn-Ende.
- PM-Aktivität läuft über die bestehenden `_activity`/`_say`-Zeilen.
- i18n de+en. UI-Gesetz: Screenshot + JUDGEN, nicht nur rendern.

Aufwand: ~1h inkl. Screenshot-Urteil (OTA danach).

## Phase 4 — Tests (Gate-fähig, self-sandboxed)

- `fake_claude.py` bekommt `__LOOP__:n` — emittiert n IDENTISCHE
  `tool_use`-Frames (+ je ein `tool_result`) vor dem Result.
- `ops/tests/test_burn_guard.py` pinnt:
  1. Fold zählt identische Folge-Calls; variierende Calls resetten.
  2. Signal feuert bei 5 und wieder bei 10 — nicht bei 6–9 (kein Spam).
  3. `flag_burn` persistiert First-Class (`t["burn"]`), Event emittiert.
  4. `review_burn` mit gemocktem `_ask`: `loop` → genau EIN korrigierender
     Steer (source="pm-burn"); `legit` → kein Steer.
  5. Zweites Feuern nach 2 Versuchen → Eskalationspfad (Push-Stub) statt Steer.
  6. `autonomy=notify` → nie ein Steer, nur Push.
- Bestehende Suiten (idle-watchdog, cancel/resume, steer-replace) bleiben grün.

Aufwand: ~1.5h.

## Phase 5 — Rollout

1. Commit (Verhalten + Tests + i18n in EINEM Commit — Gate-Base-Lag-Regel).
2. Daemon-Neustart (kein Live-Turn), OTA für das Badge.
3. Live-Verifikation am echten Fall: die Tester-Rekrutierungs-Karte ist der
   natürliche Testkandidat (lange Maschinen-Läufe).
4. Memory-Eintrag (Fehlerklasse + Verhalten), MEMORY.md-Zeile.

---

## Entscheidungen für den Owner (mit Empfehlung)

| Frage | Empfehlung |
|---|---|
| Schwelle Wiederholungen | **5** identische Folge-Calls (Retry-mit-Backoff bleibt unter 5) |
| Schwelle Tool-Calls/Turn | **75** (Nudge-Charakter; Verdopplung re-fired) |
| PM darf Maschinen-Karten korrigieren? | **Ja** — der Korrektur-Steer ist nur Text an den Worker; er führt selbst nichts aus. `notify`-Autonomy bleibt der Aus-Schalter |
| Hard-Budget-Kill (Tool-Calls/€ als echte Grenze) | **Nicht bauen** — der PM-Pfad + Stop-Button decken es; eine stumpfe Grenze killt wieder produktive Läufe (dieselbe Falle wie 1800s) |

**Gesamtaufwand:** ~5–6h. Reihenfolge strikt P1→P4 vor P5; P3 parallelisierbar.
**Ausführung:** als Worker-Karte (Worktree + Gate + Accept) oder direkt — Owner-Wahl.
