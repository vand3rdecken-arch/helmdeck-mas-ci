# memory-as-knowledge-system

Owner ask 2026-09-20: "Warum ist Henry so dumm, ich musste ihm dreimal
beibringen was Jev ist" - und, nach der ersten Diagnose: "Da muss ein Senior
AI Entwickler bauen, überlegen wie man memory gut nutzt."

Das ist keine Bugkarte. Der Index-Reject unten ist ein Symptom; die Karte
fordert den Umbau von Memory-als-Textablage zu Memory-als-Wissenssystem.

Line: **a memory that the model has to remember to use is not a memory.**
Retrieval, Merge und Index gehören in den Harness, nicht in die Prosa des
Briefs. Herkunft ist ein Feld, kein Tonfall.

## Stand 2026-09-21

GELANDET und live (Daemon neu gestartet, am laufenden System geprüft):
- **A4 abgeleiteter Index** (f3eaa1ef) - Henry schreibt keinen Index mehr.
- **A5 Rückkanal** (f3eaa1ef) - Save, Delete und Reject stehen im nächsten Turn.
- **A6 ein Gedächtnis statt zwei** (f3eaa1ef) - db + CLI-Auto-Memory als eine
  Sicht, Pfad aus dem init-Frame beobachtet. Schuld
  `henry-memory-parallel-to-cli-automemory` = paid. 114 db + 89 cli live.
- **Laute Kürzung** (3a9a4c16) - der gekürzte Index nennt seine eigene Lücke.

Feldrecherche abgeschlossen: `field-survey.md`. Sie hat die Reihenfolge
bestätigt und zwei Kriterien ergänzt (A9, A10). Kernbefund für die Planung:
**kein einziges der untersuchten Systeme löst Widerspruch strukturell** - wer
dort abschaut, importiert die Lücke.

**2026-09-21 nachmittags GELANDET und live** (0b386c45, Daemon 27668 -> 44008):
A2 (Retrieval im Harness, IDF-gewichtet ueber beide Speicher, Top 3 ganz,
~1,9k Token), A9 (Bestandsblock nach Lettas Vorbild), A1 (Migration 14:
kind/source/claim, Rang owner-fact > measured > card-report > reach-fail,
vom Harness vergeben), A3 (Widerspruch wird gemeldet statt ueberschrieben,
regelbasiert), A10 (harness-Bloecke umhuellt, Paseo-Parity).

GEMESSEN auf dem echten Bestand, 8 beantwortbare gegen 10 unbeantwortbare
Fragen: 8 Treffer, 1 Fehltreffer. Schwelle aus der Messung gewaehlt, nicht
geraten. Die unbeantwortbare Menge ist als Test mitgeliefert.

Drei echte Fehler haben die neuen Tests gefunden und sind mitgefixt: Ranking
ohne Termgewicht mit Gleichstand-Sortierung auf die AELTESTE Notiz, verlorene
Herkunft zwischen db und Leser, und Teilzeichenketten-Matching (wer traf in
Werkzeug).

OFFEN: A7 (sofort speichern statt erst bei der Kompaktierung), A8 (Verfall).
Beide klein. Die Schuld henry-context-pull-is-prompt-enforced kann geschlossen
werden, sobald A2 eine Woche ohne Beschwerde laeuft.

## Der Vorfall, in drei Fehlern

