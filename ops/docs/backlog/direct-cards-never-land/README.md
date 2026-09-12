# Direct-Karten landen nie von selbst — Henry hört von fertigen Karten nichts

**Anlass (Owner-Report + DB-Trace, 2026-09-12):** "Henry schiebt Karten mit
Antworten nicht auf Review/Done und shipt nicht." Drei verifizierte Ursachen
(actions/escalations-Tabellen in helmdeck.db, Code gelesen). Muster an den
Karten vom 12.09.:

| Karte | Turn fertig | Owner musste selbst schieben |
|---|---|---|
| 20260912-113606-direct (fast_track+direct) | 11:38 DELIVERED | Review 15:55, Done 16:06 |
| 20260912-113715-direct (direct) | 11:43 | Review 11:44, Done 16:06 |
| 20260912-220637-chat-… (worktree) | 22:13 | Review 22:28, Done 22:46 |

Ship-Entscheidung kam in allen Fällen ERST nach dem manuellen Accept
(`request_ship_decision(t, "direct-accept"/"accept")`). Henrys Broker selbst
arbeitet korrekt: alle 17 delivered-parked-Eskalationen seit 10.09. wurden
mit `move` beantwortet und die Karten stehen auf done/accepted. Das Problem
ist, dass er die Eskalation für diese Karten NIE bekommt.

## Ursache 1 — erster Turn einer Direct-Karte hat keinen Landing-Hook

`cells/engineer/cards/dispatch.py::_start_machine` (Zeile ~600-627) ist die
Completion-Path des ERSTEN Turns jeder machine/direct-Karte. Sie behandelt
nur `ship_kind`-Karten (`_maybe_ship_card_close`). Der Fast-Track-Hook
`sessions._maybe_fast_track_ship_direct` (Autocommit → ship-decision) hängt
NUR am Steer-Completion-Path (`sessions.py:1050`). Eine Direct-Karte, die im
ersten Turn fertig wird (der Normalfall: 113606 lieferte in Turn 1), landet
nie und fragt Henry nie nach dem Ship. Beleg: kein "FAST-TRACK (direct)"-
Eintrag im Actionlog von 113606, obwohl der Tree um 11:38 dirty war (der
Fable-Diff wurde erst um 11:43 vom Worker der NÄCHSTEN Karte in b40e33f
mitcommittet).

## Ursache 2 — delivered-parked schließt direct/fast_track aus (stale)

`cells/engineer/cards/turnrunner.py::_emit_delivered_parked` (Zeile ~521):
`if t.get("fast_track") or t.get("direct"): return` mit Kommentar "their own
pipelines already land/deploy" (f69fac4, 22.08.). Seit dem Owner-Dekret
2026-09-01 (d66084f) bewegt Fast-Track die Karte NIE mehr, und eine Direct-
Karte OHNE fast_track (113715) hat gar keine Pipeline. Ergebnis: genau die
Karten, die seit 29.08. der Default für Repo-Fixes sind, sind vom einzigen
Signal ausgeschlossen, das Henry FINISH-WHAT-YOU-START auslöst.

## Ursache 3 — DELIVERED muss in den ersten 200 Zeichen stehen

Gleiche Funktion: `_DELIVERED_RE.search(cleaned[:200])`. 220637 schrieb
"I fixed the cause, …" und DELIVERED erst weiter unten → keine Eskalation.
Die Harness-eigene Definition von "fertig" ist `turnrunner.is_delivered(t)`
(needs_you ∧ keine Frage ∧ nicht background) — das Literal ist ein
zusätzlicher, brüchiger Filter.

## Nebenbefund (Audit)

`escalations.record_decision` speichert bei `ship` das `kind` (none|ota|native)
nicht — in der DB steht nur `action: ship`; ob geshippt wurde, ist nur aus
dem `why`-Freitext bzw. dem Karten-Actionlog rekonstruierbar.

---

## Fix (klein, Engineer-Cell, keine FIXED-Dateien)

1. `_start_machine`: nach `notify.card_event` denselben Verzweiger wie
   `sessions.py:1034-1057` aufrufen (ship_kind → `_maybe_ship_card_close`,
   direct → `_maybe_fast_track_ship_direct`). Besser: den Verzweiger als EINE
   Funktion (`_after_turn_land(t, log)`) in sessions.py ziehen und von beiden
   Call-Sites nutzen — zwei Kopien driften (genau das ist hier passiert).
2. `_emit_delivered_parked`: Ausschluss von direct/fast_track streichen. Bei
   fast_track+direct erst NACH dem Landing-Hook emittieren (Reihenfolge:
   Autocommit läuft im Hintergrund-Thread; Henry soll den committeten Stand
   beurteilen — ggf. Emit ans Ende von `_ship()` hängen bzw. dort, wo der
   Tree sauber war, sofort emittieren).
3. Marker-Bedingung: `is_delivered(t)` statt Regex auf 200 Zeichen. Wer eine
   Karte parkt ohne DELIVERED (z. B. 063252-machine "weiter abwarten"),
   bekommt trotzdem Henrys Urteil — der darf `ignore`/`notify_owner` sagen,
   Brief deckt das ("Leave a card parked … say so explicitly").
   Dedup bleibt (offene delivered-parked pro Karte + `decided_recently`).
4. `record_decision(..., kind=kind)` mitschreiben; Broker übergibt es.

**done_when:**
- Test: Direct-Karte (fast_track) endet im ERSTEN Turn mit dirty Tree →
  Autocommit + ship-decision-Eskalation offen, ohne Owner-Move. Muss auf dem
  alten Code rot sein (Owner-Dekret 2026-09-11: root cause, real dispatch path).
- Test: Direct-Karte ohne fast_track endet needs_you → delivered-parked offen.
- Test: Worktree-Karte mit DELIVERED an Position > 200 → delivered-parked offen.
- Live: nächste Direct-Karte steht ohne Owner-Klick auf done + Henry-Ship-Urteil.

---
**Status 2026-09-12: FIXED direkt im Live-Tree** — `sessions._after_turn_land`
(ein Verzweiger für Steer- und Erst-Turn), `_emit_delivered_parked` auf
`is_delivered` ohne direct/fast_track-Ausschluss und 200-Zeichen-Regex,
`record_decision(..., kind=)` → `ship_kind`. Test
`ops/tests/test_direct_cards_land.py` (rot auf dem alten Code an Pin 1).
Nebenbefund: `test_fast_track_direct.py` war schon vorher rot (Live-DB-Guard +
`fake_turn` ohne `by=`-Parameter) — eigener Fix.
