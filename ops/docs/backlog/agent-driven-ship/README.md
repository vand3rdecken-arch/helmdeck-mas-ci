# Ship/Build agentisch — vom starren Skript zur Arbeitsanweisung

**Owner-Auftrag (2026-08-30):** "kein Skript mehr, sondern Arbeitsanweisung für
den Agent, damit er weiß was er shippen muss" — Vorbild Paseo. Ergänzt am selben
Tag um den Systemauftrag: dieselbe Prüfung für **alle anderen Gates** (iOS/EAS,
`run_gate.py`/Per-Card-Gate, Deploy-Hooks für macOS/Desktop/Website) — liegt dort
dieselbe Starrheit vor, und ist agentisch dort ebenfalls die Antwort, oder
schützt bereits ein anderer Mechanismus (Karte `20260820-221912`,
`ops/docs/backlog/load-aware-admission/`)?

Reines Design-Dokument. Kein Code, keine Skript-Änderung.

---

## 0. Vorab: was schon geshippt ist, und warum das die Frage verschiebt

Commit `ee6a8f1` (30.08., 18:47) hat den **Entscheidungs**teil bereits invertiert.
Das ist keine offene Arbeit mehr, und dieses PRD schlägt es nicht erneut vor:

| Baustein | Datei | Zustand |
|---|---|---|
| Beweislage ohne Urteil | `ops/tools/ship_facts.py` | **lebt.** 11 Änderungsklassen, 3 Versionsnummern, 8 Ressourcen |
| Der entscheidende Brief | `ops/harness/agents/ship-advisor.md` | **lebt** als Datei |
| Skript als Executor | `ops/deploy/ship.sh:186-229` | **lebt.** `SHIP_KIND=none\|ota\|native`, `SHIP_DRY_RUN=1` |
| Der Aufruf | — | **existiert nicht.** Kein Python, kein Shell, kein JSON setzt je `SHIP_KIND` |

Die Naht ist auf der Executor-Seite vollständig und auf der Aufrufer-Seite leer.
`lanemachine.py:673` reicht `dict(os.environ)` unverändert weiter; jeder
automatische Ship läuft im Hash-Fallback. Registriert als
`ship-decision-not-wired` (`spine/registry/debt.py:3566`), und dieses PRD ist die
Entscheidungsvorlage, die dieser Schuldeintrag ausdrücklich anfordert.

**Damit ist die eigentliche Frage nicht mehr "soll der Agent entscheiden" — das
ist entschieden und gebaut. Die Frage ist: (a) wie wird es angerufen, (b) reicht
Entscheiden, oder muss der Agent auch die AUSFÜHRUNG begleiten, (c) gilt dasselbe
für die anderen Pfade.**

---

## 1. Die Paseo-Korrektur — Paseo hat seine Skripte NICHT gelöscht

Der Auftrag lautet "kein Skript mehr". Die Quelle (`_paseo_src`, gelesen) sagt
etwas Genaueres, und die Differenz ist der Kern dieses Dokuments.

Paseos Release-Skills sind **13 Zeilen**. Vollständig, das ist alles:

```markdown
---
name: release-beta
description: Cut a beta release of Paseo. Use when the user says "release beta"...
user-invocable: true
---
# Release beta
Read `docs/release.md` in the Paseo repo and follow the **Beta flow** section
end-to-end. Run the **Beta release** completion checklist at the bottom of that doc.

During preparation, classify the previous-stable-to-`HEAD` diff as patch or minor
and show the target version and rationale to the user. Agents never select a major
version autonomously.
```

Der Skill ist ein **Router**, kein Verfahren. Das Verfahren steht in
`docs/release.md` (516 Zeilen). Und die Skripte existieren weiter:
`package.json:90-114` sind vierstufige `&&`-Ketten
(`release:check && version:all:patch && release:publish && release:push`).

Was Paseo tatsächlich verschoben hat:

| Ebene | Eigentümer bei Paseo | Beleg |
|---|---|---|
| **Urteil** (patch/minor, Changelog, blockiert ein Fund?) | Agent | `docs/release.md:46-56` — Rubrik in Prosa, "diff size alone does not" |
| **Harte Invarianten** | Skript, das `throw`t | `scripts/push-current-release-tag.mjs:78-99` — Tag≠HEAD und Tag-Reuse werfen, fragen nicht |
| **Autorisierung** | Mensch | `docs/release.md:30` — "Invoking a release skill is intent to start the flow, **not blanket authorization to publish**" |
| **Wechselseitiger Ausschluss** | GitHub-Actions `concurrency`, `cancel-in-progress: false` | `desktop-release.yml:46-48` — **kein agentenseitiges Lock** |
| **Nachlauf** | Agent, verpflichtend | `docs/release.md:269-285` — `create_heartbeat`, nicht `create_schedule` |

