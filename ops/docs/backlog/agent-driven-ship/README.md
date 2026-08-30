# Ship/Build agentisch — Henry entscheidet, das Skript führt aus

**Owner-Auftrag (2026-08-30), in mehreren Präzisierungen:** Ship/Build soll
agent-gesteuert laufen statt skriptgesteuert (Vorbild Paseo). Präzisiert:

1. **Henry entscheidet** — *kein* separater neuer `ship-advisor`-Agent. Henry,
   der Board-Copilot, nutzt seine **bestehenden gebundenen Verben**.
2. Henry muss **auf Board-Ebene** wissen, welche Karten/Builds ship-bereit sind,
   und koordinieren, ohne dass der Owner nachfragt. Abgrenzung zur bestehenden
   **PM-Koordinator-Rolle** (`cells/pm/`) klären — es darf nicht zwei
   konkurrierende Koordinatoren geben.
3. **Sicherheitsgrenzen** — freie Shell oder nur vordefinierte Skills/Tools?
4. Wie greift die **Android-Build-Mutex** (`ops/deploy/build_lock.sh`, `6e60712`)
   weiter?
5. **Fehlerverhalten** — was macht der Agent bei rotem Build anders als heute?
6. **Übersicht über ALLE anderen Gates** (iOS/EAS, `run_gate.py`, macOS/Desktop-
   Deploy-Hooks): Mechanismus, Schwachstelle, Empfehlung.

Reines Design-Dokument. Kein Code, keine Skript-Änderung.

> **Zur Vorgeschichte, weil die Karte als „zerstört" nachgereicht wurde:** die
> Arbeit der Vorgänger-Karte ist **nicht verloren**. Commit `143c9f4` (dieses
> Dokument, 417 Zeilen) und `ee6a8f1` (`ship_facts.py`, `ship-advisor.md`,
> `ship.sh`-Naht) liegen beide in der Historie. Dieses Dokument ist deshalb
> **keine Neuschrift bei null**, sondern die Überarbeitung auf den vollen Scope:
> die am Quelltext verifizierten Befunde zu Mutex, Fehlerverhalten und
> Gate-Tabelle bleiben erhalten, die Abschnitte zu *wer entscheidet* und *wie
> abgesichert* werden durch Präzisierung (1) umgestoßen und neu geschrieben.
> §3 und §4 sind vollständig neu. Ein zweites, konkurrierendes PRD zum selben
> Thema wäre genau der Fehler, den Präzisierung (2) verbieten will.

---

## 0. Ausgangslage — was gebaut ist, und was Präzisierung (1) davon umwirft

Commit `ee6a8f1` hat den **Entscheidungs**teil bereits invertiert:

| Baustein | Datei | Zustand |
|---|---|---|
| Beweislage ohne Urteil | `ops/tools/ship_facts.py` | **lebt.** 11 Änderungsklassen, 3 Versionsnummern, 8 Ressourcen |
| Skript als Executor | `ops/deploy/ship.sh:186-229` | **lebt.** `SHIP_KIND=none\|ota\|native`, `SHIP_DRY_RUN=1` |
| Der entscheidende Brief | `ops/harness/agents/ship-advisor.md` | lebt als Datei — **wird durch Präzisierung (1) eingezogen** |
| Der Aufruf | — | **existiert nicht.** Nichts setzt je `SHIP_KIND` |

Die Naht ist auf der Executor-Seite vollständig und auf der Aufrufer-Seite leer.
`lanemachine.py:673` reicht `dict(os.environ)` unverändert weiter; jeder
automatische Ship läuft im Hash-Fallback. Registriert als
`ship-decision-not-wired` (`debt.py:3565`, **open**).

**`ship-advisor` ist heute totes Gewicht — das stützt Präzisierung (1).** Eine
Volltextsuche über das Repo findet **genau zwei** Referenzen: einen Kommentar in
`ship.sh:178` und den Schuldeintrag `debt.py:3572`. Er steht in keiner der drei
Registraturen (`harness.SURFACES:396`), ist also nicht über `/harness` editierbar,
und keine Zeile Code lädt ihn je. Der Brief zu löschen kostet nichts.

---

## 1. Die Paseo-Korrektur — Paseo hat seine Skripte NICHT gelöscht

Der ursprüngliche Auftrag lautete „kein Skript mehr". Die Quelle (`_paseo_src`,
gelesen) sagt etwas Genaueres. Paseos Release-Skills sind **13 Zeilen** und reine
**Router** auf `docs/release.md` (516 Zeilen); die vierstufigen npm-Ketten
(`package.json:90-114`) bleiben, und `push-current-release-tag.mjs:78-99`
**wirft** bei Tag≠HEAD, statt zu fragen.

Verschoben hat Paseo drei andere Dinge:

| Ebene | Eigentümer bei Paseo | Beleg |
|---|---|---|
| **Urteil** (patch/minor, blockiert ein Fund?) | Agent | `docs/release.md:46-56` — Rubrik in Prosa |
| **Harte Invarianten** | Skript, das `throw`t | `push-current-release-tag.mjs:78-99` |
| **Autorisierung** | Mensch | `docs/release.md:30` — „intent to start the flow, **not blanket authorization to publish**" |
| **Wechselseitiger Ausschluss** | GitHub-Actions `concurrency` | `desktop-release.yml:46-48` — **kein agentenseitiges Lock** |
| **Nachlauf** | Agent, verpflichtend | `docs/release.md:269-285` — `create_heartbeat` |

Und eine Grenze: `docs/release.md:56` — „Agents never select a major version
autonomously"; `:303` — „**NEVER bump the version to fix a build problem.**"

**Folgerung:** Was HelmDeck fehlt, ist nicht die Abschaffung von `build_apk.sh` —
es ist die **Playbook-Ebene**, die **Autorisierungsgrenze** und der **Nachlauf**.
Playbook (`DEPLOY.md`) und Autorisierung (Accept) existieren bereits in anderer
Form. Der Nachlauf fehlt vollständig.

---

## 2. Zwei Defekte, die nicht vermischt werden dürfen

