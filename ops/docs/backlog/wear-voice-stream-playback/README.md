# Wear: "Stimme aktivieren" spricht gepushte Antworten nicht — Stream-Pfad reparieren

Owner-Befund (2026-09-02, 16:32, Henry-Chat): Der Button "Stimme aktivieren"
auf der Uhr (HenryScreen) ist "ziemlich broken" — Stimme an, und trotzdem
bleibt die Uhr meistens stumm. Der Owner will das Turn-by-turn-Sprechen
BEHALTEN (Owner-Aussage 16:27: "das turn by turn sprechen ist erstmal ok");
NICHT gewollt ist eine neue Sprachaktivierung/Wake-Word — nur der bestehende
Playback-Toggle soll zuverlässig funktionieren.

## Root Cause (verifiziert im Code, 2026-09-02)

`VoicePlayer.play()` hängt ausschließlich am direkten HTTP-Antwortpfad von
`ask()` (`surfaces/app/plugins/wear/HenryScreen.kt:206`): nur wenn die
`/wear/talk`-POST-Antwort selbst den `voice`-Clip trägt UND `voiceOn` gesetzt
ist, wird gesprochen.

Alle anderen Zustellwege sind stumm:

1. `refresh()` / der WearStream-Ereigniskanal (heute geshippt, Karte
   `20260902-152426-direct`, Commits `b0e75cd`/`4e1f4e1`/`fd26c45`): Antworten,
   die länger dauern als der talk()-Request, Antworten auf Turns vom
   Handy/Brille, Antworten bei ausgeschaltetem Display — genau die Fälle, die
   der WebSocket-Umbau zum NORMALFALL gemacht hat.
2. `GET /wear/chat` (Transcript-Poll, `spine/http/routes/routes_wear.py`,
   `wear_chat_get`) liefert überhaupt keine Voice-Clips — der refresh-Pfad
   KÖNNTE gar nicht sprechen, selbst wenn er wollte.

Der Server rendert den Clip bereits unconditional pro Talk-Antwort
(routes_wear: "ALWAYS render voice"), aber eben nur in der POST-Response —
der Clip reist nicht über den Ereigniskanal und nicht über das Transcript.

## Fix-Richtung

Gesprochene Wiedergabe auch für Antworten, die über refresh()/WearStream
ankommen. Zwei Kandidaten (Auswahl beim Bauen messen, nicht raten):

- **A (Pull):** Wenn refresh() eine NEUE Henry-Zeile bringt und `voiceOn`
  gilt, den Clip für genau diese Zeile nachladen (neuer kleiner Endpoint oder
  `?voice=1`-Param auf `/wear/chat`, der NUR den Clip der jüngsten
  Henry-Nachricht rendert — nicht das ganze Transcript vertonen).
- **B (Push):** Den Clip (oder eine Clip-Referenz) im WearStream-Event
  mitliefern und beim Eintreffen abspielen.

Leitplanken:
- Voice bleibt SERVER-gerendert (stehende Owner-Entscheidung,
  `ops/docs/glasses-reference.md` §4) — niemals Device-TTS.
- Nur die JÜNGSTE ungespielte Antwort sprechen, kein Nachplappern der
  Historie beim App-Start / nach reconnect (refresh() ersetzt die Liste
  wholesale — Dedup über Nachrichts-Identität, nicht über lines.size; siehe
  Kommentar HenryScreen.kt:453).
- `voiceOn` aus (Default) = exakt heutiges Verhalten, null Mehrkosten.
- Kein Wake-Word, kein Dauerzuhören — die App hat bewusst kein RECORD_AUDIO
  (AndroidManifest.xml, Diktat läuft über ACTION_RECOGNIZE_SPEECH).

## Verify

- Auf der ECHTEN Uhr (Xiaomi Watch 5, Wear OS API 36, WLAN-adb zuletzt
  `192.168.178.169:33991`): Stimme aktivieren, Frage vom HANDY aus stellen →
  Uhr spricht die Antwort. Zweiter Fall: Frage auf der Uhr stellen, Display
  aus, Antwort kommt spät → beim nächsten Blick wird genau EINE Antwort
  gesprochen, nicht die Historie.
- Reiner Kotlin-/Daemon-Change → Wear-APK-Rebuild nötig (`DEPLOY.md`);
  Daemon-Seite (routes_wear/WearStream) normal per Neustart.

## Kontext für Henry

Der Owner hat am 02.09. 16:27 gesagt "Stimme aktivieren brauche ich jetzt
nicht" — gemeint war: kein neues Sprachaktivierungs-Feature bauen. Um 16:32
präzisiert: der EXISTIERENDE Button ist kaputt und soll repariert (nicht
entfernt) werden. Henrys Memory-Notiz "Sprachaktivierung bewusst
zurückgestellt" (daemon/henry_memory/wear-os-response-mechanism-open-question.md)
betrifft das Wake-Word-Feature und bleibt gültig; sie ist KEIN Grund, diese
Reparatur liegen zu lassen.
