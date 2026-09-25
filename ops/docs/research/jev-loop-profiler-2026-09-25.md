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

## Stufe 2: deterministischer Vorfilter, Jev/Sonnet nur auf markierten Fenstern

Skript `ops/tools/research/jev_loop_probe_v2.py`, gleiche 20 Sitzungen (1.677 Schritte), gleiche 160 Hand-Labels (16 verschwendet),
beide Pflichtkarten. Weitere Transkripte mit *bekannter* Schleife gibt es nicht: ausser den zwei Pflichtkarten kenne ich keine
gelabelte Schleifenkarte, ich habe keine erfunden. Vorfilter rein im Code: Signatur = Werkzeug + normiertes Ziel (Zahlen, Hex, fuehrendes
`cd` entfernt, 100 Zeichen); markiert wird bei gleicher Signatur >= 3x in den letzten 8 Schritten, bei sich wiederholender
Schrittfolge der Laenge 2-4, bei Stop-Hook-Zaehler >= 2 im Fenster. Ergebnis 138 Fenster (126 sig, 6 seq, 6 stop). Frage an Jev
und Sonnet: `progress | no_progress` ("hat sich zwischen den Versuchen etwas geaendert, das den zweiten rechtfertigt?"), State =
Versuch 1, Schritte dazwischen (max. 6), Versuch 2, im Mittel 660 Token. "Erkannt" = Fenster als no_progress bewertet.

| Stufe | Recall (16 Hand-Waste) | Praezision | Rang 459913d5 / 02089b79 von 20 | Kosten je 1.000 Schritte | Latenz je Fenster |
|---|---|---|---|---|---|
| Stufe 1 (Jev, ohne Vorfilter, zum Vergleich) | 13/16 = 81 % | 52 % | 4 / 8 | 0,027 USD | 0,7 s |
| Vorfilter allein | 1/16 = 6 % | 1/10 = 10 % | 9 / 7 | 0 | 0 |
| Vorfilter + Jev | 1/16 = 6 % | 1/10 = 10 % | 6 / 4 | 0,0025 USD | 1,0 s (23 s fuer 138 Fenster) |
| Vorfilter + Sonnet | 1/16 = 6 % | 1/3 = 33 % | 7 / 3 | ca. 0,8 USD (CLI-Notional, zu niedrig, 28 Fenster ohne Antwort) | 337 s im Mittel (Timeouts, Maschine unter Last) |

Beobachtungen: (1) Die Hand-Waste-Schritte sind fast alle "Guard blockiert, dann anderer Befehl", also gerade *keine* Wiederholung
der Signatur; der Vorfilter sieht sie per Konstruktion nicht (Recall 6 %). (2) Die Signaturregel feuert bei normaler Arbeit
(mehrfach Edit derselben Datei, Greps mit gleicher Form): 126 von 138 Fenstern, nur 10 davon liegen in den Hand-Sitzungen und 9 sind
kein Waste. (3) Jev nennt 109 von 138 Fenstern no_progress und filtert damit nichts; Sonnet nennt 25 von 110 beantworteten und
hebt die Praezision auf 33 % (2 von 3 Treffern falsch), bei gleichem Recall. (4) Der Rang der zwei Pflichtkarten verbessert sich
mit Jev/Sonnet leicht (bis Platz 3 und 4), bei Waste-Anteilen von 2 bis 8 % ist das aber Rauschen; keine der beiden steht oben.

**Verdikt Stufe 2: Als Schleifen-Warner taugt die Kombination nicht (Praezision 10 % mit Jev, 33 % mit Sonnet bei 6 % Recall,
schlechter als die 52 % / 81 % von Stufe 1), weil die echten Schleifen dieser Karten Zyklen und Guard-Umgehungen sind, keine
Signatur-Wiederholungen, und Jev als "progress"-Richter fast alles als no_progress durchwinkt.** Ein brauchbarer Warner braeuchte
Zyklus-Regeln ueber Aufgabenebene (Hintergrundjob, Stop, Poll) und eine deutlich groessere gelabelte Schleifen-Stichprobe.

## Stufe 3: Progress-Ledger ueber ganze Karten (nur Jev, Karten-Ausgang als Label)