Und eine Grenze, die Paseo explizit zieht: `docs/release.md:56` — "Agents never
select a major version autonomously." Ferner `:303` — "**NEVER bump the version
to fix a build problem.**"

**Folgerung für HelmDeck:** "kein Skript mehr" ist als Ziel zu wörtlich. Was
HelmDeck fehlt, ist nicht die Abschaffung von `build_apk.sh` — es ist Paseos
`docs/release.md`-Ebene (das Playbook, auf das ein kurzer Brief zeigt), die
**Autorisierungsgrenze**, und der **Nachlauf**. Zwei davon existieren in HelmDeck
bereits in anderer Form (DEPLOY.md ist das Playbook; Accept ist die
Autorisierung). Der Nachlauf fehlt vollständig.

---

## 2. Zwei verschiedene Defekte, die nicht vermischt werden dürfen

Der Auftrag nennt beides in einem Atemzug. Die Messungen trennen sie sauber:

**Defekt A — das Skript reagiert nicht auf Probleme.**
`build_apk.sh` hat ~21 Stufen und **15+ fatale Ausstiege, null Retry, null
Cleanup**. Der einzige Revert im ganzen Satz steht beim *Aufrufer*
(`ship.sh:244-246`, Versions-Bump zurücknehmen). Schlimmer als das Scheitern ist
das Gegenteil: **zwei bewusst nicht-fatale Endstücke** — der Emulator-Smoke
(`build_apk.sh:263`) und `push_relay.sh` (`:270`) — plus die Desktop-Hälfte von
`push_update.sh:135-138`. Ein grüner Deploy-Hook beweist **nicht**, dass das APK
das Telefon je erreicht hat.

**Defekt B — Kollision.** Betrifft nur Pfade, die sich eine physische Ressource
teilen. Für Android ist er seit `6e60712` geschlossen (siehe §5); für die
Desktop-Builds und die Relay-Pushes ist er offen; für iOS und die Website
existiert er nicht (remote bzw. unkritisch).

Ein Agent behebt A. Ein Agent behebt B **nicht** — dafür braucht es ein Lock.
Diese Trennung ist die Achse der Tabelle in §7.

---

## 3. Scope-Frage (1): Entscheidung oder auch Ausführung?

### Was gegen "Agent führt den Build selbst aus" spricht

Drei gemessene Gründe, keine Vorsicht:

1. **Der Deploy-Hook läuft daemon-seitig, weil er Geheimnisse hält.**
   `lanemachine.py:1119` sagt es wörtlich: `_repo_hook(t, "deploy")` —
   *"daemon-side (post-merge), with the secrets agents never see"*. `ship.sh`
   braucht Relay-SSH-Credentials und den Keystore. `card.json:54-78` verbietet
   dem Agenten das Lesen von `.env`, `*.keystore`, `*.pem` **explizit**. Ein
   Agent, der den Build selbst fährt, braucht genau das, was ihm die geltende
   Policy entzieht. Das ist keine Konfigurationsfrage, das ist die
   Isolationsgrenze.
2. **Die Skripte sind teuer erkaufte Fehlerkarten.** `build_apk.sh` enthält
   mindestens neun kommentierte Messungen (EBUSY nach `--stop`; Icon-Redesign
   grün gebaut mit altem Icon; `npx` scheitert am Leerzeichen im Node-Pfad;
   Metaspace-OOM in `lintVitalAnalyzeRelease`; `expo prebuild --clean`
   überschreibt `signingConfigs` → Debug-Keystore, exit 0, Installation
   scheitert erst auf dem Telefon…). Diese Reihenfolge neu zu erfinden ist
   nicht Autonomie, sondern Amnesie.
3. **Paseo macht es auch nicht.** Die 4-stufigen npm-Ketten bleiben.

### Empfehlung: **Agent entscheidet und ÜBERWACHT; das Skript führt aus**

Drei Rollen statt zwei:

