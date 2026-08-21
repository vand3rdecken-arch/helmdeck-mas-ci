# Copilot auf den persistenten Session-Port (Voice-Latenz)

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
