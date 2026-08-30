# Repo-Onboarding mit Harness-Templates — PRD

**STATUS: ENTWURF ZUR ABNAHME. Kein Code in diesem Kartenlauf.** Dieses Dokument
beschreibt, *was* gebaut werden soll und *auf welche echten Keys* es abgebildet
wird. Es soll entschieden werden, bevor gebaut wird — die offenen
Entscheidungen stehen in §8 und §14; die **bereits entschiedenen** in §0.

**Stand:** 2026-08-30. Alle Datei:Zeile-Angaben sind in diesem Worktree gegen
`96fa973` gelesen. Wo eine Anforderung heute **nicht** abbildbar ist, steht das
als solches markiert — nicht als Key erfunden.

Pflichtkontext: Schwesterdokument `ops/docs/backlog/settings-ia-redesign/README.md`
(6-Türen-Hub, Zellen-Katalog, Autonomie-Dial). Dieses PRD ist **kein Ersatz**
dafür, sondern die Repo-Ebene darunter — siehe §7.

---

# Klartext

Wer nur wissen will, was gebaut wird, liest diese Seite und hört danach auf.

Heute muss der Owner ein Repo einrichten, indem er verstreute Einzelschalter
findet: einen Deploy-Hook-Befehl, ein WIP-Limit, eine PM-Allowlist, eine
Gate-Datei im Repo-Root. Nichts davon erklärt sich, und nichts davon hängt
sichtbar zusammen.

Künftig wählt er beim Anlegen/Importieren eines Repos **ein Template** —
„Software-Entwicklung" oder „Dokumente & Prozesse". Das Template setzt in
einem Zug alle zugehörigen Keys und schaltet die **Stationen der U-Bahn-Linie**
an oder aus: `Karte → Arbeit → Gate → Abnahme → Deploy`. Ein Dokumenten-Repo
hat schlicht keine Deploy-Station.

Diese Linie ist eine **feste Ansicht**, kein Graph-Editor: fünf Stationen in
fester Reihenfolge, angetippt zeigen sie, was dort passiert und welcher Key sie
steuert. Genau so rendert `/loopmap` heute schon die Lanes — wir erweitern das
Vorhandene, wir bauen kein zweites Bild.

Und der Owner kann diese Stationen **im Henry-Chat umschalten** („Henry, dieses
Repo braucht kein Deploy"). Henry hat den dafür nötigen Verb (`configure`)
bereits. Was er **nicht** darf: Gate, Auth und Charter eigenmächtig abschalten.
Dafür stellt er eine antippbare Rückfrage, und der Owner entscheidet.

**Die drei unbequemen Befunde**, die den Zuschnitt bestimmen (Details §2):
1. Es gibt heute **keine Repo-Registry**. Ein Repo ist ein abs. Pfad-String auf
   einer Karte. Ein Template braucht ein Objekt, an dem es hängen kann.
2. **Cells sind global**, nicht pro Repo. „Das Template seedet Cells" ist heute
   nicht ausdrückbar und ist eine echte Architekturänderung.
3. Es gibt **keinen Gate-An/Aus-Key**. Das Gate läuft, wenn eine Datei
   `helmdeck.gate` existiert. „Gate abschalten" hat heute kein Ziel —
   der Key wird eingeführt (Entscheidung **E3**, §0).

## Nachtrag UX (Owner-Rückfrage 2026-08-30)

§10–§14 beantworten die UX-Frage und sind eigenständig lesbar. Kurzfassung:

- **§10 Identität — geprüft, wie verlangt.** „project unique = folder unique =
  git unique" stimmt heute **in keinem der drei Teile**, und in einem Teil darf
  es nicht stimmen (Monorepo). Gemessen, nicht hergeleitet. Gute Nachricht: die
  kanonische Git-Identität ist bereits gebaut (`_repo_hash`) und muss nur vom
  Verzeichnisnamen zum Schlüssel befördert werden. Nebenbefund: die
  **Projekt-ID-Kollision ist ein Datenverlust-Bug** und gehört in eine
  eigene Karte.
- **§11 Onboarding — der Instinkt „Vorschlag aus dem Ordner" ist belegt.**
  Kein untersuchtes System (Vercel, Netlify, Nx, GitLab) lässt blind auswählen,
  wenn Erkennung möglich ist. Fünf Schritte, inklusive Erkennungstabelle.
- **§12 Kanban — fünf Stationen, vier Spalten.** Gate und Deploy sind
  **Übergänge**, keine Spalten. Das Modell dafür (Spalte = Projektion mehrerer
  Status) hat HelmDeck bereits, nur unbenannt. **§12.5** spezifiziert den
  beschlossenen Board-Umbau (E2), mit dem Templates Spalten definieren dürfen.
- **§13 Begriffslexikon** — verbindliche Standardbegriffe EN/DE.
- **§14 F8–F12** — die zusätzlichen Entscheidungen, die daraus folgen.

---

# 0. Getroffene Owner-Entscheidungen (2026-08-30)

Drei Fragen sind **entschieden** und im Dokument eingearbeitet. Sie sind nicht
mehr offen; wo sie vorher als Frage standen, steht jetzt das Ergebnis.

| # | Frage | Entscheidung | Wirkung im Dokument |
|---|---|---|---|
| **E1** | F8 — Repo-Identität | **Drei-Ebenen-Modell** (Repository → Project → Billing-Project), `_repo_hash` wird Schlüssel | §10.5 verbindlich, §5.1 Schlüsselform, §11.2 Schritt 2 |
| **E2** | F10 — Board | **Umbau aufgenommen:** Spalten kommen aus `/loop/map`, Template darf Spalten definieren | §12.4, neu §12.5, §4.3 |
| **E3** | F2 — Gate aus | **Echter An/Aus-Key**, den Henry kippen kann | §2.3, §4.1, §4.2, §5.3, §6.2, neu §8/F2-Ergebnis |

**Was diese drei zusammen bedeuten:** der Zuschnitt wächst gegenüber dem
Entwurf. E1 zieht eine Migration nach sich, E2 bricht eine hartkodierte Liste
im Client auf, E3 führt einen Key ein, der ein Gesetz zu Policy macht. Alle
drei sind unten mit ihren Kosten und ihren Schutzplanken beschrieben — keine
Entscheidung wird als kostenlos dargestellt.

**Ein Punkt aus E3, der ausdrücklich mitentschieden ist:** ein abschaltbares
Gate erzeugt einen Zustand, in dem vor der Abnahme **nichts** geprüft wird.
Das ist zulässig, aber es darf nie *still* eintreten — §4.2 und §9 legen fest,
dass dieser Zustand an der Station, auf dem Board und im Audit sichtbar ist.

---

# 1. Problem

Owner-Beschwerde: *„HelmDeck-Settings sind zu komplex, nicht idiotensicher."*

Die Inventur in `settings-ia-redesign` hat das für die **Workspace**-Ebene
belegt (drei vermischte Config-Stores, Duplikate, ~20 Keys ganz ohne UI,
650-Zeilen-Monolith). Dieses Dokument ergänzt den Befund um die **Repo**-Ebene,
die dort noch nicht adressiert ist:

**1.1 Ein Repo einzurichten ist unangeleitete Handarbeit an vier Orten.**
Damit ein Repo vollständig arbeitet, müssen heute gesetzt werden:

| Was | Wo | Hat es eine UI? |
|---|---|---|
| Deploy-/Preview-Befehl | `settings.repo_hooks.<abs pfad>.{deploy,preview}` | **nein** (`settings-ia-redesign` §3) |
| Gate-Kommando | Datei `<repo>/helmdeck.gate` | **nein** (Datei im Repo) |
| PM darf hier handeln | `settings.pm.repos[]` | nur `POST /pm/config` |
| Standard-Repo | `settings.default_repo` | ja (`settings.tsx:299`) |

Keiner dieser vier Orte nennt die anderen drei. Es gibt keine Ansicht „so ist
dieses Repo eingerichtet".

**1.2 Es gibt keinen Zeitpunkt „Repo wird angelegt".**
Ein Repo entsteht implizit, wenn die erste Karte einen Pfad nennt
(`routes_tracks.py:200`, validiert mit `is_git_repo` bei `:214`). Es gibt
keinen Moment, an dem gefragt werden könnte „was für ein Repo ist das?".

**1.3 Die Einstellungen sind in Maschinen-Sprache, nicht in Absichts-Sprache.**
`policy.auto_dispatch_priority = "high"` beantwortet nicht die Frage, die der
Owner tatsächlich hat: *„soll hier jemand reviewen, bevor es live geht?"*.

**1.4 Der Zusammenhang ist unsichtbar.**
`policy.auto_accept_green`, das Vorhandensein von `helmdeck.gate` und
`repo_hooks.<repo>.deploy` bilden gemeinsam die Frage „wie streng ist dieses
Repo?" — stehen aber in drei verschiedenen Stores.

---

# 2. Befund: was heute wirklich existiert

Verifiziert, weil das PRD sonst auf erfundene Keys mappt.

## 2.1 Es gibt keine Repo-Registry — der Repo-Begriff ist abgeleitet

Es existiert **kein** `repos`-Table, **kein** `add_repo`/`register_repo`,
**kein** Modul, dem „ein Repo" gehört. Ein Repo ist ein absoluter Pfad-String,
gespeichert pro Karte als `t["repo"]` (`cells/engineer/dispatch.py:50,62`).

Die einzige Stelle, die überhaupt eine Repo-*Liste* bildet, ist die
GxP-Aktivierung — und sie **leitet sie zur Laufzeit ab**
(`spine/http/routes/routes_gxp.py:32-39`):

```python
known  = set((s.get("pm") or {}).get("repos") or [])
known |= set((s.get("repo_hooks") or {}).keys())
if default_repo: known.add(default_repo)
```

> **Konsequenz für dieses PRD:** Ein Template muss an *etwas* hängen. Das
> erfordert einen neuen, ersten echten Repo-Datensatz. Das ist die zentrale
> strukturelle Vorbedingung, nicht ein Implementierungsdetail. Vorschlag §5.1.

## 2.2 Cells sind global — „Template seedet Cells" ist heute nicht ausdrückbar

`spine/registry/cells.py:266`:

```python
def enabled(cell):
    """Is this cell on? Derived live from the policy plane, default true."""
    return bool(_policies().get(cell.enabled_key, True))
```

Ein globaler Boolean pro Cell (`engineerEnabled`, `pmEnabled`, …) in
`daemon/policy_live.json`. Der `Cell`-Deskriptor (`cells.py:71-92`) hat **kein**
Repo-Feld. Der Lifecycle startet einmal pro Daemon (`:296`), nicht pro Repo.

Die einzigen existierenden Pro-Repo-Mechanismen sind `pm.repos` (PM-Allowlist),
`repo_hooks` (Deploy-Befehle) und der GxP-`repos`-Scope. **Keiner** berührt
Cell-Enablement.

> **Konsequenz:** Die Owner-Anforderung „das Template legt fest, welche Cells
> geseedet werden" ist eine echte Architekturänderung (Cell-Enablement bekommt
> eine Repo-Dimension). Sie ist bewusst als **offene Frage F1** ausgewiesen und
> nicht stillschweigend in Phase 1 eingeplant.

