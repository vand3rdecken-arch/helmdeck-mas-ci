# Chat-Step-Adapter zentralisieren — eine Nachricht, ein Vertrag

Owner-Frage (2026-08-30, nach dem abgeschnittenen Henry-Kartentext `ba71f80`):
*"Erstmal Architektur checken warum steht UI anders aus zwischen Worker- und
Henry-Chat-UI. Warum ist das nicht zentral."*

Antwort in einem Satz: **der RENDERER ist zentral, der PRODUZENT nicht.** Beim
Expo-Umbau wurde die Darstellung auf eine Komponente gezogen; die Umwandlung
"Quelldaten → Schritt" blieb pro Fläche liegen und wird bis heute in jedem
Screen und jedem Driver neu erfunden.

## Was bereits zentral IST (nicht anfassen)

- `surfaces/app/src/ui/card_transcript.tsx` — EINE `Transcript`-Komponente,
  EIN Typ `TStep`. Board-Chat und Karten-Chat rendern beide darüber
  (`chat.tsx:495` bzw. `card/[id].tsx:495`), dazu `Composer` und
  `QuestionPanel`. Der lila Rahmen der Henry-Karte ist nur `byKind === "henry"`
  (`:459` `accent2`, angewendet `:489`), das Sternchen `:471`.
- `cells/copilot/copilot.py:276` `_append_log` — der EINE Schreiber des
  Board-Chat-Logs (und damit der eine Ort, der `date` stempelt).
- `spine/comms/notice.py` — der EINE Notiz-Clip, seit `ba71f80` sauber auf
  Kanäle begrenzt, die nicht scrollen können.
- Die Label-Teilung ist **Absicht, kein Drift**: `chat.tsx:44-50` schreibt fest,
  dass der Daemon die TEILE liefert (`kind` + `cardName`) und jede Fläche das
  Label selbst setzt. Dass `HenryScreen.kt:108/324` dasselbe in Kotlin
  komponiert, ist diese Regel bei der Arbeit — nicht der Fehler, den wir suchen.

## Befund: was NICHT zentral ist

### 1. Zwei Draht-Verträge für denselben Begriff

| | Karten-Chat | Board-/Henry-Chat |
|---|---|---|
| Speicher | `timeline_store` (JSONL), **schon `TStep`-förmig** | `copilot_log.json`, Typ **`ChatMsg`** (`cls`-basiert) |
| Weg zum Client | fast unverändert (`routes_tracks.py:81`) | muss übersetzt werden |
| Übersetzer | `card/[id].tsx:666` `feed` useMemo (~45 Zeilen) | `chat.tsx:57` `toStep()` |

Ein Begriff, zwei Formate — und beide Übersetzer wohnen in *Screen-Dateien*,
nicht in einem Datenmodul. Insgesamt gibt es acht Stellen im Client, die einen
`TStep` bauen (u. a. noch `chat.tsx:664` Streaming-Zeile, `card/[id].tsx:440`
optimistisches Echo, `demo.ts:191`).

### 2. `TStep` ist eine offene, herrenlose Union

`card_transcript.tsx:30-41`:
- `kind` ist `"text" | "thinking" | … | string` — die Union ist **offen**, jeder
  Tippfehler ist gültig.
- Drei überlappende Identitätsfelder nebeneinander: `role`, `cls`, `byKind`
  (+ das als "legacy" markierte `agent`, `:41`).
- Drei parallele Token-Formen: `usage: TurnUsage` (`:38`), flach
  `tokIn/tokOut/cacheRead/cacheWrite/ctx` (`:39`), und serverseitig eine dritte.

Ein Vertrag, der alles annimmt, kann Produzenten nicht ausrichten.

### 3. Gemessene Folge A — stiller Datenverlust bei den Kosten