**Defekt A — das Skript reagiert nicht auf Probleme.** `build_apk.sh` hat ~21
Stufen und **15+ fatale Ausstiege, null Retry, null Cleanup**. Schlimmer als das
Scheitern ist das Gegenteil: **zwei bewusst nicht-fatale Endstücke** — der
Emulator-Smoke (`build_apk.sh:263`) und `push_relay.sh` (`:270`) — plus die
Desktop-Hälfte von `push_update.sh:135-138`. **Ein grüner Deploy-Hook beweist
nicht, dass das APK je ein Telefon erreicht hat.**

**Defekt B — Kollision.** Betrifft nur Pfade, die eine physische Ressource
teilen: Android (seit `6e60712` geschlossen, §6) und die Desktop-Builds (offen).
Für iOS und die Website existiert er nicht (remote bzw. zustandslos).

**Ein Agent behebt A. Ein Agent behebt B nicht** — dafür braucht es ein Lock.
Diese Trennung ist die Achse der Tabelle in §8.

---

## 3. Präzisierung (1): Henry entscheidet — der Advisor wird eingezogen

### 3.1 Henry hat die Verben bereits — ihm fehlt die Beweislage

Der entscheidende Befund: **Henry braucht kein neues Verb, um zu shippen.** Sein
Broker (`cells/copilot/henry_broker.py:399`) hat sechs gebundene Verben —
`did | move | rerun_deploy | steer | notify_owner | ignore` — und zwei davon
lösen bereits echte Ships aus:

| Verb | Code | Was es auslöst |
|---|---|---|
| `move` → `done` | `henry_broker.py:490-524` | `sessions.move_lane(..., actor="henry")` = Gate + Merge + **Deploy-Hook**. Der Prompt sagt es wörtlich (`:394-396`): „done (nimmt ab, merged, deployed)" |
| `rerun_deploy` | `henry_broker.py:531-577` | `_repo_hook(t, "deploy")` erneut — **synchron und verifiziert** (`:569-577`), mit Vorabprüfung, dass der Hook überhaupt konfiguriert ist (`:553-558`) |

`move` ist dabei **verifiziert statt optimistisch**: `:518` liest die Lane nach
dem Aufruf zurück, weil `move_lane` bei Bounce/Konflikt früh zurückkehrt und
Erfolg und Scheitern sonst identisch aussahen (`:500-512`). `rerun_deploy` läuft
seit 2026-08-28 synchron, weil ein Fire-and-Forget die Eskalation schloss, bevor
der Build fertig war, und ein **zweiter** roter Build nirgends mehr hin konnte.

Das ist genau die Rollenteilung, die das alte PRD als „neu" vorschlug — sie ist
**gebaut und gehärtet**. Was fehlt, sind zwei Nähte:

1. **Beweislage.** Henrys Broker-Prompt (`henry_broker.py:386-393`) enthält
   Eskalation, Karten-Actionlog, Audit-Auszug und `_snapshot()` — aber **kein
   `ship_facts`**. Er sieht, *dass* ein Build läuft, nie *was* geshippt werden
   müsste.
2. **Kanal.** `_repo_hook` reicht `dict(os.environ)` durch (`lanemachine.py:673`).
   Es gibt keinen Weg, `SHIP_KIND` von einem Urteil zum Executor zu bringen.

### 3.2 Wohin der Brief-Inhalt wandert — und die Falle dabei

**Das ist der wichtigste Befund dieses Dokuments, und er ist eine Warnung.**

`ship-advisor.md` ist eine **Policy-als-Daten-Datei**: Frontmatter, Schema,
`harness.brief()`-ladbar, vom Owner ohne Code-Änderung umformulierbar. Henrys
autonome Hälfte hat **keine solche Datei**. `DEFAULT_POLICY`
(`henry_broker.py:47-69`) ist ein **Python-String-Literal**.