## 2.3 Es gibt keinen Gate-An/Aus-Key

Das Gate läuft genau dann, wenn eine Datei existiert
(`cells/engineer/lanemachine.py:193-196`):

```python
gate_file = os.path.join(t.get("repo") or wt, "helmdeck.gate")
if not os.path.exists(gate_file):
    gate_file = os.path.join(wt, "helmdeck.gate")
```

Es gibt **keine** Einstellung, die das Gate deaktiviert.
`policies.gateBeforeReview` steht zwar in `daemon/policy_seed.json:5`, wird aber
**von keiner Codestelle gelesen** — es ist deklarativ (offene Schuld
`full-dynamism-decree`, `spine/registry/debt.py`).

> **Konsequenz:** „Henry, schalt das Gate für dieses Repo ab" hat heute kein
> Ziel. Entweder man löscht eine Datei im Repo (unsichtbar, nicht
> auditierbar) oder man führt den Key erst ein.
>
> **Entschieden (E3):** der Key wird eingeführt —
> `repo_profiles.<project>.stations.gate ∈ {"on","off"}`, gelesen von `_gate()`.
> Die Datei-Erkennung bleibt als *zweite* Bedingung bestehen: das Gate läuft,
> wenn der Key `"on"` ist **und** eine Gate-Datei existiert. Damit schaltet der
> Key ab, aber er schaltet nichts ein, was es nicht gibt — und ein Repo ohne
> Gate-Datei verhält sich weiter wie heute.

## 2.4 Deploy ist bereits optional — und bereits pro Repo

Das einzige Stück, das die Owner-Vision heute schon vollständig kann.
`_repo_hook` (`lanemachine.py:648-651`):

```python
hooks = (st.get("repo_hooks") or {}).get(t.get("repo") or "", {})
cmd = (hooks or {}).get(kind, "").strip()
if not cmd:
    return None
```

