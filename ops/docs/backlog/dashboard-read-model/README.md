# Dashboard-Kennzahlen als Read-Model statt Vollberechnung pro Request

Owner-Befund (2026-09-19, Chat): "Relay nicht erreichbar" auf dem Handy. Root
Cause war der Daemon: `db.events_all()` las bei JEDEM `/dashboard/data` und
`/pm/plan` alle Events (11.500 Zeilen, 2,7 MB JSON) und parste sie neu,
`/pm/plan` dreimal pro Aufruf, jedes Gerät pollt alle 8 bis 10 s. Unter
Kartenlast serialisierte das hinter dem GIL bis über die 115-s-Grenze der
Relay-Bridge. Der Docstring von `spine/storage/db.py` versprach seit dem
JSON-auf-SQLite-Umzug das Gegenteil ("dashboard stops re-parsing history"),
nichts erzwang es.

## Was heute schon steht (Commits 0265d489, 2d933209 + Folge)

- `db.events_all()`: marshal-Cache, Schlüssel `max(seq)` (append-only, prozessübergreifend).
- `events.metrics()`: 5-s-Cache, Schlüssel `db.store_signature()` (max(seq), Schreibzähler, `PRAGMA data_version`).
- `/pm/plan` leitet Board + Metrics einmal ab und reicht sie durch.
- Tests: `ops/tests/test_events_cache.py`, `ops/tests/test_metrics_cache.py`.

Das sind Caches. Sie heilen das Symptom sauber, aber die Ableitung bleibt O(Events) pro
Neuberechnung und wächst mit dem Board.

## Ziel dieser Karte

Die Kennzahlen pro Karte (Turns, Tokens, Kosten, Zeit in "working", Completion-Mode,
Touch-Zähler) werden beim `emit()` fortgeschrieben, an genau EINEM Ort, exakt nach der
No-Monkey-Patch-Regel ("folded in at event time, mutated at exactly one owner"). Der
Dashboard-Request liest dann O(Karten) fertige Zeilen. Alternative mit weniger Umbau:
Aggregation in SQL über die vorhandenen generierten Spalten (SUM/GROUP BY).

## Akzeptanz

1. `events.metrics()` liest keine Event-Blobs mehr; ein Test zählt die SELECTs.
2. Zahlen byte-identisch zur heutigen Vollberechnung auf der Live-DB (Replay-Vergleich).
3. Ein Latenzbudget-Test: `/dashboard/data` unter 50 ms bei 400 Karten / 20.000 Events.
4. Caches aus 0265d489 bleiben als zweite Verteidigung, werden aber nicht mehr gebraucht.

## Nicht Teil dieser Karte

Die Bridge-Pause (2d933209) und der Dev-Port-Reclaim sind erledigt. Die
Neustart-Lücke (~50 s Handy-Ausfall pro Daemon-Neustart, Bridge startet spät im Boot)
ist eine eigene Karte.
