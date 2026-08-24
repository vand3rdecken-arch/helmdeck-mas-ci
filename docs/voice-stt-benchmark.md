# STT-Pipeline-Benchmark (2026-08-23)

Owner-Auftrag: „Mach und teste verschiedene Pipelines. Teste auf Qualität."
Harness: `tools/stt_bench.py` — 12 deutsche HelmDeck-Sätze × 3 edge-tts-Stimmen
(36 Utterances), zwei Bedingungen: `clean16k` (Phone-Mikro-Livepfad) und
`hfp8k` (300–3400-Hz-Bandpass + 8-kHz-Dezimierung = Brillen-SCO-Simulation).
WER via jiwer (kleingeschrieben, ohne Interpunktion), Latenz = Median warm auf
der Owner-Box. Rohdaten: `tools/stt_bench_results.json`.

| Engine | WER 16k | WER 8k | Median | Größe | Bemerkung |
|---|---|---|---|---|---|
| **parakeet-tdt-0.6b-v3 int8** | **8,3 %** | **8,7 %** | 0,90 s | ~640 MB | Sieger PC |
| **zipformer-de-kroko** (Streaming) | 11,4 % | 12,9 % | **0,33 s** | ~71 MB | Sieger Gerät |
| fw-small int8 | 11,0 % | 12,9 % | 5,26 s | ~460 MB | zu langsam |
| canary-180m int8 (de) | 18,2 % | 19,3 % | 0,84 s | ~200 MB | mittel |
| fw-base int8 (alter PC-Default) | 19,7 % | 24,6 % | 1,61 s | ~140 MB | abgelöst |
| fw-tiny int8 | 25,0 % | 50,8 % | 0,82 s | ~110 MB | 8k-Einbruch |
| sherpa-whisper-tiny (Gerät Build 57) | 29,9 % | 44,7 % | 0,65 s | ~104 MB | abgelöst |

## Entscheidungen (umgesetzt)

1. **PC-Ohr = Parakeet** (`daemon/spine/media/stt.py`, Setting
   `voice_stt_model` Default `parakeet`; jeder andere Wert bleibt eine
   faster-whisper-Größe als Fallback). Gemessen im Daemon-Pfad: warm 1,3 s.
2. **Geräte-Ohr = Kroko-Zipformer** (`LiveMic.initLocalTransducer`,
   Download ~71 MB von HF beim ersten Aktivieren). Streaming-Modell — öffnet
   später Live-Partials auf dem Gerät.
3. **Brillen-Mikro ist qualitativ machbar**: beide Sieger verlieren unter
   Telefonband < 1,5 WER-Punkte, während Whisper dort einbricht. Der
   SCO-Gating-Pfad (Spike-Karte) bleibt damit attraktiv.

## Ehrlichkeit

edge-tts ist Studio-Sprache: absolute WER ist ein Best Case; es transferieren
das **Ranking** und das **Clean-vs-8k-Delta**, nicht die Zahlen. Parakeets
einziger beobachteter Schnitzer im Daemon-Smoke: „Build" → „Bild"
(Anglizismen). Echte Mikro-Messung auf dem Phone = Owner-A/B im Live-Modus
(Chip-Icon, Latenz-Note pro Turn).
