# Jev als Schleifen-Profiler (AgentPProf-Vorbild) - Messung 2026-09-25

Reine Messung, kein Produktbau. Skript: `ops/tools/research/jev_loop_probe.py`. Rohdaten (Sitzungstext) liegen
nur in `%TEMP%/jev_loop_probe`, nicht im Repo. Daemon unberuehrt, nichts gepusht.

## Aufbau

- 20 echte Karten-Sitzungen aus `~/.claude/projects/*/*.jsonl`: die zwei Pflichtfaelle (02089b79 E2E-Harness,
  459913d5 Stop-Hook) plus 18 zufaellige (Seed 925, 25 bis 300 Schritte, je Sitzung hoechstens 200), zusammen 1.677 Werkzeugschritte.
  Ein Stop-Hook-Block zaehlt als eigener Schritt.
- State je Schritt (klein, JSON): `step` und `previous` mit `{tool, cmd (gekuerzt), result (140 Zeichen), ok}`.
  Eine atomare choice-Frage: `new_task | retry_same | recovery_variant`. Keine Zahlen im State, die verglichen werden muessten.
- Jev: `POST https://api.typesafe.ai/v1/systemone`, `jev-latest`, direkt, 6 parallel.
- Hand-Referenz: ich habe vor dem Lauf 160 Schritte aus 3 Sitzungen von Hand gelabelt (459913d5 57, 02089b79 76, 2d42c3f6 27).
  Verteilung: 144 new_task, 15 recovery_variant, 1 retry_same. Sonnet (`claude -p --model sonnet`, ein Schritt je Aufruf,
  gleicher State, gleiche Klassenbeschreibung) als zweite Referenz auf denselben 160 Schritten.
- Erster Lauf (v1) war durch mich verfaelscht: der Befehlskuerzer schnitt bei Read/Edit/Grep den Dateinamen hinter dem langen
  Worktree-Pfad ab, sodass verschiedene Dateien identisch aussahen (Jev meldete deshalb 47 retry_same in einer 200-Schritte-Sitzung).
  Behoben (Pfadprefix entfernt, Edit mit Anfang des `old_string`), alles unten ist v2.

## Ergebnis

| Messgroesse | Jev | Sonnet |
|---|---|---|
| Uebereinstimmung mit Hand | 144/160 = 90,0 % | 143/157 = 91,1 % (3 Aufrufe ohne Antwort) |
| Mehrheits-Baseline (immer new_task) | 90,0 % | 90,0 % |
| Verschwendete Schritte (Hand: 16) erkannt als retry/recovery | 13 von 16 | 13 von 16 |
| Praezision "verschwendet" | 13/25 = 52 % | 13/25 = 52 % |
| Kosten je 1.000 Schritte | 0,027 USD (1.058 Token/Schritt bei 0,042 USD/Mio) | 8,69 USD (CLI-Notional, Planshare, kein API-Cent) |
| Zeit | 0,72 s je Aufruf, 1.677 Schritte in 203 s (6 parallel) | 71 s je Aufruf bei 4 parallel (CLI-Start dominiert) |

Jev und Sonnet sind gleich gut, beide **nicht besser als die Mehrheits-Baseline**: die 90 % sind fast reine new_task-Masse.
Die Fehler sind bei beiden dieselben: sie melden recovery_variant, wo ich new_task gelabelt habe (11 bzw. 12 Mal), typischerweise
ein Schritt nach einem Fehler, der aber ein neues Ziel verfolgt. Jev ist dabei 300-mal billiger und 100-mal schneller.
Statistische Grenze: nur 1 retry_same und 15 recovery in der Hand-Referenz, retry_same ist damit praktisch ungemessen.

## Sortiert der Waste-Anteil die Schleifenkarten nach oben?

Waste-Anteil = (retry_same + recovery_variant) / Schritte je Sitzung, Jev-Labels. Die bekannten Schleifenkarten landen auf
**Platz 4 (459913d5, 17,5 %) und Platz 8 (02089b79, 14,5 %) von 20**; Spitze ist 2d069a8a mit 25 %, Ende d0b410c6 mit 4,4 %.
Das ist kaum besser als Zufall (Median = Platz 10,5). In v1 (mit dem Kuerzer-Fehler) waren es Platz 9 und 7.

Warum: Die Schleifen dieser Karten sind **keine Schritt-fuer-Schritt-Wiederholungen**. 459913d5 ist ein Zyklus
"Hintergrundjob starten, Stop, Stop-Hook blockt, wieder pollen"; 02089b79 sind vom Guard blockierte Befehle und ein
abgebrochener Lauf. Jeder Einzelschritt sieht gegenueber seinem Vorgaenger legitim neu aus, ein Vorgaenger-Fenster von 1 sieht
das Muster nicht. Zudem zaehlt "recovery_variant" auch normales Ausweichen nach einem Guard-Block als Waste, das in jeder
Karte vorkommt und das Signal verwaschen macht.

## Verdikt: taugt so nicht - nur mit X

- **Als Schritt-Klassifikator taugt Jev** (gleich gut wie Sonnet, ~0,03 USD statt ~9 USD je 1.000 Schritte, unter 1 s).
- **Als Schleifen-Profiler in dieser Form taugt es nicht**: 90 % = Baseline, Praezision 52 %, die zwei Pflichtkarten sind nicht
  oben sortiert. Das liegt am Ansatz (Vorgaenger-Paar, Anteilszahl), nicht am Modell: Sonnet scheitert identisch.
- **Nur mit X**: X = deterministische Wiederholungserkennung im Code (gleiche Werkzeug+Ziel-Signatur ueber ein Fenster, Zyklus
  gleicher Schrittfolgen, Stop-Hook-Zaehler) als Vorfilter; Jev dann nur fuer die atomare Restfrage auf den markierten Fenstern
  (z. B. "wurde zwischen diesen zwei Versuchen etwas Neues gelernt?" mit den letzten 3 Schritten als State). Der Stop-Hook-Zyklus
  ist ohnehin mit einem Zaehler ohne Modell sichtbar (459913d5: 8 Stop-Hook-Schritte in 57).
- Vor jedem Vertrauen: groessere Hand-Referenz (>= 30 echte retry_same), sonst ist die Wiederholungsklasse nicht belegt.

## Grenzen der Messung

Hand-Labels stammen von einer Person (mir), Grenzfaelle (Guard-Block dann anderer Befehl = recovery?) sind Ermessen. Sonnet
lief ueber die CLI, dessen Kosten sind Notional-Planshare. Stichprobe 20 Sitzungen, nur 2 bekannte Schleifen.