Kein Hook konfiguriert → Deploy wird übersprungen, ohne Fehler. **„Dokumenten-
Repo ohne Deploy-Station" ist ohne jeden neuen Mechanismus abbildbar.** Der
Deploy-Aufruf selbst sitzt bei `lanemachine.py:1119`, nach dem Merge,
daemon-seitig im Haupt-Repo („with the secrets agents never see").

## 2.5 Henry kann bereits Settings schreiben — der Verb existiert

`cells/copilot/copilot_actions.py:102-130`, Action `configure`:
Rollen-Gate `policy.chat_configure_roles` (Default `["owner"]`), Allowlist
`ALLOWED_CONFIG` (`:67`), Schreibweg `events.save_settings` mit Checkpoint und
maskiertem Before/After-Audit-Event (`spine/storage/events.py:180-217`).

```python
ALLOWED_CONFIG = {"policy", "capacity", "value_per_card", "default_repo",
                  "registration", "dashboard", "prices", "currency",
                  "appearance", "jira"}
```

Die Allowlist ist **top-level** — d.h. *jeder* `policy.*`-Subkey ist heute schon
per Chat erreichbar. Nicht erreichbar: `repo_hooks`, `pm`, `drivers`,
`worktree_seed`.

> **Konsequenz:** Das Chat-Mapping in §6 ist überwiegend **Wiederverwendung**,
> kein Neubau. Der Scope ist damit deutlich kleiner, als die Anforderung klingt.

## 2.6 Die Policy-Plane ist bewusst *nicht* chat-erreichbar

`policy.swap()` (`spine/auth/policy.py:85`) ist der einzige Schreibweg für die
Gesetzes-Ebene, exponiert nur als `POST /policy/swap`, **owner-only**
(`routes_policy.py:21-22`), zusätzlich gesperrt durch `agentMaySwap: false`.
Unter `cells/copilot/` existiert **kein einziger** Aufruf von `policy.swap`.

## 2.7 Die U-Bahn-Ansicht existiert bereits — als feste Linie

`GET /loop/map` (`routes_info.py:42`) liefert `runtime.lanes` +
`runtime.gate` + `runtime.edges` aus `cells/engineer/sessions.py:140-195`.
Jeder Knoten trägt bereits `kind: "fixed" | "policy"`, die zugehörigen
`settings`-Keys und eine `source`-Angabe, die **zur Laufzeit aus der Quelldatei
gelesen** wird (`loop_state.py:693`).

Die UI (`surfaces/app/src/app/loopmap.tsx:279-308`) rendert das bereits als
**feste horizontale Linie** mit Kreisen und Verbindungsstrichen, plus
`FlowToken` (wandernder Punkt) und `GatePulse`. Das Gate sitzt als eigener
Knoten *zwischen* zwei Lanes (`:298-301`).

> **Konsequenz:** Die Owner-Anforderung „feste U-Bahn-Linie, kein verschiebbarer
> Graph-Editor" beschreibt das **bereits existierende** Muster. Zu bauen ist
> die Repo-Dimension und die fehlende Deploy-Station — nicht die Ansicht.

## 2.8 Was in der Ansicht heute fehlt

`Deploy` ist **kein Knoten**. Es existiert nur als Hook-Aufruf
(`lanemachine.py:1119`) und als Prosa im `instruction`-Text der `done`-Lane
(`sessions.py:162`: „Merge + Deploy…"). Ebenfalls keine Knoten: Cells, Preview-
Hook, Prozesse, Eskalationen.

---

# 3. Zielbild

**Ein Repo bekommt beim Anlegen eine Rolle, und diese Rolle ist eine sichtbare
Linie mit fünf Stationen, die man antippen und im Chat umschalten kann.**

Drei Prinzipien:

**3.1 Absichts-Sprache vorne, Keys hinten.**
Der Owner wählt „Software-Entwicklung". Das Template ist die Übersetzung in
`policy.*`-Keys. Die Keys bleiben sichtbar (antippbar an der Station) — sie
werden nicht versteckt, nur nicht mehr *zuerst* verlangt.

**3.2 Das Template ist ein Preset, kein neuer Store.**
Es schreibt ausschließlich in bestehende Keys über den bestehenden
Schreibweg `events.save_settings`. Es entsteht **kein** vierter Config-Store —
das war der Hauptbefund von `settings-ia-redesign` und wird hier nicht
wiederholt. Dasselbe Muster wie der dort geplante Autonomie-Dial: *ein*
Bedienelement, das mehrere Keys setzt.

**3.3 Die Linie ist die Erklärung.**
Es gibt keine zweite Dokumentationsebene. Was das Repo tut, *ist* die Linie;
was eine Station tut, steht an der Station, samt Key und Quelldatei-Zeile.

**Nicht-Ziele:**
- Kein frei verschiebbarer Graph-Editor. Kein Drag & Drop, keine Kanten-Malerei.
- Keine Multi-Repo-Karten, kein Repo-übergreifendes Deployment.
- Keine Änderung an Gate-, Merge- oder Deploy-*Mechanik* — nur an ihrer
  Konfiguration und Sichtbarkeit. (Seit E3 liest `_gate()` zusätzlich **einen**
  Schalter, bevor es prüft; der Prüfvorgang selbst bleibt unangetastet.)
- **Keine neuen Workflow-Status.** E2 macht die Board-*Spalten* frei, nicht die
  Zustandsmaschine — die sieben Status und ihre Übergänge bleiben (§12.5).
- Kein Ersatz für `settings-ia-redesign`; dieses PRD ist die Repo-Ebene darunter.

---

# 4. Das Stationsmodell (U-Bahn-Linie)

Fünf Stationen in fester Reihenfolge. Die Linie ist pro Repo, nicht global.

```
 ●───────●───────◆───────●╌╌╌╌╌╌╌○
Karte  Arbeit   Gate  Abnahme  Deploy
                                (aus)
```

## 4.1 Stationen und ihre echte Entsprechung

| # | Station | Entspricht im Code | Steuernde Keys | Heute abschaltbar? |
|---|---|---|---|---|
| 1 | **Karte** | Lane `backlog` (`sessions.py:142-147`) | `policy.auto_dispatch_priority`, `capacity.wip_limit` | nein — strukturell |
| 2 | **Arbeit** | Lane `working` (`:148-153`), Worktree-Erzeugung `dispatch.py:130` | `policy.machine.*`; Worktree vs. `direct_task` (`dispatch.py:334`) | nein — nur *Bauart* wählbar |
| 3 | **Gate** | Knoten `gate` (`:187-194`), Ausführung `lanemachine.py:162-262` | **neu** `repo_profiles.{project}.stations.gate`; Datei `<repo>/helmdeck.gate`; `gate_idle_s`, `gate_hard_s` | **ja — neuer Key (E3)** |
| 4 | **Abnahme** | Kante `review → done`, Verb `accept` (`:181-185`) | `policy.auto_accept_green`, `policies.sod_accept` | nein — nur *automatisierbar* |
| 5 | **Deploy** | `_repo_hook(t,"deploy")` (`lanemachine.py:1119`) | `repo_hooks.<repo>.deploy` | **ja, heute schon** (§2.4) |

## 4.2 Ehrliche Semantik von „Station aus"

Die Owner-Formulierung „das Template schaltet Stationen an/aus" trifft nur auf
Station 5 wörtlich zu. Damit die UI nicht lügt, gibt es **drei** Zustände statt
zwei:

- **Fest** (Karte, Arbeit) — die Station existiert immer. Kein Schalter, nur
  Konfiguration ihrer Bauart.
- **Automatisch** (Abnahme) — die Station bleibt in der Linie, wird aber ohne
  Halt durchfahren. `auto_accept_green: true` heißt *„niemand hält hier an"*,
  nicht *„es gibt keine Abnahme"*. Visuell: gestrichelte Kante, Station hohl.
- **Aus** (Deploy, **und Gate seit E3**) — die Station wird ausgegraut mit
  Begründung („kein Deploy-Hook für dieses Repo hinterlegt").

**Sonderregel für „Gate aus" (Folge von E3).** Ein abgeschaltetes Gate ist der
einzige Aus-Zustand, der eine *Schutzfunktion* entfernt statt eines optionalen
Schritts. Er unterliegt deshalb drei Pflichten, die kein anderer Zustand hat:

1. **Nie stumm.** Die Station wird nicht nur ausgegraut, sondern mit Warnstil
   und Klartext gerendert: „Gate aus — Karten gehen ungeprüft in die Abnahme",
   plus Akteur und Zeitpunkt der Abschaltung. Dieselbe Zeile erscheint als
   Badge über der betroffenen Board-Spalte, nicht nur in der Linie.
2. **Immer rücknehmbar.** `repo_profiles` gehört in `SIGNIFICANT_SETTINGS`
   (§5.1), damit das Abschalten einen Checkpoint erzeugt. „Gate wieder scharf"
   ist Stufe A (§6.2 #4) — Verschärfen darf nie schwerer sein als Abschalten.
3. **Nicht global.** Der Key wirkt ausschließlich auf ein Project (Ebene 2 aus
   §10.5). Es gibt keinen Weg, das Gate für *alle* Repos abzuschalten — ein
   Massen-Aus wäre genau die Wirkung, die die Policy-Plane owner-only hält
   (§2.6).

Diese Unterscheidung ist die Übersetzung des bestehenden
`kind: "fixed" | "policy"`-Tags (`sessions.py:140-195`) in Owner-Sprache — und
sie ist der Grund, warum die Ansicht die Gesetze nicht als „kaputt" darstellt.
Die bestehende UI-Regel bleibt gültig (`loopmap.tsx:62-72`): fixe Knoten werden
neutral gerendert, nicht als rotes Schloss. *„It is structure, not a problem."*

## 4.3 Was gebaut werden muss

1. **Deploy als echter Knoten.** `sessions.LANE_FLOW` um einen Knoten `deploy`
   erweitern, analog zum `gate`-Knoten mit `after: ["done"]`,
   `kind: "policy"`, `settings: ["repo_hooks.<repo>.deploy"]`.
   Damit rendert `loopmap.tsx` ihn ohne Sonderfall mit.
2. **Repo-Parameter für `/loop/map`.** Heute liefert der Endpunkt eine globale
   Sicht. Er braucht `?repo=<pfad>`, damit `enabled`/`reason` pro Station aus
   dem Repo-Profil aufgelöst werden.
3. **Station-Zustand im Knoten.** Pro Knoten zusätzlich
   `state: "fixed" | "auto" | "off"` und `off_reason`.
4. **Der Vertrag ist getestet.** `ops/tests/test_harness_layer.py:240,351`
   prüft `/loop/map` gegen die TS-Interfaces in `client.ts:308-354` in **beide**
   Richtungen. Jede Feld-Erweiterung muss dort mitgezogen werden, sonst
   bricht der Gate.
5. **Gate-An/Aus-Key (E3).** `repo_profiles.{project}.stations.gate` in
   `DEFAULTS` (`events.py:97`), gelesen an **genau einer** Stelle — in `_gate()`
   vor der Datei-Erkennung (`lanemachine.py:193-196`). Kein zweiter Leser,
   keine Kopie in der UI: der Stationszustand kommt aus `/loop/map`, nicht aus
   einer eigenen Abfrage. (Ein Flag, das an zwei Stellen ausgewertet wird, ist
   genau das Muster, das `CLAUDE.md` unter „NO MONKEY PATCHES" verbietet.)
6. **Spalten kommen aus dem Server (E2).** `/loop/map` liefert zusätzlich die
   **Spaltenliste** des Projects; `board.tsx:27` verliert seine hartkodierte
   Kopie. Details und Grenzen in §12.5 — das ist der größte Einzelposten der
   drei Entscheidungen.

---

# 5. Template-Katalog

## 5.1 Wo ein Template gespeichert wird

Neuer Top-Level-Key in `settings.json` — der erste echte Pro-Repo-Datensatz.
**Der Schlüssel ist seit E1 kein Pfad mehr**, sondern die Project-Identität aus
§10.5: `"<repo_id>:<root_dir>"`, wobei `repo_id` der `_repo_hash` ist und
`root_dir` bei einem Ein-Projekt-Repo schlicht `.` lautet.

```jsonc
"repo_profiles": {
  "1mmjd8p4:.": {
    "repo_path": "C:\\Users\\...\\helmdeck",   // nur Anzeige, nicht Schlüssel
    "template": "software-dev",
    "template_version": 1,
    "applied": "2026-08-30T12:00:00Z",
    "applied_by": "owner",
    "stations": { "gate": "on", "abnahme": "manual", "deploy": "on" },
    "columns": null,       // null = Standard aus dem Template (E2, §12.5)
    "drift": []            // Keys, die seit dem Seeden abweichen
  }
}
```

`repo_path` ist bewusst **abgeleitete Anzeige**, kein Identitätsträger: er wird
bei jedem Auflösen neu gesetzt, damit ein umgezogenes Repo seinen Datensatz
behält (F9) und ein falsch geschriebener Pfad nichts mehr kaputt macht — genau
die Brüche 2–4 aus §10.2.

Pflichten bei der Umsetzung, aus den Regeln des Hauses:

- Eintrag in `DEFAULTS` in `spine/storage/events.py:97` — **nicht** nur ein
  `or {}`-Fallback an der Lesestelle. `HARNESS.md:205-207` nennt das
  ausdrücklich als Anti-Muster, und §1c der Settings-Inventur zeigt drei tote
  Keys (`chat_admin_roles`, `nightshift.*`, `policy.dashboard`), die genau so
  entstanden sind.
- **Trap:** `save_settings` merged nur **eine** Ebene tief
  (`events.py:192-195`). Ein Patch `{"repo_profiles": {"<pfad>": {...}}}`
  ersetzt das *ganze* Repo-Objekt. Henry und die UI müssen Read-Modify-Write
  machen, sonst löscht ein Stations-Toggle das Template-Feld.
- Aufnahme in `ALLOWED_CONFIG` (`copilot_actions.py:67`), sonst ist §6 nicht
  ausführbar.
- Aufnahme in `SIGNIFICANT_SETTINGS` (`events.py:162`), damit ein
  Template-Wechsel einen Checkpoint erzeugt und rücknehmbar ist. Seit E3 ist
  das nicht mehr nur Komfort: das Abschalten eines Gates **muss** einen
  Rücknahmepunkt hinterlassen (§4.2, Pflicht 2).
- **Migration (Folge von E1).** Bestehende pfadbasierte Einträge
  (`repo_hooks`, `pm.repos`, `default_repo`, GxP-Scope) werden einmalig über
  `_repo_hash` aufgelöst und umgeschlüsselt. Der Schritt läuft mit
  Vorher/Nachher-Liste und ist rückrollbar; Pfade, die sich **nicht** auflösen
  lassen (Repo weg, kein Git), bleiben unverändert stehen und werden gemeldet
  statt still verworfen.

## 5.2 Template „Software-Entwicklung" (`software-dev`)

Für Repos, aus denen ein Artefakt gebaut und ausgeliefert wird.

| Was das Template vorlegt | Echter Key | Wert | Warum |
|---|---|---|---|
| Gate an | `repo_profiles.{project}.stations.gate` + Datei `<repo>/helmdeck.gate` | `"on"`, Datei anlegen falls fehlt | Gate-before-review ist hier Gesetz |
| Gate-Kommando | Inhalt derselben Datei | `py -3.12 "%HELMDECK_REPO%\ops\tools\run_gate.py"` | Der leichte Gate (Dekret `gate-light`) |
| Gate-Geduld | `gate_idle_s` | `300` | bestehender Default |
| Abnahme manuell | `policy.auto_accept_green` | `false` | Mensch sieht Code vor dem Merge |
| Kein Selbst-Dispatch | `policy.auto_dispatch_priority` | `""` | Owner entscheidet, was läuft |
| Deploy an | `repo_hooks.<repo>.deploy` | **Owner wird gefragt** (§8/F5) | daemon-seitig mit Secrets |
| Isolierte Arbeit | Karten-Default | Worktree (kein `direct_task`) | Worktree-Isolation |
| PM darf hier planen | `pm.repos[]` | Repo hinzufügen | sonst ignoriert die Resilienz-Leiter das Repo (`pm_resolve.py:101`) |
| Stationen | — | `Karte ● Arbeit ● Gate ◆ Abnahme ● Deploy ●` | alle fünf |

## 5.3 Template „Dokumente & Prozesse" (`docs-process`)

Für Repos mit Text, Verträgen, Spezifikationen, Checklisten. Kein Build,
kein Deploy, schnelle Runden.

| Was das Template vorlegt | Echter Key | Wert | Warum |
|---|---|---|---|
| **Kein Deploy** | `repo_hooks.<repo>` | **nicht angelegt** | `_repo_hook` liefert `None` → Station entfällt (§2.4) |
| Gate leicht, aber an | `stations.gate` + Datei `helmdeck.gate` | `"on"` + Doku-Gate (Frontmatter/Links) | ein Python-Compile-Gate ist hier sinnlos — ein *passender* Gate nicht |
| Abnahme automatisch bei Grün | `policy.auto_accept_green` | `true` | ein Textabsatz braucht kein Vier-Augen-Merge |
| Direkt im Baum arbeiten | Karten-Default | `direct_task` + `fast_track` | kein Branch/Merge-Overhead für eine Textdatei |
| Zügiger Selbst-Dispatch | `policy.auto_dispatch_priority` | `"high"` | kurze Aufgaben nicht anstauen |
| Stationen | — | `Karte ● Arbeit ● Gate ◇ Abnahme ⟿ Deploy ○` | Deploy aus, Abnahme automatisch |

> **Achtung, ehrlich benannt:** `direct_task` umgeht Worktree **und Gate**
> vollständig (`dispatch.py:348-352`, registrierte Schuld
> `direct-build-no-gate`). Für ein Dokumenten-Repo ist das vertretbar; das
> Template macht diese Schuld aber pro Repo *bewusst und sichtbar* — die
> Station „Gate" muss in diesem Fall als **aus mit Begründung** gerendert
> werden, nicht als grün.
>
> **Seit E3 ist das kein Sonderfall mehr, sondern derselbe Zustand:** ein Repo
> auf `direct_task` und ein Repo mit `stations.gate = "off"` landen beide im
> Zustand „ungeprüft vor Abnahme" und werden **identisch** dargestellt
> (§4.2, Sonderregel). Das Template liefert `gate: "on"` aus — wer es
> abschaltet, tut das bewusst und sichtbar, statt es sich über die Bauart der
> Karte einzuhandeln.

## 5.4 Was ein Template nicht darf

- Keine Keys außerhalb von `ALLOWED_CONFIG` + `repo_hooks` schreiben.
- **Keine** Policy-Plane-Werte anfassen (`gateBeforeReview`, `permissions`,
  `agentMaySwap`, Cell-Flags) — die haben einen eigenen, owner-only
  Schreibweg (§2.6).
- Keine bestehenden Werte still überschreiben: beim Anwenden auf ein Repo mit
  vorhandenen Einstellungen wird ein **Diff** gezeigt und bestätigt.

---

# 6. Chat-Command-Mapping

Der Owner will die Linie im Henry-Chat umschalten. Grundlage ist der
bestehende Action-Kanal: Henry antwortet mit Prosa plus genau einem
abschließenden ` ```actions `-Block (`board-copilot.md:88-95`), geparst von
`_ACTIONS_FENCE` (`copilot_actions.py:14`), ausgeführt in `_run_action` (`:97`).

## 6.1 Drei Berechtigungsstufen

| Stufe | Bedeutung | Mechanismus |
|---|---|---|
| **A — Henry schaltet direkt** | Policy-Hälfte. Reversibel, auditiert, kein Gesetz. | `configure`-Action, Rolle aus `policy.chat_configure_roles` |
| **B — Henry fragt, Owner tippt** | Gesetzesnahe oder privilegierte Wirkung. | `<helmdeck-ask>`-Block (`spine/ops/ask.py`, geparst `copilot.py:1024`) → bei „Ja" owner-signierter Schreibweg |
| **C — Henry lehnt ab und erklärt** | Charter-Kern, Auth, Driver, Audit. | Ablehnung mit Nennung des Keys (`board-copilot.md:185-191`) |

Stufe B ist bewusst gewählt, weil der Ask-Kanal **bereits existiert und im
Copilot-Pfad geparst wird** — auch wenn `board-copilot.md:7` heute
`ask_protocol: false` setzt. Für die Gesetzes-Rückfragen muss dieses Flag
gezielt aktiviert werden.

## 6.2 Die Mapping-Tabelle

`{repo}` = das aktuell besprochene Repo, aufgelöst aus dem Kontext oder
`settings.default_repo`. Alle Patches sind Read-Modify-Write (§5.1-Trap).

| # | Owner sagt (Beispiele) | Stufe | Action / Weg | Key & Wert |
|---|---|---|---|---|
| 1 | „Henry, dieses Repo braucht kein Deploy" · „Deploy aus" | **A** | `configure` | `repo_profiles.{repo}.stations.deploy = "off"`; `repo_hooks.{repo}.deploy` geleert |
| 2 | „Deploy wieder an" | **B** | `<helmdeck-ask>` + `configure` | Deploy-**Befehl** ist Stufe B (F5) — Henry fragt nach dem Kommando bzw. bietet das zuletzt bekannte an |
| 3 | „Schalt das Gate für dieses Repo ab" | **B** | Ask → owner-bestätigt | `repo_profiles.{project}.stations.gate = "off"` — Key existiert seit **E3**; bleibt Stufe B, weil er eine Prüfung entfernt |
| 4 | „Mach das Gate wieder scharf" | **A** | `configure` | `…stations.gate = "on"` — Verschärfen ist immer Stufe A |
| 5 | „Grüne Karten sollen hier automatisch durchgehen" | **A** | `configure` | `policy.auto_accept_green = true` |
| 6 | „Ich will jede Karte selbst abnehmen" | **A** | `configure` | `policy.auto_accept_green = false` |
| 7 | „Dieses Repo ist ein Dokumenten-Repo" · „Nimm die Doku-Vorlage" | **B** | Ask (Diff zeigen) → `configure` | ganzes Template `docs-process` (§5.3) |
| 8 | „Wie ist dieses Repo eingerichtet?" | **A** (lesend) | Prosa + Link auf `/loopmap?repo=…` | keiner |
| 9 | „Hier darf höchstens eine Karte gleichzeitig laufen" | **A** | `configure` | `capacity.wip_limit = 1` |
| 10 | „Dringende Karten sollen von selbst starten" | **A** | `configure` | `policy.auto_dispatch_priority = "high"` |
| 11 | „Der PM soll hier nicht planen" | **B** | Ask → `POST /pm/config` | `pm.repos` ohne `{repo}` — `pm` ist **nicht** in `ALLOWED_CONFIG` |
| 12 | „Nenn die Spalte ‚Freigabe' statt ‚Review'" | **A** | `configure` | `policy.lane_labels.review = "Freigabe"` |
| 12b | „Mach hier eine Spalte ‚Wartet auf Kunden' auf" | **B** | Ask (Vorschau zeigen) → `configure` | `repo_profiles.{project}.columns` — seit **E2** möglich; Stufe B, weil das Board für alle sichtbar umgebaut wird (§12.5) |
| 13 | „Schalt die PM-Cell ab" | **B** | Ask → `POST /policy/swap` | `pmEnabled = false`; Henry hat dafür heute **keinen** Weg (§2.6) |
| 14 | „Schalt Auth ab" · „Niemand muss sich mehr anmelden" | **C** | Ablehnung + Begründung | `authRequired` — Gesetz, `spine/auth/auth.py` |
| 15 | „Ändere den Charter-Kern" · „Erlaub Connectoren Shell-Zugriff" | **C** | Ablehnung + Begründung | `spine/auth/charter.py` — der eine Boden (§6.4) |
| 16 | „Lösch den Audit-Eintrag von gestern" | **C** | Ablehnung + Begründung | append-only, kein Löschpfad (`events.py:219+`) |

## 6.3 Beispiel einer Stufe-A-Antwort

> **Owner:** „Henry, dieses Repo braucht kein Deploy."
> **Henry:** „Erledigt — die Deploy-Station ist für helmdeck-docs aus. Karten
> landen nach der Abnahme direkt in Fertig."
> ```actions
> [{"type":"configure","patch":{"repo_profiles":{"7f3a2c91:.":
>   {"repo_path":"C:\\…\\helmdeck-docs",
>    "template":"docs-process","template_version":1,
>    "stations":{"gate":"on","abnahme":"auto","deploy":"off"}}}}}]
> ```
>
> Der Schlüssel ist die Project-Identität (E1), nicht der Pfad — deshalb
> funktioniert derselbe Satz auch, wenn der Owner den Ordner vorher umbenannt
> oder das Repo verschoben hat. Der Patch enthält das **vollständige**
> Profilobjekt, weil `save_settings` nur eine Ebene tief merged (§5.1-Trap).

## 6.4 Was FIXED bleibt — und die genaue Formulierung dafür

Die Owner-Vorgabe lautet „Charter/Gate/Auth bleiben FIXED
(full-dynamism-decree)". Das Dekret selbst sagt allerdings etwas Präziseres,
und das PRD muss diesem Wortlaut folgen, sonst widerspricht die Umsetzung der
Architektur (`ARCHITECTURE.md:28-52`):

> *„This section used to read ‚Fixed - the harness'. The owner decree
> superseded that: **nothing is structurally unreachable.** … The one invariant
> that replaced ‚fixed' is **trackability**: no module/state/rule change may
> happen without an append-only, actor-attributed record, and every swap must
> be reversible."*

Für dieses PRD wird „FIXED" daher operationalisiert als:

> **FIXED = nicht einseitig durch den Agenten schaltbar.**
> Gate, Auth, Audit, Driver und die Charter-Gesetze sind für Henry nicht per
> `configure` erreichbar. Sie sind nicht *unveränderlich*, aber jede Änderung
> braucht (a) eine menschliche Bestätigung, (b) einen append-only Eintrag mit
> Akteur und (c) einen Rücknahmeweg. Das ist exakt der bestehende
> `policy.swap()`-Pfad (`spine/auth/policy.py:85-114`), der den `before`-Wert
> als Rücknahme-Handle zurückgibt.

**Die eine echte Ausnahme, die auch der Owner nicht per Chat aufhebt:** die
Connector-Capability-Sandbox (`spine/auth/charter.py:11-13`) — *„Owners may ADD
house rules (further restrictions) … nobody can subtract from the core."*
Zusätzlich `capabilitySwapRequiresHuman: true`, das selbst `agentMaySwap` nicht
aushebelt (`policy.py:99-102`).

## 6.5 Zwei Löcher, die beim Bauen mitgeschlossen werden müssen

1. **Der Fallthrough.** `copilot_actions.py:415-429`: jeder *unbekannte*
   Action-Typ, der ein Textfeld trägt, wird still als `machine_task` auf dem PC
   ausgeführt. Sobald Templates neue Verben einführen, ist eine echte
   Allowlist mit lauter Ablehnung nötig — sonst wird ein Tippfehler wie
   `"type":"configur"` zu einem Maschinen-Task.
2. **`schedule_connector`** (`:339-347`) schreibt `events.save_settings`
   **ohne jedes Rollen-Gate** und umgeht `ALLOWED_CONFIG`. Das ist heute schon
   ein Loch; ein PRD, das Chat-Schaltbarkeit ausbaut, darf es nicht
   unerwähnt lassen.

---

# 7. Verhältnis zu `settings-ia-redesign`

Die beiden Karten überschneiden sich und dürfen sich nicht doppelt bauen.

| | `settings-ia-redesign` | **dieses PRD** |
|---|---|---|
| Ebene | Workspace (global) | Repo |
| Bedienmuster | 6 Türen, Zellen-Katalog, Autonomie-Dial | Template-Wahl, U-Bahn-Linie |
| Preset-Mechanik | Autonomie-Dial: ein Regler → viele Keys | Template: eine Wahl → viele Keys |
| Mechanik-Quelle | `_config_schema` mit `{door, cell, level, descKey, scope}` | **dieselbe**, erweitert um `scope: "repo"` |

**Bindende Festlegung:** Templates erzeugen **keinen** eigenen Renderer und
keine eigene Schema-Quelle. Ein Template ist eine benannte Menge von Werten
über demselben `_config_schema`. Die Repo-Linie wird die Detailansicht hinter
einer Repo-Karte in **Tür 2 (Agenten & Autonomie)** bzw. einer neuen Repo-Liste
— das entscheidet F7.

Empfohlene Reihenfolge: `settings-ia-redesign` Phase 1 (Schema-Metadaten +
generischer Renderer) **zuerst**, weil dieses PRD darauf aufsetzt. Sonst
entsteht der zweite Monolith, dessen Vermeidung der ausdrückliche Zweck der
Schwesterkarte ist.

---

# 8. Offene Fragen — zur Entscheidung durch den Owner

Ursprünglich sieben; **F2 ist seit 2026-08-30 entschieden** (§0/E3) und bleibt
hier mit dem Ergebnis stehen, damit die Begründung nachlesbar ist. Offen sind
noch F1, F3–F7. Reihenfolge = Wichtigkeit.

**F1 — Pro-Repo-Cells: Scope oder Vertagung?** *(blockiert Template-Umfang)*
Cells sind heute global (§2.2). „Das Template legt fest, welche Cells geseedet
werden" erfordert eine Repo-Dimension in `cells.enabled()`, im `Cell`-Deskriptor
und im Lifecycle-Start — plus die Frage, was mit einer laufenden Karte
passiert, wenn ihre Cell für dieses Repo aus ist.
*Empfehlung:* **vertagen.** Phase 1 seedet nur Repo-*Policy* (die Tabellen in
§5.2/§5.3 kommen ohne Cell-Flags aus). Pro-Repo-Cells als eigene Karte nach
`settings-ia-redesign` Tür 3.

**F2 — Was heißt „Gate aus" für ein Dokumenten-Repo?** — **ENTSCHIEDEN: (b),
echter An/Aus-Key.** *(war: blockiert Chat-Mapping #3)*
Es gab keinen Key (§2.3). Drei Wege standen zur Wahl:
(a) **Gate bleibt immer an, nur das Kommando wechselt** — ein Doku-Repo bekommt
einen Doku-Gate (Frontmatter/Links/tote Verweise). Gesetz bleibt unangetastet.
(b) **Neuer Key `repo_profiles.<repo>.stations.gate`**, den `_gate()` liest.
Ehrlich und auditierbar, macht aber ein Gesetz zu Policy — berührt die offene
Schuld `full-dynamism-decree`.
(c) **Datei löschen** — funktioniert heute, ist aber unsichtbar und nicht im
Audit.
*Meine Empfehlung war (a).* **Der Owner hat (b) gewählt.** Das ist die
mächtigere und die ehrlichere Variante — sie macht einen Zustand, den es über
`direct_task` faktisch längst gibt, benennbar und auditierbar, statt ihn hinter
der Bauart einer Karte zu verstecken.

**Was mit der Entscheidung mitgebaut werden muss** (der Preis von (b), damit er
nicht später überrascht):
- Der Key steht in `DEFAULTS`, wird an **einer** Stelle gelesen (§4.3 Punkt 5).
- „Aus" ist nie stumm, immer rücknehmbar, nie global — die drei Pflichten aus
  §4.2. Ohne sie ist (b) genau das, wovor (a) schützen sollte.
- Die offene Schuld `full-dynamism-decree` wird berührt: `gateBeforeReview`
  liegt deklarativ in der Policy-Plane und wird von niemandem gelesen. Der neue
  Key darf **nicht** stillschweigend zur zweiten Wahrheit daneben werden —
  entweder liest `_gate()` künftig beide (Policy-Plane als Obergrenze, Repo-Key
  als Verschärfung darunter), oder der tote Seed-Eintrag wird im selben Zug
  entfernt. Beides ist vertretbar; **nichts tun ist es nicht**, weil sonst zwei
  Schalter mit demselben Namen existieren, von denen einer wirkungslos ist.
- Das Verschärfen (`"off" → "on"`) bleibt Stufe A, das Abschalten Stufe B
  (§6.2 #3/#4).

**F3 — Bindet das Template, oder seedet es einmalig?** *(blockiert Datenmodell)*
(a) **Seed-once:** Template setzt Werte, danach ist jede Abweichung erlaubt und
wird als „weicht vom Template ab" markiert.
(b) **Gebunden:** Template ist die lebende Quelle, Einzeländerungen brauchen ein
explizites „Ausklinken".
*Empfehlung:* **(a) mit Drift-Anzeige.** (b) macht jede Chat-Änderung aus §6 zu
einem Konflikt mit dem Template.

**F4 — Wo entsteht der Onboarding-Moment?** *(blockiert UX-Einstieg)*
Heute gibt es keinen (§1.2, §2.1). Optionen: beim ersten Kartenanlegen in einem
unbekannten Repo nachfragen · eine explizite „Repo hinzufügen"-Aktion in den
Settings · Henry fragt beim ersten `direct_task` in einem unbekannten Repo.
*Empfehlung:* **alle drei denselben Dialog aufrufen lassen**, Einstieg über den
Kartenanlege-Pfad als Erstes, weil er real durchlaufen wird.

**F5 — Darf Henry Deploy-*Befehle* schreiben?** *(Sicherheitsentscheidung)*
`repo_hooks.<repo>.deploy` wird **daemon-seitig im Haupt-Repo mit den Secrets
ausgeführt** (`lanemachine.py:1119`, `:617`). Nimmt man `repo_hooks` in
`ALLOWED_CONFIG` auf, ist Chat ein Weg zu beliebiger privilegierter
Shell-Ausführung.
*Empfehlung:* **nein.** Henry darf Deploy **an/aus** schalten (Stufe A) und ein
Kommando **vorschlagen**, aber das Schreiben des Kommandos läuft über Stufe B
mit angezeigtem Volltext. Das Template liefert Kommandos aus einem kuratierten
Katalog, nicht aus freiem Text.

**F6 — Nur zwei Templates, oder eigene?**
Der Auftrag nennt „mindestens" Software-Dev und Dokumente. Eigene Templates
wären Daten (JSON in `ops/harness/`, versioniert wie Briefs) — aber dann braucht
es Editor, Validierung, Migration bei `template_version`-Sprüngen.
*Empfehlung:* Phase 1 **genau zwei, im Code**. Eigene Templates erst, wenn ein
dritter Bedarf real auftritt.

**F7 — Wo lebt die Repo-Linie in der Navigation?**
Eigener Screen `/repo/<hash>` · Detailansicht in Tür 2 · Erweiterung von
`/loopmap` um einen Repo-Umschalter oben.
*Empfehlung:* **`/loopmap` erweitern.** Der Screen existiert, rendert die Linie
bereits und ist aus Tür „Automatik" verlinkt (`settings.tsx:534`); ein
Repo-Umschalter ist deutlich weniger Fläche als ein neuer Screen.

---

# 9. Abnahmekriterien (für die spätere Baukarte, nicht für dieses Dokument)

Ein Bau gilt als fertig, wenn:

1. Ein frisch angelegtes Repo mit Template `docs-process` **ohne weitere
   Eingabe** eine Karte bis „Fertig" bringt und dabei nachweislich **keinen**
   Deploy-Hook ausführt (Beleg: kein `hook`-Event im Audit).
2. `/loop/map?repo=<pfad>` fünf Stationen mit korrektem
   `state: fixed|auto|off` liefert und `ops/tests/test_harness_layer.py`
   in beide Richtungen grün ist.
3. Der Satz „Henry, dieses Repo braucht kein Deploy" die Deploy-Station
   umschaltet, und der Audit-Trail Akteur, Vorher- und Nachher-Wert zeigt.
4. Der Satz „Henry, schalt Auth ab" eine Ablehnung mit Nennung des Gesetzes
   erzeugt — **kein** `machine_task` (§6.5, Fallthrough).
5. Screenshot der Linie beurteilt, nicht nur gerendert: Lesbarkeit, Zentrierung,
   Theming, keine Kollisionen bei fünf Stationen auf Telefonbreite.

**Zusätzlich aus den Entscheidungen E1–E3:**

6. **(E1)** Dasselbe Repo, aufgerufen über Hauptpfad, Kleinschreibung,
   Trailing-Slash, Unterordner und Worktree, löst auf **ein** Profil auf. Ein
   zweites Anlegen mit gleichem `(repo_id, root_dir)` wird **abgelehnt**, nicht
   überschrieben — und der Deploy-Hook feuert auch bei kleingeschriebenem Pfad
   (das war Bruch 2 aus §10.2).
7. **(E2)** Eine im Profil geänderte Spaltenliste erscheint im Board **ohne**
   Client-Änderung; `board.tsx` enthält keine Lane-Liste mehr (Nachweis: grep
   findet keinen zweiten `LANES`-Array). Eine Karte in einer entfernten Spalte
   geht **nicht** verloren, sondern fällt sichtbar auf ihre Standardspalte
   zurück (§12.5).
8. **(E3)** Mit `stations.gate = "off"` läuft nachweislich **kein** Gate
   (kein `gate`-Event im Audit) — und Linie *und* Board zeigen den Warnhinweis
   mit Akteur und Zeitpunkt. „Henry, mach das Gate wieder scharf" stellt den
   Zustand ohne Rückfrage her.
9. **(E3, negativ)** Es gibt keinen Aufruf, der das Gate für **mehr als ein**
   Project gleichzeitig abschaltet — auch nicht über Henry.

---

# 10. Identität: project / folder / git — Prüfergebnis

Owner-Vorgabe: *„Wichtig project unique zu folder unique zu git unique. Keine
Überschneidungen."* Auftrag war, das zu **überprüfen**. Alles unten mit
„gemessen" Markierte wurde auf dieser Maschine ausgeführt, nicht hergeleitet.

## 10.1 Urteil in einem Satz

**Die Absicht ist richtig und notwendig — die Aussage stimmt heute in keinem
der drei Teile, und in einem Teil *darf* sie gar nicht stimmen.**

| Owner-Aussage | Befund |
|---|---|
| „project unique" | **falsch** — Projekt-IDs kollidieren und überschreiben sich still |
| „folder unique" | **falsch** — ein Ordner hat beliebig viele gültige Schreibweisen |
| „git unique" | **stimmt bereits** — `_repo_hash` ist kanonisch, wird aber nirgends als Schlüssel benutzt |
| „project == folder == git" | **darf nicht gelten** — Monorepo-Standard trennt das bewusst (§10.4) |
| „keine Überschneidungen" | heute gibt es **keinerlei** Constraint, Dedup oder Kanonisierung |

## 10.2 Die gemessenen Brüche

**(1) Projekt-IDs sind nicht eindeutig — mit Datenverlust.**
`spine/ops/projects.py:41`: `pid = strftime("%Y%m%d-%H%M%S") + "-" + _slug(name)`,
und `_slug` schneidet bei 32 Zeichen ab (`:21-23`). Gemessen: zwei Projekte,
in derselben Sekunde angelegt, mit 32-Zeichen-gleichem Präfix ergeben
**dieselbe ID**. Die Ablage ist `INSERT OR REPLACE` (`spine/storage/db.py:250-254`).

> Gemessene Folge: ein Festpreis-Projekt (5000) wird von einem T&M-Projekt
> (180/h) **still ersetzt** — eine Zeile überlebt. Jede Karte mit dieser
> `project_id` wird ab da anders abgerechnet. Kein Event, kein Fehler.
> Zusatzbefund: Namen ohne lateinische Zeichen sluggen alle zu `"project"`.

**Das ist ein eigenständiger Datenverlust-Bug, unabhängig von Templates.**
Empfehlung: eigene Fix-Karte, nicht in dieses Feature einwickeln.

**(2) Ein Ordner hat viele gültige Namen.** Gespeichert wird nur
`os.path.abspath(repo)` (`cells/engineer/dispatch.py:50`). Gemessen:
`abspath` normalisiert Schrägstriche, `..` und den Schluss-Separator — aber
**nicht die Groß-/Kleinschreibung**, keine 8.3-Kurznamen und keine Junctions.

**(3) Der Deploy-Hook ist ein exakter String-Vergleich.**
`lanemachine.py:648`: `(st.get("repo_hooks") or {}).get(t.get("repo") or "", {})`.
Gemessen: derselbe Ordner in Kleinschreibung → **MISS** → Deploy läuft
still nicht. Der Code kennt das bereits: `henry_broker.py:502-517` wurde am
2026-08-27 nachgebessert, damit es wenigstens *laut* fehlschlägt
(*„oder der Repo-Pfad passt nicht exakt — kein Deploy ausgelöst"*). Der rohe
String-Schlüssel blieb.

**(4) Ein Unterordner gilt als eigenes Repo.** `is_git_repo` fragt nur
`git rev-parse --git-dir` (`gitutil.py:76-83`), was aus **jedem** Unterordner
gelingt. Gemessen: `ops/` und `cells/engineer/` bestehen die Intake-Prüfung bei
`routes_tracks.py:214`.
Folge, berechnet aus `_worktree_for` (`gitutil.py:283-288`): der Karten-Worktree
landet dann **innerhalb** des Repos (`swarmdeck/helmdeck-worktrees/…`), und
`helmdeck-worktrees` steht **nicht** in `.gitignore` (gemessen) — ein
vollständiger zweiter Checkout taucht als untracked im Hauptbaum auf, den jedes
`git add -A` einsammelt.

**(5) Sieben verschiedene Normalisierungen koexistieren.** Roh
(`repo_hooks`, `worktrees.py:81`), `abspath` (`dispatch.py:50`),
`normcase+abspath` (`gxp.py:91-97`), `normcase` ohne abspath
(`pm_resolve.py:101`), `realpath`-Hash (`gitutil.py:219`),
`normcase+realpath` (Dev-Tools). GxP und `repo_hooks` sind sich deshalb
uneins darüber, ob zwei Pfade dasselbe Repo sind.

**(6) Ein Umbenennen des Ordners ändert die Identität.** Gemessen:
`_repo_hash` vorher `2392xg1q`, nachher `071zl0yz`. Alte Worktrees sind danach
verwaist und werden vom Sweeper still übersprungen (`worktrees.py:94`).

**(7) Es gibt nirgends einen Uniqueness-Constraint.** Kein Repo-Register, keine
Kanonisierung, kein Dedup. Der einzige `UNIQUE INDEX` im Schema betrifft
`events(id)`.

## 10.3 Die gute Nachricht: die kanonische Git-Identität existiert schon

`_repo_hash` (`gitutil.py:219-242`) rechnet
`realpath(dirname(git-common-dir))` → 8 Zeichen base36. Gemessen: **Worktree,
Haupt-Repo, Kleinschreibung, Schluss-Separator und Unterordner ergeben alle
denselben Hash** (`1mmjd8p4`).

Das ist genau die gesuchte Eigenschaft „git unique" — sie ist bereits gebaut und
wird heute **ausschließlich zur Benennung eines Verzeichnisses** benutzt: nie
als Nachschlage-Schlüssel, nie auf einer Karte gespeichert, nie vom Hook-, GxP-
oder PM-Pfad konsultiert.

> **Kernempfehlung:** `_repo_hash` vom Verzeichnisnamen zum **Identitätsschlüssel**
> befördern. `repo_profiles`, `repo_hooks`, `pm.repos` und der GxP-Scope werden
> über die Repo-ID gekoppelt, nicht über den Pfad-String. Das schließt die
> Brüche (2), (3) und (5) in einem Zug — mit vorhandenem, erprobtem Code.
> Bruch (6) bleibt und braucht eine bewusste Entscheidung (F9).

## 10.4 Warum „ein Ordner = ein Repo = ein Projekt" nicht das Ziel sein sollte

Im Monorepo ist die Gleichsetzung **absichtlich falsch**, und zwar bei allen
untersuchten Systemen:

- **Vercel:** *„You'll create a new project for each directory in your monorepo
  that you wish to import"* — N Projekte über EINEM Git-Repo, jeweils
  abgegrenzt durch die Einstellung **Root Directory**.
- **Nx:** ein *project* wird durch `project.json` bzw. einen `nx`-Eintrag in
  `package.json` markiert — nicht durch den Ordner.
- **Bazel:** ein *package* ist sein Verzeichnis **minus** aller Unterordner mit
  eigener `BUILD`-Datei. Die Ordnergrenze ist ausdrücklich **nicht** die
  Identitätsgrenze.
- **Backstage:** trennt sogar dreifach — Entity, `managed-by-location`
  (wo die Definition liegt) und `source-location` (wo der Code liegt).

Und der Zusammenhang, der die Entscheidung trägt: **genau die Systeme, die
Projekt- und Repo-Identität verschmelzen (GitHub-/GitLab-Template-Repos), sind
auch die, die ein Template nicht erneut anwenden und keine Abweichung erkennen
können.** Wer später „Template aktualisieren" oder „weicht vom Template ab"
will, braucht einen eigenen Projekt-Datensatz, in dem die Bindung steht.

## 10.5 Identitätsmodell (drei Ebenen, Standardbegriffe) — **abgenommen (E1)**

> **Owner-Entscheidung 2026-08-30:** dieses Modell ist angenommen und damit die
> verbindliche Grundlage für `repo_profiles` (§5.1), den Onboarding-Schritt 2
> (§11.2) und die Migration bestehender pfadbasierter Keys.

Statt einer Gleichung eine **Hierarchie** — jede Ebene für sich eindeutig:

| Ebene | Standardbegriff | Eindeutig durch | Kardinalität |
|---|---|---|---|
| 1 | **Repository** | `_repo_hash` = `realpath(dirname(git-common-dir))` | 1 pro Git-Repo, stabil über Worktrees |
| 2 | **Project** (Vercel-Modell) | `repo_id` + **Root Directory** (relativ) | N pro Repository (Monorepo), Default `.` = 1 |
| 3 | **Delivery/Billing-Project** | vorhandenes `projects.py` | N:M zu Ebene 2 |

Der **Template-Datensatz hängt an Ebene 2** — dort, wo auch Vercel sein
Framework-Preset ablegt. Der Schlüssel für `repo_profiles` wird damit
`"<repo_id>:<root_dir>"` statt eines rohen Pfades.

Erzwungene Eindeutigkeit („keine Überschneidungen" — die Owner-Anforderung, jetzt
prüfbar):
- Zwei Ebene-2-Projekte mit gleichem `(repo_id, root_dir)` → beim Anlegen
  **abgelehnt**, nicht überschrieben.
- Ein Ebene-2-Projekt, dessen `root_dir` ein anderes enthält → **Warnung**
  („verschachtelte Projekte"), zugelassen nur mit Bestätigung (Bazel-Regel:
  das äußere endet, wo das innere beginnt).
- Ein Ordner, der ein *Worktree* dieses Repos ist → beim Import erkannt und
  auf das Haupt-Repo umgebogen, statt als neues Projekt angelegt zu werden.
  (Heute passiert das Gegenteil — Bruch (4).)

---

# 11. Onboarding-UX

Owner-Formulierung: *„User macht App oder wählt neues project/folder aus. Dann
basierend auf folder Vorschlag wie template aussieht."*

## 11.1 Dieser Instinkt ist durch die Recherche belegt

**Erkennen und vorschlagen** schlägt **blind auswählen lassen** — kein
untersuchtes System fragt blind, wenn Erkennung möglich ist:

- **Vercel:** *„Vercel automatically detects your project's framework and sets
  the best settings for you"* — gesetzt werden Framework-Preset, Build Command,
  Output Directory, Install Command, Dev Command.
- **Netlify:** füllt Build-Felder automatisch, *„You can update the fields
  afterwards as needed."*
- **GitLab:** rät sogar die Umgebungsstufe aus dem Namen (`prod|live` →
  production) und lässt sie überschreiben.
- **Nx:** leitet Projekte aus vorhandener Tooling-Konfiguration ab, mit einer
  expliziten Vorrang-Leiter.

Der Gegenpol ist **Azure DevOps**, das den Prozess bei Anlage *auswählen* lässt
und dann hart bindet: *„You can't change a project's base process after the
project is created."* Das ist die Erfahrung, die wir **nicht** wiederholen.

## 11.2 Der Ablauf (fünf Schritte)

```
1 Ordner wählen  →  2 Identität prüfen  →  3 Erkennen & vorschlagen
                                                    ↓
                    5 Anwenden + Antwortdatei  ←  4 Prüfen & ändern
```

**Schritt 1 — Ordner wählen.** Zwei Einstiege, ein Dialog: „App/Projekt neu
anlegen" (legt an; `init_repo` in `gitutil.py:86` existiert bereits) oder
„vorhandenen Ordner aufnehmen".

**Schritt 2 — Identität prüfen (neu, verhindert die Brüche aus §10).**
Verbindlich seit **E1**: aufgelöst wird auf das Drei-Ebenen-Modell (§10.5),
nicht auf einen Pfad-String. Bevor
irgendetwas vorgeschlagen wird, wird aufgelöst und *dem Nutzer gezeigt*:
Repository (Hash + Haupt-Checkout-Pfad), Root Directory, und die Antwort auf
„kennen wir das schon?". Vier Fälle mit klarer Ansage statt stiller Annahme:

| Fall | Ansage |
|---|---|
| unbekanntes Repo | „Neues Repository." → weiter |
| bereits aufgenommen | „Kennen wir schon als *X*." → öffnen statt anlegen |
| Unterordner eines bekannten Repos | „Das ist ein Unterordner von *X*. Als eigenes Projekt im Monorepo aufnehmen?" |
| Worktree eines bekannten Repos | „Das ist ein Arbeitsbaum von *X*." → auf Haupt-Repo umbiegen |

**Schritt 3 — Erkennen und vorschlagen.** Aus dem Ordnerinhalt:

| Signal im Ordner | Vorschlag | Angezeigte Begründung |
|---|---|---|
| `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `pom.xml` | `software-dev` | „Build-Datei gefunden: package.json" |
| `.github/workflows/`, `Dockerfile`, vorhandene `helmdeck.gate` | `software-dev` | „CI-Konfiguration gefunden" |
| überwiegend `.md`/`.docx`/`.pdf`, kein Build-Manifest | `docs-process` | „Fast nur Dokumente, keine Build-Datei" |
| Workspace-Marker (`pnpm-workspace.yaml`, `nx.json`, `turbo.json`, `workspaces`) | `software-dev` **+ Monorepo-Hinweis** | „Monorepo erkannt — eigenes Projekt je Paket?" |
| nichts davon | **kein Vorschlag** | siehe unten |

**Der Fehlschlag-Fall wird von Vercel wörtlich übernommen:** kein Treffer →
Preset „Sonstiges", und die Überschreib-Schalter sind **von vornherein
aufgeklappt**, statt den Nutzer eine falsche Vorauswahl korrigieren zu lassen.

**Schritt 4 — Prüfen und ändern (der eigentliche Bildschirm).** Der Vorschlag
wird **vollständig und begründet** gezeigt, bevor irgendetwas geschrieben wird:
die Linie mit ihren Stationen (§4), je Station der gesetzte Key und sein Wert,
je Zeile die Erkennungsbegründung, und jede Zeile änderbar. Fußzeile: „Diese
Werte werden geschrieben" mit genau den Keys aus §5.2/§5.3 — nichts geschieht
unangekündigt.

**Schritt 5 — Anwenden und festhalten.** Geschrieben werden die Keys **plus**
die Antwortdatei nach Copier-Vorbild: welches Template, welche Version, welche
Antworten, wer und wann. Ohne diesen Datensatz sind „Template aktualisieren"
und „weicht ab" später nicht berechenbar, sondern geraten — genau der
Unterschied zwischen Cookiecutter (kann es nicht) und Copier (kann es).

## 11.3 Was ein Template vorlegt — die vier Kategorien des Owners

Der Owner nennt „states, skills, gates, policies". Ehrlicher Stand je Kategorie:

| Kategorie | Heute abbildbar? | Wie |
|---|---|---|
| **States** | **ja, auf Spaltenebene** (E2) | Die 7 Status bleiben Maschinenzustände; das Template definiert die **Spalten** darüber (§12.5). `policy.lane_labels` benennt weiterhin um |
| **Skills** | **ja, überraschend gut** | Skills sind Dateien in `.claude/skills/` (verifiziert). Ein Template kann sie ins Repo legen — kein neuer Mechanismus, keine Registry nötig |
| **Gates** | **ja** (E3) | Gate-Kommando = Datei `helmdeck.gate` (setzbar), Gate an/aus = `stations.gate` (neuer Key, §2.3) |
| **Policies** | **ja** | `policy.*` ist vollständig über `configure` erreichbar (§2.5) |

Skills sind hier der günstigste Gewinn: weil sie schon repo-lokale Dateien sind,
sind sie **von Natur aus pro Repo** — genau die Eigenschaft, die Cells fehlt (§2.2).

---

# 12. Kanban-Mapping

Owner: *„Ganz wichtig wie wird es zu kanban gemappt. User kann review und ändern."*

## 12.1 Die Regel, die das Problem löst (Jira-Modell)

Jira trennt sauber, und HelmDeck hat dieselbe Trennung bereits — nur unbenannt:

> *„a column describes the current status of a work item"* — eine **Spalte**
> bildet **eine oder mehrere** Workflow-**Status** ab.

HelmDeck hat exakt diese zwei Achsen:
- **`lane`** — 4 Werte, `backlog|working|review|done` (`sessions.py:121`) = die **Spalten**
- **`status`** — 7 Werte, `queued|running|gating|needs_you|bounced|submitted|accepted` = die **Status**

Eine Karte kann `lane=review, status=bounced` (rotes Gate) oder
`lane=review, status=submitted` (grün, wartet auf Abnahme) sein — **eine
Spalte, zwei Status**. Das ist bereits das Jira-Modell.

**Damit ist die Antwort auf „wie mappt die U-Bahn auf Kanban" strukturell und
nicht kosmetisch:** Stationen sind **keine** Spalten. Drei Stationen sind
Haltepunkte (= Spalten), zwei sind Übergänge (= Gates auf der Kante).
AWS CodePipeline benutzt dafür dieselben Wörter: **Stage**, **Transition**, und
Bedingungen heißen dort ausdrücklich *„also referred to as **gates**"*.

## 12.2 Die Mapping-Tabelle

| U-Bahn-Station | Art | Kanban-Spalte | `lane` | `status` in dieser Spalte |
|---|---|---|---|---|
| **Karte** | Haltepunkt | Backlog | `backlog` | `queued` |
| **Arbeit** | Haltepunkt | In Arbeit | `working` | `running`, `needs_you` |
| **Gate** | **Übergang** | *(keine Spalte — Kante Arbeit→Review)* | — | `gating`, bei Rot `bounced` |
| **Abnahme** | Haltepunkt | Review | `review` | `submitted`, `bounced` |
| **Deploy** | **Übergang** | *(keine Spalte — nach dem Merge)* | — | `accepted` |
| — | Endpunkt | Fertig | `done` | `accepted` |

Fünf Stationen, vier Spalten — weil Gate und Deploy Übergänge sind, an denen
keine Karte *wohnt*. Sie werden auf dem Board als Zustand der **Kante**
gerendert (Gate läuft / Gate rot / Deploy läuft / Deploy rot), nicht als Spalte.

> **Seit E2 ist diese Tabelle der Standard, nicht das Gesetz.** Die vier Spalten
> sind das, was ein Template ohne eigene `columns` liefert; ein Template darf
> feiner schneiden (z. B. `needs_you` als eigene Spalte). Was sich **nicht**
> ändert: Gate und Deploy bleiben Übergänge — eine Spalte „Gate" wäre eine
> Spalte, in der keine Karte liegen kann. Siehe §12.5.

## 12.3 Zwei Ansichten, eine Wahrheit

Die U-Bahn-Linie und das Kanban-Board sind **Projektionen desselben Paares
`(lane, status)`** — nicht zwei Datenmodelle:

- **Board** beantwortet „wo liegt welche Arbeit gerade?" (Spalten, WIP-Limit).
- **Linie** beantwortet „welchen Weg nimmt Arbeit in diesem Repo?" (inkl. der
  Übergänge, die auf dem Board unsichtbar sind).

Dass beide aus einer Quelle kommen, ist bereits Hausregel: `/loop/map` erzwingt
genau eine Definition, und `ops/tests/test_harness_layer.py:240,351` prüft sie
in beide Richtungen gegen den Client-Vertrag. Die Linie darf **keine** zweite
Zustandsliste bekommen.

## 12.4 Was der Nutzer ändern darf — und was nicht

| Was | Änderbar? | Wie |
|---|---|---|
| Spalten**namen** | **ja** | `policy.lane_labels` — existiert bereits, ist per Chat erreichbar |
| WIP-Limit je Spalte | teilweise | `capacity.wip_limit` ist heute **global**, nicht pro Spalte (Jira: *column constraint*) → F11 |
| Reihenfolge / Anzahl der Spalten | **ja, seit E2** | Spalten kommen aus `/loop/map`, `board.tsx:27` verliert die hartkodierte Liste → §12.5 |
| Workflow-**Status** (die 7 Werte) | **nein** | Status sind Maschinenzustände, keine Ansichtssache → §12.5 „die Grenze" |
| Ob Gate/Deploy laufen | **ja** | Deploy heute (§2.4), Gate seit E3 |
| Abnahme automatisch | **ja** | `policy.auto_accept_green` |

## 12.5 Der Board-Umbau (Entscheidung E2)

Der Owner hat entschieden, den Umbau **mit aufzunehmen**: ein Template darf
Spalten definieren, nicht nur umbenennen. Das ist der größte Einzelposten der
drei Entscheidungen — hier steht, wie er sicher gebaut wird.

**Der Anlass.** `surfaces/app/src/ui/board.tsx:27` hält
`const LANES = [...] as const` — eine zweite, hartkodierte Kopie der Lane-Liste
im Client. Solange die dort steht, kann **keine** Template-Entscheidung das
Board beeinflussen. Das ist derselbe Fehler, den `settings-ia-redesign` für die
Cell-Liste beschreibt (keine hartkodierten Listen im Client) — und dieselbe
Lösung: die Liste kommt vom Server, der Client rendert nur.

**Die Grenze, die den Umbau billig hält.** Änderbar wird die **Spalte**
(Ansicht), **nicht** der **Status** (Maschinenzustand). Das ist exakt die
Jira-Trennung aus §12.1 und der Grund, warum dieser Umbau nicht die
Azure-DevOps-Falle ist (§11.1: Statusmodell nachträglich gar nicht mehr
änderbar): die Zustandsmaschine in `lanemachine.py` behält ihre Übergänge,
ihre Gate-Kante und ihren Accept-Pfad unverändert. Eine Spalte ist eine
**benannte Menge von `(lane, status)`-Paaren** — mehr nicht.

```jsonc
"columns": [
  {"id":"backlog", "label":"Backlog",           "match":{"lane":"backlog"}},
  {"id":"work",    "label":"In Arbeit",         "match":{"lane":"working"}},
  {"id":"waiting", "label":"Wartet auf Kunden", "match":{"lane":"working","status":["needs_you"]}},
  {"id":"review",  "label":"Freigabe",          "match":{"lane":"review"}},
  {"id":"done",    "label":"Fertig",            "match":{"lane":"done"}}
]
```

Im Beispiel entsteht eine **fünfte** Spalte, ohne dass ein einziger neuer
Zustand existiert: `needs_you` wird aus „In Arbeit" herausprojiziert. Genau das
ist Jiras Modell, angewandt.

**Vier Regeln, ohne die der Umbau Karten verschwinden lässt:**

1. **Vollständigkeit ist Pflicht.** Jedes mögliche `(lane, status)`-Paar muss
   von mindestens einer Spalte getroffen werden. Beim Speichern wird das
   geprüft; eine Lücke wird abgelehnt, nicht toleriert.
2. **Erster Treffer gewinnt.** Spalten werden in Reihenfolge geprüft, damit die
   speziellere Spalte (`waiting`) vor der allgemeineren (`work`) stehen kann.
   Kein „gehört in zwei Spalten"-Zustand.
3. **Fallback statt Verlust.** Trifft trotzdem nichts (alte Karte, neuer
   Status), landet die Karte sichtbar in der Standardspalte ihrer Lane, mit
   Hinweis — sie verschwindet nie.
4. **Eine Wahrheit.** Die Spaltenliste kommt aus `/loop/map` und wird vom
   Zwei-Wege-Test `ops/tests/test_harness_layer.py:240,351` gegen den
   Client-Vertrag geprüft (§4.3 Punkt 4). Die U-Bahn-Linie bekommt **keine**
   eigene Spaltenlogik — sie zeigt weiterhin Stationen, nicht Spalten (§12.3).

**Was der Umbau kostet:** `board.tsx` wird schema-getrieben (Spalten, Labels,
WIP-Anzeige aus Daten), `/loop/map` bekommt die Spaltenliste, `repo_profiles`
das Feld `columns` (Default `null` = Standard aus dem Template), und der
Wire-Vertrag muss in beide Richtungen nachgezogen werden. Das ist derselbe
Umbau, den `settings-ia-redesign` Phase 1 für die Settings ohnehin vorsieht —
weshalb die Reihenfolge aus §7 (Schwesterkarte zuerst) durch E2 **wichtiger**
wird, nicht unwichtiger.

---

# 13. Begriffslexikon (Standardbegriffe)

Owner-Vorgabe: *„Benutzt standard Begriffe."* Verbindlich für Code, Keys und
Prosa. Englisch ist die Schreibweise in Keys/Enums, Deutsch die in der UI.

| Begriff (EN, verbindlich) | Deutsch (UI) | Bedeutung hier | Quelle des Standards |
|---|---|---|---|
| **Repository** | Repository | Ebene 1, `_repo_hash` | Git |
| **Project** | Projekt | Ebene 2, `repo_id` + Root Directory | Vercel, Nx |
| **Root Directory** | Root Directory | Unterordner, der ein Projekt abgrenzt | Vercel |
| **Workspace** | Workspace | Repo-Container mehrerer Pakete | pnpm, Bazel |
| **Template** | Vorlage / Template | Konfigurationsbündel bei Anlage | Backstage, Jira |
| **Answers file** | Antwortdatei | festgehaltene Template-Wahl + Antworten | Copier |
| **Drift** | Abweichung | Ist ≠ Template | cruft |
| **Workflow / state model** | Statusmodell | erlaubte Zustände | Azure DevOps |
| **State / Status** | Status | `queued`, `running`, … | Jira, Azure DevOps |
| **Column** | Spalte | Board-Spalte = Projektion mehrerer Status | Jira |
| **WIP limit** (Jira: *column constraint*) | WIP-Limit | Kappung gleichzeitiger Arbeit | Kanban Guide, Jira |
| **Pull system** | Pull-System | Start erst bei freier Kapazität | Kanban Guide |
| **Definition of Done** | Definition of Done | Fertig-Kriterien | Scrum Guide |
| **Quality gate** | Quality Gate | Bedingungsmenge, die Freigabe entscheidet | SonarQube |
| **Stage / Transition** | Stage / Übergang | Pipeline-Abschnitt bzw. Kante | GitLab, AWS |
| **Environment** | Umgebung | `development`/`staging`/`production` | GitLab |
| **Promotion** | Promotion | Release eine Umgebung höher | Octopus Deploy |
| **Trunk / main** | Trunk | Integrationszweig | Trunk-Based Development |

**Drei Fallen, die das PRD bewusst vermeidet:**
1. **„Lead time" vs. „cycle time"** sind zwischen Kanban Guide, Kanban
   University und DORA **widersprüchlich** belegt. Wenn eines der Wörter
   auftaucht, muss die Definition danebenstehen.
2. **„Definition of Ready"** steht **nicht** im Scrum Guide — es ist eine
   Community-Konvention (Agile Alliance) und darf nicht als Standard zitiert
   werden.
3. Es gibt **keine** kanonische Spaltennamen-Liste. Jira-Default für Kanban ist
   *Backlog / Selected for Development / In Progress / Done*. HelmDecks
   bestehende Namen bleiben — sie sind über `policy.lane_labels` ohnehin frei.

---

# 14. Weitere Fragen aus der UX-Prüfung

**F8 und F10 sind entschieden** (§0/E1, §0/E2) und stehen mit Ergebnis hier;
offen bleiben F9, F11, F12.

**F8 — Wird die Repo-Identität auf `_repo_hash` umgestellt?** — **ENTSCHIEDEN:
ja, Drei-Ebenen-Modell.**
Betrifft `repo_hooks`, `pm.repos`, GxP-Scope und den neuen `repo_profiles`-Key.
Migration nötig: bestehende pfadbasierte Einträge einmalig auflösen — Ablauf
und Fehlerfall in §5.1, Abnahmekriterium 6 in §9.
*Begründung (bestätigt):* es schließt drei gemessene Brüche mit bereits
vorhandenem Code; `_repo_hash` wird vom Verzeichnisnamen zum Schlüssel
befördert, nicht neu erfunden.

**F9 — Was passiert, wenn ein Repo verschoben/umbenannt wird?** *(gemessen: Identität ändert sich)*
(a) hinnehmen und beim nächsten Öffnen „Repo neu aufnehmen?" fragen ·
(b) Identität in einer Datei **im** Repo ablegen (`.helmdeck/repo-id`), dann
überlebt sie den Umzug — kostet aber eine Datei im Kundenrepo ·
(c) Reparaturweg „Repo umgezogen: alten Eintrag übernehmen?".
*Empfehlung:* **(a) + (c)** — keine Datei in fremden Repos, aber ein
angebotener Reparaturweg statt stiller Verwaisung.

**F10 — Dürfen Templates das Statusmodell ändern, oder nur die Beschriftung?**
— **ENTSCHIEDEN: Board-Umbau aufgenommen, Templates dürfen Spalten definieren.**
Heute: 4 Lanes fix, `board.tsx:27` zusätzlich hartkodiert. Azure DevOps zeigt,
wie teuer ein pro-Projekt änderbares Statusmodell ist (nachträglich gar nicht
mehr änderbar).
*Meine Empfehlung war „nur Beschriftung".* Der Owner hat den Umbau gewählt —
umgesetzt wird er in der Variante, die die Azure-Falle vermeidet: **Spalten
werden frei, Status bleiben die sieben.** Eine Spalte ist eine Projektion über
`(lane, status)`, kein neuer Maschinenzustand. Vollständige Spezifikation samt
der vier Regeln gegen Kartenverlust: **§12.5**.
*Bewusst nicht enthalten:* neue Workflow-*Status* pro Repo. Die würden die
Zustandsmaschine, den Gate-Übergang und den Accept-Pfad berühren und sind damit
ein anderes, deutlich größeres Vorhaben — falls das später gewünscht ist,
gehört es in eine eigene Karte, nicht in dieses Feature.

**F11 — WIP-Limit pro Spalte oder global?**
`capacity.wip_limit` ist global; Kanban-Standard (Jira *column constraint*) ist
pro Spalte.
*Empfehlung:* **vertagen.** Global reicht für beide Templates; pro Spalte erst
bei echtem Bedarf.

**F12 — Bindet die Antwortdatei, oder dokumentiert sie nur?**
Verschärft F3 mit dem Recherchebefund: Jira bietet **beides als
Produktentscheidung** an (team-managed = lokal, company-managed = Schemata
propagieren), Copier kann per Drei-Wege-Merge aktualisieren.
*Empfehlung:* Phase 1 **nur dokumentieren** (Antwortdatei + Drift-Anzeige),
`update` später — aber die Datei **von Anfang an schreiben**, sonst ist die
Historie unwiederbringlich weg.

> **Nicht-Frage, sondern Auftrag:** die Projekt-ID-Kollision (§10.2, Bruch 1)
> ist ein Datenverlust-Bug mit falscher Abrechnung als Folge. Sie gehört in eine
> eigene Karte, unabhängig von diesem Feature.

---

# 15. Quellenregister

Alles unten wurde in diesem Worktree gegen `96fa973` gelesen. Externe Quellen
(§10.4, §11.1, §12.1, §13) sind Primärdokumentation der genannten Produkte.

| Thema | Datei:Zeile |
|---|---|
| Lane-/Gate-Graph (Knoten, Kanten, `kind`, `settings`) | `cells/engineer/sessions.py:140-195`, `:110`, `:121` |
| Graph-Endpunkt + Gesetze-Liste | `spine/http/routes/routes_info.py:42`, `:77-92`, `:141` |
| Graph-Zusammenbau, Knob-Schema | `spine/http/apimeta.py:24`, `:36`, `:78-129` |
| U-Bahn-UI (feste Linie, Gate inline, Badges) | `surfaces/app/src/app/loopmap.tsx:199`, `:279-308`, `:62-72` |
| Wire-Vertrag + Zwei-Wege-Test | `surfaces/app/src/data/client.ts:308-354`; `ops/tests/test_harness_layer.py:240,351` |
| Gate-Ausführung, Datei-Erkennung | `cells/engineer/lanemachine.py:162-262`, `:193-196` |
| Accept-Pfad, Merge, Deploy-Hook | `lanemachine.py:759`, `:891-974`, `:1119`, `:615-681` |
| Settings: Defaults, Schreibweg, Audit | `spine/storage/events.py:97-138`, `:147-156`, `:180-217` |
| Chat-Actions, `configure`, Allowlist | `cells/copilot/copilot_actions.py:14`, `:67`, `:97`, `:102-130`, `:415-429` |
| Copilot-Brief (was Henry ändern darf) | `ops/harness/agents/board-copilot.md:88-95`, `:122-139`, `:185-191` |
| Policy-Plane, owner-only Swap | `spine/auth/policy.py:85-114`; `spine/http/routes/routes_policy.py:21-22` |
| Charter-Kern (der eine Boden) | `spine/auth/charter.py:11-13`, `:16-31` |
| Cells global, kein Repo-Feld | `spine/registry/cells.py:71-92`, `:266-276`, `:296` |
| Repo-Liste wird abgeleitet | `spine/http/routes/routes_gxp.py:32-39` |
| Repo pro Karte, Intake-Prüfung | `cells/engineer/routes_tracks.py:200`, `:214`; `dispatch.py:50`, `:62` |
| `direct_task` ohne Gate (Schuld) | `cells/engineer/dispatch.py:334`, `:348-352` |
| Full-dynamism-Dekret | `ARCHITECTURE.md:28-52`; `spine/registry/debt.py` (`full-dynamism-decree`) |
| Schwesterkarte Settings-IA | `ops/docs/backlog/settings-ia-redesign/README.md` |
| **Projekt-ID + Ablage (Kollision)** | `spine/ops/projects.py:21-23`, `:41`, `:42-47`; `spine/storage/db.py:250-254` |
| **Kanonische Git-Identität** | `spine/git/gitutil.py:219-242` (`_repo_hash`), `:76-83` (`is_git_repo`), `:283-288` (`_worktree_for`) |
| **Die sieben Normalisierungen** | `dispatch.py:50`; `lanemachine.py:648`; `gxp.py:91-97`; `pm_resolve.py:101`; `worktrees.py:81`, `:94` |
| **Deploy-Hook-Mismatch, bereits bekannt** | `cells/copilot/henry_broker.py:502-517` |
| **Kanban: Lane- und Status-Achse** | `cells/engineer/sessions.py:121`; `surfaces/app/src/ui/board.tsx:27`, `:48-52` |
| **Skills sind repo-lokale Dateien** | `.claude/skills/` (verifiziert) |
| Externe Standards (§10.4, §11.1, §12.1, §13) | Vercel · Nx · Bazel · Backstage · Copier/cruft · Jira · Azure DevOps · Kanban Guide · Scrum Guide · SonarQube · GitLab · AWS CodePipeline · Octopus |
