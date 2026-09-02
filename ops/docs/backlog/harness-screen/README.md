# Karte: Die Harness-Seite (Phase 3 von harness-config-ui)

**Status:** offen, dispatchbar. Owner-Entscheidung 2026-09-02: als EIGENE Karte,
nicht mehr im Phase-2-Bau.

**Vorgänger:** `ops/docs/backlog/harness-config-ui/README.md` ist das bindende
Design-Dokument — **§5 (Der Bildschirm), §5.5 (Henry angedockt), §4.3 (Brief
ansehen), §6 (Wo die bestehenden Werte landen), §7 (Verständlichkeit)** sind
der Auftrag dieser Karte. Diese Datei ergänzt nur, was der Bau der Phasen 1, 2
und 4 an Fakten geliefert hat — sie ersetzt das Dokument nicht.

**Fundament steht** (Commits 5570846, c255f93, 7e5f8c6 auf diesem Branch):

| liegt bereit | wo |
|---|---|
| Auflösungskette + Projekt-Overlay | `spine/storage/projectconfig.py` — `chain()`, `resolve()`, `resolve_all()`, getrackter `write()`/`revert()` |
| Henrys Regeln als Daten | `spine/registry/behavior.py` — `BEHAVIOR_RULES`, `BLOCKS`, `describe(project)` |
| Regeln fürs UI aufbereitet | `behavior.describe()` liefert pro Regel: `block, wire, kind, control, options, scope, binds, labelKey, descKey, why, source, reads` + pro Oberfläche `{surface, path, value, default, layer, inherited}` |
| Gerenderter Brief (für „Brief ansehen") | `harness.brief(agent, project=...)`; Slots über `behavior.slots_in()` |
| Henry-Spur + Knopf-Badges | `repo_pipeline.tsx` (Phase 4, fertig) |

---

## 1. Was diese Karte baut

`/loopmap` wird die **Harness-Seite**. Es gibt danach nicht Loop-Map *und*
Harness-Seite (Nicht-Ziel „kein zweiter Bildschirm").

1. **Linke Themen-Navigation** — Stationen in Fluss-Reihenfolge, dann Henrys
   fünf Blöcke (`behavior.BLOCKS`), dann Grundgesetze, unten Erweitert.
   Reihenfolge kommt vom Server, nicht aus einer Client-Liste.
2. **Stationsfilter über dem vorhandenen Schema** — Station antippen filtert
   die Zeilen rechts. `SchemaDoor` wird wiederverwendet, nicht nachgebaut.
3. **Henrys Regeln als editierbare Zeilen** — eine Zeile pro Regel, mit
   aufklappbarem „pro Oberfläche"-Detail (das ist der Punkt: der Nutzer sieht
   EINE Regel „Antwortlänge" und darunter, dass die Uhr knapper ist als der
   Chat, statt vier unverbundener Zahlen an vier Orten).
4. **Schloss-Zeilen** — `kind: "fixed"` rendert Schloss + `why` + Quelle. Nie
   ein toter Schalter.
5. **Vererbungs-Badges** — `Geerbt vom Workspace` / `Für dieses Projekt
   gesetzt` + Zurücksetzen-Link, aus `layer`/`inherited`.
6. **„Brief ansehen"** (§4.3) — gerenderte Prosa read-only, Slots als Chips,
   Tippen springt zur Zeile. Formular ↔ Brief als Toggle.
7. **Henry angedockt** (§5.5) — Panel/Bottom-Sheet um den **bestehenden**
   `chat.tsx`. Neu ist NUR Rahmen + Launcher + Kontext-Chip; der Chip landet
   in `card_composer.tsx`.
8. **Der Umzug** (§6) — Stations-Knöpfe ziehen per Metadatum aus Tür
   Automation/System auf die Stationsseite.

## 2. Gemessene Fallen (aus dem Phase-2-Bau, nicht vermutet)

- **Der Umzug ist all-or-nothing.** `placeRows` (`settings_schema.ts:122`)
  **verwirft** eine Zeile ohne `door`, statt sie in eine Default-Tür zu legen.
  Ein Knopf, dem man `door` wegnimmt, bevor die Stationsseite ihn rendert, hat
  ÜBERHAUPT KEINE Oberfläche mehr. Umzug und Seite müssen im selben Commit
  landen — das ist der Grund, warum diese Karte nicht in Scheiben geht.
- **Der generische Renderer kennt keinen gesperrten Zustand.**
  `settings_schema_page.tsx:72-134` hat sechs Control-Zweige und keinen
  read-only-Fall; ein unbekanntes `control` rendert **NICHTS**, still. Eine
  Schloss-Zeile braucht also: neuer Zweig im `Control`, neues Feld in
  `ConfigItem` (`settings_schema.ts:33`), Spiegel in `apimeta.py` — und
  `test_harness_layer.py:551-569` parst BEIDE Seiten und hält sie gleich.
- **`SCOPES` muss um `project` wachsen** — `apimeta.py:69` *und*
  `settings_schema.ts:25` *und* i18n-Key `hub.scope.project`.
  `test_settings_hub_vocabularies` hält die Hälften gleich und wird rot, wenn
  eine fehlt. `writeTargetFor()` (`settings_schema.ts:71`) braucht einen
  dritten Zweig: Projekt-Zeilen schreiben weder nach `/settings` noch nach
  `/me/config`, sondern auf den neuen Projekt-Pfad.
- **Jede Zeile braucht `descKey` in ZWEI Sprachen**, sonst besteht sie den
  Vertragstest nicht (`test_harness_layer.py:648`). Für ~24 Regeln × Label +
  Beschreibung sind das ~50 neue i18n-Einträge.
- **Der warme Henry-Prozess.** Workspace-Regeln rendern in den Basis-Brief
  (Änderung ⇒ `behavior.fingerprint()` ändert sich ⇒ `_persist_drop`),
  projektabhängige reisen als Turn-Overlay über `extra_system`
  (`copilot.py:1505`). `behavior.fingerprint(project)` liegt bereit; **die
  Verdrahtung an `_persist_get` fehlt noch** und gehört in diese Karte.
- **`done` ist keine gezeichnete Station.** `/loop/map` liefert
  `stations = [backlog, working, gate, review, deploy]`; `done` existiert als
  Lane, wird aber nicht gezeichnet. Eine Regel, die nur auf `done` bindet,
  erscheint nirgends.
- **Node-Modules im Worktree.** Für `tsc` und Expo braucht der Worktree echte
  `node_modules`; ein Junction auf einen anderen Checkout lässt Metro in
  DESSEN `src/app` wurzeln und die App rendert „Welcome to Expo". Kopieren
  (robocopy, ~40 s, 1,4 GB) funktioniert — danach wieder löschen.
- **DOM-Zusicherungen sehen keine abgeschnittenen Texte.** `numberOfLines`
  schneidet per CSS, `inner_text` liefert trotzdem das ganze Wort. Für die
  neuen Zeilen `scrollWidth` gegen `clientWidth` prüfen — Muster steht in
  `ops/tests/e2e_pipeline_track.py`.

## 3. Abnahme (aus dem Design-Dokument §8, Zeile 3)

- Kein Knopf verliert seine Editierbarkeit.
- Kein Knopf ist an zwei Orten editierbar — die alte Tür-Zeile verschwindet im
  selben Commit.
- **Der Rundlauf in beide Richtungen:** eine per Chat gesetzte Änderung
  erscheint live in der Zeile, eine per Zeile gesetzte steht in Henrys
  Verlauf/Audit — beides derselbe `swap()`-Eintrag.
- Jedes Element hat seine §7.0-Herkunftszeile.
- Screenshots Phone + Desktop **gejudged**, nicht nur gerendert.

## 4. Erledigt, bevor diese Karte startet

Die `configure`-Allowlist ist geklärt (Owner-Entscheidung 2026-09-02, Schuld
`configure-allowlist-not-derived` auf `paid`): `jira` steht jetzt im Brief, mit
einer ausdrücklichen Warnung zum Token. Brief und erzwungene Menge nennen
dieselben Schlüssel, und `behavior.allowlist_drift()` hält sie ab jetzt gleich.

**Folge für §5.5:** die Anforderung „die Allowlist wird abgeleitet, nicht
doppelt gepflegt" ist damit als *Gleichheitsprüfung* erfüllt, nicht als
Generierung. Wer den Absatz in dieser Karte doch noch aus dem Schema rendern
will, muss wissen, was dabei verloren geht: die Prosa trägt pro Schlüssel eine
Erklärung („green gate auto-accepts (autonomy) vs human accepts (control)"),
die das Schema nicht hat. Der Vertragstest verhindert das Auseinanderlaufen
bereits — Generieren wäre also Kür, nicht Pflicht.