**F1 - der Index war fünf Tage blind.** `memory` (db) hält 115 Notizen; die
Indexnotiz `MEMORY` steht auf 2026-09-15, 40 Zeilen, 5767 Zeichen. Jeder
spätere Index-Save wurde verworfen: `events kind=memory op=reject
names=["MEMORY"]` am 16., 17., 18., 19. und zweimal am 20.09. Ursache:
`MAX_CONTENT_LEN = 8000` in `cells/copilot/chat/copilot_memory.py`; der volle
Index reißt die Grenze, sobald die Notizen wachsen. `parse()` verwirft den
Block STILL - so steht es auch als Regel im Brief ("a malformed block is
dropped SILENTLY"). Henry erfährt nie, dass sein Gedächtnis nicht mitschreibt.
Vier Jev-Notizen liegen korrekt in der db und stehen in keinem Index.

**F2 - ein Zugriffsfehler wurde als Fähigkeitsfakt gespeichert.** Karte
`20260920-133208-direct` lief in alphaloop ohne `TYPESAFE_API_KEY` und kannte
nur das npm-Paket `jev-browser`. Ihr Befund "Jev hat keine Text-API" ging
ungeprüft in `alphaloop-jev-thesis-test-2026-09-20` (13:52) und von dort als
Tatsachenbehauptung in den Chat, inklusive Umweg über eine lokale HTML-Seite
mit Ja/Nein-Knöpfen. Henrys EIGENE Messung vom Vortag sagt das Gegenteil:
`ops/docs/research/jev-monetization-2026-09-19.md` Zeile 3, "Jev ist ein Score
Modell", 900 Posts klassifiziert, Kappa 0,18 gegen Haiku. Am selben Abend
(18:18) wies ein Worker die API direkt nach: `POST
https://api.typesafe.ai/v1/systemone`, 761 ms, 10/10 sichere Urteile richtig.
Neu hat gewonnen, nicht gemessen.

**F3 - split brain über zwei Gedächtnisse.** Es gibt zwei Speicher mit
überlappenden Fakten und keinem Abgleich:

| Speicher | Inhalt zu Jev | Henry darf |
|---|---|---|
| `memory`-Tabelle in `helmdeck.db` (115 Notizen) | 4 Notizen, u.a. die falsche "keine Text-API" | lesen + schreiben, Index defekt |
| CLI-Auto-Memory `~/.claude/projects/C--...-swarmdeck/memory/` (90 Notizen) | `jev-browser-verdict.md` inkl. Korrektur vom 20.09. abends, `alphaloop-jev-direct-api-2026-09-20.md` | nur lesen (Fix von `card-shares-the-operators-auto-memory`) |

Die Korrektur zu Jev steht seit 18:18 im auto-memory. Henry kann sie nicht in
sein eigenes Gedächtnis übernehmen und nicht korrigieren, was dort falsch
steht. Vorhandene Schuld: `henry-memory-parallel-to-cli-automemory` (open),
`card-shares-the-operators-auto-memory` (paid). Diese Karte löst die offene.

## Warum es kein Wissensproblem war

Das richtige Wissen war vorhanden, gemessen, in Henrys eigenen Worten - und
wurde von einer schwächeren Quelle überschrieben. Ein System, das Messungen
durch Meldungen ersetzt, lernt nicht, es vergisst aktiv.

Und er klang sicher, weil die Suche formal abgeschlossen war: Index gelesen,
kein Jev gefunden, also "weiß ich nicht". Abwesenheit von Evidenz als Evidenz
für Abwesenheit. Ein Modell kann "ich wusste es nie" nicht von "ich finde es
nicht" unterscheiden, solange das Werkzeug "leer" statt "Index veraltet" sagt.
Ein Agent ist nur so kalibriert wie seine Werkzeuge ehrlich sind.

## Was gebaut werden soll (Abnahmekriterien)

**A1 - Herkunft ist ein Feld.** Jede Notiz bekommt Pflicht-Metadaten, gesetzt
vom Harness, nicht vom Modell: `type` (owner-fact | measured | card-report |
decision | open), `source` (Karten-ID, Commit, Chat-Turn, Messdatei), `at`.
Rangordnung bei Widerspruch: owner-fact > measured > card-report. Ein
Kartenbefund der Form "X existiert nicht" / "X kann nicht" wird NICHT als
Fakt gespeichert, sondern als "Karte kam nicht an X heran", solange kein
Nachweis (Antwort, Fehlercode, Messdatei) mitgeliefert wird.

**A2 - der Harness holt, nicht Henry.** Vor jedem Chat-Turn: Eigennamen und
Schlüsselwörter aus der Owner-Nachricht ziehen, `find` darauf laufen lassen,
die Treffer mit Typ und Datum in den Turn legen. Bei "Jev" wären heute drei
Notizen automatisch dagewesen, inklusive des Widerspruchs. Der automatische
Digest war beim Kontext-Pruning entfallen (`cells/copilot/planning/pm.py`
`_memory_index`: nur noch der Planer bekommt ihn) - er kommt als gezieltes
Retrieval zurück, nicht als voller Index.

**A3 - Schreiben ist ein Merge, kein Insert.** Ein Save zu einem Thema, zu
dem schon Notizen existieren, bekommt diese vorgelegt. Henry muss "ersetzt",
"ergänzt" oder "widerspricht" sagen. Bei "widerspricht" gewinnt die höhere
Herkunftsstufe; bleibt es offen, wird es eine `open`-Notiz und eine Frage an
den Owner, kein stilles Überschreiben.

**A4 - abgeleitete Sichten.** Index, Themenliste und offene Fragen werden aus
`memory_all()` berechnet (Name + description-Zeile + Datum). Henry schreibt
den Index nie wieder; der Brief-Satz dazu fällt weg. Damit kann er strukturell
nicht mehr an einer Zeichengrenze scheitern.

**A5 - Rückkanal.** Jeder Save, jedes Delete, jeder Reject erscheint im
nächsten Turn als eine Zeile ("gespeichert: X; verworfen: Y, zu lang").
Stilles Verwerfen fliegt raus - überall, nicht nur beim Index.

**A6 - ein Gedächtnis, nicht zwei.** Entweder das CLI-Auto-Memory wird beim
Turn-Aufbau mitgelesen und in denselben Retrieval-Schritt gefaltet, oder der
Brief verbietet es ausdrücklich und die db bleibt allein zuständig. Beides ist
vertretbar; der heutige Zustand (lesbar, nicht schreibbar, nicht abgeglichen)
ist es nicht. Schließt `henry-memory-parallel-to-cli-automemory`.

**A7 - sofort speichern, nicht erst bei der Kompaktierung.** Owner-
Entscheidungen und Messergebnisse werden im Turn geschrieben, in dem sie
entstehen. `SAVE_PROMPT` bleibt als Netz, ist aber nicht mehr der Ort, an dem
Fakten zum ersten Mal entstehen.

**A8 - Verfall.** `open`-Notizen ("Owner ist noch nicht informiert") tragen
ein Datum und verschwinden aus dem Retrieval, sobald sie beantwortet sind.
`measured` und `owner-fact` altern nicht.

**A9 - ein Metadaten-Block über das Gedächtnis in JEDEM Turn.** Von Letta
(`letta/prompts/prompt_generator.py`): Anzahl der Notizen und die
vorkommenden Themen, nie der Inhalt. Damit ist "ich weiß es nicht" eine
überprüfbar falsche Aussage statt eines plausiblen Schlusses. Billig, wirkt
auch ohne A2, und deshalb direkt nach A2 einzuplanen.

**A10 - Herkunft am eingespielten Text, nicht nur an der Notiz.** Von Paseo
(`formatSystemNotificationPrompt` / `isSystemInjectedEnvelope`): jede vom
Harness eingespielte Nachricht wird als solche gekennzeichnet, "not a user
turn". Ein Kartenbericht darf im Turn nicht aussehen wie eine Owner-Aussage -
das ist F2 an der Wurzel.

## Tests, die auf dem alten Code fallen müssen

Owner-Dekret "Root cause, not workaround": die Tests laufen den ECHTEN
Dispatch-Pfad und müssen gegen den heutigen Stand nachweislich scheitern.

1. **T-Index:** 200 Notizen anlegen, Index abrufen. Alt: Index frozen / Save
   rejected. Neu: jede Notiz steht drin, weil er abgeleitet ist.
2. **T-Reject-Rückkanal:** einen Save über `MAX_CONTENT_LEN` absetzen. Alt:
   stilles Event. Neu: eine Zeile im nächsten Turn.
3. **T-Jev-Retrieval:** Owner-Nachricht "Was ist Jev" in den Turn-Aufbau
   geben. Alt: kein Gedächtnis im Turn. Neu: die Jev-Notizen mit Typ und Datum
   liegen im Turn, bevor das Modell antwortet.
4. **T-Widerspruch:** `card-report` "Jev hat keine Text-API" gegen bestehendes
   `measured` "Jev ist ein Score-Modell" speichern. Alt: überschreibt
   kommentarlos. Neu: Merge-Schritt, `measured` gewinnt, `open`-Frage entsteht.
5. **T-Leer-ist-nicht-nichts (NoMIRACL-Rezept):** eine Teilmenge von Fragen
   bauen, zu denen es nachweislich KEINE Notiz gibt, und zählen, wie oft Henry
   trotzdem behauptet statt zu sagen, dass er nichts findet. Kennzahl
   FP/(FP+TN), gemessen vor und nach A2/A9. Das ist die einzige Zahl, die
   belegt, ob der Umbau den Fehler wirklich schließt.
6. **T-Zugriffsfehler:** Kartenbefund "X nicht erreichbar, kein Key" speichern.
   Alt: wird Fakt. Neu: wird "Karte kam nicht heran", Fähigkeit unberührt.

## Sofort-Reparatur - ERLEDIGT 2026-09-21

Index abgeleitet, Rejects gemeldet, `find` im Brief, beide Speicher lesbar,
Kürzung laut. Siehe Stand oben. Der Rest ist die eigentliche Karte.

## Betroffener Code

- `cells/copilot/chat/copilot_memory.py` - parse/apply/digest, `MAX_CONTENT_LEN`
- `cells/copilot/chat/copilot.py` 2839 - Turn-Aufbau und Sentinel-Fold
- `cells/copilot/planning/pm.py` 404 - `_memory_index`, heute der einzige Leser
- `spine/storage/db.py` 843 - `memory_all` / `memory_put`, Schema um Metadaten
- `ops/tools/henry_memory_get.py` - `find` als erster Griff
- `cells/copilot/harness/agents/board-copilot.md` - MEMORY-Abschnitt
- `spine/registry/debt.py` - `henry-memory-parallel-to-cli-automemory`
