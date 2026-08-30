# Repo-Onboarding mit Harness-Templates — PRD

**STATUS: ENTWURF ZUR ABNAHME. Kein Code in diesem Kartenlauf.** Dieses Dokument
beschreibt, *was* gebaut werden soll und *auf welche echten Keys* es abgebildet
wird. Es soll entschieden werden, bevor gebaut wird — die offenen
Entscheidungen stehen in §8.

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
   `helmdeck.gate` existiert. „Gate abschalten" hat heute kein Ziel.

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
> auditierbar) oder man führt den Key erst ein. Entscheidung: **offene Frage F2.**

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
  Konfiguration und Sichtbarkeit.
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
| 3 | **Gate** | Knoten `gate` (`:187-194`), Ausführung `lanemachine.py:162-262` | Datei `<repo>/helmdeck.gate`; `gate_idle_s`, `gate_hard_s` | **kein Key vorhanden** → F2 |
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
- **Aus** (Deploy; ggf. Gate nach F2) — die Station wird ausgegraut mit
  Begründung („kein Deploy-Hook für dieses Repo hinterlegt").

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

---

# 5. Template-Katalog

## 5.1 Wo ein Template gespeichert wird

Neuer Top-Level-Key in `settings.json` — der erste echte Pro-Repo-Datensatz:

```jsonc
"repo_profiles": {
  "C:\\Users\\...\\helmdeck": {
    "template": "software-dev",
    "template_version": 1,
    "applied": "2026-08-30T12:00:00Z",
    "applied_by": "owner",
    "stations": { "gate": "on", "abnahme": "manual", "deploy": "on" },
    "drift": []            // Keys, die seit dem Seeden abweichen
  }
}
```

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
  Template-Wechsel einen Checkpoint erzeugt und rücknehmbar ist.

## 5.2 Template „Software-Entwicklung" (`software-dev`)

Für Repos, aus denen ein Artefakt gebaut und ausgeliefert wird.

| Was das Template vorlegt | Echter Key | Wert | Warum |
|---|---|---|---|
| Gate an | Datei `<repo>/helmdeck.gate` | anlegen, falls fehlt | Gate-before-review ist hier Gesetz |
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
| Gate leicht | Datei `helmdeck.gate` | Doku-Gate (Links/Frontmatter) oder keine → **F2** | ein Python-Compile-Gate ist hier sinnlos |
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
| 3 | „Schalt das Gate für dieses Repo ab" | **B** | Ask → owner-bestätigt | `repo_profiles.{repo}.stations.gate = "off"` — **existiert erst nach F2** |
| 4 | „Mach das Gate wieder scharf" | **A** | `configure` | `…stations.gate = "on"` — Verschärfen ist immer Stufe A |
| 5 | „Grüne Karten sollen hier automatisch durchgehen" | **A** | `configure` | `policy.auto_accept_green = true` |
| 6 | „Ich will jede Karte selbst abnehmen" | **A** | `configure` | `policy.auto_accept_green = false` |
| 7 | „Dieses Repo ist ein Dokumenten-Repo" · „Nimm die Doku-Vorlage" | **B** | Ask (Diff zeigen) → `configure` | ganzes Template `docs-process` (§5.3) |
| 8 | „Wie ist dieses Repo eingerichtet?" | **A** (lesend) | Prosa + Link auf `/loopmap?repo=…` | keiner |
| 9 | „Hier darf höchstens eine Karte gleichzeitig laufen" | **A** | `configure` | `capacity.wip_limit = 1` |
| 10 | „Dringende Karten sollen von selbst starten" | **A** | `configure` | `policy.auto_dispatch_priority = "high"` |
| 11 | „Der PM soll hier nicht planen" | **B** | Ask → `POST /pm/config` | `pm.repos` ohne `{repo}` — `pm` ist **nicht** in `ALLOWED_CONFIG` |
| 12 | „Nenn die Spalte ‚Freigabe' statt ‚Review'" | **A** | `configure` | `policy.lane_labels.review = "Freigabe"` |
| 13 | „Schalt die PM-Cell ab" | **B** | Ask → `POST /policy/swap` | `pmEnabled = false`; Henry hat dafür heute **keinen** Weg (§2.6) |
| 14 | „Schalt Auth ab" · „Niemand muss sich mehr anmelden" | **C** | Ablehnung + Begründung | `authRequired` — Gesetz, `spine/auth/auth.py` |
| 15 | „Ändere den Charter-Kern" · „Erlaub Connectoren Shell-Zugriff" | **C** | Ablehnung + Begründung | `spine/auth/charter.py` — der eine Boden (§6.4) |
| 16 | „Lösch den Audit-Eintrag von gestern" | **C** | Ablehnung + Begründung | append-only, kein Löschpfad (`events.py:219+`) |

## 6.3 Beispiel einer Stufe-A-Antwort

> **Owner:** „Henry, dieses Repo braucht kein Deploy."
> **Henry:** „Erledigt — die Deploy-Station ist für helmdeck-docs aus. Karten
> landen nach der Abnahme direkt in Fertig."
> ```actions
> [{"type":"configure","patch":{"repo_profiles":{"C:\\…\\helmdeck-docs":
>   {"template":"docs-process","template_version":1,
>    "stations":{"gate":"on","abnahme":"auto","deploy":"off"}}}}}]
> ```

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

Alle sieben blockieren den Bau ganz oder teilweise. Reihenfolge = Wichtigkeit.

**F1 — Pro-Repo-Cells: Scope oder Vertagung?** *(blockiert Template-Umfang)*
Cells sind heute global (§2.2). „Das Template legt fest, welche Cells geseedet
werden" erfordert eine Repo-Dimension in `cells.enabled()`, im `Cell`-Deskriptor
und im Lifecycle-Start — plus die Frage, was mit einer laufenden Karte
passiert, wenn ihre Cell für dieses Repo aus ist.
*Empfehlung:* **vertagen.** Phase 1 seedet nur Repo-*Policy* (die Tabellen in
§5.2/§5.3 kommen ohne Cell-Flags aus). Pro-Repo-Cells als eigene Karte nach
`settings-ia-redesign` Tür 3.

**F2 — Was heißt „Gate aus" für ein Dokumenten-Repo?** *(blockiert Chat-Mapping #3)*
Es gibt keinen Key (§2.3). Drei Wege:
(a) **Gate bleibt immer an, nur das Kommando wechselt** — ein Doku-Repo bekommt
einen Doku-Gate (Frontmatter/Links/tote Verweise). Gesetz bleibt unangetastet.
(b) **Neuer Key `repo_profiles.<repo>.stations.gate`**, den `_gate()` liest.
Ehrlich und auditierbar, macht aber ein Gesetz zu Policy — berührt die offene
Schuld `full-dynamism-decree`.
(c) **Datei löschen** — funktioniert heute, ist aber unsichtbar und nicht im
Audit.
*Empfehlung:* **(a).** Ein Repo ohne jede Prüfung braucht das Konzept „Gate aus"
gar nicht — es braucht einen *passenden* Gate. Das hält das Gesetz intakt und
löst das Owner-Problem trotzdem.

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

---

# 10. Quellenregister

Alles unten wurde in diesem Worktree gegen `96fa973` gelesen.

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