| Rolle | Wer | Womit |
|---|---|---|
| **Entscheiden** — shippen? was? Ressourcen da? | Agent (`ship-advisor`) | `ship_facts.py` → `SHIP_KIND` |
| **Ausführen** — die 21 Stufen in der bewiesenen Reihenfolge | Skript | `ship.sh` → `build_apk.sh` |
| **Beurteilen** — hat es funktioniert; was tun wenn nicht | Agent | Tail + `ship_facts.py` erneut |

Die dritte Rolle ist neu und schließt Defekt A, ohne die Isolationsgrenze zu
verletzen: der Agent liest ein Ergebnis, statt Geheimnisse zu halten.

**Ausdrücklich NICHT im Scope:** freie `gradlew`-Aufrufe durch den Agenten. Das
ist genau der Bypass, den `android-build-lock-advisory`
(`spine/registry/debt.py:3604`) als offene Schuld führt — ein ungesperrter Build
**tötet** einen laufenden, weil `build_apk.sh` mit `--stop` beginnt.

---

## 4. Scope-Frage (2): Sicherheitsgrenzen

**Befund: HelmDeck hat den Mechanismus bereits, und er ist strenger als Paseos.**
Paseo hat für seine Release-Skills *überhaupt keine* Tool-Policy (kein
`allowed-tools`, kein `.claude/settings.json` im Repo); die Autorisierung ist
konversationell. HelmDeck kann das nicht kopieren — ein Accept ist asynchron, der
Owner sitzt nicht daneben.

Was existiert:

| Mechanismus | Ort | Wirkung |
|---|---|---|
| `permissions.allow` / `.deny` | `ops/harness/settings/card.json:54-78` | Echte Allow/Deny-Liste pro Surface |
| PreToolUse-Guard | `ops/tools/card_tool_guard.py` | **Fail-closed**, kuratierte Build/Test-Allowlist auf argv-Ebene |
| `--permission-mode` | `drivers.py:448` (aus Driver-Cfg, nicht aus dem Brief) | `plan` \| `acceptEdits` \| … |
| `--setting-sources` | `harness.cli_args()` | Das Einzige, was eine Schicht **ausschließt** |

Zwei gemessene Fallen, die den Entwurf binden:
`--settings` allein schließt nichts aus (rein additiv), und **eine
Settings-Datei, die der CLI missfällt, wird SCHWEIGEND verworfen**
(`HARNESS.md:299-311`).

**Empfehlung:** Der Ship-Advisor bekommt eine **eigene Settings-Schicht**
(`ops/harness/settings/ship.json`) statt freier Shell. Erlaubt:
`py -3.12 ops/tools/ship_facts.py*`, `Bash(git log*/diff*/show*)`,
`SHIP_DRY_RUN=1 bash ops/deploy/ship.sh`. Verweigert: alles unter
`surfaces/app/android`, jedes direkte `gradlew`, jedes `Write`/`Edit`.
Der Advisor braucht **keine Schreibrechte** — er produziert vier Zeilen
(`DECISION/WHY/NEXT/UNVERIFIED`).

**Bekannter Konstruktionsaufwand, nicht verschweigen:** Das Brief-Schema
(`ops/harness/schema/agent.schema.json`) hat `additionalProperties: false` und
**kein** `tools`-Feld; die Tool-Haltung muss über `settings:` laufen. Ferner ist
`ship-advisor` heute in keiner der drei Registraturen (`harness.SURFACES:396`,
`_BY_AGENT:655`, `describe():367`) — er ist damit **nicht über `/harness`
editierbar**, was dem Prinzip "Policy ist Daten, vom Owner ohne Code-Änderung
umformulierbar" widerspricht. Das ist Teil der Arbeit, nicht ein Nebeneffekt.

---

## 5. Scope-Frage (3): Wie die Android-Mutex im Agenten-Flow weiter greift

**Kurzantwort: unverändert, weil sie an der richtigen Stelle sitzt — unter dem
Skript, nicht neben dem Aufrufer.**

`ops/deploy/build_lock.sh` ist maschinen-global
(`$HOME/.helmdeck/locks/android-build`, bewusst außerhalb jedes Worktrees),
`mkdir`-atomar, und der Halter wird per `kill -0` **bewiesen**, nicht geglaubt.
Alle vier Gradle-Eingänge nehmen ihn (`build_apk.sh:27`, `build_wear_apk.sh:39`,
`release.sh:74`, `ship.sh` transitiv). Ein agentisch ausgelöster Ship ruft
weiterhin `ship.sh` → `build_apk.sh` → `android_build_lock` auf. **Die Mutex
greift, ohne dass der Agent von ihr weiß.**