Skript `ops/tools/research/jev_loop_probe_v3.py`. Vorbild: Magentic-One Progress-Ledger (Stillstandszaehler) und SWE-PRM
(arXiv 2509.02360, Prozess-Signal eines kleinen Richters ueber die Trajektorie). Nur Jev, direkte API, **alle 5 Schritte ein Aufruf**
(plus ein Aufruf am Kartenende), zwei choice-Fragen in einem Request: `solving` (on_track | stuck_or_looping, mit `probabilities`) und
`waste_type` (identical_retry, guard_workaround, bg_poll_cycle, redundant_exploration, none). State: Kartenziel (task + description),
letzte Owner-/Steer-Nachricht, die letzten 10 Schritte voll (Aktion + Ergebnis, Ergebnisse ueber 4.000 Zeichen auf Kopf+Ende je 2.000),
davor eine deterministische Zusammenfassung (Schrittzahl, Werkzeugzaehler, bearbeitete Dateien, blockierte Befehle, Stop-Hook-Zaehler,
fehlgeschlagene Schritte). Mittel 5.700 Token je Aufruf, Maximum 15.100 (Grenze 32.768).

### Daten und ein Label-Problem (wichtig)

Die HelmDeck-DB (Kopie des Live-Standes, nicht in place gelesen) enthaelt **praktisch keine Owner-Abbrueche**: 406 Karten `accepted`,
8 `bounced` (fast alle `daemon_restart`, kein Urteil ueber die Arbeit), keine `cancelled`-Karten mit Sitzung (geloeschte Karten haben
keine Session-ID). Ein sauberes "accepted = geloest, gescheitert = nicht geloest" gibt es also nicht. Ersatz-Label, ehrlich als Proxy:
**nicht sauber geloest** = Karte wurde nach `done` wieder nach `working` geholt (Nacharbeit, 18), hat ein `error`-Event (11), einen
`burn`-Tripwire (2) oder Status `bounced` (1); **geloest** = `accepted` ohne eines davon. Karten mit 15 bis 400 Schritten, 30 nicht
geloest gegen 31 zufaellig gezogene geloeste (Seed 925), 7.636 Schritte, 1.554 Aufrufe. Die Karte dieser Sitzung (20260925-093039,
Status bounced durch den Daemon-Neustart) habe ich ausgeschlossen. **Die zwei Pflichtkarten sind `accepted` ohne Nacharbeit und zaehlen
daher als geloest**, obwohl sie Schleifen enthielten; ich habe sie aus der Auswertung genommen und zeige sie nur als Kurven.

Nicht geloest (30): 20260830-081301-direct 20260830-145725-direct 20260830-194212-chat-nur-prd-schreiben-kein 20260831-071706-machine
20260902-041610-direct 20260902-152426-direct 20260902-201524-direct 20260904-072534-direct 20260905-073624-proc-20260905-s7
20260906-141923-machine 20260908-131937-machine 20260909-171235-direct 20260909-221920-chat-umbau-team-geraete-zu-einer
20260910-134430-machine 20260912-063252-machine 20260914-182413-chat-chat-ux-fix-owner-beschwerd 20260917-013436-machine
20260917-214447-direct 20260918-092307-proc-20260918-s3 20260918-103706-direct 20260919-085300-machine 20260919-085611-machine
20260919-095550-direct 20260920-123327-direct 20260920-220342-direct 20260921-013734-direct 20260922-211749-direct
20260923-051804-direct 20260924-192114-machine 20260925-084609-direct (Kartennamen teils gekuerzt, Praefix eindeutig).

Geloest (31): 20260830-070056-direct 20260830-155404-chat-phase-2-bau-prd-akzepti 20260831-090903-direct 20260901-180204-proc-20260901-s3
20260901-202935-machine 20260902-040607-machine 20260902-075327-direct 20260902-184655-machine 20260903-224635-direct 20260909-113845-direct
20260909-171746-machine 20260910-113027-machine 20260910-115442-machine 20260911-111108-tbh-a-mcp-capper 20260914-153752-direct
20260914-170231-direct 20260914-224710-direct 20260915-073801-direct 20260916-125836-direct 20260916-181550-direct 20260917-092358-machine
20260917-214006-direct 20260918-092305-proc-20260918-s2 20260918-095829-direct 20260918-125620-direct 20260919-204007-direct
20260920-133208-direct 20260922-190039-direct 20260922-193225-direct 20260923-085952-direct 20260924-132120-direct.
Pflicht (nur Kurven): 20260924-222503-direct-2, 20260924-223336-machine.

### Ergebnis

