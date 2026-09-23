# henry-lookup-and-ask-discipline - Henry schlaegt einen Grund nicht nach, obwohl er kann, und seine Rueckfragen folgen keiner Regel

**Status 2026-09-23 (owner: "Das direkt fixen"): GEFIXT in place, drei Teile.**
1. Brief-Regel REASON BEFORE BUILD (`board-copilot.md`, vor FIRST WORD) - lebt
   sofort, kein Neustart (Brief-Fingerprint).
2. Brief-Regel TAPPABLE QUESTION (`board-copilot.md`, unter HOW TO REPLY):
   Ask-Block nur bei echter Entscheidung, nie als Abschluss, nie "Noch etwas?",
   nie zwei Turns hintereinander ohne Substanz - lebt sofort.
3. Overlay-Widerruf: `chat(..., overlay=)` von den drei Routen gesetzt
   (`routes_wear.py`, `routes_glance.py`, `routes_copilot.py`);
   `copilot._surface_switch()` ist der EINE Schreiber von `_device_ovl_last`
   und stellt dem ersten getippten Turn nach einem Geraete-Turn eine
   Widerrufszeile voran. Die drei Overlays tragen zusaetzlich "THIS ONE REPLY
   ONLY" im ersten Satz. Test: `ops/tests/test_copilot_surface_switch.py`
   (9 Checks). BRAUCHT DAEMON-NEUSTART - Routen und copilot.py sind beim Start
   importiert.
Nicht gefixt (bewusst): die Lean-Chat-Entscheidung (kein MCP im Chat-Port)
bleibt - sie war nicht die Ursache.

**Owner, 2026-09-23 15:2x:** "Das problem ist das Henry erstmal 3 mal weigert
fuer mich Grund zu schauen und dann 3 mal unsinnige Fragen stellen"

Beide Haelften sind exakt gezaehlt. Chatverlauf 14:34-15:15 (seq 2944-2975):

| Zeit | Zug |
|---|---|
| 14:35 | Owner: "Ja, was war das Problem wie jetzt publishen" -> Henry: "Warum Wear abgelehnt wurde, weiss ich noch nicht ... Ich lass jetzt 94 bauen ... und den Wear-Grund auslesen" (Weigerung 1: Grund wird in die Bau-Karte gebuendelt) |
| 14:38 | Owner: "Warum willst du fuer mich Grund fuers ablehnen nicht, vlt muss man das fixen und dann erst bauen" -> Henry: "Ich hab die Karte umgestellt: Sie liest zuerst den genauen Grund aus" (Weigerung 2: wieder die Karte, nicht er) |
| 14:41 | Owner: "Ja schaust du fuer mich den Grund. Nicht nach?" -> Henry: "Noch nicht." - und startet ERST JETZT `hands` |
| 14:46 | Ergebnis da. Die Haende brauchten 5 Minuten. |
| 14:51 | Erste Rueckfrage, inhaltlich berechtigt ("Erst Befund zeigen / Durchziehen / Stoppen") |
| 15:00 | "Passt das so?" |
| 15:02 | "Noch etwas?" |
| 15:03 | "Sonst noch was?" |
| 15:15 | "Bis dahin?" |

Sechs Minuten und drei Aufforderungen fuer eine Fuenf-Minuten-Abfrage, danach
vier inhaltsleere Rueckfragen hintereinander.

## Haelfte A - er konnte, und hat es nicht getan

Owner-Korrektur 15:3x: "Er konnte Haende einsetzen hat es aber einfach
ignoriert." Stimmt, und der Verlauf beweist es haerter als jede Erklaerung:

| Zeit | Zug |
|---|---|
| 14:30 | Henry startet SELBST `hands` (20260923-143043-hands-37be4b): "Open Google Play Console ... app HelmDeck (phone, NOT Wear)" |
| 14:33 | Ergebnis da - drei Minuten. |
| 14:35 | Owner fragt nach dem Wear-Grund. Henry: "weiss ich noch nicht ... der Grund steht in der Console", buendelt ihn in die Bau-Karte. |
| 14:38 | Owner haakt nach. Henry stellt die Karte um. |
| 14:41 | Owner haakt zum dritten Mal nach. Henry startet `hands` (8ff9ac) fuer den Wear-Grund. |
| 14:46 | Ergebnis da - fuenf Minuten. |

Fuenf Minuten vor der ersten Weigerung hatte er die Haende fuer GENAU diese
Console benutzt, wusste also: sie funktionieren, sie kommen an die Seite,
sie brauchen drei Minuten. Kein Haende-Job lief (37be4b war um 14:33 zu,
das "ONE at a time" griff nicht). `hands.own_hands` steht auf AN. Er hat den
Wear-Blick am 14:30 ausdruecklich ausgeklammert ("phone, not Wear") und ihn
danach als Teil des Bauens behandelt statt als Frage, die man nachschlaegt.

Eine Erklaerung aus seiner Begruendung gibt es nicht - Henrys Vorueberlegung
wird nicht persistiert (nur das Ergebnis, f16fcdf9). Was sich sagen laesst:
der Brief kennt kein "Grund VOR Bau", nur "BIAS TO ACTION"; und ein moeglicher
Verstaerker ist das voice-style-Overlay, das - falls heute ein gesprochener
Turn lief - "Do NOT read files or run commands ... ANSWER FROM WHAT YOU
ALREADY HAVE" dauerhaft ins Transkript schreibt (siehe Haelfte B fuer den
Mechanismus). Ob das griff, ist nicht belegt.