Drei Eigenschaften, die im Agenten-Flow aktiv erhalten bleiben müssen:

1. **`ship_facts.py:278-294` meldet den Lock-Zustand bereits als Ressource.** Der
   Brief sagt dem Advisor schon heute (`ship-advisor.md:76-77`): ein gehaltener
   Lock bedeutet **QUEUE, nicht Fehler** — "say it so nobody reads a waiting card
   as a stuck one". Der Advisor darf daraus **nie** "nicht shippen" ableiten.
2. **Der `HOOK-NOTE`-Herzschlag ist lebenswichtig.** `build_lock.sh:97-99` druckt
   jede Minute, weil die Karte durch **Stille** (900 s) begrenzt wird, nicht durch
   Laufzeit. Ein Agent, der die Ausführung "aufräumt" und diese Zeilen
   unterdrückt, lässt einen gesund wartenden Build abschießen.
3. **Reentranz** (`:78`) — ein Advisor, der `SHIP_DRY_RUN=1` zur Prüfung fährt und
   danach echt shippt, darf sich nicht selbst blockieren. `ship.sh` nimmt den
   Android-Lock nicht selbst, nur transitiv; das bleibt so.

**Zwei offene Löcher, die der Agent NICHT schließt** (und die das PRD deshalb
nicht als gelöst verkaufen darf):

- **Der Lock ist kooperativ.** Ein rohes `./gradlew` nimmt ihn nicht und tötet
  einen laufenden Build. Debt `android-build-lock-advisory`. Die im Schuldeintrag
  vorgeschlagene Lösung — ein `gradlew`-Wrapper, der vor dem Delegieren
  erwirbt — ist Code, kein Brief. **Ein Agent kann diese Lücke nicht schließen;
  er kann nur selbst nicht hineinlaufen.**
- **Ein lebender, aber hängender Halter wird unbegrenzt bewartet** (nur ein
  *toter* Halter wird übernommen). Genau hier ist agentisches Urteil sinnvoll:
  Henry sieht den Halter bereits (`henry_broker.py:230-256`,
  `android-build.lock: pid N (LIVE …) | <label>`) und könnte "seit 90 Minuten
  derselbe Halter, keine Ausgabe" als Eskalation bewerten. Das ist eine
  Henry-Aufgabe, keine Ship-Advisor-Aufgabe.

---

## 6. Scope-Frage (4): Fehlerverhalten — was der Agent konkret anders macht

Heute: `build_apk.sh` scheitert → `exit 1` → `ship.sh` nimmt den Versions-Bump
zurück → `_repo_hook` setzt `ok=False` → `_say_card` schreibt "Deploy
fehlgeschlagen" → `escalations.emit("deploy-red", …)`. Der Tail (1500 Zeichen)
wird gespeichert, aber **niemand klassifiziert ihn**.

Ein Teil der Leiter existiert bereits: `sessions._try_auto_fix_deploy`
(`:1184-1213`, `_DEPLOY_FIX_CAP = 3`) steert den Worker mit dem echten Tail und
eskaliert erst nach der Kappe. Das PRD baut darauf auf statt daneben.

Die vier konkreten Unterschiede:

**(a) Fehlerklasse statt Fehlertext.** Die Tails sind bereits diagnostisch —
`build_apk.sh` schreibt für jede Stufe eine eindeutige Zeile. Ein Agent
klassifiziert:

| Klasse | Signatur | Richtige Reaktion — heute vs. agentisch |
|---|---|---|
| **Transient** | `EPERM`/`EBUSY` auf `node_modules` | heute: rot. agentisch: **einmal wiederholen** — die Ursache (Gradle-Daemon gibt Jar-Handles verzögert frei) ist gemessen und verschwindet von selbst |
| **Ressource fehlt** | "JDK 17 missing", kein Keystore, `RELAY_HOST` unset | heute: rot nach 15 min. agentisch: **`ship_facts.py` VORHER gelesen** → gar nicht erst starten, Ressource benennen |
| **Kollision** | `[build-lock] … waiting` | heute: sieht aus wie Stillstand. agentisch: **"wartet auf X"**, kein Alarm |
| **Echter Codefehler** | Gradle-Compile-Error | heute: rot. agentisch: rot — **korrekt, nicht wiederholen** |
| **Grün, aber nicht geliefert** | `push_relay.sh` WARN, Smoke übersprungen | heute: **still als Erfolg** | agentisch: **das ist der wichtigste Fall** (s. c) |

