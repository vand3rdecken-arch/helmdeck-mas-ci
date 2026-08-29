# Repo-Onboarding mit Harness-Templates — Design (Phase 1)

**Status:** Entwurf zur Abnahme. Kein Produktivcode. Phase 2 = eigene Karten.
**Owner-Decree:** 2026-08-29 (Neuausrichtung + Nachtrag „U-Bahn-Karte, Chat als Änderungsweg").
**Mockup:** [`repo-templates-mockup.html`](repo-templates-mockup.html) (klickbar, im Browser öffnen).

Antwort auf: *„Settings zu komplex, muss idiot-proof sein."*
Leitsatz des Decrees: **sehen statt konfigurieren.**

---

## 0. Die Kurzfassung für den eiligen Leser

Drei Dinge, die diese Recherche geändert haben — sie stehen hier oben, weil sie
den Bauplan bestimmen:

1. **Der Chat-Änderungsweg existiert schon.** `configure` in
   `cells/copilot/copilot_actions.py:102` ist rollen-gated, akzeptiert
   Punkt-Keys, auditiert, und weist Harness-Keys bereits *mit Route statt Wand*
   ab. Phase 2 erweitert ihn, sie erfindet ihn nicht.
2. **Die zwei Vorlagen sind zwei Maschinen, die es beide schon gibt** — Karten
   (`cells/engineer/`) und Prozesse (`cells/process/processes.py` mit den Modi
   `do/prepare/cowork/teach/human`). Die Vorlage *wählt*, sie *baut nicht*.
3. **Der Blocker: es gibt keinen Repo-Scope.** Kein Repo-Datensatz, keine
   `repos`-Tabelle, kein `register_repo`. Ein Repo ist heute ein Pfad-String auf
   einer Karte. Fast alles, was eine Vorlage vorbelegen will, ist aktuell
   **global**. **Der Repo-Scope muss vor dem Vorlagen-Katalog gebaut werden** —
   sonst überschreiben sich zwei Repos gegenseitig. Das ist die eine echte
   Entscheidung, die ich brauche (§8, Frage 1).

---

## 1. Was der Owner will (Anforderung, unverändert)

1. Beim Anlegen/Onboarden eines Repos wählt der Owner einen **Repo-Typ als
   Vorlage** — mindestens „Software-Entwicklung" und „Dokumente/Inhalte".
2. Die Vorlage bestimmt vorab: welche Cells geseedet werden, welche
   Tests/Reviews laufen, wie deployt wird. **Einzeloptionen verschwinden hinter
   der Vorlage**, Feintuning bleibt zwei Ebenen tiefer erreichbar.
3. **U-Bahn-Karte**: feste Stationsfolge `Karte → Arbeit → Gate → Abnahme →
   Deploy`; die Vorlage bestimmt, welche Stationen aktiv sind. **Reine Anzeige,
   kein frei editierbarer Graph-Editor.**
4. **Änderung läuft über den Chat, nicht über Schalter.** Der Owner sagt Henry
   „schalt Review für Repo X aus"; Henry übersetzt das in eine
   configure-/Template-Änderung; die Karte zeigt sofort den neuen Verlauf.
5. Nur die flexible `policy.*`-Hälfte ist per Chat änderbar. Governance/Auth/
   Gate bleiben fix. Jede Änderung auditiert.

---

## 2. Befund: was heute wirklich existiert

Alles hier ist am Code verifiziert (Datei:Zeile), nicht aus dem Gedächtnis.

### 2.1 Es gibt ZWEI Policy-Ebenen (nicht verwechseln)

| | **Ebene A** `settings.json` → `policy.*` | **Ebene B** `policy_live.json` → `policies.*` |
|---|---|---|
| Defaults | `spine/storage/events.py:97` | `daemon/policy_seed.json:4` |
| Lesen | `events.settings()` (`events.py:147`) | `policy.get_policies()` (`spine/auth/policy.py:62`) |
| Schreiben | `events.save_settings()` (`events.py:180`), `POST /settings` | `policy.swap()` (`policy.py:85`) — einziger Pfad |
| **Per Chat erreichbar** | **ja** (`policy` steht in `ALLOWED_CONFIG`) | nur `POST /policy/swap`, Agent braucht `agentMaySwap` |
| Audit | `emit("settings", …)`, Secrets maskiert | `emit("reconfig", …)` |

`policy.machine` ist Ebene A. `worktreeIsolation`, `gateBeforeReview`,
`sod_accept` sind Ebene B.

> **Falle, die ich selbst getreten bin:** in meinem ersten Mockup stand
> `policy.worktree_isolation` — **den Key gibt es nicht.** Ebene B hat
> `worktreeIsolation`, und `ARCHITECTURE.md:160-162` gibt zu, dass die
> geseedeten Governance-Flags **noch gar nicht gelesen werden**: „gate/auth/
> economics still hard-wire their own checks rather than reading the seeded
> PolicySet". Eine Vorlage, die `worktreeIsolation: false` setzt, hätte
> **keinerlei Wirkung** — und der Karte hätte man das nicht angesehen.

### 2.2 Die echten `policy.*`-Keys (Ebene A, vollständig)

| Key | Default | Definiert | Wirkt |
|---|---|---|---|
| `policy.lang` | `"de"` | `events.py:104` | UI-Sprache |
| `policy.lane_labels` | `{}` | `events.py:111` | Spalten-Umbenennung |
| `policy.auto_dispatch_modes` | `["do","prepare"]` | `events.py:113` | welche Schritt-Modi allein starten |
| `policy.auto_accept_green` | `false` | `events.py:116` | grünes Gate → Auto-Abnahme |
| `policy.auto_dispatch_priority` | `""` | `events.py:119` | ab welcher Priorität selbst dispatcht wird |
| `policy.chat_configure_roles` | `["owner"]` | `events.py:122` | wer per Chat konfigurieren darf |
| `policy.load_admission` | `{enabled,cpu_max_pct,…}` | `events.py:132` | CPU-Bremse für Gate/Hooks |
| `policy.machine` | `{enabled,roles,roots,perm}` | `dispatch.py:270` (inline!) | Machine-/Direct-Karten |
| `policy.ask_repair` | `true` | `turnrunner.py:194` (inline!) | Reparaturzug bei Prosa-Frage |
| `policy.auto_continue` | `true` | `sessions_bg.py:99` (inline!) | Auto-Steer nach BG-Task |
| `policy.device` | `{claim_ttl_s}` | `dispatch.py:552` (inline!) | Geräte-Claim-TTL |
| `policy.house_rules` | `""` | `routes_info.py:39` | **additive** Hausregeln |
| `policy.chat_admin_roles` | — | — | **tot**, wird nicht mehr gelesen (`spine/auth/auth.py:53-56`), steht aber noch 10× im Copilot-Brief |

Dazu, außerhalb von `policy`: `capacity.wip_limit`, `repo_hooks`,
`default_repo`, `pm.repos`, `registration`, `dashboard`, `appearance`, `jira`.

### 2.3 Der echte Karten-Lebenszyklus (die Stationen)

`LANES = ("backlog","working","review","done")` — `cells/engineer/sessions.py:121`.
Deklariert als Daten in `LANE_FLOW` (`sessions.py:140-195`), jeder Knoten mit
`kind: fixed|policy` **und** dem `settings`-Key, der ihn steuert.

| Übergang | Verb | kind | gesteuert von |
|---|---|---|---|
| `backlog → working` | dispatch | policy | `policy.auto_dispatch_priority`, `capacity.wip_limit` |
| `working → review` | submit | **fixed** | — |
| `review → working` | bounce | **fixed** | — |
| `review → done` | accept | policy | `policy.auto_accept_green` |
| Gate-Knoten | — | **fixed** | `between: ["working","review"]` |

**Drei Korrekturen an der Stationsliste des Decrees** — die Karte darf nicht
lügen:

1. **Das Gate sitzt ZWISCHEN Arbeit und Abnahme**, nicht danach
   (`sessions.py:187-194`).
2. **„Abnahme" IST die Review-Lane.** Der Code sagt es wörtlich:
   `lanemachine.py:1162` — `lane = "done"  # Review == Abnahme`.
3. **„Deploy" ist keine Lane, sondern ein Schritt INNERHALB der Abnahme** —
   `_repo_hook(t,"deploy")` in `lanemachine.py:1119`, direkt nach
   `status="accepted"` (`:1116`). Als Station zeichnen: ja, der Owner muss sie
   sehen. Aber im Datenmodell ist sie ein Schritt, und die Karte muss das im
   Untertitel sagen.

### 2.4 Was das Gate wirklich tut

`ops/tools/run_gate.py` ist **LIGHT BY DECREE** (Header `:6-12`) — genau zwei
Prüfungen: `py_compile` über `daemon/ spine/ cells/`, und
`import daemon.swarm` + `import spine.http.server`. Kein Test-Suite-Lauf,
kein i18n-lint (per Decree entfernt, `:41-44`).

**Konsequenz für die „Dokumente"-Vorlage:** das Gate wird **nicht
abgeschaltet**. Es findet in einem Text-Repo nichts zu kompilieren und meldet
`"gate: nothing to run on this branch - PASS"` (`run_gate.py:68-70`). Die
Vorlage muss also gar nichts abschalten — sie muss die Station nur **ehrlich
als „läuft leer" beschriften**. Das ist der Unterschied zwischen einem
Gesetzesbruch und einer Anzeige.

### 2.5 Die Grenze fix/policy ist bereits maschinenlesbar

`HARNESS.md:392-397`: `sessions.flow()` und `loop_state.machine()` taggen
**jeden** Knoten mit `kind: "fixed"|"policy"`, und jeder Policy-Knoten nennt den
`settings`-Key, der ihn steuert. Fixed-Knoten tragen zusätzlich ein `source`
`"datei.py:zeile"`, **zur Laufzeit aus der Quelldatei gelesen**.

Und `routes_info.py:46-51` / `sessions.py:123-139` sagen den Grund: die Graphen
werden **abgeleitet, nie beschrieben**.

> **Das ist die Bauvorschrift für die U-Bahn-Karte.** Eine fest verdrahtete
> Stationsliste im Client wäre exakt die Duplikation, gegen die diese Kommentare
> geschrieben wurden — und ein Verstoß gegen das NO-MONKEY-PATCHES-Gesetz
> (`CLAUDE.md`). Die Karte rendert aus `/loop/map`, Punkt.

### 2.6 Es gibt keinen Repo-Scope — der eigentliche Blocker

Kein Repo-Datensatz. Keine `repos`-Tabelle (`spine/storage/db.py:60-68`:
`tracks, projects, processes, connector_state, events`). Kein
`register_repo`/`add_repo`. Ein Repo betritt das System **implizit als
absoluter Pfad auf einer Karte** (`dispatch.py:50`).

Drei vorhandene Muster für Repo-Bezug — alle sind Pfad-Schlüssel *im einen
globalen Blob*:

| Mechanismus | Form | Ort |
|---|---|---|
| `repo_hooks` | `{"<abs pfad>": {"preview":…,"deploy":…}}` | `lanemachine.py:615-617`, gelesen `:648` |
| `pm.repos` | Allowlist `[]` | `cells/pm/pm.py:38` |
| `gxp.lock` `repos` | `[abs pfad]` oder `null` | `spine/auth/gxp.py:182-188` |

`GET /gxp/state` baut die einzige De-facto-Repo-Liste — `known_repos` =
`pm.repos ∪ repo_hooks.keys() ∪ {default_repo}` (`routes_gxp.py:32-39`), **zur
Laufzeit abgeleitet, nie gespeichert.**

**Der Präzedenzfall, den der Owner schon entschieden hat** — `spine/auth/gxp.py:11-22`:

> `SCOPE IS PER REPO, NOT GLOBAL AND NOT PER CARD (owner call, and he was right)`
> … *„Scope has to follow the ARTEFACT, and in HelmDeck the artefact boundary is the repo."*

Dieselbe Begründung trägt die Vorlage. GxP hat dafür ein **eigenes Dokument
außerhalb von `settings.json`** gewählt — und genau das ist auch hier der
richtige Ort (§4.1).

---

## 3. Die Vorlagen

Eine Vorlage ist eine **Datei** in `ops/harness/templates/<id>.md` — YAML-
Frontmatter + Prosa, exakt wie `ops/harness/agents/*.md`, geladen mit
mtime-Reload und **Fallback auf den Built-in bei jedem Fehler**
(`spine/registry/harness.py`). Damit gilt für Vorlagen dieselbe Regel wie für
Briefs: *eine kaputte Datei kann nie eine Karte am Starten hindern.*

Der Charter sanktioniert das übrigens schon wörtlich — `spine/auth/charter.py:21`,
unter MAY BE BUILT:

> `TEMPLATES: views chosen from the reviewed catalog, driven by declared data.`

### 3.1 `software-dev`

| Was | Wert | Geltung heute | Status |
|---|---|---|---|
| Stationen | alle fünf aktiv | — | Anzeige |
| `repo_hooks.<repo>.deploy` | Build-/Deploy-Befehl | **pro Repo** | existiert |
| `policy.auto_accept_green` | `false` | global | existiert |
| `policy.auto_dispatch_modes` | `["do"]` | global | existiert |
| `capacity.wip_limit` | `3` | global | existiert |
| Kartenart | `new_track` (Worktree + Branch) | pro Karte | **neu als Repo-Default** |
| Cells | engineer, process, copilot | global (Ebene B) | existiert, global |
| Gate | **immer an** | fest | Gesetz |

### 3.2 `documents`

| Was | Wert | Geltung heute | Status |
|---|---|---|---|
| Stationen | Karte, Arbeit, Abnahme (kein Deploy) | — | Anzeige |
| `repo_hooks.<repo>.deploy` | `""` (leer ⇒ Schritt entfällt) | **pro Repo** | existiert |
| `policy.auto_accept_green` | `false` | global | existiert |
| `policy.auto_dispatch_modes` | `["do","prepare"]` | global | existiert |
| `capacity.wip_limit` | `5` | global | existiert |
| Kartenart | `new_direct_task` (kein Worktree) | pro Karte | **neu als Repo-Default** |
| Cells | process, copilot | global (Ebene B) | existiert, global |
| Gate | **an, läuft leer** (`PASS`) | fest | Gesetz |

**Ehrliche Bilanz:** von zwölf Vorbelegungen sind heute **zwei** wirklich
pro Repo (`repo_hooks`), **sechs** global, und **zwei** existieren nur pro
Karte. Ohne Repo-Scope ist die Vorlage ein Etikett ohne Wirkung.

---

## 4. Der Bauplan

### 4.1 Repo-Scope zuerst (Voraussetzung für alles andere)

Ein Repo-Dokument nach dem Vorbild von `gxp.lock` — **außerhalb** von
`settings.json`, weil `HARNESS.md:229-233` unmissverständlich ist:

> *„… the chat path whitelists **top-level keys only** — so any `policy.*`
> sub-key is reachable from chat once `policy` is listed. **If your knob must
> not be chat-editable, it does not belong under `policy`.**"*

Alles unter `policy` ist per Konstruktion chat-schreibbar. Der Repo-Datensatz
gehört also **nicht** dorthin, sonst kann ein Satz im Chat die Vorlage eines
fremden Repos umschreiben.

Vorschlag `daemon/repos.json`:

```jsonc
{
  "C:/pfad/zum/repo": {
    "template": "software-dev",
    "applied_at": "2026-08-29T…Z",
    "applied_by": "owner",
    "overrides": { "policy.auto_accept_green": true }
  }
}
```

- Gelesen über **eine** Zugriffsfunktion (`repos.for_path(p)`), gemischt als
  `Default → Vorlage → overrides`.
- Geschrieben über **einen** Mutator (`repos.apply_template` /
  `repos.set_override`), der auditiert — dasselbe Ein-Eigentümer-Muster wie
  `policy.swap`.
- **Vorsicht** (`events.py:152`, `:192-194`): `events.settings()` **überschreibt
  Top-Level-Keys, es merged nicht tief**, und `save_settings` merged nur eine
  Ebene. Deshalb eine eigene Datei statt eines verschachtelten Blocks im
  Settings-Blob.

### 4.2 Die U-Bahn-Karte: reine Anzeige, abgeleitet

**Nicht neu bauen.** `/loop/map` (`routes_info.py:42`) liefert bereits
`runtime.lanes`, den Gate-Knoten mit `between`, `kind` je Knoten, die
steuernden `settings`-Keys und `editable`. `surfaces/app/src/app/loopmap.tsx`
rendert daraus bereits eine Stationsreihe mit Gate-Puls — in **Flexbox mit
RN-Views**, keine SVG, keine Koordinaten (`loopmap.tsx:279-308`).

Zu tun bleibt:
- `/loop/map` nimmt einen optionalen `?repo=` und filtert die Knoten über die
  Vorlage — analog zum bestehenden `modes`-Filter in
  `loop_state.machine()` (`:725-737`), der genau dieses Muster schon fährt.
- Inaktive Station = gestrichelt + „nicht aktiv", **nicht** ausgeblendet: der
  Owner soll sehen, was es *gäbe*.
- Farben aus `theme/tokens.ts`: backlog `txtTertiary`, working `ai`, review
  `human`, done `ok`, Gate `accent2`. **Lücke:** `gating` fehlt in
  `statusTokens` (`tokens.ts:98-107`) und fällt auf Grau zurück — beim Bau
  mitnehmen, in `ops/tools/gen_tokens.py`, nicht in der Komponente.

### 4.3 Der Chat-Änderungsweg (erweitern, nicht erfinden)

`copilot_actions.py:102-130` kann heute schon alles Nötige. Zwei Ergänzungen:

1. Ein Verb `apply_template` (oder `configure {"template": …}`) mit `repo`-Bezug.
2. `ALLOWED_CONFIG` bekommt **nicht** einfach einen neuen Top-Level-Key; der
   Repo-Datensatz wird über den Mutator aus §4.1 geschrieben, mit eigener
   Rollenprüfung (`policy.chat_configure_roles` wiederverwenden).

**Vokabular-Vorschlag** (Satz → Wirkung):

| Owner sagt | Henry tut | Erlaubt? |
|---|---|---|
| „Repo Y soll wie ein Doku-Repo laufen" | `apply_template(Y, "documents")` | ja |
| „Kein automatischer Deploy mehr" | `repo_hooks.<Y>.deploy = ""` | ja |
| „Grüne Karten darfst du selbst abnehmen" | `policy.auto_accept_green = true` | ja (heute global!) |
| „Höchstens 2 Karten gleichzeitig" | `capacity.wip_limit = 2` | ja (heute global!) |
| „Schalt die Review aus" | **Ablehnen + Route** | nein — Review *ist* die Abnahme |
| „Lass das Gate weg" | **Ablehnen + Route** | nein — Harness, kein Policy-Key |
| „Mach mich zum Admin" | **Ablehnen** | nein — Auth, `permissions.set_role_caps` |

Die Ablehnung existiert schon als guter Text (`copilot_actions.py:122-126`):
Harness-Keys werden *mit Route* abgewiesen („sag ‚leg eine Karte dafür an'").
**Diese Zeile ist der Ton, den die ganze Vorlagen-Fläche treffen soll.**

### 4.4 Wo die Vorlage im UI auftaucht

- **Repo-Onboarding**: Vorlagen-Wahl als Schritt (Mockup §1).
- **Settings**: Tür „System" bzw. die Repo-Zeile zeigt die U-Bahn-Karte
  read-only + „Ändern? Sag es Henry."
- **Kein zweiter Edit-Ort.** Das ist bereits bindendes Nicht-Ziel der
  Settings-IA-Karte.

---

## 5. Verhältnis zur laufenden Settings-IA-Karte

`ops/docs/backlog/settings-ia-redesign/` ist **kein Duplikat, sondern die
Ebene darunter** — und teilweise schon gebaut:

| Karte | Status |
|---|---|
| 1 `settings-schema-v2` | **erledigt** |
| 2 `settings-hub-shell` | **erledigt** |
| 3 `cells-catalog` · 4 `autonomy-dial` · 5 `settings-search` · 6 `connect-wizards` | offen |

Das Muster ist identisch, nur eine Ebene höher: der **Autonomie-Dial** (Karte 4)
fasst mehrere Keys zu *einer* verständlichen Stufe zusammen — die **Repo-Vorlage**
tut dasselbe für einen ganzen Repo-Typ.

⚠ **Konflikt, der entschieden werden muss:** Dial *und* Vorlage schreiben beide
`policy.auto_accept_green` und `policy.auto_dispatch_*`. Ohne Vorrangregel
überschreiben sie sich gegenseitig. Siehe §8 Frage 2.

Bindendes Nicht-Ziel von dort, das hier weiter gilt:
> „Keine zweite Chat-UI, kein zweiter Edit-Ort für irgendeinen Key (Decree)."

Die U-Bahn-Karte als **reine Anzeige** erfüllt das exakt.

---

## 6. Empfehlung

1. **Repo-Scope zuerst bauen** (`daemon/repos.json` + ein Leser + ein Mutator,
   Muster `gxp.lock`). Ohne ihn ist jede Vorlage Kosmetik.
2. **Genau zwei Vorlagen** ausliefern (`software-dev`, `documents`). Ein dritter
   Typ ist erst sinnvoll, wenn die ersten beiden im Alltag getragen haben.
3. **Karte aus `/loop/map` ableiten**, `?repo=` ergänzen. Keine Stationsliste im
   Client.
4. **Chat-Weg erweitern, nicht neu bauen** — `configure` hat Rollen, Audit und
   den richtigen Ablehnungston schon.
5. **Ebene-B-Flags in Phase 2 nicht anfassen.** `worktreeIsolation` &
   Co. werden noch nicht gelesen (`ARCHITECTURE.md:160-162`); eine Vorlage, die
   sie setzt, verspricht Wirkung, die es nicht gibt. Entweder erst die
   Durchsetzung bauen — oder die Finger davon lassen. Ich empfehle: Finger weg.

**Vorgeschlagene Phase-2-Karten:** `repo-scope-record` → `repo-templates-catalog`
→ `loopmap-per-repo` → `chat-template-verb`. Reihenfolge zwingend: 1 vor allem
anderen.

---

## 7. Nicht-Ziele

- Kein frei editierbarer Graph-Editor (Owner-Entscheidung).
- Keine Änderung an Gate, Auth, Audit, Worktree-Isolation *als Gesetz*.
- Kein zweiter Edit-Ort, keine zweite Chat-UI.
- Keine Vorlage darf eine Station abschalten, die ein Gesetz ist. Sie darf sie
  nur **ehrlich beschriften** (Gate im Doku-Repo: „läuft leer").

---

## 8. Offene Fragen an den Owner

**1 — Repo-Scope: eigene Datei oder erst mal global?**
Empfehlung: eigene Datei `daemon/repos.json` (Muster `gxp.lock`), weil alles
unter `policy` per Konstruktion chat-schreibbar ist. Alternative: Vorlagen
vorerst nur global (ein Workspace = ein Repo-Typ) — deutlich billiger, aber
zwei Repos unterschiedlichen Typs sind dann nicht möglich.

**2 — Vorrang zwischen Autonomie-Dial und Repo-Vorlage.**
Beide schreiben dieselben Keys. Wer gewinnt? Vorschlag: Vorlage setzt den
Ausgangswert beim Onboarding, der Dial darf ihn danach pro Workspace
überschreiben, und die Karte zeigt „vom Standard abgewichen".

**3 — Darf eine Vorlage `capacity.wip_limit` überhaupt anfassen?**
Das ist eine Eigenschaft der *Maschine* (wie viel Last der PC verträgt), nicht
des Repo-Typs. Ich neige zu **nein** — raus aus der Vorlage.

**4 — Paseo-Quelle.**
`~/Downloads/_paseo_src` ist vom Worktree-Guard dieser Karte **blockiert**; ich
konnte die Quelle nicht wie beauftragt lesen. Das Paseo-Material hier stammt
aus dem bereits recherchierten Abschnitt der Settings-IA-Karte (Drei Scopes:
app-lokal / pro Host / **pro Projekt-Datei** — was §4.1 stützt) und ist damit
**zweiter Hand**. Soll eine Folgekarte ohne diesen Guard das gegenprüfen?
