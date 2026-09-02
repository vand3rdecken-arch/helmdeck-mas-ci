# Copilot auf den persistenten Session-Port (Voice-Latenz)

**GEBAUT 2026-08-21 direkt im Live-Tree (Owner-Decree), Commit 2783c10.**
Gemessen: Turn warm 1.6s (vorher 12s). Abnahme < 5s ERFUELLT.

**NACHGEZOGEN 2026-09-02: Punkt 3 der Auftragsliste unten - "Model-Wechsel via
Control-Plane, nicht Respawn" - war NICHT gebaut.** `_persist_get` killte den
Prozess bei jedem Tier-Wechsel. Im TEXT-Chat machte das die Waerme weitgehend
wirkungslos: der Composer steht per Default auf "auto" (card_composer.tsx),
also waehlt turnopts.pick_model das Tier aus dem TEXT jeder Nachricht neu
("danke" -> haiku, normale Frage -> sonnet, "debug/analysiere/refactor" ->
opus). Ein gewoehnliches Gespraech warf den warmen Prozess damit Turn um Turn
weg und zahlte erneut Node-Boot (8-12s) PLUS den vollen --resume-Prefill der
Board-Session (~20s bei 128k gemessen) - warm war er nur fuer eine Serie von
Nachrichten, die zufaellig aufs gleiche Tier routeten.

Jetzt schaltet _persist_switch das laufende Modell per set_model um
(drivers.apply_opts-Paritaet) und uebernimmt den neuen Key NUR bei
bestaetigtem Erfolg; jeder Fehlschlag faellt auf den alten Respawn-Pfad
zurueck. Zusaetzlich waermt jetzt auch der Board-Chat vor (bisher nur Voice),
und die Karten-Antwort streamt (Debt card-henry-reply-not-streamed bezahlt).
Test: ops/tests/test_copilot_warm_switch.py.

Karte bleibt als Doku; offen nur noch: Langzeit-Beobachtung (Idle-Prozesse,
Rotation unter Kompaktierung).

## Warum (gemessen 2026-08-21)
Ein Sprach-Turn braucht ~12s, davon ~8s reiner CLI-Spawn-Overhead:
`claude -p --model haiku` mit trivialem Prompt = 7.8-19.7s gemessen, bevor
das Modell ein Token schreibt. Der Board-Copilot (copilot.chat) spawnt pro
Turn einen frischen Prozess mit --resume; die KARTEN haben das Problem schon
geloest: drivers._ClaudeSession haelt den Prozess zwischen Turns (persistenter
stream-json-Port, Paseo-Modell) - Turn-Kosten = reine Modellzeit.

## Auftrag
copilot.chat auf drivers._ClaudeSession portieren (ein persistenter Prozess
pro Chat-User), dabei erhalten:
- Actions-Parsing + Live-Strip (_strip_actions_live), /chat/live-Pump,
  Voice-Streaming-Haken (_vstream), Stats-Fold (ctx/usage pro Turn)
- Session-Rotation/Kompaktierung (_maybe_compact) auf dem neuen Port
- Model-/Permission-Wechsel via Control-Plane (drivers.apply_opts), nicht
  Respawn - Voice-Turns wechseln auf haiku und zurueck
- Fallback: stirbt der Prozess, naechster Turn resumed per --resume (heutiger
  Pfad bleibt als Degradation)

## Abnahme
Sprach-Turn ("was laeuft auf dem Board") Ende-zu-Ende < 5s auf diesem Rechner;
Text-Chat unveraendert (Actions, Steer, Kontext-Meter); Kartenverhalten
unberuehrt.
