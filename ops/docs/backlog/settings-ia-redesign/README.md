# Settings-IA-Redesign — Einstellungen neu aufbauen

Owner-Beschwerde (2026-08-26): "Zu viele Optionen, 3× gleiches Symbol, selbst ich
verstehe nicht, was dahinter ist." Die Gruppierung des Mehr-Tabs (2b77a55) war
Kosmetik; dieses Dokument ist der Grundriss für den echten Umbau.

## Befund (Inventur, vollständig in Agent-Recherche 2026-08-26)

1. **Drei getrennte Config-Stores, für den Nutzer unsichtbar vermischt:**
   `settings.json` (Business/Jira/Nightshift/Relay/PM/…), Policy-Plane
   (`policy_seed.json`: 6 Gesetzes-Toggles + 6 Cell-Flags, Screen "Module"),
   gerätelokale Zustand-Stores (Pairing, LAN, Voice, Analytics im Mehr-Tab).
2. **Duplikate:** `nightshift.*` ist in settings.tsx UND im Automatik-Hub
   editierbar (zwei Formulare, gleiche Keys); WIP-Limit existiert doppelt
   (`capacity.wip_limit` editierbar + `policies.wipLimit` read-only); PM-Loop
   und Nightshift überlappen konzeptionell (`/nightshift` ist bereits ein
   Alias auf `pm.status()`).
3. **Settings ohne UI:** `prices`, `currency`, `glance_token/_decide/_talk/_origin`,
   `worktree_seed`, `drivers`, `dashboard`, `policy.load_admission`, `web_url`
   + ~13 PM-Subkeys (`repos`, `window`, `replan_minutes`, `max_dispatch_per_day`,
   `monthly_eur`, `watch_*`, …).
4. **settings.tsx ist ein 650-Zeilen-Monolith** aus 10 ungeordneten Panels
   (Setup-once neben Häufig-genutzt), owner-only als ganzer Screen.
5. **Cells sind unerklärt:** Enable-Flags verstecken sich im Screen "Module"
   hinter Gesetzes-Toggles; nirgends steht, WAS eine Cell tut oder welche
   Einstellungen zu ihr gehören.

## Referenz-Muster (Recherche-Extrakt)

- **Home Assistant:** Settings-Root = ~6 benannte Türen in Nutzer-Sprache
  (Devices & Services / Automations / People / System); Seltenes/Gefährliches
  eine Ebene tiefer in "System". Integrationen = Karte pro Subsystem mit
  eigener Config-Seite + geführtem Hinzufügen-Wizard. → Blaupause für Cells.
- **Obsidian / VS Code:** Plugin-Liste = Toggle + Zahnrad, jede Extension-Seite
  aus ihrem Schema GENERIERT; Suche über alles + "Commonly Used" oben.
  → Blaupause für schema-getriebene Cell-Seiten (wir haben `config_schema` schon).
- **Cursor / Claude Code:** Autonomie = EIN gut lesbarer Modus-Dial
  (Safe → Auto), Detail-Regeln dahinter als Advanced-Schicht — nicht 50 Toggles.
- **Slack / Discord / Open WebUI:** harte Trennung persönlich/Gerät vs.
  Workspace/Admin; Admin-Fläche für Nicht-Admins schlicht unsichtbar.
- **Paseo (lokale Quelle, `_paseo_src`):** Settings als Zwei-Spalten-Navigator
  mit Sektions-TABELLE (`{id, labelKey, icon}` → Nav generiert); drei explizite
  Scopes (App-lokal / pro Host / pro Projekt-Datei); Autonomie-Modus ist ein
  Composer-Control pro Session, KEIN Setting; "General" bewusst dünn; leere
  Werte werden gelöscht statt persistiert (absent = default).
- **NN/g / Toptal:** progressive Disclosure (3–5 primäre Controls, Rest hinter
  "Erweitert"), Ordnung nach Änderungs-Häufigkeit, destruktives ans Ende.

## Zielbild

