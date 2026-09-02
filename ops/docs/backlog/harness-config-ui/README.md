# PRD: Die Harness-Konfiguration, sichtbar und einstellbar

**Owner-Beschwerde (2026-09-02):** Henrys eigene Verhaltensregeln — Ton,
Trigger, was er selbst tun darf — stehen als Fließtext und sind nirgends
sichtbar oder einstellbar. Gleichzeitig zeigt `settings.json` nur eine schmale
Policy-Scheibe und `policy_seed/live.json` eine tiefere Charter, die per Chat
gar nicht editierbar ist. Drei Ebenen, für den Nutzer unsichtbar vermischt.

**Der Befund ist schlimmer als die Beschwerde.** Es ist nicht ein Brief,
sondern **sieben Prosa-Quellen**, die zusammen einen Henry ergeben:

| Quelle | Umfang | erreichbar über |
|---|---|---|
| `ops/harness/agents/board-copilot.md` | 321 Zeilen | `/harness`-Editor (Owner) |
| `cells/copilot/copilot.py::VOICE_STYLE` | 25 Zeilen | **gar nicht** — Code |
| `cells/copilot/henry_broker.py::DEFAULT_POLICY` | 23 Zeilen | `settings.henry_policy` — **alles oder nichts** |
| `spine/http/routes/routes_wear.py::WEAR_BRIEF` | 20 Zeilen | **gar nicht** — Code |
| `spine/http/routes/routes_glance.py::GLASS_BRIEF` | 19 Zeilen | **gar nicht** — Code |
| `ops/harness/agents/ship-advisor.md` | 112 Zeilen | `/harness`-Editor |
| `cells/copilot/copilot.py::_SAVE_PROMPT` | 17 Zeilen | **gar nicht** — Code |

Und sie widersprechen sich messbar. Das Längengesetz steht **viermal mit vier
Werten**: 3 Sätze im Chat (`board-copilot.md:92`), 2 Sätze gesprochen
(`VOICE_STYLE`), 2 Sätze auf der Uhr (`WEAR_BRIEF`), 2 Sätze / 240 Zeichen bei
automatischen Meldungen (`spine/comms/notice.py:36`). Keine dieser Zahlen ist
ein Knopf. Das ist kein Schönheitsfehler, es ist die eigentliche
Modellierungs-Anforderung: **eine Regel hat einen Wert PRO OBERFLÄCHE**, nicht
einen globalen. Ein Design, das das übergeht, kann die vier Zahlen nur zu einer
zusammenpressen und würde Henrys Verhalten auf drei Oberflächen ändern.

