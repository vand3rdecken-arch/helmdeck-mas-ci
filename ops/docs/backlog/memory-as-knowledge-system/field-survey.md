# Wie machen es die anderen? Gedächtnis in Agenten-Harnessen

Recherche 2026-09-21, ausgelöst von der Owner-Frage "wie macht man den Harness
jetzt klug, kannst du nicht bei pi, orca oder paseo abschauen". Grundlage für
die Karte `ops/docs/backlog/memory-as-knowledge-system`.

**Quellenlage zuerst.** Von den drei genannten liegt nur **Paseo** als Quelle
auf der Maschine (`Downloads/_paseo_src`). Für `pi` existiert hier nur unser
eigener, nie live verifizierter Treiber (`spine/agent/pi_driver.py`, Kopfnotiz:
keine CLI, kein Konto auf dieser Box). **`orca` kommt im Repo nirgends vor** -
ohne Quelle und ohne Beleg wird es hier nicht behauptet. Das
WhatsApp-Claude-Projekt in `Downloads/whatsapp-claude-agent` wurde geprüft und
hat **keine Gedächtnisschicht** (ein Treffer auf "memory" in
`src/whatsapp/client.ts`, ein In-Memory-Cache). Alles Übrige stammt aus
Primärquellen im Netz, jede Zeile mit URL.

---

## 1. Die eigene Messung (zählt mehr als jede fremde Doku)

Bevor irgendetwas übernommen wird: würde einfache Suche den Vorfall vom
20.09. verhindert haben? Nachgespielt auf dem echten Bestand von 199 Notizen
(114 db + 88 CLI-Auto-Memory), reine Worthäufigkeit mit Seltenheitsgewicht
(IDF), keine Einbettungen, kein Modellaufruf:

| Nachricht | Platz 1 |
|---|---|
| "Was ist Jev" | die Korrektur mit der direkten API |
| "Kannst du den key nicht lokal laden" | die Thesen-Test-Notiz, die den Austausch festhält |
| "warum ist der relay nicht erreichbar" | `helmdeck-relay-unreachable-is-daemon-cpu` |

**Ohne** Seltenheitsgewicht zieht "lokal laden rechner" Notizen über
Zertifikate und Expo-Builds herein - das Gewicht ist der ganze Trick.

Zweite Messung, gegen die naheliegende Übernahme von Devins
Trigger-Beschreibungen: Suche **nur über die description-Zeile** ist deutlich
schlechter - "Was ist Jev" liefert dann **keine einzige** Jev-Notiz, weil
unsere Beschreibungen als Inhaltsangabe geschrieben sind, nicht als
Auslöser. Also: über den **vollen Notiztext** suchen, nicht über den Index.
Devins Design ließe sich erst übernehmen, wenn alle 199 Beschreibungen als
Trigger neu geschrieben würden - das ist der Preis, den die fremde Doku nicht
nennt.

Kosten, gemessen:

```
alle 199 Notizen im Turn   ~98.000 Token   ausgeschlossen
nur der Index              ~4.000 Token    heute (gekürzt, 71 von 199)
die 3 besten Notizen ganz  ~2.800 Token    der Vorschlag
```

---

## 2. Was die anderen tatsächlich tun

### Claude Code Auto-Memory - die beste Vorlage für unsere Lage
<https://code.claude.com/docs/en/memory>

- **Zweistufig:** nur der Index `MEMORY.md` wird automatisch geladen, und zwar
  "the first 200 lines ... or the first 25KB, whichever comes first". Die
  Themendateien liest das Modell bei Bedarf selbst.
- **Metadaten:** `type` mit genau vier Werten (`user`, `feedback`, `project`,
  `reference`) plus `modified`, ein ISO-Zeitstempel, den **der Harness**
  setzt. Doku: "The timestamp shows how current the fact is". Loch in ihrem
  eigenen Design: der Zeitstempel wird nur ergänzt, wenn schon Frontmatter da
  ist - "Claude Code never adds frontmatter to a file that has none".
- **Überlauf wird GEMELDET.** Der beste Einzelfund der ganzen Recherche: nach
  einem Schreibvorgang misst der Harness den Index gegen das Limit, und bei
  Überschreitung "the write still succeeds, but Claude Code returns an error
  telling Claude to rewrite the index, because everything past the limit is
  dropped on the next load".
- **Widerspruch:** nichts. Für CLAUDE.md steht es offen in der Doku: "if two
  rules contradict each other, Claude may pick one arbitrarily."
