# Lifecycle-Sweep meldet "SETTLED" auf einem laufenden Turn

Befund (2026-09-20, Karte `20260920-110834-chat-revise-the-alphaloop-cluste`,
Analyse des 409 "no pending question"): Turn 2 startete 12:25:20.9 (Steer,
`Turn gestartet`), der Sweep schrieb um 12:27:05 die Notiz "SETTLED - Turn war
schon beendet, Status hing auf 'running' (Schreib-Rennen)" und setzte
`needs_you`, der Turn lieferte seine Antwort um 12:27:11. Events-Tabelle:

    12:25:20 turn completed (Turn 1)   12:27:05 settle stale_running   12:27:11 turn completed (Turn 2)

Der Settle-Zweig in `cells/engineer/cards/lifecycle.py` (Ast `st == "running"`,
`drivers.has_session` und NICHT `drivers.turn_inflight`) hat also einen Turn für
beendet erklärt, der sechs Sekunden später noch Output produzierte. Das ist eine
Lebenszyklus-Beobachtung, die lügt: genau die Klasse, aus der spaeter "Karte
haengt"-Meldungen und doppelte Push-Nachrichten entstehen (`notify.card_event`
lief mit).

## Was zu klaeren ist

1. Warum `turn_inflight()` fuer diese Karte um 12:27:05 False war. Kandidaten:
   der Reader-Thread hatte die pid/handle nach dem Interrupt-and-Replace des
   vorigen Turns nicht neu registriert; der Turn lief unter dem Direct-/Desktop-
   Lock und `turn_queued` sah ihn nicht mehr; ein Race zwischen `_turn`s
   Handle-Anmeldung und dem Sweep-Snapshot.
2. Ob `_track_idle_s` mit `min_idle_s` hier greifen sollte (Turn 2 hatte keine
   run_dir-Aktivitaet, weil der Guard jeden Zugriff blockte).

## Akzeptanz

1. Ein Test, der einen laufenden Turn (Fake-Driver mit registriertem Handle,
   ohne run_dir-Aktivitaet) durch `sweep_zombies` laufen laesst und beweist,
   dass KEIN settle emittiert wird. Muss auf dem heutigen Code fehlschlagen,
   sonst ist die Ursache eine andere und der Test wird angepasst, bis er sie trifft.
2. `settle stale_running` wird nur emittiert, wenn `turn_inflight` UND ein
   zweites, unabhaengiges Zeugnis (Prozess tot oder Handle abgemeldet) zustimmen.
3. Die Notiz nennt das Zeugnis, auf das sie sich stuetzt.

## Nicht Teil dieser Karte

Das Verschlucken der Owner-Frage durch delegierte Steers ist erledigt
(`sessions.HUMAN_SOURCES`, `held_steers`, Test `test_delegated_steer_held`).