Was NICHT die Ursache ist, damit es niemand wieder hinschreibt: Henrys
Chat-Port laedt zwar keine MCP-Server (`_lean_mcp_args`, `copilot.py:799`),
aber `hands` traegt die volle Bruecke und er hatte sie gerade benutzt. "Er
kann nicht" war eine falsche erste Lesart dieser Karte.

**Zu bauen:** eine harte Regel, keine Sprosse: Eine Frage nach einem GRUND
(warum abgelehnt, warum rot, warum langsam) wird NACHGESCHLAGEN, bevor
irgendetwas gebaut oder geplant wird - mit eigenen Tools oder sofort mit
`hands`, nie als Nebensatz einer Karte. Wer den Grund nicht kennt, plant
nicht. Und wenn der Owner dieselbe Frage ein zweites Mal stellt, ist die
einzige zulaessige Antwort die Handlung, nicht ein neuer Plan.

## Haelfte B - warum die Rueckfragen inhaltsleer werden

**Auf dem Board ist das Frage-Format ein UNGEREGELTER Kanal.**

- `board-copilot.md:7` traegt `ask_protocol: false`. Das Ask-Protokoll (die
  `<helmdeck-ask>`-Grammatik samt Regeln) wird nur in Briefs eingesetzt, die
  `ask_protocol: true` deklarieren - die beiden WORKER-Oberflaechen
  (`spine/registry/harness.py:238-246`). Henrys Board-Brief bekommt sie nie.
- Trotzdem PARST der Chat sie (`copilot.py:2960`, `ask.parse`), persistiert
  sie an der Bot-Zeile (`copilot.py:3044`) und die App rendert die Knoepfe.
- Es gibt auf dem Board also eine Grammatik, die angenommen wird, aber keine
  einzige Regel, WANN sie angebracht ist. Kein "frag nur, wenn du blockiert
  bist", kein "keine Frage ohne Entscheidung dahinter".

Folge: das Verhalten wird durch Nachahmung gesetzt, nicht durch Politik. Ab
der ersten berechtigten Frage (14:51) endet jeder weitere Turn mit einem
Ask-Block, weil der vorherige einen hatte. Die drei um 15:00, 15:02 und
15:03 sind DIESELBE Frage dreimal - "ist noch etwas?" - ohne eine
Entscheidung dahinter, jede mit einem "Etwas anderes"-Knopf, jede vom Owner
mit einem Wort abgenickt, und die naechste kam trotzdem. Das ist nicht drei
Fragen, das ist eine Schleife.

**Der zweite, schaerfere Pfad (gleiche Familie, code-belegt):** die Uhr und
die Brille teilen sich Henrys Session mit dem Telefon.
`spine/http/routes/routes_wear.py:529` ruft `copilot.chat()` mit DEMSELBEN
User - die Docstring darueber feiert das ausdruecklich ("a watch message has
always landed in the same Claude session the phone resumes"). Ihr Overlay
`wear-brief.md:12` sagt: "you MUST end EVERY reply with a `<helmdeck-ask>`
block offering 2-6 next moves" - auf einer Uhr voellig richtig, dort kann der
Owner nicht tippen. Und Overlays reiten laut `copilot.py:2546` INNERHALB des
Turn-Textes ("per-turn overlays ride inside the turn text so voice<->typed
does not respawn"), also im persistenten Transkript. Ein einziger Uhr-Turn
schreibt damit ein "MUSS bei JEDER Antwort" dauerhaft in die Session, die
danach jede getippte Antwort am Telefon formt - bis die Session rotiert.

Dasselbe gilt in die andere Richtung fuer `voice-style.md`: "Do NOT read files
or run commands for a spoken question ... ANSWER FROM WHAT YOU ALREADY HAVE"
und "Do not end with a question unless you are genuinely BLOCKED". Auf einem
gesprochenen Turn richtig; im Transkript haengen geblieben, erklaert es
Haelfte A gleich mit. Die beiden Overlays widersprechen sich sogar direkt -
das eine verbietet Rueckfragen, das andere macht sie zur Pflicht.

**Zu bauen:**
1. Eine Board-Regel fuer das Frage-Format: nur bei einer echten Entscheidung
   des Owners, nie als Gespraechsfueller, nie zwei Turns hintereinander ohne
   neuen Inhalt. Entweder als gerenderte Regel (`behavior.py`, damit sie im
   /harness-Editor steht) oder ueber `ask_protocol: true` mit einer
   board-eigenen Fassung.
2. Ein Turn-Overlay darf kein Dauerzustand werden. Entweder reitet es im
   SYSTEM-Teil (wo es pro Turn ersetzt wird) statt im Turn-Text, oder der
   naechste Turn einer anderen Oberflaeche hebt es explizit auf ("dieser Turn
   ist getippt: die Uhr-Regeln gelten NICHT"). Heute gilt die Regel des
   zuletzt benutzten Geraets.

## Warum das dieselbe Wurzel ist wie owner-decision-writeback

Beide Karten beschreiben Verhalten, das aus dem TRANSKRIPT stammt statt aus
einer abgeleiteten, an einem Ort gepflegten Wahrheit: dort eine
Owner-Entscheidung, die nicht in die Quelle geschrieben wurde, hier eine
Geraete-Regel, die im Transkript haengt und weiterwirkt. In beiden Faellen
ist die gelebte Politik das, was zufaellig noch im Kontext steht.