Das widerspricht dem eigenen Prinzip der Karte, die den Broker gebaut hat
(`ops/docs/backlog/henry-exception-broker/README.md:57-61`: „Henry's policy lives
in his BRIEF (data, editable)… Changing behaviour = editing prose, not shipping
Python"), und der Modulkopf behauptet es sogar (`henry_broker.py:16-17`: „Policy
is DATA"). Der einzige Datenpfad ist der Settings-Key `henry_policy`
(`:382`) — ein **Ganz-oder-gar-nicht-Override** ohne Default-Wert und ohne
UI-Fläche.

> **Konsequenz: „Ship-Urteil in Henry falten" verschiebt Policy naiv umgesetzt
> AUS den Daten IN Python.** Das ist eine Regression gegen das Harness-Gesetz,
> nicht bloß eine Umbenennung. Die Voraussetzung für Präzisierung (1) ist, dem
> Broker **zuerst eine echte Brief-Datei zu geben** — dann ist das Einziehen des
> Advisors ein Umzug von Prosa in Prosa und kostet nichts.

Empfohlene Form: `ops/harness/agents/board-broker.md` (oder ein zweiter,
klar markierter Abschnitt in `board-copilot.md`), registriert wie die anderen
Briefs, mit `DEFAULT_POLICY` als Inhalt plus den drei Ship-Regeln aus
`ship-advisor.md`, die ein Hash nicht ausdrücken kann:

- *Im Zweifel `native`* — die Fehlerkosten sind asymmetrisch (20 Minuten vs. eine
  stillschweigend gestrandete native Änderung; der livemic-Beinaheunfall vom
  23.08.).
- *Niemals die Version bumpen, um einen Build zu reparieren* (Paseo
  `release.md:303`; HelmDeck ist hier verwundbar, weil ein nativer Ship mit einem
  Bump **beginnt**).
- *Widersprüche melden statt mitteln* — wenn `app.json`, APK und Relay nicht
  übereinstimmen, ist **das** die Schlagzeile.

### 3.3 Wo das Urteil läuft

Der Broker ist der natürliche Ort, und zwar aus einem Grund, der bereits im Code
steht: `settings.repo_hooks[repo]["deploy"]` ist **schon heute Policy-Daten**,
kein Code (`lanemachine.py:645-648`). `rerun_deploy` liest genau diesen Eintrag
und führt ihn aus. `SHIP_KIND` muss also nur **zur Ereigniszeit** in die
Umgebung dieses einen Aufrufs — nie in eine Datei, denn eine Entscheidungsdatei
wäre exakt das *stored flag*, das `ee6a8f1` entfernt hat.

`_repo_hook` ist dabei der **einzige Flaschenhals aller Deploy-Pfade** —
`lanemachine.py:1119`, `sessions.py:978/1115/1162`, `dispatch.py:881`,
`henry_broker.py:569`. Eine Naht dort erreicht alle sechs.

**Nicht im Scope:** freie `gradlew`-Aufrufe durch Henry. Das ist der Bypass, den
`android-build-lock-advisory` (`debt.py:3604`, **open**) führt — ein ungesperrter
Build **tötet** einen laufenden, weil `build_apk.sh` mit `--stop` beginnt.

---

## 4. Präzisierung (2): Board-Ebene und die PM-Abgrenzung

### 4.1 Die Abgrenzung existiert bereits — sie steht nur in keinem Dokument

**Es gibt kein Zwei-Koordinatoren-Problem beim Shippen, und das ist beweisbar.**
Der PM kann strukturell nicht shippen:

| Fähigkeit | PM (`cells/pm/`) | Henry |
|---|---|---|
| Karte → `done` (Accept + Merge + **Deploy**) | **nie** — `pm_resolve.py:325-326`: „accept/merge stay gated to you - **the law**" | `henry_broker.py:490-524` |
| `rerun_deploy` | existiert nicht | `henry_broker.py:531-577` |
| Deploy-/Build-/Lock-Zustand sichtbar | **nein** (s. u.) | `henry_broker.py:200-203` |
| Verben überhaupt | **keine** — die Rolle gibt nur JSON aus (`pm.md:111,141`) | 6 (Broker) + 24 (Chat) |

Der PM erreicht `backlog→working` (`pm.py:1185`) und `→review`
(`pm_resolve.py:331`) — die Gate-Kante. Die Accept-Kante ist ihm per Gesetz
verwehrt. Eine Volltextsuche über `cells/pm/` nach `deploy|ship|apk|ota` liefert
**zwei** Treffer, beide reine *Zielstring*-Schlüsselwortsuche
(`pm.py:741`, `pm_triangle.py:156`) — **kein einziger Zustandswert**.

Die kanonische Formel steht bereits im Code, zweimal wortgleich —
`pm_comm.py:129-130` und `copilot.py:684-686`:

> **„the PM detects and asks, Henry acts"**

Der PM reicht deshalb aktiv an Henry weiter: fünf explizite Übergaben
(`pm.py:776` quota-pacing, `:855` plan-gate-red, `:939` triangle-tilt,
`pm_watchdog.py:193` context-bloat, `pm_comm.py:167` owner-ask-deferred), mit
Dublettenschutz (`pm_comm.py:99-103`). Die Begründung steht in
`pm_comm.py:80-81`: „Henry is the exception broker WITH HANDS… That is what every
one of these notices was already ASKING FOR in prose; **it was just asking the
wrong person**."

**Der eigentliche Defekt ist das Spiegelbild.** Nicht zwei Koordinatoren,
sondern: der PM plant gegen Ziele wie „in den Play Store deployen"
(wörtlicher Zielstring in `ops/tests/test_notice_routing.py:129`), gatet den Plan
auf Budget/Timeline/Scope — und **kann nicht sehen, ob überhaupt ein Build
läuft**. `copilot._snapshot()` (die Board-Sicht des PM, `pm.py:365`) enthält
keine Lock-, Build- oder Deploy-Zeile.

**Empfehlung:** Die Abgrenzung nicht neu erfinden, sondern **aufschreiben** — sie
existiert heute in genau einem Python-Docstring und in keinem Design-Dokument
(geprüft: `ARCHITECTURE.md:74` führt beide Cells ohne Rollenabgrenzung; die
Henry-Karte konflatiert sie sogar, `henry-exception-broker/README.md:16`). Ein
Satz in `ARCHITECTURE.md` genügt: *Der PM erkennt und fragt; Henry handelt.
Shippen ist eine Handlung.*

### 4.2 Was Henry auf Board-Ebene fehlt — vier benannte Lücken

Henrys Broker-Snapshot (`henry_broker.py:184-204`) ist bereits gut: jede
nicht-archivierte Karte mit Lane/Status/`fast_track`/`direct`/`turn_active`, dazu
`ship.lock`, `android-build.lock` **mit Halter-Label**, Box-Last und
Build-Prozesse — alles live abgeleitet, nie ein gespeichertes Flag. Vier
konkrete, am Quelltext verifizierte Lücken stehen zwischen dem und
„Henry koordiniert Ships":

**(a) Geshippte Karten sind unsichtbar.** `henry_broker.py:192-193` filtert
`lane == "done"` **heraus**. Henry sieht nie, was gerade geliefert wurde — genau
die Information, die Koordination („diese drei Karten hängen an Build 76")
braucht.

**(b) Der Snapshot amputiert sich bei vollem Board.** `henry_broker.py:204`:
```python
return "\n".join(lines[:40])
```
Die Kartenzeilen werden **zuerst** angehängt, die vier Maschinenzeilen
(`ship.lock`, `android-build.lock`, Box-Last, Build-Prozesse) **zuletzt**. Ab ~37
aktiven Karten fallen sie still weg — Henry verliert die Kollisionswahrnehmung
**genau dann, wenn das Board am vollsten ist**. Nicht im Code vermerkt.

**(c) Das Lock-Label nennt nie eine Karte.** Alle drei Gradle-Eingänge
beschriften den Lock mit `${HELMDECK_CARD:-manuell/kein Karten-Kontext}`
(`build_apk.sh:28`, `build_wear_apk.sh:40`, `release.sh:75`). **Nichts im Daemon
setzt diese Variable je** — verifiziert, die Volltextsuche findet ausschließlich
diese drei Konsumenten. `_repo_hook` reicht `dict(os.environ)` unverändert durch
(`lanemachine.py:673`), während `_gate` sehr wohl `HELMDECK_REPO` injiziert
(`:230`). Henrys `android-build.lock`-Zeile liest also **immer**
„manuell/kein Karten-Kontext". Das ist eine Ein-Zeilen-Lücke mit hohem Ertrag:
dieselbe Injektionsstelle, die `SHIP_KIND` braucht (§3.3), liefert auch das Label.

**(d) Ship-Bereitschaft wird nirgends berechnet.** Es gibt **kein**
`events.emit("ship"|"deploy"|"build")` im ganzen Repo, kein `shipped_in`-Feld,
keine Zuordnung Karte→Build. Der Ship-Ausgang ist ein flüchtiges
`t["deploy_hook"] = {"ok", "tail"}` (`lanemachine.py:680`), das beim **nächsten
Steer gelöscht** wird (`sessions.py:837-840`). Ein OTA-Ship hinterlässt
überhaupt nichts — `ship_facts.py:100-104` sagt es selbst: „An OTA ship leaves
NOTHING - no marker, no commit."

Ableitbar wäre Ship-Bereitschaft aus `lane=="review" && status=="submitted" &&
merge_kind ∈ (mergeable, already_merged, redundant_uncommitted)`
(`lanemachine.py:1030-1035`) — **nichts berechnet oder zeigt das heute.**

### 4.3 Die unbequeme Nebenwirkung: die Naht entfernt die einzige Bündelung

Heute gilt strikt **ein Accept = ein Ship**; eine Bündelung mehrerer Karten in
einen Build existiert nicht (kein Aufrufer von `_repo_hook` nimmt je eine Liste).
Fast-Track ist sogar das Gegenteil: er shippt **nach jedem fertigen Turn**
(`sessions.py:954-955`).

Die einzige vorhandene Zusammenfassung ist **zufällig und hash-basiert**: das
Ship-Singleton (`ship.sh:12-21`, „join-or-wait, never stack") lässt den wartenden
Ship durchlaufen, und der Fingerprint-Vergleich direkt darunter macht ihn zum
No-Op, falls der Halter denselben Baum bereits geshippt hat.

**Mit `SHIP_KIND=native` wird genau dieser Vergleich übersprungen**
(`ship.sh:209-210` setzt `SHIP_OTA_ONLY=0` und umgeht den `$CUR = $LAST`-Zweig).
Das agentische Verdrahten **entfernt** also die einzige existierende Entprellung.
Das ist kein Argument dagegen — aber es macht Board-Ebene (Präzisierung 2) zur
**Voraussetzung** statt zur Kür: wenn drei Accepts in fünf Minuten je einen
20-Minuten-APK-Build auslösen, ist das eine Regression gegenüber heute. Henry
muss „diese drei Karten teilen sich einen Build" beurteilen dürfen — das ist
Koordination, und mit `ship_facts.changed_files()` (Delta seit dem letzten
`deploy: bump`, also über beliebig viele Accepts akkumuliert) liegt die
Datengrundlage bereits vor.

---

## 5. Präzisierung (3): Sicherheitsgrenzen

**Kurzantwort: Henry hat heute freie Shell auf dem Live-Baum, und die
Dokumentation behauptet das Gegenteil.**

### 5.1 Der Befund

`ops/harness/settings/copilot.json:18-19` sagt:

> „The copilot runs `--permission-mode plan` and executes nothing itself (it
> emits an ```actions block the daemon executes), so it is granted no tools here."

**Das ist seit `1112018` falsch.** `copilot.py:166-176`:
```python
return (events.settings().get("henry_permission_mode") or "").strip() or "acceptEdits"
```
Der Default ist `acceptEdits`, für **beide** Henry-Flächen. Dazu:

| Kontrolle | `card.json` (Karten-Worker) | Henry |
|---|---|---|
| PreToolUse-Guard | `card_tool_guard.py`, fail-closed (`:45-52`) | **keiner** — auf keinem der beiden Pfade |
| `permissions.allow` | 10 kuratierte Einträge (`:55-66`) | **fehlt komplett** |
| `permissions.deny` | Secrets + `*.pem`/`*.keystore` (`:67-77`) | 8 Lesepfade (`copilot.json:34-42`) |
| Settings-Schicht | `--settings card.json --setting-sources project` | Chat: `copilot.json`; **Broker: gar keine** |

Kein `allow`-Eintrag bedeutet **keine Verengung**; ohne PreToolUse-Hook und mit
`acceptEdits` im Headless-Modus ist Bash unbeschränkt und unbestätigt. Die Regel
„PERMISSION-SURFACE FILES NEVER GET DIRECT HANDS" (`board-copilot.md:230-241`,
nennt `card_tool_guard.py`, `auth.py`, `charter.py`, `gxp.py`, `run_gate.py`) ist
**reiner Prompt-Text ohne Durchsetzung**.

**Zusatzbefund — der Broker erbt die Repo-Hooks.** `henry_broker.py:117-118`
übergibt weder `--settings` noch `--setting-sources` und läuft mit `cwd` =
Repo-Wurzel. Er erbt damit `~/.claude` **und** `.claude/settings.json` des Repos —
inklusive des `Stop`-Hooks `loop_state.py --stop-hook` (`.claude/settings.json:3-4`).
Genau davor schützt sich der Chat bewusst (`copilot.json:11-15`: der Hook
„BLOCKS a turn that isn't at a resting build-loop state… he can neither cause nor
fix"). **Der Broker ist ungeschützt** — und ein laufender Ship ist genau der
Zustand, der die Build-Loop-Position auf nicht-ruhend setzt. Kein Test, kein
Kommentar, kein Schuldeintrag erwähnt das.

### 5.2 Die Falle beim „nur vordefinierte Verben"-Weg

Wenn Henry Ship-Entscheidungen über die `actions`-Blocklogik ausdrücken soll,
gilt eine harte, gemessene Einschränkung: **ein unbekannter Verb-Typ wird nicht
abgelehnt, sondern still zu einem `machine_task` umgeleitet**
(`copilot_actions.py:600-609`) — also zu einem Agenten mit echtem Ordner, der
Kommandos ausführen **darf**. Ein erfundenes `{"type": "ship"}` eskaliert damit
zu einer Shell, statt zu scheitern.

Das ist der eigentliche technische Grund für Präzisierung (1): **neue Verben sind
Code** (`copilot_actions.py` ist eine `if kind ==`-Kette, 24 Zweige), und ein
nicht-eingebautes Verb ist gefährlicher als ein fehlendes.

### 5.3 Empfehlung

1. **Den stale Kommentar in `copilot.json:18-19` korrigieren.** Er beschreibt
   eine Sicherheitseigenschaft, die es nicht mehr gibt — das ist schlimmer als
   gar keine Doku, weil jede spätere Prüfung darauf hereinfällt.
2. **Broker-Spawn eine Settings-Schicht geben** (`--settings copilot.json
   --setting-sources ""`, wie der Chat). Schließt den Stop-Hook-Befund und ist
   ein Ein-Zeilen-Fix an `henry_broker.py:117-118`.
3. **Für den Ship-Pfad eine `permissions.allow`-Liste**, statt freier Shell:
   `py -3.12 ops/tools/ship_facts.py*`, `Bash(git log*/diff*/show*)`,
   `SHIP_DRY_RUN=1 bash ops/deploy/ship.sh`. Verweigert: alles unter
   `surfaces/app/android`, jedes direkte `gradlew`.
4. **Keine neuen Verben erfinden** — `SHIP_KIND` reitet auf der bestehenden
   `rerun_deploy`/`move`-Naht mit.

Zwei gemessene Fallen binden jeden Entwurf (`HARNESS.md:299-311`): `--settings`
allein schließt nichts aus (rein additiv), und **eine Settings-Datei, die der CLI
missfällt, wird SCHWEIGEND verworfen**.

---

## 6. Präzisierung (4): Wie die Android-Mutex weiter greift

**Kurzantwort: unverändert, weil sie unter dem Skript sitzt, nicht neben dem
Aufrufer.**

`ops/deploy/build_lock.sh` ist maschinen-global
(`$HOME/.helmdeck/locks/android-build`, bewusst außerhalb jedes Worktrees, weil
zwei Checkouts **einen** Gradle-Daemon teilen), `mkdir`-atomar, und der Halter
wird per `kill -0` **bewiesen**, nicht geglaubt (`:88-121`). Alle vier
Gradle-Eingänge nehmen ihn. Ein agentisch ausgelöster Ship ruft weiterhin
`ship.sh` → `build_apk.sh` → `android_build_lock`. **Die Mutex greift, ohne dass
Henry von ihr weiß.**

Drei Eigenschaften müssen im Agenten-Flow aktiv erhalten bleiben:

1. **Gehaltener Lock heißt QUEUE, nicht Fehler.** `ship_facts.py:278-294` meldet
   den Zustand bereits als Ressource, und Henrys Snapshot nennt den Halter
   (`henry_broker.py:230-267`). Ein Urteil darf daraus **nie** „nicht shippen"
   ableiten — die Kommentare beider Stellen sagen genau das, weil es der Fehlgriff
   vom 30.08. war.
2. **Der `HOOK-NOTE`-Herzschlag ist lebenswichtig.** `build_lock.sh:96-99` druckt
   jede Minute, weil der Deploy-Hook durch **Stille** begrenzt wird (900 s,
   `lanemachine.py:657`), nicht durch Laufzeit. Ein Agent, der die Ausgabe
   „aufräumt", lässt einen gesund wartenden Build abschießen.
3. **Reentranz** (`:78`) — `SHIP_DRY_RUN=1` zur Prüfung und danach echt shippen
   darf sich nicht selbst blockieren. `ship.sh` nimmt den Android-Lock nicht
   selbst, nur transitiv; das bleibt so.

**Zwei Löcher, die ein Agent NICHT schließt** (und die dieses PRD deshalb nicht
als gelöst verkauft):

- **Der Lock ist kooperativ.** Ein rohes `./gradlew` nimmt ihn nicht und tötet
  einen laufenden Build via `--stop`. Debt `android-build-lock-advisory`. Die
  vorgeschlagene Lösung — ein `gradlew`-Wrapper — ist **Code, kein Brief**, und
  hat eine eigene Falle: `surfaces/app/android` ist git-ignoriert und wird von
  `expo prebuild --clean` neu erzeugt, der Wrapper müsste also aus einem
  `with*.js`-Plugin re-appliziert werden. **Ein Agent kann diese Lücke nicht
  schließen; er kann nur selbst nicht hineinlaufen.**
- **Ein lebender, aber hängender Halter wird unbegrenzt bewartet** (nur ein
  *toter* wird übernommen). Hier ist agentisches Urteil sinnvoll: Henry sieht den
  Halter bereits und könnte „seit 90 Minuten derselbe Halter, keine Ausgabe" als
  Eskalation bewerten — **sofern** Befund §4.2(b) behoben ist, sonst fehlt ihm
  die Zeile bei vollem Board, und §4.2(c), sonst weiß er nicht, wessen Build das ist.

---

## 7. Präzisierung (5): Fehlerverhalten

Heute: `build_apk.sh` scheitert → `exit 1` → `ship.sh` nimmt den Versions-Bump
zurück (`:244-246`) → `_repo_hook` setzt `ok=False` → `escalations.emit("deploy-red")`
(`lanemachine.py:1137`). Der Tail wird gespeichert, aber **niemand klassifiziert
ihn**. Ein Teil der Leiter existiert: `sessions._try_auto_fix_deploy`
(`_DEPLOY_FIX_CAP = 3`) steert den Worker mit dem echten Tail und eskaliert erst
nach der Kappe.

Die vier konkreten Unterschiede:

**(a) Fehlerklasse statt Fehlertext.** Die Tails sind bereits diagnostisch —
`build_apk.sh` schreibt je Stufe eine eindeutige Zeile:

| Klasse | Signatur | heute → agentisch |
|---|---|---|
| **Transient** | `EPERM`/`EBUSY` auf `node_modules` | rot → **einmal wiederholen** (Ursache gemessen: Gradle gibt Jar-Handles verzögert frei) |
| **Ressource fehlt** | JDK 17 fehlt, kein Keystore, `RELAY_HOST` unset | rot nach 15 min → **`ship_facts` VORHER gelesen**, gar nicht erst starten |
| **Kollision** | `[build-lock] … waiting` | sieht aus wie Stillstand → **„wartet auf X"**, kein Alarm |
| **Echter Codefehler** | Gradle-Compile-Error | rot → rot, **korrekt, nicht wiederholen** |
| **Grün, aber nicht geliefert** | `push_relay.sh` WARN, Smoke übersprungen | **still als Erfolg** → der wichtigste Fall (s. c) |

**(b) Niemals die Version bumpen, um einen Build zu reparieren.** HelmDeck ist
verwundbar, weil ein nativer Ship mit einem Bump *beginnt*: dreimal scheitern
hieße drei verbrannte `versionCode`s. `ship.sh:244-246` nimmt heute korrekt
zurück — die Regel gehört in den Brief, sonst erfindet ein Agent den
Retry-durch-Bump.

**(c) Der Ship endet nicht bei `exit 0`.** Das ist der schärfste Gewinn und die
direkte Übertragung von Paseos Nachlauf-Pflicht. Das Repo hat den Beleg selbst
gebaut: `push_site.sh:59-66` beweist nach dem Deploy **am Origin** (5×6 s), dass
die neue Version wirklich ausgeliefert wird; `push_relay.sh:86-108` per
sha256-Rückvergleich des Artefakts, das das Telefon bekäme. Der Android-Ship hat
diesen Beweis **nicht**. `ship_facts.py` liefert die Bausteine (`app.json` vs.
APK via `aapt2` vs. `/apk/version.json`) bereits — sie laufen nur nie **nach**
einem Ship.

**(d) Widersprüche melden statt mitteln.** Der Regelfall ist real: DEPLOY.md
dokumentiert einen 52-Minuten-Build, der `versionName 1.0.2` erzeugte, während
`app.json` `1.0.8` sagte — **nichts in der Pipeline vergleicht die drei Zahlen.**

**Zwei Struktur-Defekte am Fehlerkanal, die dabei mit anzufassen sind:**
`deploy-red` ist als **einziger** Eskalations-Typ **nicht entprellt** (anders als
`load-contention`, `delivered-parked`, `landed-not-closed`) — wiederholt rote
Deploys stapeln offene Einträge. Und `escalations.jsonl` hat **keine Rotation**:
`fold()` liest bei jedem `list_open()` die ganze Datei neu, alle 90 s plus vier
Dedup-Stellen pro Ereignis.

---

## 8. Präzisierung (6): Systemweite Prüfung aller Gates und Ship-Pfade

Zwei Spalten für „Schwachstelle", weil §2 zwei Defekte trennt: **[A]** blindes
Fehlerverhalten, **[B]** Kollision.

| Gate / Pfad | Aktueller Mechanismus | Bekannte Schwachstelle | Empfehlung |
|---|---|---|---|
| **Ship-Entscheidung** `ship.sh` | `SHIP_KIND`-Naht gebaut; ohne sie Hash-Fallback | **[A]** Nichts setzt je `SHIP_KIND`; Hash kann „nicht shippen" nicht ausdrücken. Am 30.08. im selben Baum: nur `.py`/`ops/` geändert → Fallback sagte „OTA only" | **agentisch verdrahten** — Kern dieser Karte, Debt `ship-decision-not-wired` |
| **Android-APK** `build_apk.sh` | ABL (maschinen-global, `mkdir`+Live-PID); 21 Stufen | **[A]** 15+ fatale Ausstiege, kein Retry; **zwei nicht-fatale Endstücke** ⇒ grün ≠ geliefert. **[B]** Lock **kooperativ** — rohes `gradlew` tötet via `--stop`; hängender Halter wird ewig bewartet | **beides**: agentische Ergebnis-Beurteilung (§7) **+** `gradlew`-Wrapper (Debt `android-build-lock-advisory`) |
| **Wear-APK** `build_wear_apk.sh` | Nimmt ABL (`:39`); nur manuell | **[A]** Gradle kompiliert **Kopien**: `.kt` unter `plugins/wear/` editieren → `BUILD SUCCESSFUL`, `UP-TO-DATE`, altes APK (gemessen 29.08., zweimal grün) | **Mutex reicht.** Aber die Falle gehört als Fakt in `ship_facts.py` — sie ist die Klasse „grün und falsch" |
| **`release.sh android`** | Nimmt ABL (`:74`), vor dem Bump | **[A]** Niedrigfidelitäts-Zwilling: kein `npm ci`, kein `prebuild`, **keiner der 7 `with*.js`-Plugins**, nacktes `assembleRelease` (zieht `:wear` mit) | **weder noch — konvergieren.** Zwei Wege zu einem Artefakt mit ungleicher Fidelität ist die Ursache, nicht das Locking |
| **Per-Card-Gate** `_gate` | Per-Worktree-Lock (in-process) + `_admit_heavy` + **Stille**-Grenze (300 s) | **[B]** Lock **nur in-process** — sieht eine Shell oder einen zweiten Daemon nicht (genau das Argument, das für Android ein *Datei*-Lock erzwang). **[A]** `_admit_heavy` (bis 30 min) liegt **innerhalb** des Gate-Locks | **weitgehend ausreichend.** Echte Lücke ist [A] auf der Urteilsebene: Gate-rot unterscheidet „Code kaputt" nicht von „Box thrashte" |
| **`run_gate.py`** selbst | `py_compile` + 2 Importe, ~Sekunden; kein Lock | **[A]** Kein Retry, keine Diagnose; Truncation auf 1200 Zeichen | **bereits ausreichend.** Gate-light ist Dekret (`9dcde19`); **nicht wieder anfetten** |
| **Load-aware Admission** | CPU-Beobachtung, `wait_s` 1800 s, dann **trotzdem zulassen**; eskaliert `load-contention` | **[B] Bewusst kein Ausschluss**, sondern Awareness — deshalb ließ sie am 30.08. beide Builds zu. **[A]** `resources.py` liefert `free_ram_mb()`, `_admit_heavy` liest es **nie** | **ausreichend für seinen Zweck — nicht zur Mutex umbauen.** Awareness ≠ Exclusion ist die richtige Lehre. Offen: RAM verdrahten |
| **OTA-Push** `push_update.sh` | Atomarer Remote-Swap (`.new`→`.old`); kein Lock | **[B]** Zwei Läufe teilen `/tmp/hd-update.tgz` und dieselbe Swap-Sequenz. **[A]** Desktop-Hälfte ist **warn-only** ⇒ Desktop driftet still vom Telefon weg | **Mutex ergänzen** (gleiche Primitive wie ABL) **+** Desktop-Divergenz als eigene Ship-Art |
| **`push_relay.sh`** | **Vorbildlich**: lädt das Artefakt zurück, vergleicht sha256 (`:86-108`) | **[B]** Geteilte `/tmp`-Pfade auf der VM. **[A]** Kein Rollback | **Mutex ergänzen.** Die Verifikation ist bereits das Modell für alle anderen |
| **Windows-Desktop** `release_desktop.sh` | **Kein Lock.** `build-win.ps1` mit `package.json`-Restore | **[B]** Konkurrierende Builds streiten um dasselbe entpackte `winCodeSign-2.6.0`-Verzeichnis (`build-win.ps1:34` löscht und entpackt es rekursiv neu, während ein zweiter daraus signiert) und um das `package.json`-Rewrite-Fenster. **[A]** `--version` wird **geglaubt, nie geprüft**, obwohl `gh release view` 60 Zeilen später ohnehin läuft | **beides.** Desktop-Build-Mutex **+** die Versionswahl ist eine echte Urteilsfrage (Paseos patch/minor-Rubrik) |
| **macOS-Desktop** `desktop-mac.yml` | CI-`concurrency`; echtes Verify im Run (`hdiutil`, `codesign`, `spctl`) | **[B]** durch CI gelöst. **[A]** **Nichts in HelmDeck pollt GitHub Actions** — kein `workflow_run`, kein `check_run` im Code. Ein roter Mac-Build ist unsichtbar | **agentisch** — exakt Paseos Nachlauf-Muster (`create_heartbeat`, Abbruchbedingung definiert). Ausschluss reicht bereits |
| **iOS / EAS** | **Vollständig handgeführt.** `eas submit` nur als Copy-Paste-Zeile in `DEPLOY.md:735` | **[A]** Größte Lücke: **`ship_facts.py` kennt iOS gar nicht.** Drei zwingend menschliche Schritte; Debt `ios-submit-local-asc-key`. **[B]** existiert nicht — Build läuft remote | **agentisch, höchster Hebel.** Playbook ist bereits Prosa (`DEPLOY.md` §2b–2d); es fehlt die Faktenschicht. ABL wäre hier die **falsche** Primitive |
| **Website** `push_site.sh` | **Bester Beweis im Repo**: Origin-Probe, 5 Retries, `/health` | **[A]** Läuft **nie automatisch** — der Deploy-Hook ruft kein `wrangler deploy`. Debt `site-deploy-outside-hook`; Vorfall: Landingpage gemerged, 2 Tage alte Version live | **agentisch verdrahten** — `site` als vierte Ship-Art neben `none\|ota\|native` |
| **`push_glance.sh` / `push_pair_worker.sh`** | Retry-Verify wie `push_site.sh` | **[A]** Ist `*_ORIGIN` nicht gesetzt, wird **deployt, Verifikation übersprungen, `exit 0`** — ein Loch genau in der Eigenschaft, für die diese Skripte vorbildlich sind | **Code-Fix, nicht agentisch.** Unverifizierter Erfolg muss unverifiziert *heißen* |

### Was die Tabelle als Muster zeigt

1. **Die Kollisions-Spalte ist fast leer — außer bei Android und Desktop.** Das
   bestätigt `build_lock.sh`s eigene Analyse: die umkämpfte Ressource ist *lokale
   Compute auf einer Box*. iOS baut remote, macOS in CI, die Website ist
   zustandslos.
2. **Die [A]-Spalte ist nirgends leer.** Kein einziger Pfad klassifiziert seinen
   eigenen Fehler. Die Starrheit liegt **überall** vor, die Kollisionsanfälligkeit
   nur an zwei Stellen.
3. **Das Repo hat die Lösung dreimal unabhängig gefunden und nie verallgemeinert.**
   `push_site.sh` (Origin-Probe), `push_relay.sh` (sha256-Rückvergleich),
   `asc_build_state.py` (Apples eigenes Urteil abfragen, weil „`eas submit` exit 0"
   nichts beweist). Dazu `asc_guide.py`/`meta_wearables_guide.py` — Fakten-Tools
   für Agenten, die dem Dekret vom 30.08. **zeitlich vorausgehen**. Das gemeinsame
   Prinzip ist schärfer als „Fakten melden":

   > **Lies das eigene Signal der Laufzeit, nicht einen Cache davon.**
   > `ship_facts.py` verwirft `.native_fp`. `asc_guide.py` verwarf das gerenderte
   > DOM (die Apps-Seite zeigte „No Apps", während `GET /v1/apps` die App längst
   > zurückgab — ein DOM-Scraper hätte eine existierende App neu angelegt; er
   > wurde gelöscht und hinterließ einen Grabstein, `asc_guide.py:167-168`).
   > `push_site.sh` verwirft `git log` („The commit history is not the deploy
   > state", `DEPLOY.md:450`). `asc_build_state.py` verwirft „exit 0".

   Das ist wortgleich **NO MONKEY PATCHES**, angewandt auf Deployment — und
   dieselbe Disziplin, die `henry_broker._snapshot()` bereits befolgt. **Die
   eigentliche Empfehlung dieses PRD ist, dieses Prinzip zur Regel für alle Pfade
   zu machen — nicht, Skripte durch Prosa zu ersetzen.**

---

## 9. Vorgeschlagene Form

Fünf Artefakte; drei existieren bereits, zwei sind neu und klein.

1. **`ops/harness/agents/board-broker.md` — NEU, und Voraussetzung für alles
   andere** (§3.2). `DEFAULT_POLICY` zieht aus dem Python-Literal in eine
   Brief-Datei, registriert wie die übrigen. Erst dann ist das Einziehen des
   Advisors ein Umzug von Prosa in Prosa statt eine Regression gegen
   Policy-als-Daten.
2. **`ops/harness/agents/ship-advisor.md` — löschen**, Inhalt geht in (1) auf.
   Kostet nichts: zwei tote Referenzen (§0).
3. **`ops/tools/ship_facts.py` — erweitern statt ersetzen.** Heute Android-only;
   die Desktop-Welt wird in **einer Zeile** abgetan (`:83`), iOS und Website
   fehlen ganz. Ohne Fakten kann kein Brief für diese Pfade urteilen.
4. **`ops/deploy/…` — bleiben Executor.** Keine Skript-Änderung in dieser Karte.
5. **`DEPLOY.md` — ist bereits HelmDecks `docs/release.md`.** Paseos Skill ist ein
   Router auf ein Playbook; HelmDeck hat das Playbook, und der Brief zeigt bislang
   nur schwach darauf. Die billigste Angleichung im ganzen Entwurf.

**Die eine Naht.** `_repo_hook` ist der Flaschenhals aller sechs Deploy-Pfade und
reicht heute `dict(os.environ)` durch (`lanemachine.py:673`), während `_gate`
zwei Zeilen weiter oben sehr wohl injiziert (`:230`). Dort reiten `SHIP_KIND`
**und** `HELMDECK_CARD` (§4.2c) mit, ohne das Kommando anzufassen — zur
Ereigniszeit, nie über eine Datei.

**Reihenfolge (die Abhängigkeiten sind echt):** (1) Brief-Datei → (2) Broker
bekommt Settings-Schicht (§5.3.2, Ein-Zeilen-Fix) → (3) `ship_facts` in Henrys
Prompt + Snapshot-Lücken (a)–(d) → (4) `SHIP_KIND`/`HELMDECK_CARD` an der
`_repo_hook`-Naht → (5) Nachlauf-Beweis (§7c).

---

## 10. Verify — Abnahmekriterien für die Bau-Karte

1. Ein Accept, der **nur** `.py`/`ops/`/Doku ändert, shippt **nichts** — und die
   Karte sagt warum. (Heute: Hash-Fallback pusht ein OTA.)
2. Eine `.kt`-Änderung unter `surfaces/app/plugins/` wird als **nativ** erkannt
   (der Beinahe-Unfall vom 23.08., den der Hash falsch beantwortete).
3. Zwei Accepts kurz hintereinander: der zweite **wartet sichtbar** („wartet auf
   `<Label>`, pid N"), wird nicht als hängend gemeldet, der `HOOK-NOTE`-Herzschlag
   hält den Stille-Watchdog ruhig — **und das Label nennt die Karte**, nicht
   „manuell/kein Karten-Kontext" (§4.2c).
4. Ein Ship mit fehlendem JDK/Keystore startet **gar nicht erst** 15 Minuten
   Arbeit, sondern benennt die Ressource.
5. Nach einem nativen Ship stimmen die drei Zahlen überein (`app.json` / APK via
   `aapt2` / `/apk/version.json`) — **und ein Widerspruch ist die Schlagzeile**.
   Dieser Test existiert heute nirgends.
6. Bei **40 aktiven Karten** enthält Henrys Broker-Snapshot die Lock-Zeilen noch
   (§4.2b) — heute nicht.
7. Fällt das Urteil aus, ist das Verhalten **definiert und sichtbar** — siehe
   offene Frage (a).

## 11. Nicht-Ziele

- Skripte löschen. Paseo tut es nicht; die 21 Stufen sind gemessene Fehlerkarten.
- Der Agent ruft `gradlew` direkt auf. Das ist der Bypass, der Builds tötet.
- Die Load-aware Admission zur Mutex machen. Awareness ≠ Exclusion, bewusst.
- Den Gate wieder anfetten. `gate-light` ist Dekret.
- **Einen neuen Verb-Typ für Ships.** Unbekannte Verben werden zu `machine_task`
  mit Shell (§5.2) — die bestehende `move`/`rerun_deploy`-Naht ist der Weg.
- **Einen zweiten Koordinator.** Der PM erkennt und fragt, Henry handelt (§4.1).

---

## 12. Offene Fragen — nur der Owner kann sie entscheiden

**(a) Was passiert, wenn Henrys Ship-Urteil ausfällt?** Der Schuldeintrag nennt
das ausdrücklich als die Entscheidung, die Code nicht allein treffen darf. Drei
Optionen: auf den Hash zurückfallen (bequem — aber genau die Drift, die `ee6a8f1`
entfernt hat, und still), gar nicht shippen (sicher, aber ein Accept liefert dann
nichts), oder als Eskalation parken (passt zur Architektur, kostet Latenz).

**(b) Ein Agenten-Turn pro Accept — Kosten und Latenz.** Jeder Accept zahlte
Tokens und einige Sekunden. Alternativen: immer; oder nur, wenn `ship_facts`
mehrdeutig ist (billig, aber „mehrdeutig" wäre selbst wieder eine feste
Heuristik — genau die Form, die hier abgeschafft wird).

**(c) Bündelung.** §4.3: die Naht entfernt die einzige existierende Entprellung.
Soll Henry mehrere Accepts zu **einem** Build zusammenfassen dürfen (spart 20-min-
Builds, verzögert aber die erste Karte), oder bleibt es bei einem Ship pro Accept?

**(d) Reichweite.** Nur Android jetzt, oder gleich iOS/Website/Desktop mit? Die
Tabelle sagt: iOS hat den größten Hebel, aber auch den größten Faktenschicht-Bau.

**(e) Autorisierungsgrenze.** Paseo trennt „Skill starten" von „veröffentlichen
dürfen". HelmDeck kennt nur Accept = deployt. Soll ein *nativer* Ship (20 min,
Versions-Bump, für installierte APKs unwiderruflich) dieselbe Schwelle behalten
wie ein OTA?