**(b) Niemals die Version bumpen, um einen Build zu reparieren.** Paseo verbietet
das ausdrücklich (`docs/release.md:303`). HelmDeck ist hier verwundbar, weil ein
nativer Ship mit einem Bump *beginnt*: dreimal scheitern hieße drei verbrannte
`versionCode`s. `ship.sh:244-246` nimmt heute korrekt zurück — diese Regel gehört
in den Brief, sonst erfindet ein Agent den Retry-durch-Bump.

**(c) Der Ship endet nicht bei `exit 0`.** Das ist der schärfste Gewinn und die
direkte Übertragung von Paseos Nachlauf-Pflicht. Das Repo hat den besten Beleg
schon selbst gebaut: `push_site.sh:59-66` deployt und **beweist danach am Origin**
(5 Versuche × 6 s), dass die neue Version wirklich ausgeliefert wird — entstanden
aus dem Vorfall, bei dem "merged" als "geshippt" gelesen wurde.
`push_relay.sh:86-108` tut dasselbe per sha256-Vergleich des Artefakts, das das
Telefon wirklich bekäme. Der Android-Ship hat diesen Beweis **nicht**;
`ship_facts.py` liefert die Bausteine (`app.json` vs. APK via `aapt2` vs.
`/apk/version.json` des Relays) bereits, und der Brief verlangt den Vergleich
schon (`ship-advisor.md:78-82`) — nur läuft er nie **nach** einem Ship.

**(d) Widersprüche melden statt mitteln.** `ship-advisor.md:107-111` schreibt es
bereits vor. Der Regelfall dafür ist real: DEPLOY.md dokumentiert einen
52-Minuten-Build, der `versionName 1.0.2` erzeugte, während `app.json` `1.0.8`
sagte — **nichts in der Pipeline vergleicht die drei Zahlen.**

---

## 7. Systemweite Prüfung — alle Gates und Ship-Pfade

Zwei Spalten für "Schwachstelle", weil §2 zwei Defekte trennt: **[A]** blindes
Fehlerverhalten, **[B]** Kollision.