**Anschluss, nicht Neubau.** Diese Karte ersetzt nichts von dem, was schon
steht. Sie benutzt vier fertige Bauteile: die U-Bahn-Pipeline
(`surfaces/app/src/ui/repo_pipeline.tsx`; PRD-Karte 20260830-065545 =
`ops/docs/backlog/repo-onboarding-templates/README.md` §4 „Das Stationsmodell"),
den generischen Schema-Renderer (`settings_schema_page.tsx`,
accounts-boards-prd Phase 4), die Policy-Plane mit ihrem einen getrackten
Writer (`spine/auth/policy.py::swap`) — und **den einen Chat**
(`card_transcript.tsx` + `card_composer.tsx`, von `chat.tsx` und der
Kartenseite bereits geteilt) mit Henrys existierenden Verben `configure` und
`set_station` (`board-copilot.md:123-146`). Kein zweiter Edit-Ort, kein
zweiter Chat, kein Drag-Drop-Editor — der Chat wird in den Bildschirm
**eingebettet**, nicht dupliziert (§5.5).

**Nichts erfinden — das Design-Gesetz dieser Karte.** Jedes UI-Element unten
hat eine benannte Herkunft aus einem Produkt, das Millionen Nutzer schon
bedienen können (§7.0). Ein Element ohne Herkunftszeile kommt nicht auf den
Bildschirm. Das ist keine Bescheidenheit, sondern die G3-Strategie: „ohne
Einarbeitung verständlich" heißt konkret „der Nutzer hat es woanders schon
gelernt".

---

## 1. Ziele

- **G1** Alles, was zur Harness gehört — Stationen, die Knöpfe, die sie
  regieren, und Henrys Verhaltensregeln — ist EIN aufgelöstes Config-Objekt
  **pro Projekt**, in der DB gespeichert, mit einer sichtbaren Vererbungskette.
- **G2** Henrys bisher unsichtbare Regeln werden **strukturierte Einträge** mit
  Label, Erklärungssatz, Wert und Herkunft — und der Brief wird aus ihnen
  gerendert statt sie zu enthalten.
- **G3** Der Nutzer versteht den Bildschirm ohne Einarbeitung: er sieht zuerst
  das Bild der Maschine, tippt eine Station an und findet genau die Knöpfe, die
  diese Station regieren — in seiner Sprache, mit einem Satz Erklärung.
- **G4** Was Gesetz ist, sieht aus wie Gesetz: Schloss, der Grund im Klartext,
  und die Datei, die es durchsetzt.

## 2. Nicht-Ziele (die Grenze aus der Anforderung, wörtlich)

- **Kein Enforcement wird exposed.** `spine/auth/auth.py`, `permissions.py`,
  `charter.py`, `gxp.py`, `card_tool_guard.py`, `ops/tools/run_gate.py` und die
  Gate-Rails in `lanemachine.py` bleiben unberührt und unkonfigurierbar. Diese
  Karte fasst ausschließlich **Werte um das Enforcement herum** an. Der
  Permissions-Matrix aus `policy_seed.json` und der `capability_charter` werden
  **nur read-only angezeigt** (mit Quell-Link), nie editierbar gemacht.
- **Kein Graph-Editor.** Die Pipeline bleibt eine PROJEKTION (der Kommentar in
  `repo_pipeline.tsx:20` ist bindend). Antippen navigiert, es zieht nichts.
- **Kein fünffacher Stations-Schalter.** Siehe §5.3: genau EINE Station ist
  wirklich schaltbar, und die UI sagt das, statt vier Attrappen anzubieten.
- **Kein Umbau der settings.json-Persistenz.** Das Projekt-Objekt ist ein
  Overlay darüber, keine Migration.
- **Kein zweiter Bildschirm.** `/loopmap` wächst in diese Rolle hinein; es gibt
  danach nicht Loop-Map *und* Harness-Seite.

---

## 3. Das Modell: eine Auflösungskette, sechs Scopes

Heute liegt Konfiguration in drei Töpfen, die nichts voneinander wissen:
`settings.json` (Workspace), `daemon/policy_live.json` (Gesetze + Charter) und
`ops/harness/agents/*.md` (die Briefs, nur über den Owner-Editor erreichbar).
Dazu kommen Werte, die **gar nicht** Konfiguration sind, sondern Konstanten im
Code (`henry_broker._INTERVAL_S = 90`, `_MAX_ATTEMPTS = 2`,
`chat_dedupe.WINDOW = 600`).

Das Zielbild fügt eine Schicht hinzu und **entfernt keine**:

```
Code-Default  →  Seed (policy_seed.json / BEHAVIOR_RULES)  →
Workspace (settings.json)  →  PROJEKT (neu: DB)
```

Später gewinnt. **Abwesend heißt geerbt**, nie „auf null gesetzt" — leere Werte
werden gelöscht statt persistiert (die Paseo-Regel, die
`settings-ia-redesign` schon zitiert). Jede Zeile im UI zeigt ihren Zustand:
`Geerbt vom Workspace` oder `Für dieses Projekt gesetzt` mit einem
Zurücksetzen-Link. Das ist exakt das GitHub-Muster (Repo-Settings zeigen
„inherited from organization") und macht die Kette ohne Erklärtext lesbar.

**Speicher.** Eine Tabelle in der Form, die für Accounts schon steht:

```
project_config(project, key, value, updated_at, PK(project, key))
```

Gleiche Gestalt wie das ausgelieferte `user_config(user, key, ...)`, gleicher
`_version`-Bump für den SSE-Cursor, damit ein zweites offenes Gerät live
nachzieht. `SCOPES` wächst um `project`:

```
SCOPES = ("profile", "board", "workspace", "device", "system", "project")
```

**Ein Writer, getrackt.** Jeder Schreibvorgang läuft über denselben Pfad wie
heute `policy.swap()`: er gibt den Vorwert zurück (der Rückgängig-Griff) und
spiegelt op/actor/before/after in den append-only Sink. Das Append-only-Gesetz
bleibt unberührt, weil es nicht umgangen, sondern benutzt wird.

**Autorität bleibt, wie sie ist.** `agentMaySwap` ist `false`. Henry darf eine
Regeländerung **vorschlagen** (er ist der Exception-Broker, das ist sein Job) —
ausführen darf er sie nicht ohne menschliche Bestätigung. Das schließt den
Kreis: die Beschwerde war „ich sehe seine Regeln nicht", die Antwort ist „du
siehst sie, und er darf dich um eine Änderung bitten".

**Welches Projekt gilt wann — die Auflösungsregel, explizit.** Henry ist EIN
Agent pro Workspace, und viele seiner Turns haben gar kein Repo
(`machine_task`, Board-Fragen). Ein Projekt-Scope ohne Auflösungsregel wäre
eine gespeicherte Annahme — genau die Klasse, die das No-Monkey-Patch-Gesetz
verbietet. Deshalb wird die Projektzugehörigkeit **am Ereignis** aufgelöst,
an genau einem Owner:

- **Karten-Turns** (Worker, Broker-Eskalationen zu einer Karte): das Repo der
  Karte. Es steht am Dispatch fest.
- **Chat-Turns mit Repo-Bezug** (`direct_task`, `configure` mit `repo`,
  Pipeline-Fragen): das genannte Repo, sonst `default_repo`.
- **Alles andere** (Board-Fragen, `machine_task`, Smalltalk): Workspace-Werte,
  Projekt-Overlay bleibt schlicht unangewendet.

**Der warme Prozess ist die Leitplanke für den Transportweg.** Henrys
1.6s-Warm-Turns leben davon, dass der Basis-Brief EINMAL beim Spawn mitfährt
(`--append-system-prompt`, `copilot.py:332`) und danach nicht neu gerendert
wird. Daraus folgt die Aufteilung: **Workspace-Regeln rendern in den
Basis-Brief** (eine Änderung bumpt die Config-Version → `_persist_drop`, der
nächste Turn spawnt mit dem neuen Brief — der Mechanismus existiert), und
**projektabhängige Regeln reisen als Turn-Overlay** über den vorhandenen
`extra_system`-Pfad (`copilot.py:1505`), genau wie heute `VOICE_STYLE` und die
Wear/Glass-Briefs. Kein Respawn pro Projektwechsel, kein kalter Henry nach
jedem Regel-Edit.

---

## 4. Henrys Regeln als strukturierte Einträge

### 4.1 Die Mechanik: der Brief wird gerendert, nicht ersetzt

Der Brief bleibt eine Datei und bleibt Prosa. Was sich ändert: die Absätze, die
wirklich einen Wert tragen, werden zu **Slots**, und die Werte rendern hinein.
Das Muster existiert bereits — `harness.py` spleißt heute `{{ask_protocol}}`
ein, weil Prompt und Parser zusammen ausgeliefert werden müssen.

```
BEHAVIOR_RULES = [
  {"key": "voice.length",
   "block": "voice",                      # der Themenblock in der linken Navigation
   "title": "Antwortlänge",
   "desc": "Wie viel Henry schreibt, wenn du nichts anderes sagst.",
   "kind": "policy",                      # policy | fixed  (wie LANE_FLOW)
   "control": "single",
   "options": ["knapp", "normal", "ausführlich"],
   "scope": "workspace",                  # überschreibbar pro Projekt
   "binds": [],                           # Stationen, an denen die Regel greift
   "why": "...",
   # EIN Wert pro Oberfläche - der heutige Zustand, nicht eine Erfindung
   "per_surface": {
     "chat":   {"default": "knapp",     "renders": "board-copilot.md:{{rule:voice.length}}"},
     "voice":  {"default": "sehr knapp", "renders": "VOICE_STYLE:{{rule:voice.length}}"},
     "wear":   {"default": "sehr knapp", "renders": "WEAR_BRIEF:{{rule:voice.length}}"},
     "notice": {"default": "sehr knapp", "renders": "notice.py:MAX_SENTENCES"}},
   "source": "ops/harness/agents/board-copilot.md:92"},
  ...
]
```

**Oberflächen sind bereits ein registriertes Vokabular** —
`spine/registry/harness.py:404` führt die Surface-Tabelle
(`{key, agent, label}`), aus der `/harness` schon heute den Editor baut. Die
Regeln hängen sich dort an, statt eine zweite Liste aufzumachen. Im UI ist das
eine Zeile mit einem aufklappbaren „pro Oberfläche"-Detail: der Nutzer sieht
*eine* Regel „Antwortlänge" und darunter, dass die Uhr knapper ist als der
Chat — statt vier unverbundene Zahlen an vier Orten.

Damit werden auch `VOICE_STYLE`, `WEAR_BRIEF` und `GLASS_BRIEF` aus dem Code
zu Briefs unter `ops/harness/agents/` (was sie sind: Policy, kein Mechanismus)
— derselbe Zug, der `board-copilot.md` schon aus `copilot.py` befreit hat.

Deklariert wird die Tabelle **neben dem Lader** (`spine/registry/harness.py`),
aus demselben Grund, aus dem `LANE_FLOW` neben `move_lane()` steht und
`_config_schema` importierbar auf Modulebene liegt: ein Vertrag, den niemand
importieren kann, ist ein Vertrag, den niemand prüfen kann.

**Zwei Vertragstests, beide nach vorhandenem Vorbild** (`test_harness_layer.py`,
`test_settings_hub_vocabularies`):

1. **Slot-Gleichheit.** Jede Regel hat genau einen Slot im Brief, jeder Slot
   genau eine Regel. Eine Regel ohne Slot ändert nichts und *behauptet* es —
   genau die Klasse Fehler, gegen die der Renderer gebaut wird.
2. **Byte-Identität bei Defaults.** Mit allen Werten auf Default muss der
   gerenderte Brief **byteweise** dem heutigen entsprechen. Das ist die
   Abnahme, die verhindert, dass der Umbau Henrys Verhalten still verschiebt.

### 4.2 Die ehrliche Liste

Der Brief ist zu 28 KB **Begründung**, nicht Regelwerk. Parametrisierbar ist
nur ein Teil; der Rest (die Do/Don't-Beispiele, die Decree-Herleitungen) bleibt
Prosa und wird read-only angezeigt. Diese Karte behauptet **nicht**, dass der
ganze Systemprompt ein Formular wird — das wäre die unehrliche Version.

Fünf Blöcke, ~18 Einträge. Spalte „heute" ist die Fundstelle des Fließtexts:

**Ton & Länge** *(Scope: Workspace — es gibt einen Henry)*

| Eintrag | Control | Default | heute |
|---|---|---|---|
| Antwortlänge | knapp/normal/ausführlich | knapp | `board-copilot.md:92` „AT MOST 3 short sentences" |
| Anrede | du/Sie | du | `:18` „always du" |
| Sprache | de/en | de | `:18` + `policy.lang` (existiert, ohne Bezug zum Brief) |
| Trockener Humor | Schalter | an | `:21` „Mild dry humor is allowed" |
| Interne Begriffe vermeiden | Schalter | an | `:73` „never internal jargon (Snapshot, Lane, Gate, Worktree)" |
| **Eigene Hausregeln** | Freitext | leer | **`policy.house_rules` — existiert seit Monaten und hatte NIE eine Oberfläche** |
| Beispiel-Dialoge | read-only | — | `:25-42`, „examples are the law" |

**Eigeninitiative** *(Scope: Projekt — ein Doku-Repo will das anders als ein Code-Repo)*

| Eintrag | Control | Default | heute |
|---|---|---|---|
| Selbst machen vs. delegieren | Dial 3-stufig | gemischt | `:43` BIAS TO ACTION |
| Dauer schätzen + „musst nicht warten" | Schalter | an | `:65` SPEED OF FIRST WORD |
| Zwischenstand ungefragt beim Wiederkommen | Schalter | an | `:75` Regel 3 |
| Karten selbst durchs Gate fahren | Schalter | an | `:253` FINISH WHAT YOU START |
| Rückfragen bei unklarem Auftrag | 0–3 | 2 | `:220` BIG OR FUZZY |
| Alte Karten gegen neuere prüfen | Schalter | an (fix empfohlen) | `:310` STALE-CARD CHECK |

**Was Henry selbst darf** *(Scope: Projekt)*

| Eintrag | Control | Default | heute |
|---|---|---|---|
| Eigene Hände für Kleinkram | Schalter | an | `:202` YOU HAVE HANDS |
| Erlaubte Aktionen | Mehrfachauswahl über die Verben | alle | `:107-132` die Aktionsliste |
| Standardweg für Repo-Arbeit | direkt / Worktree+Review | direkt | `:213` TRIAGE (Decree 2026-08-29) |
| Geschützte Dateien | Liste, **nur additiv** | Code-Liste | `:240` PERMISSION-SURFACE FILES |
| Löschen ohne Auftrag | read-only, fix | fragen | `:236` |
| Schreibrechte im Turn | plan/acceptEdits | acceptEdits | `settings.henry_permission_mode` — **existiert, ohne UI** |
| **Henry darf Regeln selbst ändern** | Schalter | **aus** | `policies.agentMaySwap` — heute unsichtbar |

> **Die Grenze, explizit.** Ein Verb hier auszuschalten ist eine echte
> Verengung. Ein Verb einzuschalten **erteilt keine Berechtigung** — der Server
> prüft weiterhin `chat_admin_roles` / `machine.roles` / den Tool-Guard und die
> allow/deny-Listen in `ops/harness/settings/copilot.json`. Diese Zeilen sind
> der Gürtel; das Enforcement ist der Hosenträger und bleibt Code. Die Zeile
> sagt das im Untertitel, statt es den Nutzer herausfinden zu lassen.
> „Geschützte Dateien" ist aus demselben Grund additiv: dieselbe Regel, unter
> der `policy.house_rules` schon steht (`charter.py:12` — hinzufügen ja,
> abschwächen nie).
>
> **Eine Lücke, die diese Karte schließt, statt sie zu erben.**
> `harness.write_agent` (`spine/registry/harness.py:647-678`) validiert heute
> **nur die Frontmatter**; der Body ist ausdrücklich „free prose (it is the
> policy)". Das heißt: die Sicherheitssätze *im Brief* — die
> `configure`-Allowlist, die Liste der Permission-Dateien, „vor dem Löschen
> fragen" — sind heute per Editor überschreibbar. Sie sehen aus wie
> Invarianten und sind keine. Sobald diese Sätze Regeln mit `kind: "fixed"`
> sind, sind sie es wirklich: der Renderer setzt sie, der Editor kann sie nicht
> mehr wegschreiben, und die Vertragsprüfung merkt es, wenn ein Slot fehlt.
> Das ist der Punkt, an dem das Sichtbarmachen die Sicherheit **erhöht** statt
> sie aufzuweichen.

**Melden & Fragen** *(Scope: Projekt)*

| Eintrag | Control | Default | heute |
|---|---|---|---|
| Nachfass-Intervall | Sekunden | 90 | **hartkodiert** `henry_broker._INTERVAL_S` |
| Nachfass-Versuche | Zahl | 2 | **hartkodiert** `_MAX_ATTEMPTS` |
| Meldung aufs Handy | Schalter | an | Push-Pfad, kein Knopf |
| Nicht stören von–bis | Zeitfenster | leer | existiert nicht |
| Doppelmeldungen unterdrücken | Sekunden (Erweitert) | 600 | **hartkodiert** `chat_dedupe.WINDOW` |
| Nie „kann ich nicht" | read-only, fix | an | `:202` NEVER DEAD-END (Owner-Decree) |

**Gedächtnis** *(Scope: Workspace)* — Notizen an/aus, Index-Pfad (read-only),
Verdichtungsschwelle (Erweitert). Heute: `:264` DU HAST EIN GEDAECHTNIS.

### 4.3 Der Brief, lesbar — ein Klick, kein Suchen

Die Regeln als Formular (§4.2) sind die eine Hälfte der Sichtbarkeit. Die
andere: der Owner muss den **ganzen Brief** sehen können, so wie Henry ihn
wirklich bekommt — sonst bleibt das Misstrauen „was steht da noch drin, was
ich nicht sehe". Dafür bekommt jeder Henry-Block oben einen Link
**„Brief ansehen"**, pro Oberfläche (Chat / Sprache / Uhr / Push):

- **Gerenderte Prosa, read-only**, mit den Slots als farbigen Chips im Text —
  der Wert steht IM Satz, dort wo er wirkt. Tippen auf einen Chip springt zur
  Settings-Zeile. Das ist das Merge-Tag-Muster der E-Mail-Template-Editoren
  (Mailchimp/HubSpot: Prosa mit hervorgehobenen `*|Variablen|*`) — Millionen
  Nutzer kennen „hervorgehoben = das ist der einstellbare Teil".
- **Alles Nicht-Hervorgehobene ist sichtbar fix** — gedimmte Prosa, kein
  Chip. Kein versteckter Absatz: die Ansicht rendert die Datei vollständig,
  inklusive der Do/Don't-Beispiele und Decrees.
- **Formular ↔ Brief ist ein Toggle**, kein zweiter Ort — dasselbe Muster wie
  VS Code „Open Settings (JSON)" (UI-Ansicht und Roh-Ansicht derselben Werte)
  und GitHub Actions „View workflow file" neben der Pipeline-Ansicht. Beides
  sind Fenster auf denselben Zustand; editiert wird in der Formular-Ansicht.
- Die Ansicht existiert nach Phase 2 gratis: sie zeigt exakt das Artefakt,
  das der Renderer ohnehin baut und das die Byte-Identitäts-Abnahme prüft.
  Kein zweiter Render-Pfad.

### 4.4 Der Autonomie-Dial bekommt endlich etwas zu tun

`settings-ia-redesign` Karte 4 (`autonomy-dial`, offen) beschreibt einen Dial
*Nur melden / Fragen / Selbst handeln* über `pm.autonomy` +
`policy.auto_accept_green` + `auto_dispatch_*`. Mit dieser Karte bekommt er
seine eigentliche Masse: er ist ein **Preset über eine benannte Teilmenge**
obiger Regeln (Eigeninitiative + Aktionsrechte). Jede vom Dial gesetzte Zeile
trägt das Badge `vom Dial gesetzt` und darf einzeln übersteuert werden — dann
zeigt der Dial „angepasst". Das ist das Stripe/Vercel-Muster (Preset oben,
Einzelzeilen darunter, Abweichung sichtbar) und schließt eine offene Karte,
statt eine konkurrierende aufzumachen.

> **Gemessene Korrektur an der Vor-Karte.** Dort steht, der Dial mappe auf
> `pm.autonomy`. Das trägt nicht: `pm.autonomy` gatet ausschließlich die
> PM-Zelle (`cells/pm/pm.py:764, 1212, 1227, 1362`) und erreicht **weder
> Henrys Brief noch den Broker**. Ein Dial, der heute auf „Nur melden" steht,
> ändert an Henrys Eigeninitiative exakt nichts — was genau erklärt, warum der
> Owner seine Regeln nirgends wiederfindet. Der Dial braucht die Regeln aus
> §4.2 als Substanz; deshalb kommt Karte 5 nach Karte 2 und nicht davor.

---

## 5. Der Bildschirm

`/loopmap` heißt künftig **Harness** und ist die eine Adresse. Es ist heute
schon der Bildschirm „die Maschine, lesbar gemacht", rendert schon die Pipeline
und endet heute in einer Sackgasse („Ändern? Sag es Henry."). Genau diese
Sackgasse wird zum Eingang.

### 5.1 Layout, breit (Desktop/Tablet)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  Harness                                        Projekt: [ HelmDeck      ▾ ] │
│  So arbeitet dieses Projekt.                              [ Suche…         ] │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│      ●━━━━━━━━━━━●━━━━━━━━━━◇━━━━━━━━━━━●━━━━┄┄┄┄┄┄┄○                        │
│    Karte       Arbeit      Gate       Abnahme      Deploy                    │
│    3 Knöpfe      🔒 2        🔒          2          aus – kein Befehl        │
│                                                                              │
│    Henry ├──legt an────steuert──────────entscheidet──entscheidet Ship──┤     │
│                                                                              │
│    ▸ Build-Loop  ALIGN › ANALYZE › EXECUTE › TEST › CLEAN › BUILD › COMMIT   │
├────────────────────┬─────────────────────────────────────────────────────────┤
│ STATIONEN          │  Abnahme                                    🔒 Gesetz   │
│   Karte         3  │  ─────────────────────────────────────────────────────  │
│   Arbeit      🔒 2 │  Beim Eintritt läuft der Quality-Gate. Rot → die Karte  │
│   Gate        🔒   │  geht mit sichtbarem Grund zurück.                      │
│ ▸ Abnahme        2 │  Fix, weil eine Abnahme sonst nur eine Meinung wäre.    │
│   Deploy         ○ │  → cells/engineer/sessions.py:154                       │
│                    │                                                         │
│ HENRY              │  Grüne Karten automatisch annehmen          [ ●———  ]   │
│   Ton & Länge      │  Aus: du nimmst jede Karte selbst ab. An: eine grüne    │
│   Eigeninitiative  │  Karte merged ohne dich.                                │
│   Was er darf      │  Workspace · geerbt                                     │
│   Melden & Fragen  │                                                         │
│   Gedächtnis       │  Henry fährt fertige Karten selbst durchs Gate  [●——]   │
│                    │  Er schiebt auf Abnahme, prüft grün, und nimmt an —     │
│ GRUNDGESETZE    🔒 │  statt auf deinen Zug zu warten.                        │
│                    │  Projekt · für dieses Projekt gesetzt · zurücksetzen    │
│ ⚙ Erweitert        │                                                         │
│                    │  ▸ Erweitert (3)                                        │
└────────────────────┴─────────────────────────────────────────────────────────┘
```

**Phone:** dieselbe Information als Drilldown — Pipeline oben (horizontal
scrollbar, wie heute), darunter die Blockliste, Tippen öffnet die Detailseite.
Kein zweites Layout-Konzept; identisch zur ausgelieferten Hub-Mechanik.

Nicht eingezeichnet, aber Teil des Layouts: unten rechts der angedockte
Henry-Knopf (öffnet Panel/Bottom-Sheet, §5.5) und in jeder Zeile der
„Henry fragen"-Link; im Kopf jedes Henry-Blocks „Brief ansehen" (§4.3).

### 5.2 Die drei Zonen und warum genau diese

- **Oben der Graph — automatisch erzeugt, in einer Reihe** (GitHub
  Actions/CircleCI). Er ist gleichzeitig das Inhaltsverzeichnis: Station
  antippen filtert die Liste darunter. Der `onSelect`-Prop existiert bereits
  und `loopmap.tsx:315` benutzt ihn schon.
- **Links die Themen-Navigation** (Stripe/Vercel/GitHub-Repo-Settings): erst
  die Stationen in Fluss-Reihenfolge, dann Henrys Blöcke, dann die Gesetze,
  ganz unten Erweitert. Die Reihenfolge kommt vom Server, nicht aus einer
  Client-Liste — dieselbe Regel, unter der `DOORS` schon steht.
- **Rechts eine Zeile pro Knopf**: Label, Control, ein Satz, Scope-Badge. Nie
  mehr als 5 Zeilen sichtbar, Rest hinter `Erweitert (n)`.

### 5.3 Gates als Umschalter — die ehrliche Fassung

Die Anforderung will „Gates als Umschalter". Der Code ist an dieser Stelle
brutal ehrlich (`sessions.py:240`): `SWITCHABLE_STATIONS = ("deploy",)`, mit
der Begründung *„A UI offering five toggles would be found out the first time
one was tapped."* Das bleibt so. Umgesetzt wird es als:

- **Deploy** trägt einen echten Schalter (An verlangt den Befehl).
- **Karte, Arbeit, Gate, Abnahme** tragen ein Schloss, den `why`-Satz und den
  Datei-Link. Kein Schalter, keine Attrappe.
- **Aber jede Station trägt ihre Knöpfe** — und das ist die Form, in der
  „Umschalter" wahr ist: Karte hat `auto_dispatch_priority` und `wip_limit`,
  Abnahme hat `auto_accept_green` und `sod_accept`. Vorher hatte die Station
  Abnahme genau einen Knopf; mit Henrys Regeln hat sie vier.

Die Zählung im Badge („3 Knöpfe") ist ableitbar, nicht gepflegt: `/loop/map`
liefert bereits `editable` (die Schnittmenge aus den `settings:`-Pfaden der
Knoten und dem, was das Schema wirklich rendert). Neue Daten braucht es dafür
nicht.

### 5.4 Was die Pipeline neu bekommt (Erweiterung, kein Ersatz)

`repo_pipeline.tsx` bleibt die eine Komponente und bleibt eine Projektion.
Ergänzt wird:

1. **Knopf-Badge pro Station** — Zahl oder Schloss, aus `editable` abgeleitet.
2. **Auswahl-Zustand als Navigation** — vorhanden, wird nur genutzt.
3. **Die Henry-Spur** — ein Band unter der Reihe, das die Stationen überspannt,
   an denen Henry handelt, mit seinem Verb pro Station. Datenquelle ist das
   `binds`-Feld der Regeln; der Server aggregiert, der Client bekommt fertige
   Segmente. Keine Stationsliste im Client — dieselbe Regel wie bisher.
4. **Build-Loop als zweite, eingeklappte Reihe** — dieselbe visuelle Grammatik,
   dieselbe Komponente. `/loop/map` liefert `build` bereits.

Die Zustandsvokabeln bleiben, wie ausgeliefert: durchgezogen = an, gestrichelt
+ `off_reason` = aus, Gate pulsiert. Zwei verschiedene „aus" (Vorlage benutzt
die Station nicht / Deploy hat keinen Befehl) bleiben unterscheidbar.

**Der dritte Zustand ist bereits spezifiziert und nur nie gebaut worden.** Die
Vor-PRD (`repo-onboarding-templates/README.md` §4.2) definiert *drei* Zustände
— **Fest / Automatisch / Aus** —; die ausgelieferte Komponente rendert nur
zwei. „Automatisch" (hohle Station, gestrichelte Kante) ist exakt die Vokabel,
die diese Karte braucht: eine Station, die läuft, **aber ohne dich** — grüne
Karten mit `auto_accept_green`, Karten, die Henry selbst durchs Gate fährt.
Der Zustand wird also nicht erfunden, sondern eingelöst.

Die `edges` liegen bereits im Payload und werden von der Komponente heute
ignoriert (sie zeichnet einen geraden Verbinder). Für die Henry-Spur bleibt
das so — die Spur ist ein Band unter der Reihe, keine zweite Kantenmenge.

### 5.5 Henry im Bildschirm — der Chat als gleichberechtigter Bedienweg

Der Owner soll jede Einstellung auf ZWEI Wegen ändern können, die auf
demselben Zustand landen: die Zeile antippen **oder** es Henry sagen. Das
Vorbild ist ausgeliefert und bekannt: **Copilot in den Windows-11-
Einstellungen** (Chat-Panel neben der Settings-Seite, „schalte den Dunkelmodus
ein" flippt den sichtbaren Schalter) — dasselbe Muster als Seitenpanel kennt
jeder VS-Code-Nutzer vom Copilot-Chat. Konkret:

- **Ein Chat, angedockt, nicht dupliziert.** Rechts unten ein Henry-Knopf
  (Intercom-Launcher-Muster); Tippen öffnet auf breiten Screens ein
  Seitenpanel, auf dem Phone das Bottom-Sheet. Innen leben
  `card_transcript.tsx` + `card_composer.tsx` — **dieselbe Instanz des
  Workspace-Chats** (gleiche Session, gleicher Verlauf), nur an dieser Adresse
  aufgeklappt. Das Ein-Chat-Gesetz (Owner-Direktive) bleibt damit wahr; die
  Sackgasse „Ändern? Sag es Henry." wird zum Knopf, der Henry wirklich öffnet.
- **Kontext reist mit, sichtbar.** Jede Settings-Zeile trägt „Henry fragen";
  Tippen öffnet das Panel mit einem **Kontext-Chip** über dem Composer
  (`Abnahme · Grüne Karten automatisch annehmen`) — das Attach-Context-Muster
  aus dem VS-Code-Copilot-Chat. Der Chip reist als `configure`-`repo`/Key-
  Kontext im Turn mit; Henry muss nicht raten, welche Zeile gemeint war.
- **Ein Schreibpfad, kein zweiter.** Henry ändert über seine existierenden
  Verben (`configure`, `set_station`); die landen im selben getrackten
  `swap()`-Pfad wie ein Zeilen-Tap. Chat-Änderung und Hand-Änderung stehen
  im selben Audit, mit demselben Rückgängig-Griff.
- **Die Allowlist wird abgeleitet, nicht doppelt gepflegt.** Heute zählt
  `board-copilot.md:134-146` zwölf Keys per Hand auf — eine zweite Liste
  neben dem Schema, die auseinanderlaufen KANN und wird. Ab Phase 2 rendert
  dieser Brief-Absatz als `fixed`-Slot **aus dem Schema** (`editable=true` ⇒
  chat-konfigurierbar): was die Seite editieren kann, kann der Chat editieren,
  per Konstruktion dieselbe Menge. Das ist derselbe UMZUG-Grundsatz wie §6,
  auf die Allowlist angewandt.
- **Der Rundlauf ist sichtbar.** Henrys Änderung bumpt `_version`, der
  SSE-Cursor zieht die offene Seite nach (der Mechanismus, der heute schon
  zwei Geräte synchron hält), die betroffene Zeile blitzt kurz auf, und
  Henrys Antwort verlinkt sie („✓ Grüne Karten werden jetzt automatisch
  angenommen → Abnahme"). Der Nutzer sieht den Schalter sich bewegen — das
  ist der Moment, der Vertrauen in den Chat-Weg baut.
- **Schlösser gelten auch im Chat.** Ein `fixed`-Wert bleibt per Chat genauso
  unveränderbar wie per Zeile; Henry antwortet mit dem `why`-Satz und der
  Quelle — denselben Daten, die die Zeile zeigt (sein Brief tut das heute
  schon: „the action refuses it BY NAME with the route that IS open",
  `:125`). Und `agentMaySwap=false` heißt: bei Charter-Werten schlägt Henry
  vor und der Owner bestätigt mit einem Tap im Panel — Vorschlag und
  Bestätigung im selben Verlauf, auditierbar.

---

## 6. Wo die bestehenden Werte landen

**„Landet bei" heißt UMZUG, nie Duplikat.** Mehrere der Knöpfe unten sind
heute in Tür Automation/System editierbar; die Stationsseite würde sie ein
zweites Mal rendern — ein Verstoß gegen das eigene Phase-3-Kriterium und gegen
das Decree „kein zweiter Edit-Ort für irgendeinen Key". Der Mechanismus für
den Umzug ist ausgeliefert und hat einen Präzedenzfall: `policy.lane_labels`
ist in Phase 4 der Vor-PRD per `door`-Metadatum von Automation nach Boards
gezogen, **ohne Client-Edit** (`apimeta.py:146-155` dokumentiert genau das).
Die Stationszuordnung ist ein weiteres Metadatum derselben Art (`station:
"backlog"` statt einer neuen Tür); die alte Tür-Zeile verschwindet im selben
Daemon-Commit, in dem die Stationsseite sie bekommt. Tür Automation behält,
was keiner Station gehört (Nightshift-Fenster etc.).

**Aus `settings.json`, Zweig `policy.*`** (vollständig, 18 Schlüssel im Code
belegt):

| Schlüssel | landet bei | Stufe | heute |
|---|---|---|---|
| `auto_dispatch_priority`, `auto_dispatch_modes` | Station **Karte** | basic | Tür Automation |
| `capacity.wip_limit` | Station **Karte** | basic | Tür System |
| `auto_accept_green` | Station **Abnahme** | basic | Tür Automation |
| `sod_accept` | Station **Abnahme** | advanced | **ohne UI** |
| `ask_repair` | Station **Arbeit** | advanced | **ohne UI** |
| `auto_continue` | Station **Arbeit** | advanced | **ohne UI** |
| `load_admission` | Station **Gate** | advanced | **ohne UI** (4-Feld-Objekt — eine Stationsseite kann eine Gruppe rendern, das flache Schema konnte es nicht) |
| `repo_hooks.<repo>.deploy` | Station **Deploy** | basic | nur über Henry |
| `house_rules` | Henry ▸ **Ton & Länge** | basic | **ohne UI** |
| `chat_admin_roles`, `chat_configure_roles`, `machine.roles` | Tür **Team**, von hier nur **verlinkt** | advanced | ohne UI |
| `lane_labels` | bleibt Tür **Boards** | — | ausgeliefert |
| `lang`, `backdrop`, `dashboard` | bleiben Tür **Mein Profil** | — | ausgeliefert |
| `esign`, `device`, gxp-Zweig | bleiben Compliance, nur verlinkt | — | eigene Karte |

**Aus `policy_seed.json` / `policy_live.json`** (nur der Nicht-Sicherheitsteil):

| Wert | landet bei | Modus |
|---|---|---|
| `gateBeforeReview`, `auditAppendOnly`, `worktreeIsolation`, `authRequired`, `measuredEconomics` | Block **Grundgesetze** | read-only, Schloss + `why` + Quelle (die `laws`-Liste aus `/loop/map` liefert sie bereits mit Quell-Link) |
| `charter.laws` (5 Sätze) | Block **Grundgesetze** | read-only, Quelle `CLAUDE.md` |
| `agentMaySwap` | Henry ▸ **Was er darf** | echter Schalter, Default aus |
| `wipLimit` | **entfällt** — Dublette | löst sich auf `capacity.wip_limit` auf (die Dublette ist seit `settings-ia-redesign` bekannt; `policy.load()` seedet heute schon aus der Capacity) |
| `buildLoopEnabled` | zweite Reihe **Build-Loop** | Schalter |
| `engineerEnabled`, `pmEnabled`, `processEnabled`, `connectorsEnabled`, `copilotEnabled` | bleiben Tür **Cells** | ausgeliefert |
| `permissions{}` (Rollenmatrix) | **nicht exposed** | höchstens read-only-Tabelle in Tür Team, Quelle `spine/auth/permissions.py` |
| `capability_charter` | **nicht exposed** | read-only; Swap bleibt menschlich (`capabilitySwapRequiresHuman`) |

**Aus `settings.json`, Henry-Zweig** (existiert, hatte nie eine Oberfläche):

| Schlüssel | landet bei | Anmerkung |
|---|---|---|
| `henry_policy` | Henry ▸ **Ton & Länge**, Erweitert | Heute **alles-oder-nichts**: gesetzt, ersetzt es `DEFAULT_POLICY` des Brokers vollständig (`henry_broker.py:385`). Es ist derzeit **unset**, also lebt der Code-Default — der Owner hat einen Schalter, der nur „ganz oder gar nicht" kann. Er löst sich in die Regeln aus §4.2 auf; der Freitext bleibt als `house_rules` (additiv) erhalten |
| `henry_permission_mode` | Henry ▸ **Was er darf** | `plan` \| `acceptEdits`, Default `acceptEdits`, gilt für Chat **und** Broker |
| `voice_model` | Henry ▸ **Ton & Länge**, Erweitert | pinnt das schnelle Modell auf gesprochenen Turns; unset → haiku |

**Aus dem Code, bisher gar keine Konfiguration** (§4.2): `_INTERVAL_S = 90`,
`_MAX_ATTEMPTS = 2`, `chat_dedupe.WINDOW = 600`, `notice.MAX_CHARS = 240` /
`MAX_SENTENCES = 2`. Sie werden Regeln mit dem Code-Wert als Default — der
bisherige Zustand bleibt also der Auslieferungszustand.

**`env.SWARM_WIP_MINUTES`** bleibt read-only mit Erklärung. Es ist eine
Umgebungsvariable; `routes_info.py:78` nennt das ausdrücklich als den Fall, in
dem ein Chip auf einen Bildschirm zeigte, der den Knopf nie enthielt. Anzeigen
ja, tappbar nein.

---

## 7. Verständlichkeit — die konkreten Mittel

### 7.0 Die Herkunftstabelle — jedes Element ist irgendwo schon gelernt

Owner-Anforderung wörtlich: nichts erfinden. Deshalb hier die vollständige
Liste — jedes Element, sein Vorbild, und was genau übernommen wird. Ein
Element, das in dieser Tabelle fehlt, gehört nicht auf den Bildschirm
(und wer eines ergänzt, ergänzt die Zeile mit):

| Element | Vorbild (bekannt aus) | übernommen wird |
|---|---|---|
| Pipeline in einer Reihe, auto-generiert | GitHub Actions / CircleCI | Graph = Projektion des Ist-Zustands, antippen navigiert, nichts ziehbar |
| Linke Themen-Navigation + eine Zeile pro Wert + ein Erklärsatz | GitHub-Repo-Settings / Stripe Dashboard | Struktur, Zeilenanatomie (Label · Control · Satz · Badge) |
| „Geerbt vom Workspace" + Zurücksetzen | GitHub Org→Repo-Settings-Vererbung | Badge-Wortlaut, Reset-Link pro Zeile |
| Markierung „für dieses Projekt gesetzt" | VS-Code-Settings (blauer Balken = modified, Zahnrad → Reset) | Abweichung vom Default ist auf einen Blick sichtbar |
| Erweitert (n) eingeklappt | Vercel-Settings / NN/g Progressive Disclosure | max. 5 Zeilen sichtbar, Rest gezählt hinter einem Aufklapper |
| Suche über alles | VS-Code-Settings-Suche | ein Feld filtert Stationen + Regeln + Türen gleichzeitig |
| Schloss + Grund + Quelle | Chrome/Edge „Wird von deiner Organisation verwaltet" | Gesperrtes sieht gesperrt aus UND sagt von wem/warum — nie ein toter Schalter |
| Preset-Dial oben, Einzelzeilen darunter, „angepasst" bei Abweichung | Stripe/Vercel-Presets, Browser-Datenschutzstufen | §4.4, Dial setzt eine benannte Teilmenge |
| Brief-Ansicht: Prosa mit Wert-Chips | Mailchimp/HubSpot Merge-Tags in E-Mail-Templates | hervorgehoben = einstellbar, gedimmt = fix (§4.3) |
| Formular ↔ Brief als Toggle | VS Code „Open Settings (JSON)", GitHub Actions „View workflow file" | zwei Fenster auf denselben Zustand, kein zweiter Edit-Ort |
| Chat-Panel neben den Settings, Chat flippt sichtbare Schalter | Copilot in den Windows-11-Einstellungen | §5.5, der Rundlauf Zeile↔Chat |
| Angedockter Chat-Knopf unten rechts | Intercom-Launcher | Auffindbarkeit ohne Nav-Eintrag |
| Kontext-Chip über dem Composer | VS-Code-Copilot-Chat „Attach Context" | „Henry fragen" reicht die Zeile mit, statt sie beschreiben zu lassen |

### 7.1 Die Zeilen selbst

- **Ein Satz pro Zeile, Pflicht.** `descKey` ist bereits vertraglich
  zweisprachig geprüft (`test_harness_layer.py`); die Regeln erben denselben
  Vertrag. Eine Zeile ohne Erklärsatz besteht den Gate nicht.
- **Keine Interna in Labels.** „Karte, Arbeit, Abnahme" — nicht Lane, nicht
  Worktree. Henrys eigener Brief verbietet ihm diese Wörter im Chat (`:73`);
  der Bildschirm hält sich an dieselbe Regel.
- **Schloss heißt Grund.** Jede fixe Zeile zeigt `why` + `file:line`. Ohne den
  Grund liest ein Schloss als „willkürlich gesperrt" statt „bewusst fest" —
  die Begründung steht so schon in `sessions.py:134`.
- **Vorher/Nachher bei Henry-Regeln.** Der Brief enthält bereits Do/Don't-Paare
  (`:25-42`). Die Ton-Zeilen zeigen sie als Vorschau — der Nutzer sieht, was
  ein Wert bewirkt, statt es zu raten.
- **Herkunft statt Rätsel.** `Geerbt` / `Für dieses Projekt gesetzt` /
  `vom Dial gesetzt`, jeweils mit Zurücksetzen.
- **Suche** über denselben Index wie Karte 5 (`settings-search`), erweitert um
  Stationen und Regeln.

---

## 8. Phasen (je eine dispatchbare Karte, in dieser Reihenfolge)

| # | Karte | Inhalt | Abnahme |
|---|---|---|---|
| 1 | `project-config-store` | `project_config`-Tabelle, Auflösungskette, Scope `project`, getrackter Writer über den `swap()`-Pfad, `_version`-Bump | Zwei Projekte halten verschiedene Werte; ein gelöschter Wert erbt wieder statt auf null zu fallen; jede Änderung steht im Audit |
| 2 | `behavior-rules-model` | `BEHAVIOR_RULES` als Daten neben `harness.py`; `VOICE_STYLE`/`WEAR_BRIEF`/`GLASS_BRIEF` wandern aus dem Code nach `ops/harness/agents/`; Slots + `per_surface`; beide Vertragstests; `write_agent` schützt fixe Slots; die `configure`-Allowlist rendert als `fixed`-Slot aus dem Schema (§5.5) | **Bei Defaults sind alle sieben gerenderten Briefe byteweise identisch zum heutigen Stand**; eine Regel ohne Slot bricht den Gate; ein Editor-Versuch, einen `fixed`-Slot zu überschreiben, wird abgewiesen |
| 3 | `harness-screen` | `/loopmap` wird die Harness-Seite: Stationsfilter über dasselbe Schema, linke Navigation, `SchemaDoor` wiederverwendet; die Stations-Knöpfe ziehen per Metadatum aus ihren alten Türen um (lane_labels-Präzedenzfall); **Henry angedockt** (§5.5: Panel/Bottom-Sheet um die geteilten Transcript+Composer, „Henry fragen"-Kontext-Chip) und **„Brief ansehen"** (§4.3, rendert das Phase-2-Artefakt) | Kein Knopf verliert seine Editierbarkeit; kein Knopf ist an zwei Orten editierbar — die alte Tür-Zeile verschwindet im selben Commit; **der Rundlauf beide Richtungen: eine per Chat gesetzte Änderung erscheint live in der Zeile, eine per Zeile gesetzte steht in Henrys Verlauf/Audit — beides derselbe `swap()`-Eintrag**; jedes Element hat seine §7.0-Herkunftszeile; Screenshots Phone + Desktop gejudged |
| 4 | `pipeline-henry-track` | Knopf-Badges, Henry-Spur, Build-Loop als zweite Reihe — in `repo_pipeline.tsx`, ohne Stationsliste im Client | Eine im Daemon ergänzte Regel erscheint in der Spur **ohne Client-Änderung** (das ist der Dummy-Knob-Test aus Phase 4 der Vor-PRD, auf Regeln übertragen) |
| 5 | `autonomy-dial` *(bestehende offene Karte)* | Dial als Preset über die Regel-Teilmenge, Einzel-Übersteuerung sichtbar | Dial-Stufe ↔ Einzelregeln in beide Richtungen konsistent |

1 → 2 sind unabhängig von 3 → 4; 5 braucht 2.

## 9. Risiken (die ehrlichen 5 %)

- **Verhaltensdrift beim Umbau.** Die Briefe sind über Monate gewachsen, jede
  Zeile hat ein Datum und einen Anlass. Die Byte-Identitäts-Abnahme in Phase 2
  ist deshalb nicht Kür, sondern die einzige Absicherung, dass „strukturiert"
  nicht „still verändert" heißt — und sie muss über **alle sieben Quellen**
  laufen, nicht nur über `board-copilot.md`.
- **Die vier Längengesetze sind vielleicht kein Versehen.** Es kann sein, dass
  Chat, Sprache, Uhr und Push absichtlich verschieden knapp sind. Deshalb wird
  in Phase 2 **nichts vereinheitlicht**: `per_surface` konserviert alle vier
  Werte exakt und macht sie nur sichtbar. Ob sie zusammengelegt gehören, ist
  eine Owner-Entscheidung, die er erst treffen kann, wenn er sie nebeneinander
  sieht — genau das ist der Zweck dieser Karte.
- **Zu viel parametrisieren.** Die Versuchung ist, aus 321 Zeilen 60 Knöpfe zu
  machen. §4.2 nennt 18 und benennt den Rest ausdrücklich als Prosa. Wer die
  Liste erweitert, muss den `why`-Satz mitliefern — sonst entsteht genau der
  Bildschirm, über den sich der Owner 2026-08-26 beschwert hat.
- **Prompt-Cache pro Projekt.** Der Brief wird heute per mtime gecached; er
  muss künftig auf `(Projekt, config-version)` cachen, sonst rendert er pro
  Turn neu oder — schlimmer — liefert den Brief des falschen Projekts.
- **Scope-Wahl pro Regel ist eine Vermutung.** Ton = Workspace, Initiative =
  Projekt ist begründet (ein Henry, aber ein Doku-Repo arbeitet anders als ein
  Code-Repo), aber erst im Gebrauch bewiesen. Falsch geraten kostet eine
  Scope-Änderung im Schema, keine Migration — das ist der Grund, es als
  Metadatum zu führen und nicht als zwei Tabellen.
- **Projekt-Scope könnte v1-Overkill sein.** Heute hat der Workspace faktisch
  ein aktives Repo (`pm.repos` = eins). Wenn Phase 1 zu schwer wird: die
  Auflösungskette und die Vererbungs-UI zuerst mit **leerem** Projekt-Layer
  ausliefern (Badge zeigt dann immer „Geerbt") und die `project_config`-Schreib-
  seite nachziehen. Die Kette ist von Tag eins die richtige Form; nur der
  vierte Layer darf später kommen. Nicht erlaubt ist der umgekehrte Schnitt —
  Projekt-Werte ohne sichtbare Vererbung —, denn der reproduziert exakt die
  Unsichtbarkeit, gegen die diese Karte gebaut wird.
- **Stiller Ausfall des Settings-Layers.** Die gemessene Falle aus
  `ops/harness/README.md` gilt weiter: eine Settings-Datei, die die CLI nicht
  mag, wird **schweigend** verworfen. Wenn Phase 2 den Brief generiert,
  gehört `probe_harness_settings.py --validate` in den Ablauf.