| Vorhersage des Karten-Ausgangs aus | AUC (nicht geloest gegen geloest) |
|---|---|
| (a) letzte P(stuck) | 0,57 |
| (b) Tiefpunkt = hoechste P(stuck) im Verlauf | 0,71 |
| (b) Mittel P(stuck) im letzten Drittel | 0,61 |
| Anteil stuck-Antworten ueber die Karte | 0,65 |
| (c) hoechster Ledger-Zaehler (+1 stuck, -1 on_track, min. 0) | 0,62 |
| **Kontrolle: nur die Schrittzahl der Karte** | **0,72** |

- **Ledger-Alarm (Zaehler >= 3):** 19 von 30 nicht geloesten Karten (63 %), aber auch **14 von 31 geloesten** (Fehlalarm 45 %).
  Erster Alarm im Median 123 Schritte vor Kartenende (72 % der Laufzeit); die Vorwarnung ist frueh, weil sie auch bei den geloesten
  Karten frueh feuert. Beste Schwelle je Einzelmerkmal (in-sample, also obere Schranke): Trefferquote 62 bis 67 %.
- **Die Schrittzahl allein schlaegt jedes Jev-Merkmal** (Median 127 Schritte bei nicht geloesten, 78 bei geloesten; laengere Karten
  haben mehr Aufrufe und damit mehr Gelegenheit fuer Stuck-Antworten). Jev fuegt auf Kartenebene keine belegbare Information
  ueber "lange Karte" hinaus.
- `waste_type` liefert plausible Typen (guard_workaround und bg_poll_cycle dominieren), trennt die Gruppen aber nicht: `none`
  in 50 % der Aufrufe bei geloesten, 45 % bei nicht geloesten Karten.
- **Pflichtkarten:** 459913d5 (Stop-Hook-Zyklus) steht bei P(stuck) 0,71 / 0,92 / 0,67 / 0,94 / 0,75 in den Schritten 5 bis 25, waste_type
  meist bg_poll_cycle (Schritte 15 bis 35), faellt gegen Ende auf 0,06 bis 0,11 und springt im letzten Schritt wieder auf 0,62; Ledger-Alarm
  bei Schritt 15, 42 Schritte vor Ende von 57. 02089b79 (E2E-Harness) hat nur zwei stuck-Spitzen (0,90 und 0,98 bei Schritt 10 bis 15,
  danach unter 0,45), der Ledger erreicht nie 3, kein Alarm; waste_type wechselt zwischen guard_workaround und redundant_exploration.
  Also: der Stop-Hook-Zyklus wird als Schleife erkannt, das Guard-Umgehen der zweiten Karte nicht als ganze Karte.
- **Kosten und Laufzeit:** 0,0485 USD je 1.000 Schritte (1 Aufruf je 5 Schritte, 5.700 Token, 0,042 USD je Mio), 0,78 s je Aufruf; alle
  1.554 Aufrufe in einem 4-Minuten-Lauf mit 6 Threads.

### Verdikt Stufe 3

**Als Kartenausgangs-Vorhersager taugt der Jev-Ledger nicht** (AUC 0,57 bis 0,71, nicht besser als die reine Schrittzahl mit 0,72;
Fehlalarm 45 % auf geloesten Karten); als **Live-Warner fuer den Stop-Hook-Zyklus** (459913d5) zeigt er ein brauchbares Signal, aber mit nur
einer solchen Karte ist das kein Beleg. Groesste Grenze ist das Label: Nacharbeit und error-Events sind schwache Stellvertreter fuer "nicht
geloest", und die zwei bekannten Schleifenkarten stehen in der DB als sauber akzeptiert. Fuer eine belastbare Aussage braeuchte es
explizite Owner-Urteile (Stopp, Bounce mit Grund) und einen Vergleich gegen einen billigen Nicht-Modell-Baseline (Schrittzahl, Anteil
blockierter Schritte).

## Eingestellt 25.09.

Owner-Entscheid: Die Jev-Entwicklung wird eingestellt, keine weiteren Jev- oder Baseline-Läufe. Drei Erkenntnisse aus Stufe 1 bis 3:

1. Echte Schleifen sind Guard-Umgehung und Hintergrundjob-Poll-Zyklen, keine identischen Wiederholungen. Paarvergleiche und Signatur-Vorfilter verfehlen sie deshalb.
2. Der Stop-Hook-Zyklus ist früh erkennbar (459913d5: Alarm bei Schritt 15 von 57).
3. Das Board speichert keine echten Scheitern-Urteile (keine Owner-Abbrüche, `bounced` sind fast nur Daemon-Neustarts). Das blockiert jede belastbare Auswertung gegen den Kartenausgang.