| Gate / Pfad | Aktueller Mechanismus | Bekannte Schwachstelle | Empfehlung |
|---|---|---|---|
| **Ship-Entscheidung** `ship.sh` | `SHIP_KIND`-Naht gebaut; ohne sie Hash-Fallback | **[A]** Nichts setzt je `SHIP_KIND`; Hash kann "nicht shippen" nicht ausdrücken. Am 30.08. im selben Baum: nur `.py`/`ops/` geändert → Fallback sagte "OTA only" | **agentisch verdrahten** — Kern dieser Karte, Debt `ship-decision-not-wired` |
| **Android-APK** `build_apk.sh` | ABL (maschinen-global, `mkdir`+Live-PID); 21 Stufen | **[A]** 15+ fatale Ausstiege, kein Retry, kein Cleanup; **zwei nicht-fatale Endstücke** ⇒ grün ≠ geliefert. **[B]** Lock ist **kooperativ** — rohes `gradlew` tötet via `--stop`; hängender Halter wird ewig bewartet | **beides**: agentische Ergebnis-Beurteilung (§6) **+** Mutex-Loch per `gradlew`-Wrapper schließen (Debt `android-build-lock-advisory`) |
| **Wear-APK** `build_wear_apk.sh` | Nimmt ABL (`:39`), bewusst nach den Fail-fast-Checks; nur manuell | **[A]** Gradle kompiliert **Kopien**: `.kt` unter `plugins/wear/` editieren → `BUILD SUCCESSFUL`, `UP-TO-DATE`, altes APK (gemessen 29.08., zweimal grün) | **Mutex reicht.** Aber: diese Falle gehört als Fakt in `ship_facts.py` — sie ist genau die Klasse "grün und falsch" |
| **`release.sh android`** | Nimmt ABL (`:74`), vor dem Bump | **[A]** Niedrigfidelitäts-Zwilling: kein `npm ci`, kein `prebuild`, **keiner der 7 `with*.js`-Plugins**, nacktes `assembleRelease` (zieht `:wear` mit) | **weder noch — konvergieren.** Zwei Wege zu einem Artefakt mit ungleicher Fidelität ist die Ursache, nicht das Locking |
| **Per-Card-Gate** `_gate` | Per-Worktree-Lock (in-process) + `_admit_heavy` + **Stille**-Grenze (300 s) | **[B]** Lock ist **nur in-process** — sieht eine Shell oder einen zweiten Daemon nicht (genau das Argument, das für Android ein *Datei*-Lock erzwang). **[A]** `_admit_heavy` (bis 30 min) liegt **innerhalb** des Gate-Locks (`:225`/`:231`) | **weitgehend ausreichend.** Der Lock ist tree-scoped und Gates sind kurz. Echte Lücke ist [A] auf der Urteilsebene: Gate-rot unterscheidet "Code kaputt" nicht von "Box thrashte" |
| **`run_gate.py`** selbst | `py_compile` + 2 Importe, ~Sekunden; kein Lock | **[A]** Kein Retry, keine Diagnose. Truncation auf 1200 Zeichen | **bereits ausreichend.** Gate-light ist Dekret (`9dcde19`); nicht wieder anfetten |
| **Load-aware Admission** (`20260820-221912`) | CPU-Beobachtung, `wait_s` 1800 s, dann **trotzdem zulassen**; benannter Halter; eskaliert `load-contention` | **[B] Ist BEWUSST kein Ausschluss**, sondern Awareness (`:94-96`) — deshalb ließ sie am 30.08. beide Builds zu. **[A]** `resources.py` liefert `free_ram_mb()`, `_admit_heavy` liest es **nie**; nur 2 Aufrufstellen (direktes `build_apk.sh` passiert sie nicht) | **ausreichend für seinen Zweck — nicht zur Mutex umbauen.** Die Trennung Awareness/Exclusion ist die richtige Lehre aus 30.08. Offen: RAM verdrahten |
| **OTA-Push** `push_update.sh` | Atomarer Remote-Swap (`.new`→`.old`); kein Lock | **[B]** Zwei Läufe teilen `/tmp/hd-update.tgz` und dieselbe Swap-Sequenz. **[A]** Desktop-Hälfte ist **warn-only** ⇒ Desktop driftet still vom Telefon weg | **Mutex ergänzen** (billig, gleiche Primitive wie ABL) **+** Desktop-Divergenz als eigene Ship-Art behandeln |
| **`push_relay.sh`** | **Vorbildliche Verifikation**: lädt das Artefakt zurück und vergleicht sha256 (`:86-108`) | **[B]** Geteilte `/tmp`-Pfade auf der VM. **[A]** Kein Rollback | **Mutex ergänzen.** Verifikation ist bereits das Modell für alle anderen |
| **Windows-Desktop** `release_desktop.sh` | **Kein Lock.** `build-win.ps1` mit `package.json`-Restore | **[B]** Konkurrierende Builds streiten um dasselbe entpackte `winCodeSign-2.6.0`-Verzeichnis (`build-win.ps1:34` löscht und entpackt es **rekursiv neu**, während ein zweiter Build daraus signiert) und um das `package.json`-Rewrite/Restore-Fenster — ein zweiter Build snapshottet die *verstümmelte* Datei. **[A]** `--version` wird **geglaubt, nie geprüft**, obwohl `gh release view` 60 Zeilen später ohnehin aufgerufen wird | **beides.** Desktop-Build-Mutex ergänzen **+** die Versionswahl ist eine echte Urteilsfrage (Paseos patch/minor-Rubrik) |
| **macOS-Desktop** `desktop-mac.yml` | CI-`concurrency` (`cancel-in-progress: true`); Publish opt-in; echtes Verify im Run (`hdiutil`, `codesign`, `spctl`) | **[B]** durch CI gelöst. **[A]** **Nichts in HelmDeck pollt GitHub Actions** — kein `workflow_run`, kein `check_run` irgendwo im Code. Ein roter Mac-Build ist unsichtbar | **agentisch** — und zwar exakt Paseos Nachlauf-Muster (`create_heartbeat`, Abbruchbedingung definiert). Ausschluss bereits ausreichend |
| **iOS / EAS** | **Vollständig handgeführt.** Kein Build+Submit-Skript; `eas submit` existiert nur als Copy-Paste-Zeile in `DEPLOY.md:735` | **[A]** Größte Lücke im System: **`ship_facts.py` kennt iOS gar nicht.** Drei zwingend menschliche Schritte (ASC-Key, Push-Keys, `ensureAscAppAsync`); Debt `ios-submit-local-asc-key` ("funktioniert auf der Box des Owners und nirgends sonst"). **[B]** existiert nicht — Build läuft remote | **agentisch, höchster Hebel.** Das Playbook ist bereits Prosa (`DEPLOY.md` §2b–2d); es fehlt nur die Faktenschicht + ein Brief, der darauf zeigt. ABL wäre hier die **falsche** Primitive |
| **Website** `push_site.sh` | **Bester Beweis im Repo**: Origin-Probe mit 5 Retries, `/health` prüft, dass der *richtige* Worker antwortet | **[A]** Läuft **nie automatisch** — der Deploy-Hook ruft kein `wrangler deploy`. Debt `site-deploy-outside-hook` offen; Vorfall: Landingpage gemerged, 2 Tage alte Version live. **[B]** kein Lock, aber laut scheiternd | **agentisch verdrahten** — `site` als vierte Ship-Art (`SHIP_KIND`) neben `none\|ota\|native` |
| **`push_glance.sh` / `push_pair_worker.sh`** | Retry-Verify wie `push_site.sh` | **[A]** Ist `*_ORIGIN` nicht gesetzt, wird **deployt, Verifikation übersprungen, `exit 0`** — ein Loch genau in der Eigenschaft, für die diese Skripte vorbildlich sind | **Code-Fix, nicht agentisch.** Unverifizierter Erfolg muss unverifiziert *heißen* |