### A. Ein Settings-Hub mit 6 Türen (ersetzt settings.tsx-Monolith + Mehr-Wildwuchs)

Route `/settings` wird ein Navigator (Phone: Drill-down-Liste, Desktop/wide:
Zwei-Spalten wie Paseo). Türen, in Nutzer-Sprache, jede mit Untertitel:

1. **Allgemein** — Sprache, Aussehen (Backdrop), Benachrichtigungen/Vorlesen,
   Analytics. Scope-Mix aus Workspace + Gerät, klar gekennzeichnet. *Jede Rolle.*
2. **Agenten & Autonomie** — der Kern. Oben EIN Dial: „Wie selbstständig
   arbeiten die Agenten?" (Stufe 1 *Nur melden* / Stufe 2 *Fragen* / Stufe 3
   *Selbst handeln*) — mappt auf `pm.autonomy` + `policy.auto_accept_green` +
   `policy.auto_dispatch_*` als EIN Presets-Schalter. Darunter „Erweitert"
   (eingeklappt): die Einzel-Knobs, Nachtschicht-Zeitfenster, PM-Ziel & Budget
   (in %-Quota, Decree), WIP-Limit, Tarife. *Owner.*
3. **Zellen** — Katalog wie Obsidian-Plugins: pro Cell eine Karte mit
   Ein-Satz-Beschreibung („Engineer — baut Karten in isolierten Worktrees"),
   Enable-Toggle, Status, Zahnrad → generierte Detail-Seite aus dem um
   `cell`-Metadaten erweiterten `config_schema`. Die 6 Gesetzes-Toggles aus
   „Module" ziehen hierher um als read-mostly „Grundgesetze"-Block (Änderung
   → Henry-Eskalation, nicht Toggle-Flip). *Owner.*

   **Erweiterbarkeits-Anforderung (bindend für Phase 3):** die Zellen-Liste
   wird zur Laufzeit aus `spine/registry/cells.py::enabled()` + dem
   Schema-Index gerendert — KEINE hartcodierte Cell-Liste im Client (anders
   als heute `LINKS`/`GROUPS` in more.tsx). Eine neue Cell braucht NUR einen
   Schema-Eintrag (Name, `descKey`, ihre Knobs mit `door`/`level`) im Daemon;
   die Karte, das Icon-Slot, die Detail-Seite und die Suchindexierung
   entstehen automatisch aus dem generischen `SettingsPage`-Renderer (Punkt C).
   Kein `cells/<id>/ui/settings.tsx` pro Cell, kein manuelles Icon-Picking im
   Client. Akzeptanztest für Phase 3: eine Dummy-Cell mit 2 Knobs im Schema
   hinzufügen, OHNE Client-Codeänderung erscheint sie korrekt im Katalog.
4. **Verbindungen** — Capability-Inventar: Jira (als geführter
   Verbinden-Wizard statt 4 nackter Felder), URL-Import, Connectoren-Liste
   mit Status + Zeitplan, Glasses/Glance (die bisher UI-losen `glance_*`-Keys).
   *Owner.*
5. **Team & Geräte** — Nutzer (Rollen, Einladen, Tokens), Registrierung,
   Geräte-Registry, Telefon-Kopplung (Relay-URL + QR), gestrandete
   Geräte-Karten. *Owner.*
6. **System** — Nutzung/Quota (UsagePanel), Updates/Version, Preise-Tabelle,
   `worktree_seed`, `load_admission`, Loop-&-Harness-Schaubild (Link),
   Abmelden + Gefahrenzone. *Owner, unterste Tür.*

### B. Mehr-Tab schrumpft

Mehr = Verbindungsstatus-Zeile + **Protokolle** (Verlauf, Eskalationen,
Sitzungen, Aufnahmen — das sind Logs, keine Settings) + genau EIN Eintrag
„Einstellungen" (die 6 Türen) + Feedback. Gerätelokale Toggles ziehen in
Tür 1 (mit „Dieses Gerät"-Badge). Nicht-Owner sehen nur Tür 1 — Rest
unsichtbar statt 403.

### C. Mechanik: Schema first (kein zweiter Monolith)

- `spine/http/apimeta.py::_config_schema` wird die EINE Quelle für alle
  Workspace-Knobs, erweitert um Metadaten pro Knob:
  `{ door, cell?, level: basic|advanced, descKey, scope }`.
- Der Client bekommt EINEN generischen `SettingsPage`-Renderer (den
  automation.tsx-Control-Switch verallgemeinern): Tür-/Cell-Seiten sind
  Schema-Filter, keine handgebauten Panels. Neuer Knob = ein Daemon-Eintrag.
- Handgebaut bleiben nur: Autonomie-Dial, Wizards (Jira, Pairing, Einladen),
  Users/Devices-Listen, Harness-Brief-Editor.
- **Suche** über den Schema-Index (Label + descKey, beide Sprachen) als
  Suchfeld oben im Hub; dazu „Häufig benutzt"-Block (initial kuratiert:
  Autonomie-Dial, Nachtschicht an/aus, PM-Ziel, Sprache).
- Scope sichtbar machen: jede Zeile trägt ein stilles Badge „Gerät" /
  „Workspace"; die Policy-Plane-Gesetze sind visuell als Gesetze markiert.

### D. Aufräumarbeiten im selben Zug

- Nightshift-Duplikat auflösen: EIN Edit-Ort (Tür 2, Erweitert); der
  settings.tsx-Block entfällt. Prüfen, ob `nightshift.*` ganz in `pm.*`
  aufgeht (Alias existiert schon) — wenn ja, Migration + Debt-Eintrag.
- WIP-Limit: eine Quelle (`capacity.wip_limit`), Modules-Anzeige verweist.
- PM-Subkeys mit UI-Lücke (`max_dispatch_per_day`, `monthly_eur`, `repos`, …)
  ins Schema aufnehmen (level: advanced) statt neue Panels.
- settings.tsx, modules.tsx, automation.tsx lösen sich in den Hub auf;
  `/automation`-Route bleibt als Redirect (Deep-Links, Chat-Verweise).

## Phasen (je eine dispatchbare Karte)

| # | Karte | Inhalt | Akzeptanz |
|---|---|---|---|
| 1 | `settings-schema-v2` | Daemon: Schema-Metadaten (door/cell/level/descKey/scope), fehlende Knobs (PM-Subkeys, glance_*, load_admission) aufnehmen; Endpoint liefert vollständigen Index | Schema enthält jeden heute editierbaren Knob genau 1×; run_gate grün |
| 2 | `settings-hub-shell` | Hub-Navigator (6 Türen, Phone-Drilldown + Desktop-Zweispalter), generischer SettingsPage-Renderer, Türen 1/2/6 live; alte Panels ziehen um | Kein Knob verliert seine Editierbarkeit; settings.tsx gelöscht; Screenshots beider Layouts gejudged |
| 3 | `cells-catalog` | Tür 3: Cell-Karten mit Beschreibung/Toggle/Status/Detail-Seite; Gesetze-Block zieht aus modules.tsx um | Jede Cell erklärt sich in einem Satz; modules.tsx gelöscht; Cell-Disable wirkt weiter auf Nav |
| 4 | `autonomy-dial` | Presets-Dial über pm.autonomy + auto_accept + auto_dispatch; Erweitert-Schicht; Nightshift-Dedup (+ evtl. pm-Migration mit Debt) | Dial-Stufe ↔ Einzel-Knobs konsistent in beide Richtungen; nightshift nur noch 1 Edit-Ort |
| 5 | `settings-search` | Suchfeld + „Häufig benutzt" im Hub, Index aus Schema | Jeder Knob per Suche in ≤2 Taps erreichbar |
| 6 | `connect-wizards` | Jira-Wizard, Pairing-Flow, Einladen-Flow als geführte Schritte in Tür 4/5 | Jira ohne Doku verbindbar; Wizards brechen sauber ab |

Reihenfolge fix: 1 → 2 → 3, danach 4–6 parallelisierbar. Jede Karte:
tsc + run_gate + Playwright-Screenshots (Phone 390×844 + Desktop) gejudged.

## Plausibilitätsprüfung gegen den Code (2026-08-26, vor Dispatch eingearbeitet)

Verifiziert und TRAGFÄHIG:
- `pm.autonomy` kennt exakt notify/ask/act (`cells/pm/pm.py`) — das
  Dial-Mapping in Tür 2 erfindet keine neuen Zustände.
- `_config_schema` ist bereits als importierbares Contract-Modul gebaut
  (`spine/http/apimeta.py`), mit Contract-Test
  `ops/tests/test_harness_layer.py` (Control-Union + Zwei-Sprachen-Pflicht).
  Phase 1 MUSS diesen Test um die neuen Metadaten-Felder erweitern
  (door/cell/level/descKey/scope je Pflicht), sonst rendern neue Knobs
  wieder still als nichts.
- `GET /cells` liefert schon heute ein registry-getriebenes Manifest
  (`spine/registry/cells.py::manifest()`) — der Katalog (Tür 3) setzt darauf
  auf statt auf eine Client-Liste. Der Dummy-Cell-Akzeptanztest ist damit
  real machbar; `enabled()` defaultet unbekannte Keys auf true, `/policy/swap`
  toggelt generisch. Phase 1 ergänzt `Cell` um ein nutzerlesbares `descKey`
  (das vorhandene `role`-Feld ist technisch, keine Nutzer-Erklärung).

KORREKTUREN am Zielbild:
1. **Rollen-Widerspruch Tür 1:** „Allgemein — jede Rolle" kollidiert mit der
   Realität, dass `POST /settings` owner-only ist (server.py 403). Sprache/
   Aussehen sind für Nicht-Owner heute schlicht nicht schreibbar. Lösung in
   Phase 2 wählen und umsetzen: entweder (a) gerätelokaler Sprach-Override
   (Zustand-Store, wie Voice/Analytics) mit Workspace-Default vom Owner, oder
   (b) neues schmales `POST /me/prefs` (jede Rolle, nur whitelisted
   Personal-Keys). NICHT `/settings` für Nicht-Owner öffnen (Auth-Gesetz).
2. **Plugin-Kernel-Nav (Debt `plugin-kernel-dual-nav`, offen):** Der Hub in
   Phase 2 registriert sich im Kernel-Surface-Registry
   (`surfaces/app/src/plugins/surfaces/tabs.ts`) und entfernt dort die
   Einträge automation/settings/modules; die 1:1-Fallback-Tabellen in
   `(tabs)/_layout.tsx` im SELBEN Commit nachziehen. Der Umbau darf das
   Dual-Nav-Debt nicht vertiefen (keine dritte Navigationsquelle); wenn er
   es nicht tilgen kann, Debt-Eintrag fortschreiben.
3. **Nightshift-Merge ist Daemon-Arbeit, nicht UI-Dedup:** Neben pm.py liest
   auch `cells/engineer/dispatch.py` (und routes_control/routes_settings)
   `settings.nightshift` direkt. Phase 4 behandelt die Zusammenlegung als
   echte Migration mit allen Lesern — oder lässt die Keys stehen und
   dedupliziert NUR die Edit-Oberfläche (eine Form, ein Ort). Letzteres ist
   der kleinere, erlaubte erste Schritt.
4. **Klarstellung Akzeptanztest Phase 3:** „ohne Client-Codeänderung" heißt:
   Client-Bundle unverändert; die Dummy-Cell entsteht als Eintrag in
   `CELLS` + Schema — dass dafür der Daemon neu startet, ist erwartbar.

## Nicht-Ziele

- Keine Änderung der Gesetze selbst (gate-before-review etc. bleiben fix).
- Kein Umbau der Daemon-Settings-Persistenz (deep-merge bleibt).
- Keine zweite Chat-UI, kein zweiter Edit-Ort für irgendeinen Key (Decree).