- **Falle:** eine CLAUDE.md über 4 MiB wird **still** übersprungen.

### Anthropic Memory-Tool (`memory_20250818`)
<https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool>

Sechs Befehle über Dateien unter `/memories`, **keinerlei Metadaten**. Wichtig
für uns sind die **vorgeschriebenen Rückgabetexte**: "The path {path} does not
exist" für einen Fehltreffer, aber eine normale (leere) Auflistung für ein
leeres Verzeichnis - und das SDK **legt das Wurzelverzeichnis vorab an**, damit
der erste Lesezugriff nie ein Fehltreffer ist. Genau die Unterscheidung, an
der Henry gescheitert ist. Kürzung wird ebenfalls angesagt ("truncates the text
view of files longer than 16,000 characters").

### OpenAI Codex, AGENTS.md
<https://learn.chatgpt.com/docs/agent-configuration/agents-md>

Statische Verkettung von der Wurzel zum Arbeitsverzeichnis, **32 KiB
Obergrenze** (`project_doc_max_bytes`), darüber werden Dateien **einfach
weggelassen, ohne Signal** - nur ein manueller Prüfaufruf ist dokumentiert.
Dieselbe Klasse wie unsere `--settings`-Falle in `HARNESS.md`. Codex hat
daneben ein echtes Gedächtnis (`~/.codex/memories/`), geschrieben
**automatisch und zeitversetzt**: "Codex waits until a chat has been idle long
enough to avoid summarizing work that's still in progress"
(<https://learn.chatgpt.com/docs/customization/memories>).

### Windsurf / Cascade - die sauberste Beschreibung des Zwei-Stufen-Ladens
<https://docs.devin.ai/desktop/cascade/memories>

Vier Aktivierungsarten für Regeln, davon `model_decision`: "Only description
shown initially; full content loaded on demand". Gemessene Grenzen: 12.000
Zeichen je Workspace-Regeldatei, 6.000 global, darüber wird gekürzt. Ob das
Modell von der Kürzung erfährt: **nicht dokumentiert**.

### Devin Knowledge - das einzige Design mit Nachkontrolle
<https://docs.devin.ai/product-guides/knowledge> ·
<https://docs.devin.ai/product-guides/session-insights>

Eintrag = Name + **Trigger-Beschreibung** + Inhalt + optionales `!`-Makro.
"Devin retrieves Knowledge when relevant, not all at once or all at the
beginning." Der interessante Teil ist die **Knowledge-Usage-Ansicht**, die
Einträge in **Useful** und **Misleading** einteilt, mit den dokumentierten
Fehlerbildern "written for previous codebase versions" und "knowledge items
conflicting with each other". Satz zum Merken: "a single outdated knowledge
item can degrade session quality across your entire team." Auflösung ist
**Mensch im Kreis**, keine automatische Invalidierung. Achtung: Knowledge ist
**abgekündigt** und wandert in Skills.

### Zep / Graphiti - das einzige echte Zeitmodell
<https://arxiv.org/abs/2501.13956> ·
<https://raw.githubusercontent.com/getzep/graphiti/main/graphiti_core/edges.py>

Kanten tragen `valid_at` / `invalid_at` (Weltzeit) und `created_at` /
`expired_at` (wann das System es erfuhr). Bei einem neuen Fakt werden ähnliche
Kanten per Einbettung gesucht, **ein LLM-Aufruf** entscheidet Dublette gegen
Widerspruch (`resolve_edge`, Antwortmodell `EdgeDuplicate` mit
`contradicted_facts`), und die alte Kante wird **gestempelt, nicht gelöscht**.
Gemessene Schwäche, die man kennen muss: Issue
<https://github.com/getzep/graphiti/issues/1666> - mit einem kleinen Modell
bricht die Widerspruchserkennung ein (1 von 9 Wiederholungen korrekt), veraltete
Fakten überleben **still** ihren eigenen Widerspruch.

### mem0
<https://arxiv.org/abs/2504.19413>

Nach der Extraktion entscheidet **ein LLM-Aufruf** über den ähnlichsten
Bestandsnotizen zwischen **ADD / UPDATE / DELETE / NOOP**. Gleicher Schnitt wie
Graphiti, gleiche Schwäche: was nicht in die Kandidatenliste kommt, überlebt.
Historie wird in einer SQLite-Tabelle geführt (`old_memory`, `new_memory`,
`event`), aber Issue <https://github.com/mem0ai/mem0/issues/7316>: die Historie
wird nie mit dem Vektorspeicher abgeglichen - **die Prüfspur kann lügen**.

### Amp - die Gegenposition: gar kein Gedächtnis
<https://ampcode.com/docs/threads> · <https://ampcode.com/notes/how-i-use-amp>

Amp hat bewusst keines. Stattdessen Thread-Verweise, "Handoff" in einen
frischen Thread und Suche über alte Threads. Betriebsrat des Autors: "a lot of
the problems that people who are new to working with agents run into can be
traced back to them not starting new threads often enough". Cognition
argumentiert ähnlich gegen geteilten Kontext
(<https://cognition.com/blog/dont-build-multi-agents>): Gedächtnis als
**Kompression einer durchgehenden Spur**, nicht als zersplitterter Speicher.

### Paseo - hat GAR KEIN Gedaechtnis, und das ist der Befund
Quelle gelesen: `Downloads/_paseo_src`.

Paseo ist ein Multiplexer um fremde Agenten-CLIs und delegiert alles, was
anderswo Gedaechtnis waere, an den Anbieter. Belege fuer die Verneinung:
keine Einbettungen, kein Vektorspeicher (repo-weite Suche nach
`embedding|vector|lancedb|chroma|faiss|rag` = null Treffer); im
Werkzeugkatalog `packages/server/src/server/agent/tools/paseo-tools.ts` sind
39 Werkzeuge registriert, alle Orchestrierung, **kein** `remember`,
`save_note`, `search_knowledge`. Gespeichert wird nur Konfiguration und ein
Sitzungszeiger (`agent-storage.ts`, `STORED_AGENT_SCHEMA`), **kein
Gespraechsinhalt, keine Fakten**. Die eigene Doku sagt es (`docs/architecture.md`):
"Timeline rows are runtime memory; provider history is the durable transcript
authority and resumed agents rebuild from it."

Kein Abruf vor dem Turn: `prompt-attachments.ts` baut den Prompt
ausschliesslich aus dem, was Mensch oder Orchestrator ausdruecklich angehaengt
haben. Eine `@datei`-Erwaehnung fuegt einen **Pfad** ein, nie den Inhalt.
Keine Kompaktierung: Paseo beobachtet die des Anbieters und bildet sie auf ein
Wire-Item ab, **schreibt aber nichts vorher heraus**. Kein Versionieren, keine
Herkunft auf Aussagenebene; Korrektur passiert durch **Zerstoerung** (Rewind)
oder **Fork**, nicht durch Abgleich. `CLAUDE.md` liest Paseo nie selbst, es
waehlt nur die Quellen (`settingSources: ["user","project","local"]`).

Der ehrlichste Satz der ganzen Recherche steht in Paseos Handoff-Skill:
**"The receiving agent has zero context."** Das ist die Architektur, laut
ausgesprochen.

**Was trotzdem zu klauen ist - Paseos Ehrlichkeits-Muster:**

1. **Der `<paseo-system>`-Umschlag** (`agent-prompt.ts`, `formatSystemNotificationPrompt`
   / `isSystemInjectedEnvelope`): jede vom Harness eingespielte Nachricht wird
   gekennzeichnet, "so the receiving agent recognizes the prompt as
   system-injected context - not a user turn". Genau die Unterscheidung, die
   uns gefehlt hat: ein Kartenbericht ist keine Owner-Aussage.
2. **Kuerzung nennt Verlust UND Rettungsweg**: `[truncated ${omitted} chars;
   use get_agent_activity for the full response]`. Unser Index-Nachtrag vom
   21.09. hat unabhaengig dieselbe Form gefunden - hier ist der Beleg, dass sie
   sich bewaehrt.
3. **Fenster wird beziffert**: "Showing X of Y activities (limited to Z)".
4. **Leer wird benannt**, nicht leer geliefert: "No activity to display."
5. **Gegenbeispiel, das Paseo selbst nicht sauber loest**:
   `agent-timeline-content.ts` kappt bei 64 KiB mit blankem `.slice()`, **ohne
   Marker** - ein Orchestrator, der `get_agent_activity` aufruft, bekommt
   still beschnittene Shell-Ausgaben.

Fazit zur Owner-Frage: bei Paseo laesst sich fuer Gedaechtnis **nichts**
abschauen, weil es keines hat. Fuer **Ehrlichkeit der Werkzeuge** ist es die
beste Vorlage im Feld.

### Ohne Beleg geblieben
Letta/MemGPT (Recherche laeuft), Cursor Memories (Doku-Seiten leiten inzwischen auf
die Rules-Seite um, Mechanik **undokumentiert**; die verbreitete Erzählung vom
Sidecar-Modell ist Drittquelle).

---

## 3. Die Literatur zum eigentlichen Fehler

Gesucht war: Agent behauptet etwas falsch, weil die Suche still leer zurückkam.
Eine Arbeit genau dazu gibt es **nicht**. Die nächstliegenden, jeweils
gemessen:

- **NoMIRACL** <https://arxiv.org/html/2312.11361v2> - Anteil der Fälle, in
  denen ein Modell antwortet, obwohl nichts Relevantes gefunden wurde. Bei
  LLaMA-2 und Orca-2 **über 88 Prozent**. Das ist die beste Zahl für unseren
  Fehler, und das Rezept ist billig nachbaubar: eine Teilmenge ohne relevante
  Treffer bauen und FP/(FP+TN) berichten.
- **Sufficient Context** <https://arxiv.org/abs/2411.06037> - große Modelle
  "often output incorrect answers instead of abstaining when the context is not
  sufficient".
- **FaithEval** <https://openreview.net/forum?id=UeVx6L59fg> - eigener
  Teilbereich "unanswerable context"; größer ist nicht treuer.
- **False Success** <https://arxiv.org/abs/2606.09863> - und der für uns
  wichtigste Nebenbefund: **ein LLM-Richter ist als Wächter gegen diese Klasse
  fast wertlos** (AUROC bis 0,54 auf AppWorld), eine deterministische
  Zustandsprüfung schlägt ihn um Längen.
- **Guardrails as Scapegoats** <https://arxiv.org/html/2607.19449v1> - Agenten
  behandeln leere Antwortkörper als echte Daten. Exakt die Form `{"results":
  []}`.
- **MINJA** <https://arxiv.org/abs/2503.03704> - wer mit dem Agenten reden
  darf, kann in sein Gedächtnis schreiben. Relevant, sobald fremde Nutzer an
  Henry kommen.

Zu Messzahlen der Anbieter (Zep, mem0, LOCOMO): beide Seiten werfen sich
gegenseitig Rechenfehler vor, und ein unabhängiges Audit findet 6,4 Prozent
falsche Antworten im Schlüssel. **Als Marketing behandeln.**

---

## 4. Was daraus für HelmDeck folgt

Reihenfolge nach Nutzen je Aufwand.

1. **Suche im Harness, vor dem Turn** - gemessen wirksam (Abschnitt 1), kein
   fremdes System nötig. Das schließt die offene Schuld
   `henry-context-pull-is-prompt-enforced`, deren Eintrag selbst sagt, dass ein
   übersprungener Aufruf von außen nicht von einer berechtigten Auslassung zu
   unterscheiden ist.
2. **Jede Kürzung und jeder Fehltreffer meldet sich** - Vorbild Claude Code
   (Fehler beim Überlauf) und das Memory-Tool (getrennte Texte für "gibt es
   nicht" und "ist leer"). Teilweise am 21.09. geliefert.
3. **Herkunft und Zeitstempel als Pflichtfelder, gesetzt vom Harness** -
   Vorbild Claude Codes vier Typen; deren Loch (kein Stempel ohne vorhandenes
   Frontmatter) vermeiden, indem Frontmatter beim Anlegen erzwungen wird.
4. **Widerspruch beim Schreiben, mit Rangordnung statt LLM-Urteil** - Graphiti
   und mem0 setzen beide auf einen LLM-Aufruf, und beide haben dokumentiert
   dieselbe stille Schwäche. Bei 199 Notizen ist eine Regel (Owner-Aussage >
   eigene Messung > Kartenbericht) billiger, prüfbar und nach der
   False-Success-Arbeit vermutlich besser.
5. **Alte Notiz stempeln, nicht löschen** - Graphitis einzige unstrittig gute
   Idee, und mit unserer Append-Only-Kultur ohnehin deckungsgleich.
6. **Nachkontrolle, welche Notiz geholfen und welche geschadet hat** - Devins
   Useful/Misleading. Erst sinnvoll, wenn (1) steht, denn vorher gibt es keine
   Abrufe zu bewerten.

**Nicht übernehmen:** Vektordatenbank und Wissensgraph. Beide lösen ein
Größenproblem, das wir bei 199 Notizen nicht haben, und bringen die
dokumentierte stille Fehlerquelle mit. Devins Trigger-Beschreibungen erst nach
einer Neufassung aller Beschreibungen (Messung in Abschnitt 1).