### Was die Tabelle als Muster zeigt

1. **Die Kollisions-Spalte ist fast leer — außer bei Android und den
   Desktop-Builds.** Das bestätigt `build_lock.sh`s eigene Analyse: die
   umkämpfte Ressource ist *lokale Compute auf einer Box*. iOS baut remote,
   macOS in CI, die Website ist zustandslos.
2. **Die [A]-Spalte ist nirgends leer.** Kein einziger Pfad klassifiziert seinen
   eigenen Fehler. Das ist die systemweite Antwort auf die Owner-Frage: die
   Starrheit liegt **überall** vor, die Kollisionsanfälligkeit nur an zwei
   Stellen.
3. **Das Repo hat die Lösung dreimal unabhängig gefunden und nie verallgemeinert.**
   `push_site.sh` (Origin-Probe), `push_relay.sh` (sha256-Rückvergleich),
   `asc_build_state.py` (Apples eigenes Urteil abfragen, weil "`eas submit` exit 0"
   nichts beweist). Dazu `asc_guide.py` und `meta_wearables_guide.py` — Fakten-Tools
   für Agenten, die dem Dekret vom 30.08. **zeitlich vorausgehen**.
   Das gemeinsame Prinzip ist schärfer als "Fakten melden":

   > **Lies das eigene Signal der Laufzeit, nicht einen Cache davon.**
   > `ship_facts.py` verwirft das gespeicherte `.native_fp`. `asc_guide.py`
   > verwirft das gerenderte DOM (die Apps-Seite zeigte "No Apps", während
   > `GET /v1/apps` die App längst zurückgab — ein DOM-Scraper hätte die Karte
   > losgeschickt, eine existierende App neu anzulegen; er wurde gelöscht und
   > hinterließ einen Grabstein-Kommentar, `asc_guide.py:167-168`).
   > `push_site.sh` verwirft `git log` ("The commit history is not the deploy
   > state", `DEPLOY.md:450`). `asc_build_state.py` verwirft "exit 0".

   Das ist wortgleich das NO-MONKEY-PATCHES-Dekret aus `CLAUDE.md`, angewandt
   auf Deployment. **Die eigentliche Empfehlung dieses PRD ist, dieses Prinzip
   zur Regel für alle Pfade zu machen — nicht, Skripte durch Prosa zu ersetzen.**

---

## 8. Vorgeschlagene Form (kein Code, nur die Form)

Vier Artefakte, drei davon existieren bereits:

1. **`ops/tools/ship_facts.py` — erweitern statt ersetzen.** Heute Android-only;
   die Desktop-Welt wird in **einer Zeile** abgetan (`:83`,
   `"desktop surface - separate release path"`), iOS und Website fehlen ganz.
   Ohne Fakten kann kein Brief für diese Pfade urteilen.
2. **`ops/deploy/…` — bleiben Executor.** Keine Skript-Änderung in dieser Karte.
3. **`ops/harness/agents/ship-advisor.md` — bleibt der Brief**, plus die zwei
   Regeln aus §6: "niemals bumpen, um einen Build zu reparieren" und "der Ship
   endet erst, wenn das Artefakt nachweislich ausgeliefert wird".
4. **`DEPLOY.md` — ist bereits HelmDecks `docs/release.md`.** Paseos Skill ist ein
   Router auf ein Playbook; HelmDeck hat das Playbook und der Brief zeigt bislang
   nur schwach darauf. Das ist die billigste Angleichung im ganzen Entwurf.

**Wo der Advisor läuft.** Der Schuldeintrag schlägt bereits die Form vor
(`debt.py:3596-3601`): eigener Schritt **vor** dem Deploy-Hook, Entscheidung in
den Actionlog der Karte, `SHIP_KIND` zur Ereigniszeit — **nie über eine Datei**,
denn eine Entscheidungsdatei wäre exakt das stored flag, das `ee6a8f1` entfernt
hat. Technisch ist die Stelle eindeutig: `_repo_hook` ist der einzige Flaschenhals
aller drei Deploy-Pfade (`lanemachine.py:1119`, `sessions.py:978`, `:1162`), und
`:673` reicht heute `dict(os.environ)` durch — dort ritte `SHIP_KIND` mit, ohne
das Kommando anzufassen.

---

## 9. Verify (Abnahmekriterien für die Bau-Karte)

1. Ein Accept, der **nur** `.py`/`ops/`/Doku ändert, shippt **nichts** — und die
   Karte sagt warum. (Heute: Hash-Fallback pusht ein OTA.)
2. Eine `.kt`-Änderung unter `surfaces/app/plugins/` wird als **nativ** erkannt.
   (Das ist der Beinahe-Unfall vom 23.08., den der Hash falsch beantwortete.)
3. Zwei Accepts kurz hintereinander: der zweite **wartet sichtbar** ("wartet auf
   `<Label>`, pid N"), wird nicht als hängend gemeldet, und der
   `HOOK-NOTE`-Herzschlag hält den Stille-Watchdog ruhig.
4. Ein Ship mit fehlendem JDK/Keystore startet **gar nicht erst** 15 Minuten
   Arbeit, sondern benennt die Ressource.
5. Nach einem nativen Ship stimmen die drei Zahlen überein (`app.json` / APK via
   `aapt2` / `/apk/version.json`) — **und ein Widerspruch ist die Schlagzeile**,
   nicht eine Fußnote. Dies ist der Test, den es heute nirgends gibt.
6. Fällt der Advisor aus, ist das Verhalten **definiert und sichtbar** — siehe
   offene Frage (a).

## 10. Nicht-Ziele

- Skripte löschen. Paseo tut es nicht; die 21 Stufen sind gemessene Fehlerkarten.
- Der Agent ruft `gradlew` direkt auf. Das ist der Bypass, der Builds tötet.
- Die Load-aware Admission zur Mutex machen. Awareness ≠ Exclusion, bewusst.
- Den Gate wieder anfetten. `gate-light` ist Dekret.
- Ein zweiter Ort für die Ship-Entscheidung. **Ein** Eigentümer, zur Ereigniszeit.

---

## 11. Offene Fragen — nur der Owner kann sie entscheiden

**(a) Was passiert, wenn der Advisor ausfällt?** Der Schuldeintrag nennt das
ausdrücklich als die Entscheidung, die Code nicht allein treffen darf. Drei
Optionen: auf den Hash zurückfallen (bequem — aber genau die Drift, die
`ee6a8f1` entfernt hat, und still), gar nicht shippen (sicher, aber ein
Accept liefert dann nichts), oder an Henry eskalieren (passt zur bestehenden
Architektur, kostet Latenz).

**(b) Ein Agenten-Turn pro Accept — Kosten und Latenz.** Jeder Accept zahlte
Tokens und einige Sekunden. Alternativen: immer; oder nur, wenn `ship_facts`
mehrdeutig ist (billig, aber "mehrdeutig" wäre selbst wieder eine feste
Heuristik — genau die Form, die hier abgeschafft wird).

**(c) Reichweite.** Nur Android jetzt, oder gleich iOS/Website/Desktop mit? Die
Tabelle sagt: iOS hat den größten Hebel, aber auch den größten Faktenschicht-Bau.

**(d) Autorisierungsgrenze.** Paseo trennt "Skill starten" von "veröffentlichen
dürfen". HelmDeck kennt nur Accept = deployt. Soll ein *nativer* Ship (20 min,
Versions-Bump, unwiderruflich für installierte APKs) dieselbe Schwelle behalten
wie ein OTA?