`cells/copilot/copilot.py:1136` baut `usage = {"in": …, "out": …, "cost": …}`
und stempelt es `:1156` als `usage` auf einen `TStep`. Der Renderer liest in
`usageLabel` (`card_transcript.tsx:329`) aber `input_tokens` / `output_tokens` /
`cache_*` (Typ `TurnUsage`, `:26-29`). **Jede Henry-Nachricht, die in eine
Karten-Timeline gefaltet wird, trägt ihre Kosten mit und zeigt sie nie** —
`usageLabel` gibt `""` zurück. Nichts schlägt fehl, nichts warnt: Python ist
untypisiert, das Feld ist optional, der Renderer schweigt.

### 4. Gemessene Folge B — der Feldname für den Text ist nicht verabredet

`spine/ops/actionlog.py:15` schreibt `detail`, `TStep` liest `text`. Deshalb
braucht `card/[id].tsx` **11 `as any`-Casts**, `chat.tsx` genau 1. Diese Casts
*sind* der fehlende Vertrag, vom Typsystem selbst protokolliert.

### 5. Gemessene Folge C — der Bug von heute

Weil kein Produzent "eine Nachricht an den Owner" besitzt, wurde die Frage
"wie lang darf sie sein" an vier unabhängigen Stellen beantwortet:
`notice.short` (240), `card_mirror.RESULT_MAX` (400), die Push-Budgets
(230/180) und `clampText` (1600). `ba71f80` hat drei davon aus dem Chat-Pfad
entfernt, ein zweiter Owner-Entscheid am selben Tag auch die vierte:
`RESULT_MAX` ist **ersatzlos weg**. Gemessen an seinem eigenen Log waren 10 von
10 gekürzten Spiegel-Zeilen Karten, die der Owner AUS DEM CHAT gestartet hatte —
dort gibt es den „einen Tap entfernten" Volltext gar nicht (~3.600–4.300 Zeichen
Verlust je Zeile). Im Chat-Pfad bleibt damit kein Budget mehr übrig; Budgets
haben nur noch Kanäle, die nicht scrollen können.

Das war Symptombehandlung an der richtigen Stelle — die Ursache ist dieser
fehlende Produzenten-Vertrag: **vier Stellen konnten die Frage überhaupt nur
deshalb unabhängig beantworten, weil keine von ihnen sie besitzt.**

## Vorschlag: drei Phasen, sequenziell

**Phase 1 — den Vertrag schliessen (nur Typen, kein Verhalten).**
`TStep.kind` zur geschlossenen Union machen; `role`/`cls`/`agent` auf `byKind`
zusammenführen; EINE Token-Form. Danach listet
`npx tsc --noEmit -p tsconfig.typecheck.json` jeden abweichenden Produzenten von
selbst auf — die Inventur macht der Compiler, nicht der nächste Agent.

**Phase 2 — ein Adapter-Modul.** Neu: `surfaces/app/src/data/steps.ts`, Besitzer
von `ChatMsg → TStep` und `ActionLog → TStep`. `chat.tsx` und `card/[id].tsx`
importieren nur noch. Die 11 `as any` fallen weg; neue Flächen erben die
Abbildung, statt sie zu erraten.

**Phase 3 — serverseitig EIN Builder.** Ein `TStep`-Bauer in `spine/`, durch den
jeder Driver und `copilot.py` faltet. Erledigt den `{in,out,cost}`-Fehler an der
Quelle statt im Renderer.

Phase 1 ist die Voraussetzung für 2 und 3 und für sich allein schon nützlich:
sie macht die Divergenz sichtbar, ohne etwas zu bewegen.

## Nicht in dieses Kartendeck

- `RESULT_MAX` (erledigt: ersatzlos entfernt, siehe Befund 5).
- Die Label-Komposition pro Fläche (siehe oben: Absicht).
- `voice_mode.tsx:582` rendert bewusst nicht über `Transcript` — mit
  begründendem Kommentar. Erst nach Phase 2 neu bewerten.
