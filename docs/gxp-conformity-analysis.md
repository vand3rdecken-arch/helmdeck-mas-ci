# GxP-Konformität von HelmDeck — Gap-Assessment

> **Status:** Analyse, kein Umbau. Erstellt 2026-08-23 gegen Commit `3c184d3`
> (Branch `chat-gxp-konformität-für-helm`, App 1.0.19 / versionCode 59).
> Jede Aussage unten ist am Quellcode belegt (`datei:zeile`); die Kernbefunde
> wurden nach der Recherche einzeln am Code nachgeprüft.
>
> **Dieses Dokument ist kein Validierungsdokument.** Es ist die Vorarbeit dazu:
> die ehrliche Bestandsaufnahme, aus der ein Validierungsplan entstehen könnte.

---

## 0. Kurzfassung für den Owner

HelmDeck ist **heute nicht GxP-konform und in seiner aktuellen Betriebsart auch
nicht GxP-konform machbar** — nicht wegen fehlender Features, sondern wegen
eines Konstruktionsprinzips: *fertige Arbeit wartet nicht auf den Owner*
(`cells/copilot/henry_broker.py:46-50`). Genau dieses Prinzip ist das,
was 21 CFR Part 11 und EU-GMP Annex 11 verbieten.

Drei Sätze, die die Lage beschreiben:

1. **Ein LLM darf hier seine eigene Arbeit abnehmen, mergen und deployen.**
   Henry (`henry_broker.py:264-273`), Fast-Track (`sessions.py:757-805`) und
   `auto_accept_green` (`processes.py:290-295`) sind drei unabhängige Pfade,
   auf denen Code ohne menschliche Freigabe auf das Telefon kommt.
2. **Das Gate, das das verhindern soll, prüft zwei Dinge: ob Python parst und
   ob der Daemon importiert** (`tools/run_gate.py:45-57`). Bei Änderungen
   außerhalb von `daemon/` gibt es *"nothing to run on this branch - PASS"*
   (`run_gate.py:59-61`). Es gibt keinen automatisch laufenden Test — nirgends.
3. **Der Audit-Trail ist Konvention, nicht Mechanik.** Kein Hash-Chain, keine
   Signatur, kein Trigger; `tools/reset.py:64` enthält ein `DELETE FROM events`.
   Das gesamte Identitäts- und Rechtemanagement schreibt **null** Audit-Einträge
   (`spine/auth/auth.py` importiert `events` nicht).

Gleichzeitig — und das ist der eigentlich interessante Teil — hat HelmDeck
**mehr regulierungsnahe Substanz als die meisten Systeme dieser Größe**:
Append-only-Ereignissenke, Flight-Recorder pro Karte, Worktree-Isolation,
Gate-vor-Review als Architekturprinzip, ein Checkpoint-/Rollback-Mechanismus
und ein ungewöhnlich ehrliches Schuldenregister mit 25 offenen, selbst
deklarierten Abkürzungen (`spine/registry/debt.py`). Die *Architektur*
einer unabhängigen Prüfstufe ist vorhanden. Ausgehöhlt wurde ihr *Inhalt*.

Die belastbare Schlussfolgerung: **Der Weg zu GxP führt nicht über hundert
Bugfixes, sondern über einen zweiten Betriebsmodus** — siehe §7.

---

## 1. Scope und regulatorische Grundlage

Geprüft wurde gegen:

| Regelwerk | Relevanz hier |
|---|---|
| **21 CFR Part 11** (FDA, Electronic Records / Electronic Signatures) | §11.10 Kontrollen für geschlossene Systeme, §11.50/11.70 Signaturmanifestation und -bindung, §11.200/11.300 Signatur- und Passwortkontrollen |
| **EU GMP Annex 11** (Computerised Systems) | §4 Validierung, §7 Datenspeicherung, §9 Audit Trail, §10 Change Control, §12 Sicherheit |
| **GAMP 5 (2nd ed.)** | Kategorisierung, V-Modell, Lieferantenbeurteilung, Critical Thinking |
| **ALCOA+** | Attributable, Legible, Contemporaneous, Original, Accurate + Complete, Consistent, Enduring, Available |

### 1.1 Zwei völlig verschiedene GxP-Rollen — die Unterscheidung entscheidet alles

Bevor irgendeine Lücke bewertet werden kann, muss geklärt sein, **in welcher
Rolle** HelmDeck in einem regulierten Umfeld stünde. Es gibt zwei, und sie
haben stark unterschiedliche Anforderungsprofile:

**Rolle A — HelmDeck hält selbst GxP-Datensätze.**
Ein Pharma-Kunde führt Aufgaben, Freigaben und Nachweise in HelmDeck. Dann ist
HelmDeck ein regulated system: Part 11 und Annex 11 gelten vollumfänglich und
direkt. Elektronische Unterschriften, Audit Trail Review, Benutzerverwaltung
nach §11.300 — alles Pflicht.

**Rolle B — HelmDeck baut GxP-regulierte Software (oder betreibt Prozesse, die
GxP-Datensätze berühren).**
HelmDeck ist dann Teil der validierten Toolchain bzw. der SDLC-Umgebung des
Lieferanten. Hier greifen primär GAMP 5 (Entwicklungsprozess, Change Control,
Traceability, Testnachweise) und Annex 11 §10, und der Kunde wird eine
**Lieferantenaudit** durchführen.

**Beide Rollen scheitern heute — aber an unterschiedlichen Stellen.** Rolle A
scheitert an Signatur/Identität/Audit-Trail (§3, §4, §5). Rolle B scheitert an
Validierung/Change-Control (§6). Die realistischere Markteintrittsrolle ist
**B**, und sie ist auch die deutlich billigere: dort ist der Sollzustand ein
*dokumentierter, nachvollziehbarer Entwicklungsprozess*, nicht ein
signaturfähiges Records-System.

### 1.2 GAMP-5-Kategorisierung

HelmDeck ist **Kategorie 5 (custom application)** — kundenspezifisch
entwickelte Software ohne etablierte Marktbasis. Das ist die aufwendigste
Kategorie: volle Spezifikations- und Testtiefe, Lieferantenaudit, Design Review.

Erschwerend: die Arbeitskraft ist ein **nichtdeterministisches LLM**. GAMP 5
2nd ed. behandelt KI/ML in Appendix D11 und verlangt für lernende/
probabilistische Komponenten ausdrücklich zusätzliche Kontrollen
(Datenintegrität des Trainings-/Prompt-Kontexts, Reproduzierbarkeit,
Performance-Monitoring). HelmDeck erfüllt davon derzeit nichts: die Modell-IDs
sind gleitende Aliase ohne Snapshot-Pinning (`spine/agent/turnopts.py:24-30`),
und die Prompts/Briefs, die das Verhalten bestimmen, werden **nirgends
versioniert oder am Turn-Ereignis mitgeschrieben**.

---

## 2. Gesamtbewertung nach Bereich

| Bereich | Reifegrad | Kernproblem |
|---|---|---|
| **Audit-Trail** | 🟠 teilweise | Inhaltlich reich, mechanisch ungeschützt, große Abdeckungslücken, keine Review-/Exportfunktion |
| **Datensicherheit** | 🔴 unzureichend | Alles im Klartext at rest, HTTP als Default, keine Brute-Force-Bremse, unsignierte OTA-Updates |
| **Nutzerverwaltung** | 🔴 unzureichend | Keine E-Signatur, keine Deaktivierung, Namen wiederverwendbar, Desktop-App loggt ohne Credential als Owner ein |
| **Validierung** | 🔴 unzureichend | Gate prüft Syntax + Import; kein automatischer Test; vier Pfade ohne Review in Produktion |

Skala: 🟢 konform · 🟡 kleine Lücken · 🟠 wesentliche Lücken · 🔴 nicht konform

---

## 3. Audit-Trail

### 3.1 Was vorhanden ist (und funktioniert)

Die Ereignissenke `spine/storage/events.py:175-191` schreibt jedes
Ereignis **doppelt**: als Zeile nach `daemon/events.jsonl` und per
Write-through in die SQLite-Tabelle `events`
(`spine/storage/db.py:68-72`). Rund 30 Ereignisarten sind instrumentiert:
`filed`, `edit`, `archive`, `delete`, `lane`, `gate`, `merge`, `done`, `touch`,
`turn`, `reconfig`, `harness`, `checkpoint`, `connector`, `import`, `process`,
`escalation`.

Zusätzlich existiert pro Karte ein **Flight Recorder**
(`spine/ops/actionlog.py`): `recordings/<id>/actions.jsonl`, plus bei
Desktop-steuernden Treibern eine Bildschirmaufzeichnung (`screen.mp4`).

Das ist deutlich mehr als üblich. Das Problem ist nicht die Menge, sondern die
Schutzwirkung und die Lücken.

### 3.2 Befunde

**GXP-A1 — Append-only ist Konvention, nicht Mechanik. [KRITISCH]**
Es gibt keinen `CREATE TRIGGER`, keine Hash-Kette, kein `prev_hash`, keine
Signatur, kein WORM-Medium. `db.conn()` (`db.py:28-35`) gibt eine
uneingeschränkte SQLite-Verbindung heraus; jeder In-Process-Code kann
`UPDATE events` oder `DELETE FROM events` ausführen. Und genau das ist
mitgeliefert: `tools/reset.py:61-68` enthält `c.execute("DELETE FROM events")`.
Die Behauptung in `cells/engineer/cardadmin.py:66` (*"The audit trail is
NOT deletable - events and the recording stay"*) ist am Code widerlegt.
→ *Part 11 §11.10(c),(e); Annex 11 §9*

**GXP-A2 — Das gesamte Identitätsmanagement ist unauditiert. [KRITISCH]**
`spine/auth/auth.py` importiert `events` nicht und emittiert null
Ereignisse (verifiziert: `grep -c emit` → 0). Damit erzeugen **keine** Spur:
Benutzer anlegen (`auth.py:61-74`), Benutzer löschen (`auth.py:76-83`),
Passwort ändern (`auth.py:85-94`), **Rollenwechsel** (`auth.py:96-105`),
Token ausstellen (`auth.py:109-119`), Token widerrufen (`auth.py:121-127`),
Login, Logout und **fehlgeschlagener Login** (`auth.py:131-143`). Eine
Rechteausweitung von `client` auf `owner` ist im System unsichtbar.
→ *Part 11 §11.10(e), §11.300(d); Annex 11 §12.4*

**GXP-A3 — Die beiden freigaberelevantesten Ereignisse tragen keinen Akteur. [KRITISCH]**
Verifiziert am Code: `events.emit("done", tid, mode=…, ai_cost=…, value=…,
models=…, tokens_in=…, tokens_out=…)` (`lanemachine.py:843-845`) und
`events.emit("lane", tid, frm=prev, to=lane)` (`lanemachine.py:913`) enthalten
**kein `actor`-Feld**. Wer eine Karte abgenommen hat, ist nur durch zeitliche
Korrelation mit dem unmittelbar davor emittierten `touch`-Ereignis
(`lanemachine.py:840`) erschließbar — bei Sekundenauflösung in Lokalzeit und
paralleler Abnahme mehrdeutig. Der Kartendatensatz selbst speichert **weder
`created_by` noch `accepted_by`** (`dispatch.py:62-81`, `lanemachine.py:849-854`).
→ *ALCOA+ „Attributable"; Part 11 §11.10(e)*

**GXP-A4 — Der Akteur ist über den Request-Body fälschbar. [HOCH]**
Verifiziert: `routes_policy.py:20-32` nimmt den authentifizierten Benutzer
entgegen, schreibt aber `actor=body.get("actor") or "user"` in den Audit-Trail.
Schlimmer ist `routes_policy.py:45-53`: `/reconfig/track` emittiert `op`,
`pluginId`, `actor`, `replaced`, `note` **direkt aus dem Request-Body** in die
Ereignissenke — ein Endpunkt, über den jeder Owner/Operator beliebigen Inhalt
in den „append-only" Audit-Trail injizieren kann. Nur `by=user["name"]` ist
belastbar.

**GXP-A5 — Jeder Neustart dupliziert Ereignisse und vernichtet das JSONL-Archiv. [HOCH]**
Verifiziert: `db._migrate()` (`db.py:110-128`) läuft bei **jedem** Boot
(`server.py:444`), importiert `events.jsonl` mit einem einfachen `INSERT` (keine
UNIQUE-Constraint auf der Tabelle) und benennt die Datei anschließend nach
`.imported` um. Da `emit()` (`events.py:178`) die Datei im laufenden Betrieb neu
anlegt, werden beim nächsten Boot **alle Ereignisse der Vorsitzung erneut
eingefügt** — sie stehen dann doppelt in der Tabelle, aus der ausschließlich
gelesen wird (`events.read_events()` → `db.events_all()`). Zusätzlich
überschreibt `os.replace(ej, ej + ".imported")` das Archiv des vorletzten
Laufs. Der Kommentar bei `events.py:184` (*"the jsonl append above is the
durable record regardless of db state"*) ist damit unzutreffend. Folgewirkung:
alle abgeleiteten Kennzahlen (Kosten, Token, Gate-Statistik) sind überhöht.
→ *ALCOA+ „Accurate", „Complete"*

**GXP-A6 — Es gibt keine Audit-Trail-Review-Funktion. [KRITISCH für Rolle A]**
Kein `/events`, kein `/audit`, keine Route liefert die Ereignisliste. Was
existiert, sind Aggregate (`/dashboard/data`), eine auf `kind=="turn"` gefilterte
Kartenansicht (`routes_tracks.py:55-56`) und der Checkpoint-Browser. Keine
Filterung nach Akteur/Zeitraum/Datensatz, kein Export, keine druckbare Kopie,
keine Nur-Lese-Prüferrolle. Annex 11 §9 („regelmäßig zu überprüfen") und §8
(„lesbare Kopien") sind mit der ausgelieferten Software nicht erfüllbar.

**GXP-A7 — Zeitstempel sind Lokalzeit ohne Zone. [HOCH]**
`time.strftime("%Y-%m-%d %H:%M:%S")` (`events.py:176`) — kein UTC, kein Offset.
`utcnow`/`timezone.utc` kommen im gesamten Audit-Pfad nicht vor. Besonders
irreführend: `escalations.py:25` formatiert `%Y-%m-%dT%H:%M:%S` — sieht aus wie
ISO-8601, ist aber Lokalzeit ohne `Z`. `actionlog.py:18` speichert `%H:%M:%S`
**ohne Datum**. Dauerberechnungen subtrahieren formatierte Lokalzeit-Strings
(`events.py:363-381`) und liefern über eine DST-Umstellung negative Werte. Die
Agenten-Transkripte hingegen sind UTC — die Diskrepanz ist im Code vermerkt
(`claude_transcript_fmt.py:100`).

**GXP-A8 — Kein „Grund der Änderung", kein Vorher-Wert. [HOCH]**
Außer `reconfig` (`policy.py:113`, mit `before`/`after`) speichert kein
Ereignis den Zustand vor der Änderung. Ein Karten-`edit` (`cardadmin.py:142`)
schreibt nur die neuen Werte. Ein Feld für den Änderungsgrund existiert
nirgends im Schema. → *Annex 11 §9; Part 11 §11.10(e)*

**GXP-A9 — Weitere unauditierte Zustandsänderungen. [HOCH]**
Nicht instrumentiert sind unter anderem: alle Einstellungsänderungen
(`events.save_settings`, `events.py:149-173` — emittiert nichts; nur bei den
fünf `SIGNIFICANT_SETTINGS` entsteht ein Checkpoint), Projekt-CRUD inklusive
Hard-Delete (`projects.py:69-73`), Entfernen eines Anhangs
(`cardadmin.py:263-274`), Prozessschritt-Änderungen (`processes.py:142-167`),
**erfolgreiche Deployments** (`_repo_hook(t,"deploy")`) und die Zerstörung von
Worktrees (`worktrees.py:61-142` emittiert kein einziges Ereignis).

**GXP-A10 — Aufzeichnungen sind für jeden angemeldeten Benutzer lesbar. [HOCH]**
`routes_runs.py` enthält **keine** Rollenprüfung. Jeder authentifizierte
Benutzer — auch ein selbstregistrierter `client` — kann alle Runs auflisten und
jede Bildschirmaufzeichnung und Timeline herunterladen. Zum Vergleich: die
Karten-Routen filtern Clients sauber auf eigene Karten
(`routes_tracks.py:27-28` u. a.).

**GXP-A11 — Keine Aufbewahrung, keine Archivierung, kein Backup. [HOCH]**
Es gibt keinerlei Retention-Code für Audit-Daten. Alle audit-relevanten Dateien
sind git-ignoriert, existieren einfach vorhanden auf **einem** Host, ohne
geplantes Backup, ohne Integritätsprüfung, ohne Restore-Test. `db.py:32-33`
setzt `synchronous=NORMAL` — bei Stromausfall können zuletzt bestätigte
Transaktionen verloren gehen. → *Part 11 §11.10(c); Annex 11 §7.2*

**GXP-A12 — Stille Datenvernichtung an mehreren Stellen. [MITTEL–HOCH]**
- `copilot.py:428` — der Board-Chat wird pro Benutzer auf die **letzten 80
  Nachrichten** gekürzt. Genau dort werden Karten beauftragt und Freigaben
  ausgesprochen. Kein Archiv.
- `sessions.py:369` u. a. — `session_chain[-6:]`: das siebtälteste Transkript
  einer Karte verliert seine Verknüpfung dauerhaft.
- `checkpoints.py:36-39` — Konfigurations-Snapshots werden bei 60 stumm
  gelöscht; da Einstellungsänderungen *nur* als Checkpoint erfasst werden
  (GXP-A9), verschwindet mit dem 61. Snapshot der Nachweis des ersten.
- `worktrees.py:30` prüft mit `--untracked-files=no` — **unversionierte
  Agenten-Artefakte werden bei jeder normalen Abnahme mitgelöscht**; der
  Orphan-Pfad `worktrees.py:121-140` löscht per `rmtree(..., ignore_errors=True)`
  ganz ohne Dirty- oder Merge-Prüfung.
- `lanemachine.py:659,689,…,850` — `tt.pop("gate_report")` / `pop("merge_report")`:
  **der Grund, warum eine Karte abgelehnt wurde, wird beim nächsten
  Zustandswechsel aus dem Datensatz entfernt.**

> **Nebenbefund, der zufällig schützt:** `tools/reset.py:66` bildet den Pfad
> `os.path.join(ROOT, "events.jsonl")` mit `ROOT` = Repo-Wurzel
> (`reset.py:20-21`), während die Datei tatsächlich unter `DAEMON_ROOT` liegt
> (`events.py:15` + `paths.py:19`). Der Pfad existiert nie. Die SQLite-Tabelle
> wird gelöscht, das JSONL überlebt — und wird beim nächsten Boot teilweise
> wieder importiert. Der Zustand nach einem Reset ist nicht deterministisch.

---

## 4. Datensicherheit

### 4.1 Was solide ist

- **Passwort-Hashing:** PBKDF2-HMAC-SHA256, 200 000 Iterationen, 16-Byte-Salt,
  `hmac.compare_digest` (`auth.py:37-48`). Fachlich korrekt.
- **Relay-Verschlüsselung:** echtes Zero-Knowledge. NaCl-Box (Curve25519 +
  XSalsa20-Poly1305), versiegelt **vor** dem Relay; das Relay hält keinen
  Schlüssel und persistiert nichts (`relay/relay.py:5-16`).
- **Cloudflare Worker (Glasses):** Pfad-Allowlist, `Cookie`/`Authorization`
  werden upstream entfernt, `set-cookie` downstream, Body-Caps, `redirect:
  manual` (`glasses/worker/src/index.js:26-73`). Sauber gebaut.
- **TLS, wenn aktiviert, schließt richtig:** mit Zertifikat weicht Klartext-HTTP
  auf Loopback zurück, ein defektes Zertifikat degradiert **nicht**, sondern
  fällt auf Loopback (`server.py:496-512`); TLS-Minimum 1.2 (`server.py:501`).
- **`.gitignore`-Abdeckung** für Secrets ist gut, und `deploy/publish_source.sh:170`
  hat einen Secret-Scanner.

### 4.2 Befunde

**GXP-S1 — Alles at rest im Klartext. [KRITISCH]**
`helmdeck.db` ist eine unverschlüsselte SQLite-Datei (`db.py:31-33`, kein
SQLCipher). `users.json` enthält **alle Device-Tokens im Klartext**
(`auth.py:113-118`) — sie werden nie gehasht. `settings.json` enthält den
privaten Curve25519-Schlüssel des Daemons (`relay.sk`), `glance_token`,
`registration.invite_code`, `jira.api_token`. `fcm_service_account.json` enthält
einen RSA-Privatschlüssel. Kein `os.chmod`, keine ACL, kein KMS, keine
Schlüsselrotation. Und: `checkpoints.py:24-29` kopiert `settings.json` in jeden
Checkpoint → bis zu **60 historische Kopien jedes je gesetzten Secrets**.
→ *Annex 11 §12.1; Part 11 §11.10(c)*

**GXP-S2 — Klartext-HTTP ist der Default und der dokumentierte Telefonpfad. [KRITISCH]**
Ohne Zertifikat bindet der Server auf `0.0.0.0:8140` im Klartext
(`server.py:496`, `:515`). Das Session-Cookie trägt `HttpOnly; SameSite=Lax`,
aber **kein `Secure`** (`server.py:129-130`). Das mitgelieferte Zertifikat ist
selbstsigniert (`tools/make_tls_cert.py`), wird von iOS/Android abgelehnt — was
strukturell dazu führt, dass der reale Betrieb auf Klartext bleibt: `DEPLOY.md:517-524`
beschreibt als unterstützten Weg, die PC-IP in die Cleartext-Allowlist
einzutragen. Ein permanenter Bearer-Token wandert damit unverschlüsselt durchs LAN.

**GXP-S3 — Unsignierte OTA-Updates. [KRITISCH für Rolle B]**
`relay.py:382-383`: *"Unsigned JSON is valid per the spec (code signing
optional)"*. Wer den Relay-Host oder das Update-Verzeichnis kontrolliert, kann
**beliebiges JavaScript still in jede installierte App ausliefern**. Für die
Validierung ist das der Totalschaden: die laufende Version ist nicht die
validierte Version, und sie lässt sich auch nicht als solche nachweisen.
→ *Annex 11 §10; GAMP 5 Change Control*

**GXP-S4 — Keine Brute-Force-Bremse, keine Sperre, kein Sicherheits-Log. [HOCH]**
Kein Lockout, kein Fehlversuchszähler, kein Rate-Limit, keine Verzögerung
(`auth.py:131-140` gibt bei Fehlschlag `None` zurück und protokolliert nichts).
HTTP-Zugriffs-Logging ist explizit abgeschaltet (`server.py:75`). Damit ist ein
Brute-Force-Angriff gegen ein Minimum von 8 Zeichen weder gebremst noch
sichtbar. → *Part 11 §11.300(d)*

**GXP-S5 — Secret-Offenlegung an die niedrigste Rolle. [HOCH]**
Verifiziert: `checkpoints_diff_get` (`routes_checkpoints.py:21-26`) nimmt `user`
entgegen und **prüft die Rolle nie** — im Gegensatz zur Restore-Route direkt
darunter. Dispatch bei `server.py:261-263` liegt hinter der generischen
401-Prüfung, aber vor jeder Rollenprüfung. `checkpoints.diff()` liefert
`before`/`after` **im Klartext** für jedes geänderte Einstellungsfeld
(`checkpoints.py:78-93`). Jeder angemeldete Benutzer, auch ein selbst
registrierter `client`, kann damit `relay.sk`, `glance_token` und
`registration.invite_code` auslesen.

**GXP-S6 — Token im URL-Query-String. [HOCH]**
`server.py:96-97` extrahiert den Token per `self.path.split("token=")[1]` — ein
naives Substring-Verfahren, keine Query-Analyse. Vollprivilegierte Tokens landen
damit in Proxy-Logs, Browser-History und `Referer`-Headern; vor dem Daemon
stehen Cloudflare Tunnel und ein Worker.

**GXP-S7 — Der Connector-„Sandbox" ist ein Lint, keine Sicherheitsgrenze. [HOCH]**
`spine/auth/charter.py:34-46` ist eine Liste von 11 Regex-Mustern, die
einmalig bei der Installation über den Quelltext laufen. Die „Laufzeit-Sandbox"
(`connectors.py:116-129`) ist ein `subprocess` **mit den vollen Rechten des
Daemon-Benutzers**, vollem Dateisystem- und Netzzugriff und geerbtem
`os.environ`; einzige Grenze ist ein 90-Sekunden-Timeout. Die Regexe sind
trivial umgehbar (`importlib` statt `subprocess`, `os.getenv` statt
`os.environ`, `pathlib.write_text` statt `open(…,"w")`), und die Regel gegen
Kern-Importe (`charter.py:43-44`) matcht noch die **alten flachen Modulnamen**
und ist gegen die heutige `spine.*`-Struktur wirkungslos. Zudem führt
`connectors.py:100-113` beim Auflisten `exec_module` **im Daemon-Prozess** aus —
die Out-of-Process-Zusage gilt nur für `run()`.

**GXP-S8 — Shell-Ausführung aus Konfiguration. [HOCH]**
`settings.drivers[].command` wird mit `shell=True` ausgeführt
(`drivers.py:990`), ebenso die Repo-Hooks `preview`/`deploy`
(`lanemachine.py:70`, `:497`). Das ist eine RCE-Primitive per Konfiguration —
und die Konfiguration liegt außerhalb der Versionskontrolle.

**GXP-S9 — Maschinenaufgaben: `bypassPermissions` über das ganze Dateisystem als Default. [KRITISCH]**
`dispatch.py:264-275`: `perm = "bypassPermissions"`, `roles = ["owner"]`,
`roots = []` → `machine_root_ok()` gibt bedingungslos `True` zurück. Treiber ist
zwangsweise `claude-desktop` mit `mcp__windows-mcp__*` (volle Maus-, Tastatur-
und Bildschirmkontrolle). Der freie Aufgabentext geht ungefiltert in den
Agenten-Prompt — es gibt **keine Injektionsgrenze zwischen Board-Inhalt und
Agenten-Anweisung**. Selbst deklariert als offene Schuld
`machine-task-blast-radius` (`debt.py:291-320`).

**GXP-S10 — Kein Backup, keine Integritätsprüfung, kein Restore-Test. [HOCH]**
Kein `PRAGMA integrity_check` im gesamten Daemon, kein geplantes Dump, kein
WAL-Archiving, kein Offsite. Checkpoints schließen die Nutzdaten explizit aus
(`checkpoints.py:6-8`: *"Work data (tracks, events, recordings) is never part of
a restore"*). Kein dokumentiertes RTO/RPO.

**GXP-S11 — Datenschutzerklärung widerspricht dem Code. [HOCH, GDPR-relevant]**
`relay/relay.py:95` und `:117` sagen zu: *"keine Werbung und keine Analyse-/
Tracking-SDKs"* und *"Nicht verarbeitet werden: … Analysedaten"*. Die App liefert
`posthog-react-native` mit (`app/package.json:37`) und ist **Opt-out mit
Default an** (`app/src/data/analytics.ts:46`). Zusätzlich überträgt
`loops_client.py:40-66`, ausgelöst aus der unauthentifizierten
Registrierungsroute (`routes_auth.py:60-65`), **E-Mail-Adresse und Vornamen**
neuer Nutzer an Loops.so — ohne Einwilligung und ohne Erwähnung in der
Erklärung. Das ist unabhängig von GxP zu korrigieren.

**GXP-S12 — Unbegrenzter Anthropic-Egress. [HOCH, vertraglich]**
Über `drivers.build_argv` (`drivers.py:352-374`) verlässt praktisch alles das
Haus: vollständige Repository-Inhalte, Kartentexte, Chat, gelesene Dateien,
Anhänge, Screenshots. Kein DPA modelliert, keine Region-Pinning, kein
Zero-Retention-Flag, keine Redaktionsschicht. Für einen Pharma-Kunden ist das
der erste Punkt jeder Lieferantenprüfung.

**GXP-S13 — Bildschirm- und Tastaturaufzeichnung ohne Maskierung. [HOCH]**
`media/wincap.py:50` nimmt per `gdigrab -i desktop` den **gesamten Bildschirm**
auf, nicht das App-Fenster — inklusive allem, was gerade sichtbar ist.
`ops/teach.py:41-45` protokolliert zusätzlich **jeden Tastenanschlag** im
Klartext nach `actions.jsonl`, ohne Passwortmaskierung. Diese Dateien liegen
unverschlüsselt, unklassifiziert und ohne Aufbewahrungsregel im Run-Ordner.

---

## 5. Nutzerverwaltung und elektronische Unterschriften

### 5.1 Der zentrale Befund

**Es existiert keinerlei elektronische Unterschrift.** Eine Suche über
`daemon/` und `app/src/` nach `signature`, `re-auth`, `four-eyes`,
`Vier-Augen` liefert im gesamten Auth- und Abnahmepfad null Treffer.

Der Abnahmevorgang — das Äquivalent einer QA-Freigabe — ist:
`routes_track_actions.py:128-147` prüft **keine Rolle**, verlangt **keine
Re-Authentifizierung**, fordert **keine Begründung** und startet die Abnahme in
einem Hintergrund-Thread. Auf der Oberfläche ist es ein einzelner Tap:
`app/src/ui/board.tsx:594-597` (`NextUp onDone` → `api.moveLane(k.id,"done")`)
merged und deployt die Karte ohne Rückfrage. Zum Vergleich: das *Löschen eines
Benutzers* zeigt einen Bestätigungsdialog (`settings.tsx:248`).

Gegen 21 CFR §11.50(a) geprüft:

| Gefordert | Vorhanden |
|---|---|
| (1) Gedruckter Name des Unterzeichners | ✗ nur als `actor` auf **einem** `touch`-Ereignis; das `done`-Ereignis trägt ihn nicht |
| (2) Datum und Uhrzeit | ~ Lokalzeit ohne Zone, und es ist die Emit-Zeit eines Hintergrund-Threads, nicht die Klickzeit |
| (3) **Bedeutung** (approved / reviewed / rejected) | ✗ **vollständig abwesend** — die Bedeutung wird aus `lane == "done"` erschlossen; kein Feld, keine Auswahl, kein Freitext |
| §11.70 Signatur-Datensatz-Bindung | ✗ eine Zeile in einer Textdatei, keine kryptografische Bindung; das Entfernen ist nicht feststellbar |
| §11.200(a)(1)(ii) Re-Authentifizierung beim Signieren | ✗ |

### 5.2 Weitere Befunde

**GXP-U1 — Ein LLM darf abnehmen, mergen und deployen. [KRITISCH — der Kernkonflikt]**
Verifiziert: `henry_broker.py:264-273` startet `sessions.move_lane(t["id"],
lane, kwargs={"actor": "henry"})` für `lane in ("review","done")`. Der
Handlungsverb stammt aus einem **modellgenerierten JSON-Blob**, das per
`re.search(r"\{.*\}", txt, re.S)` (`:92-95`) aus Freitext geparst wird. Die
Policy weist Henry ausdrücklich an, selbst abzunehmen (`:46-50`: *"Fertige
Arbeit wartet nicht auf den Owner"*), und er läuft unbeaufsichtigt im
90-Sekunden-Takt. Verschärfend: der Karten-Actionlog, den Henry zur Beurteilung
vorgelegt bekommt (`:203`, `:208`), enthält agenten- und ownergeschriebenen
Text — **Inhalt, den Henry bewerten soll, kann Henry anweisen, abzunehmen**
(Prompt-Injection in den Freigabepfad).
`actor="henry"` ist kein Benutzer in `users.json`, hat keine Rolle und ist nicht
authentifiziert. → *Part 11 §11.10(d),(g),(h); Annex 11 §2*

**GXP-U2 — LLM-Aktionen werden unter dem Namen des Menschen protokolliert. [KRITISCH]**
`copilot.py:1055` → `copilot_actions.py:209-210`: eine vom *Modell* beschlossene
Aktion wird mit `actor = <Login-Name des chattenden Menschen>` in den
Audit-Trail geschrieben. Ein Prüfer kann nicht unterscheiden zwischen „der
QA-Leiter hat freigegeben" und „das LLM hat freigegeben, während der QA-Leiter
etwas anderes fragte". Das macht den Audit-Trail nicht nur unvollständig,
sondern **aktiv irreführend** — regulatorisch schlimmer als eine Lücke.

**GXP-U3 — Die Desktop-App meldet sich ohne Credential als Owner an. [KRITISCH]**
Verifiziert: `desktop/main.js:292-306` ruft bei jedem Start
`python -m spine.auth.mint_token owner desktop` auf und injiziert
`{baseUrl, token}` in den SPA-URL-Fragment (`:367-373`); `app/src/data/config.ts:94-96`
übernimmt es. **Das Öffnen der Desktop-App ist ein Owner-Login ohne jede
Authentifizierung.** Die wichtigste Zugangskontrolle des Systems fehlt auf
seiner Hauptoberfläche. → *Part 11 §11.10(d), §11.300*

**GXP-U4 — Benutzernamen sind nach dem Löschen wiederverwendbar. [KRITISCH]**
`auth.py:69` prüft Eindeutigkeit nur gegen *aktuell existierende* Benutzer;
`auth.py:76-83` entfernt den Datensatz physisch, ohne Tombstone. Ein neu
angelegter „alice" erbt damit stillschweigend die gesamte historische
Zuordnung der alten „alice" im Audit-Trail. → *Part 11 §11.300(a) —
ausdrücklich: keine zwei Personen dürfen dieselbe Kennung führen*

**GXP-U5 — Keine Deaktivierung, nur Zerstörung. [HOCH]**
Es gibt kein `active`/`disabled`/`locked`-Feld. Off-Boarding heißt: Identität
löschen — und damit die Nachvollziehbarkeit beschädigen (GXP-U4).
→ *Annex 11 §12.3*

**GXP-U6 — Der Owner kann jedes Passwort setzen und jeden Token prägen. [HOCH]**
`server.py:321-335` erlaubt dem Owner, das Passwort jedes Benutzers zu setzen
(`auth.py:85-94`) und für jeden Benutzer Tokens auszustellen
(`auth.py:109-119`); `server.py:195-199` gibt zudem **alle Tokens aller
Benutzer im Klartext** zurück. Damit kann der Owner unter fremder Identität
handeln und Datensätze erzeugen. Die von §11.300(a)/(b) geforderte Eigenschaft
„nur der Kontoinhaber kennt sein Passwort" existiert nicht.

**GXP-U7 — Tokens laufen nie ab und überleben den Logout. [HOCH]**
Kein `expires`-Feld, keine TTL-Prüfung (`auth.py:114-117`, `:154-158`), keine
Scope-Begrenzung — ein Token authentifiziert *als der Benutzer mit dessen voller
Rolle*. **Jeder Login prägt einen weiteren permanenten Token**
(`routes_auth.py:38`, `:69`, `:87`), und `logout` löscht nur die Session, nicht
den Token (`routes_auth.py:91-95`). Selbst deklarierte offene Schuld:
`pair-token-no-ttl` (`debt.py:270-288`).

**GXP-U8 — Keine Funktionstrennung, kein Vier-Augen-Prinzip. [KRITISCH]**
Niemand vergleicht, wer eine Karte bearbeitet hat, mit dem, der sie abnimmt —
`routes_track_actions.py:128-147` liest die Karte vor der Aktion gar nicht.
Vier-Augen-Kontrollen existieren im gesamten Code nicht. Die Route hat zudem
**keine eigene Rollenprüfung**: ein `operator` kann jede Karte abnehmen.

**GXP-U9 — `_load()` fällt bei defekter `users.json` offen aus. [HOCH]**
`auth.py:20-27` fängt `ValueError` und liefert `[]`. Eine abgeschnittene Datei
präsentiert sich damit als „keine Benutzer", was `/auth/state` auf
`setup_needed` schaltet und `/auth/setup` (`routes_auth.py:26-29` prüft nur
`if auth.list_users()`) **für jeden unauthentifizierten Aufrufer öffnet** — der
dann Owner wird.

**GXP-U10 — Einladungscode: statisch, geteilt, unbegrenzt, unbefristet. [MITTEL]**
Ein einziger String in den Einstellungen (`events.py:82`), wird bei Nutzung
nicht verbraucht (`routes_auth.py:48-51`), hat keine TTL, ist nicht
personengebunden und erzeugt beim Registrieren kein Ereignis. `registration.open`
schaltet die Anmeldung vollständig frei.

**GXP-U11 — Passwortrichtlinie: 8 Zeichen. [MITTEL]**
`auth.py:66-67` und `:86-87` — das ist die gesamte Richtlinie. Keine
Komplexität, keine Historie, kein Ablauf, kein erzwungener Wechsel.
Session-TTL 30 Tage (`auth.py:17`), **kein Inaktivitäts-Timeout**; das Docstring
behauptet „sliding", `resolve()` (`auth.py:145-162`) aktualisiert `expires`
jedoch nie. → *Annex 11 §12.3*

**GXP-U12 — Das Rechtemodell ist nicht spezifizierbar. [HOCH für Validierung]**
Es gibt keine Berechtigungsmatrix. Durchsetzung sind ~60 verstreute
`if user["role"] != "owner"`-Vergleiche über 15 Routenmodule; `operator` ist
**ausschließlich durch Auslassung definiert**. Ein Prüfer kann den
Berechtigungsumfang nur durch Lesen jeder einzelnen Route ermitteln — eine
Spezifikation, gegen die getestet werden könnte, ist so nicht erstellbar.
Zusätzlich sind freigaberelevante Schwellen **per Chat änderbare Daten**:
`chat_admin_roles` steuert Move/Delete/Archive/Fast-Track
(`copilot_actions.py:205-272`), `auto_accept_green` und `machine.roles` liegen
in `settings.json`.

---

## 6. Validierung, Test und Change Control

### 6.1 Das Gate — verifiziert am Quelltext

`helmdeck.gate` ruft `tools/run_gate.py`. Der komplette Prüfumfang:

1. `py_compile` über `daemon/**/*.py` — „parst es?" (`run_gate.py:45-48`)
2. `python -c "import daemon.swarm"` — „verdrahtet der Daemon?" (`run_gate.py:55-57`)
3. Lief keine der beiden: `print("gate: nothing to run on this branch - PASS")`
   und `sys.exit(0)` (`run_gate.py:59-61`)

**Konsequenz von (3):** eine Änderung, die nur `app/`, `deploy/`, `docs/`,
`relay/`, `web/` oder `desktop/` berührt — also praktisch die gesamte
Mobil- und Desktop-Oberfläche — **passiert das Gate mit null ausgeführten
Prüfungen**. Die Lints wurden am 2026-08-21 per Dekret entfernt
(`run_gate.py:41-44`).

`ARCHITECTURE.md:17` bezeichnet das Gate als *„QA sign-off"*. Gegen den
tatsächlichen Prüfumfang ist das erheblich überzeichnet.

**GXP-V1 — Es läuft an keiner Stelle automatisch ein Funktions- oder Regressionstest. [KRITISCH]**
Rund 78 Testdateien existieren. Ausgeführt werden sie von: nichts.
`tools/run_suite.py:2-9` sagt es selbst: *„MANUAL tool, nothing schedules or
gates on this … never per card, never on a schedule"*. Von den zwei
CI-Workflows enthält `desktop-mac.yml` **keinen einzigen Testschritt**, und
`mac-e2e-smoke.yml:29-35` ist `workflow_dispatch`-only gegen ein **fest
verdrahtetes Release-Tag `v1.0.7`**, während die App bei 1.0.19 steht. Die
Hooks in `.claude/settings.json` rufen `tools/loop_state.py`, das sich selbst
als *„a state doctor, not a gate"* bezeichnet (`:39`) und **immer 0 zurückgibt**
(`:749`). Git-Hooks sind nicht installiert.
→ *Annex 11 §4.1/§4.8; GAMP 5 V-Modell-Verifikation*

**GXP-V2 — Das Fehlersignal des Gates ist absichtlich aushebelbar. [HOCH]**
`lanemachine.py:84-87` bewertet ein gedrucktes `gate: PASS` **höher als einen
Exit-Code ungleich 0**. Selbst registriert als `gate-exit-code-vs-stdout-verdict`
(`debt.py:527`).

**GXP-V3 — Vier Pfade erreichen Produktion ohne Review. [KRITISCH]**

| Pfad | Branch | Gate | Menschliche Abnahme | Deploy |
|---|---|---|---|---|
| Karte → Review → Done | ja | ja (2 Prüfungen) | ja | automatisch |
| `auto_accept_green` an | ja | ja (2 Prüfungen) | **nein** | automatisch |
| **Fast-Track** | **nein** | **nein** | **nein** | automatisch, **nach jedem Turn** |
| **Direct Task** | **nein** | **nein** | nein (live tree) | automatisch |
| **Henry `did`** | **nein** | **nein** | **nein** | live tree, alle 90 s |
| Maschinenaufgabe | **nein** | **nein** | **nein** | kein Merge-Pfad |

Fast-Track ist explizit so gebaut: `sessions.py:764-767` — *„autocommit only …
→ deploy hook. NO test gate, NO merge"* — und feuert automatisch nach **jedem**
beendeten Turn in einem Hintergrund-Thread (`:805`). Schlägt das Deployment
fehl, steuert `sessions.py:811-840` bis zu drei Reparatur-Turns nach —
**nachdem** die Änderung bereits auf main gemerged ist. Selbst deklariert:
`fast-track-no-gate` (`debt.py:991`), `direct-build-no-gate` (`debt.py:959`),
`henry-direct-hands` (`debt.py:13`) — alle offen.

**GXP-V4 — Keine Requirements-Traceability. [KRITISCH]**
Kein RTM, keine User Requirement Specification, keine Functional/Design Spec,
kein IQ/OQ/PQ, kein Testprotokoll, kein Testbericht. `acceptance.md` enthält
fünf Given/When/Then-Sätze (`:16-27`) — **von keinem Test, keiner Karte und
keiner Release-Notiz referenziert**, datiert 2026-07-19 und inhaltlich veraltet
(beschreibt `web/`, das inzwischen unter `archive/` liegt). Anforderungen leben
als Freitext in einer git-ignorierten Datenbank; eine Karte trägt keine
Requirement-ID und keinen Testverweis. `docs/adr/` enthält **einen** ADR.

**GXP-V5 — Kein Artefakt lässt sich auf einen Commit zurückführen. [KRITISCH]**
Kein `git rev-parse HEAD` in `deploy/*.sh`, kein Build-Fingerprint im
APK/OTA-Bundle, keine SHA in `version.json`, kein SBOM. Mehrere JS-only-OTAs
werden unter **derselben** Version ausgeliefert (`DEPLOY.md:57-58`) — ein
OTA-Bundle ist damit **überhaupt nicht** auf Quellcode abbildbar. Der Daemon
meldet gar keine Version (kein `__version__`, keine `/version`-Route).
→ *Annex 11 §4.3/§10*

**GXP-V6 — Keine Umgebungstrennung. [KRITISCH]**
Ein Daemon, eine Datenbank (`db.py:11`, kein `HELMDECK_DB`, kein
`HELMDECK_ENV`), ein Produktions-OTA-Kanal (`app.json`: `production`, fest
verdrahtet). Worktrees isolieren *Quellcode*, nicht die Umgebung: die Turns
sprechen weiterhin mit demselben Daemon, derselben DB, denselben Einstellungen.
Die Profile `store`/`owner`/`demo`/`headless-companion`
(`app/src/kernel/profiles.ts`) sind UI-Zusammenstellungen, keine Umgebungen.
**Dokumentierter Vorfall:** ein Testlauf schrieb drei Fake-Einträge in die
*echte* `processes.json` und Zeilen in die *echte* `events.jsonl`
(`debt.py:1474-1490`, offen; `test_processes_db_migration.py:7-13,37-40`) —
manuell und unbezeugt bereinigt. → *Annex 11 §4.1/§4.2*

**GXP-V7 — Das werkzeugerzeugende Werkzeug ist unversioniert und nichtdeterministisch. [HOCH]**
Modell-IDs sind gleitende Aliase (`turnopts.py:24-30`), keine
Snapshot-Versionen; die Claude-Code-CLI ist nicht gepinnt. Das Modell **wird**
pro Turn protokolliert (`econ.py:62`, `models=`) — das ist gut. Der **Prompt
nicht**: kein Prompt-Hash, keine Brief-Version am Turn-Ereignis. Eine Änderung
an einem Brief verändert das Verhalten jeder nachfolgenden Karte ohne jede
Audit-Verknüpfung. Modelle sind zudem mitten in einer Sitzung umschaltbar
(`debt.py:180-182`). Das System dokumentiert überdies selbst, dass seine Agenten
Anweisungen nicht zuverlässig befolgen (`ask-protocol-prompt-compliance`,
`debt.py:373`).

**GXP-V8 — Rollback nur teilweise. [HOCH]**
Vorhanden und gut: `deploy/rollback_update.sh` mit drei Stufen und
anschließender Manifest-Prüfung — allerdings **Tiefe 1**. Konfiguration ist über
`checkpoints.py` rollbackfähig (60 tief, Restore selbst wieder
checkpointgesichert). **Nicht rollbackfähig:** alles auf den branchlosen Pfaden
(Fast-Track, Direct, Henry, Maschinenaufgaben) — *„there is no snapshot to roll
back to"* (`debt.py:977-979`). Kein Datenbank-Backup, kein Restore-Test.
Zusätzlich: `merge` pusht nicht (`debt.py:224-226`) — ein Plattenausfall
verliert abgenommene Arbeit.

**GXP-V9 — Die Laufzeitkonfiguration liegt außerhalb der Versionskontrolle. [HOCH]**
`settings.json`, `users.json` und `helmdeck.db` sind bewusst git-ignoriert
(`CLAUDE.md:36-37`) — **einschließlich der Flags, die die menschliche Freigabe
abschalten** (`auto_accept_green`, `repo_hooks.<repo>.deploy`, `machine.roots`,
`chat_admin_roles`). → *Annex 11 §4.3/§7*

**GXP-V10 — Keine kontrollierte Dokumentation. [HOCH]**
Kein SOP, kein Validierungsplan, kein Validierungsbericht, kein IQ/OQ/PQ, kein
Benutzerhandbuch, keine Schulungsnachweise, kein Periodic Review, kein CAPA,
keine Risikobeurteilung, keine Lieferantenbeurteilung. Die vorhandenen
Dokumente sind fachlich stark (`DEPLOY.md` mit 828 Zeilen und echten
Ausführungsnachweisen, `HARNESS.md`, `docs/voice-interaction-design.md`), aber
**ohne Version, ohne Freigabe, ohne Gültigkeitsdatum, ohne Revisionshistorie** —
und teils inhaltlich abgedriftet: `CLAUDE.md:39` verweist auf `daemon/debt.py`,
tatsächlich liegt das Register unter `spine/registry/debt.py`.

**GXP-V11 — Das Schuldenregister widerspricht dem eigenen Gesetz. [Kontext]**
25 offene Einträge (verifiziert). `full-dynamism-decree` (`debt.py:1146`) hält
ausdrücklich fest, dass die Neuausrichtung *„CONTRADICTS the CLAUDE.md law
'never weaken the fixed harness'"* und die Kern-Durchsetzung *„now removed"* ist.
`glasses-native-uncompiled` (`debt.py:2456`) räumt ein, dass nativer Code in
einem Release ausgeliefert wird, **der nie kompiliert wurde**. Und `gate-light`
(`debt.py:2234-2243`) beschreibt die Folge selbst: *„A card can now pass the
gate with a real behavioral regression … it lands on base and deploys
(fast-track) before run_suite.py notices, hours later at best."*

> Dieses Register ist regulatorisch **zweischneidig**: es dokumentiert
> ungewöhnlich ehrlich bekannte Schwächen — was ein Auditor grundsätzlich
> positiv wertet — belegt aber zugleich, dass die Risiken *bekannt* sind und
> ohne CAPA-Prozess bestehen bleiben. Bekannt-und-unbehandelt wiegt in einer
> Inspektion schwerer als unbekannt.

---

## 7. Empfehlung: nicht reparieren, sondern einen zweiten Betriebsmodus bauen

Die 40 Befunde oben einzeln abzuarbeiten wäre teuer und würde HelmDeck
gleichzeitig genau das nehmen, was es auszeichnet: Geschwindigkeit,
Autonomie, Fast-Track. Ein Board, das für jede Bewegung eine Signatur mit
Re-Authentifizierung verlangt, ist kein HelmDeck mehr.

Der Ausweg liegt in der Architektur, die bereits existiert. HelmDeck hat mit
`spine/auth/policy.py` einen **einzigen, getrackten Mutationspfad für
Policy**, mit `policy_seed.json` ein Seed-Konzept und mit dem Charter eine
Stelle, an der etwas „human-only regardless" sein darf. Das ist exakt der
Aufhänger für:

### Ein `gxp`-Profil — ein Policy-Seed, der die schnellen Pfade hart abschaltet

Konkret müsste das Profil folgende Zustände erzwingen und **agentenseitig
unschaltbar** machen (analog zur Capability-Charter-Regel `policy.py:99-102`,
aber diesmal mit echter Durchsetzung, nicht mit einem aufruferseitigen String):

- `fast_track` global aus; `new_direct_task` aus; `machine.enabled` aus
- Henry auf `notify_owner` beschränkt — `move`, `did` und `rerun_deploy` gesperrt
- `auto_accept_green` aus, nicht setzbar
- Gate zwingend mit `run_suite.py` statt der Zwei-Punkt-Prüfung
- Abnahme nur über einen Signaturpfad: Re-Authentifizierung, Bedeutungsauswahl
  (freigegeben/geprüft/abgelehnt), Pflicht-Begründung, und der Signaturblock
  wird **auf dem Kartendatensatz** gespeichert, nicht nur als Seitenereignis
- Vier-Augen: der Akteur der Abnahme darf nicht der Dispatcher der Karte sein

Das ist mit der vorhandenen Cell-/Policy-Mechanik machbar und lässt den
Normalbetrieb unangetastet.

### Reihenfolge — was zuerst zählt

**Stufe 0 (unabhängig von GxP, sollte ohnehin passieren).** Diese Punkte sind
keine Compliance-Kür, sondern echte Mängel im heutigen Betrieb:

1. **GXP-S11** — die Datenschutzerklärung stimmt nicht mit dem Code überein
   (PostHog opt-out-default-an; Loops.so bekommt E-Mail + Vorname bei
   Registrierung). Rechtsrisiko heute, unabhängig von jedem Pharma-Kunden.
2. **GXP-S5** — `checkpoints_diff_get` ohne Rollenprüfung gibt `relay.sk` und
   `glance_token` an jeden `client` heraus. Einzeiler.
3. **GXP-U3** — Desktop-App als Owner ohne Credential.
4. **GXP-A5** — Ereignis-Duplizierung bei jedem Neustart verfälscht alle
   Kennzahlen; die Kostenzahlen im Dashboard sind heute zu hoch.
5. **GXP-A2** — Audit-Ereignisse für Benutzer-/Rollen-/Token-Operationen
   nachrüsten (`auth.py` importiert `events` schlicht nicht).
6. **GXP-S1/S4** — Tokens at rest hashen, Lockout und Fehlversuchs-Logging.

**Stufe 1 — Part-11-Technik** (nur nötig für Rolle A): E-Signatur mit
Bedeutung und Re-Auth, Audit-Trail-Review-Route mit Filter und Export,
UTC-Zeitstempel, Hash-Kette über die Ereignissenke, Vorher-Wert und
Änderungsgrund, Tombstones statt Löschen bei Benutzern, Deaktivierung,
Vier-Augen.

**Stufe 2 — CSV/GAMP 5** (nötig für beide Rollen): Validierungsplan,
URS/FS/DS, RTM, IQ/OQ/PQ, automatisch laufender Regressionstest im Gate,
Umgebungstrennung dev/test/prod, Artefakt-zu-Commit-Traceability,
OTA-Code-Signing, kontrollierte SOPs, CAPA-Prozess für das Schuldenregister.

### Die ehrliche Einschätzung zur Marktfrage

Für **Rolle B** (HelmDeck baut regulierte Software) ist der Abstand
überbrückbar: dort sind die harten Blocker Signierung der Updates (GXP-S3),
Umgebungstrennung (GXP-V6), automatischer Test im Gate (GXP-V1),
Traceability (GXP-V4/V5) und die Abschaltbarkeit der reviewfreien Pfade
(GXP-V3) — durchweg Engineering-Arbeit an Stellen, die HelmDeck ohnehin
schwächen.

Für **Rolle A** (HelmDeck hält GxP-Datensätze) ist der Abstand groß und der
Nutzen fraglich: dort konkurriert HelmDeck mit validierten
Dokumentenmanagement- und QMS-Systemen, und die geforderten Kontrollen
widersprechen dem Produktkern.

**Empfehlung: Rolle B verfolgen, Rolle A vorerst nicht.** Und in jedem
Pharma-Gespräch offenlegen, dass ein LLM ohne menschliche Freigabe deployen
kann, solange das nicht abschaltbar ist — dieser eine Punkt entscheidet die
Lieferantenprüfung, und er kommt sicher zur Sprache.

---

## 8. Befundregister

| ID | Befund | Schwere | Beleg |
|---|---|---|---|
| GXP-U1 | LLM (Henry) nimmt ab, merged, deployt; Verb aus Modell-JSON; prompt-injizierbar | KRITISCH | `henry_broker.py:46-50,92-95,264-273` |
| GXP-V3 | Vier Pfade erreichen Produktion ohne Review | KRITISCH | `sessions.py:757-805`, `debt.py:13,959,991` |
| GXP-V1 | Kein automatisch laufender Funktions-/Regressionstest | KRITISCH | `run_gate.py:45-61`, `run_suite.py:2-9` |
| GXP-U2 | LLM-Aktionen unter dem Namen des Menschen protokolliert | KRITISCH | `copilot.py:1055`, `copilot_actions.py:209-210` |
| GXP-U3 | Desktop-App = Owner-Login ohne Credential | KRITISCH | `desktop/main.js:292-306,367-373` |
| GXP-U4 | Benutzernamen nach Löschen wiederverwendbar | KRITISCH | `auth.py:69,76-83` |
| GXP-U8 | Keine Funktionstrennung, kein Vier-Augen; Abnahmeroute ohne Rollenprüfung | KRITISCH | `routes_track_actions.py:128-147` |
| GXP-A1 | Append-only ist Konvention; `DELETE FROM events` mitgeliefert | KRITISCH | `tools/reset.py:61-68`, `db.py:28-35` |
| GXP-A2 | Identitätsmanagement komplett unauditiert | KRITISCH | `auth.py` (0 × `emit`) |
| GXP-A3 | `done`- und `lane`-Ereignis ohne Akteur | KRITISCH | `lanemachine.py:843-845,913` |
| GXP-A6 | Keine Audit-Trail-Review-/Exportfunktion | KRITISCH (Rolle A) | keine Route vorhanden |
| GXP-S1 | Alles at rest im Klartext, inkl. Tokens und Privatschlüssel | KRITISCH | `auth.py:113-118`, `db.py:31-33`, `checkpoints.py:24-29` |
| GXP-S2 | Klartext-HTTP als Default und dokumentierter Telefonpfad | KRITISCH | `server.py:129-130,496`, `DEPLOY.md:517-524` |
| GXP-S3 | Unsignierte OTA-Updates | KRITISCH | `relay.py:382-383` |
| GXP-S9 | Maschinenaufgaben: `bypassPermissions`, `roots=[]` als Default | KRITISCH | `dispatch.py:264-275`, `debt.py:291` |
| GXP-V4 | Keine Requirements-Traceability, `acceptance.md` veraltet und ungenutzt | KRITISCH | `acceptance.md:16-27` |
| GXP-V5 | Kein Artefakt auf Commit rückführbar; OTA gar nicht | KRITISCH | `deploy/*.sh`, `DEPLOY.md:57-58` |
| GXP-V6 | Keine Umgebungstrennung; dokumentierter Produktionsdaten-Vorfall | KRITISCH | `db.py:11`, `debt.py:1474-1490` |
| — | *keine elektronische Unterschrift überhaupt* | KRITISCH | §5.1 |
| GXP-A4 | Akteur über Request-Body fälschbar; Audit-Injektion via `/reconfig/track` | HOCH | `routes_policy.py:20-32,45-53` |
| GXP-A5 | Neustart dupliziert Ereignisse, vernichtet JSONL-Archiv | HOCH | `db.py:110-128`, `events.py:178-190` |
| GXP-A7 | Zeitstempel Lokalzeit ohne Zone; Fake-ISO; Datum fehlt | HOCH | `events.py:176`, `escalations.py:25`, `actionlog.py:18` |
| GXP-A8 | Kein Vorher-Wert, kein Änderungsgrund | HOCH | `events.py:175-177`, `cardadmin.py:142` |
| GXP-A9 | Settings, Projekte, Deploys, Worktree-Löschung unauditiert | HOCH | `events.py:149-173`, `worktrees.py:61-142` |
| GXP-A10 | Alle Bildschirmaufzeichnungen für jeden Benutzer lesbar | HOCH | `routes_runs.py` (keine Rollenprüfung) |
| GXP-A11 | Keine Aufbewahrung, kein Backup, `synchronous=NORMAL` | HOCH | `db.py:32-33` |
| GXP-S4 | Kein Lockout, kein Rate-Limit, kein Sicherheits-Log | HOCH | `auth.py:131-140`, `server.py:75` |
| GXP-S5 | Secret-Offenlegung an `client` via Checkpoint-Diff | HOCH | `routes_checkpoints.py:21-26` |
| GXP-S6 | Vollprivilegierter Token im URL-Query-String | HOCH | `server.py:96-97` |
| GXP-S7 | Connector-„Sandbox" = 11 umgehbare Regexe, gleiche Rechte | HOCH | `charter.py:34-46`, `connectors.py:116-129` |
| GXP-S8 | `shell=True` auf Konfigurationsstrings | HOCH | `drivers.py:990`, `lanemachine.py:70,497` |
| GXP-S10 | Kein Backup, keine Integritätsprüfung, kein Restore-Test | HOCH | `checkpoints.py:6-8` |
| GXP-S11 | Datenschutzerklärung widerspricht Code (PostHog, Loops.so) | HOCH | `relay.py:95,117` vs. `analytics.ts:46`, `loops_client.py:40-66` |
| GXP-S12 | Unbegrenzter Anthropic-Egress ohne DPA/Redaktion | HOCH | `drivers.py:352-374` |
| GXP-S13 | Vollbild- und Tastaturaufzeichnung ohne Maskierung | HOCH | `wincap.py:50`, `teach.py:41-45` |
| GXP-U5 | Keine Deaktivierung, nur Zerstörung | HOCH | `auth.py:76-83` |
| GXP-U6 | Owner kann jedes Passwort setzen, jeden Token prägen, alle Tokens lesen | HOCH | `server.py:195-199,321-335` |
| GXP-U7 | Tokens ohne Ablauf, überleben Logout, jeder Login prägt einen neuen | HOCH | `auth.py:114-117`, `routes_auth.py:87,91-95` |
| GXP-U9 | `_load()` fällt bei defekter `users.json` offen aus | HOCH | `auth.py:20-27`, `routes_auth.py:26-29` |
| GXP-U12 | Rechtemodell nicht spezifizierbar; Schwellen per Chat änderbar | HOCH | ~60 verstreute Prüfungen; `copilot_actions.py:205-272` |
| GXP-V2 | Gate-Verdikt aus stdout schlägt Exit-Code | HOCH | `lanemachine.py:84-87`, `debt.py:527` |
| GXP-V7 | Modelle als gleitende Aliase; Prompt nicht versioniert | HOCH | `turnopts.py:24-30`, `econ.py:62` |
| GXP-V8 | Rollback nur OTA (Tiefe 1) und Config; branchlose Pfade gar nicht | HOCH | `rollback_update.sh`, `debt.py:977-979` |
| GXP-V9 | Laufzeitkonfiguration außerhalb der Versionskontrolle | HOCH | `CLAUDE.md:36-37` |
| GXP-V10 | Keine kontrollierte Dokumentation, keine SOPs | HOCH | `docs/` |
| GXP-A12 | Stille Datenvernichtung: Chat-80, Session-Chain-6, Checkpoints-60, untracked files, `gate_report` | MITTEL–HOCH | `copilot.py:428`, `worktrees.py:30,121-140`, `lanemachine.py:850` |
| GXP-U10 | Einladungscode statisch, unbegrenzt, unbefristet, unauditiert | MITTEL | `events.py:82`, `routes_auth.py:48-51` |
| GXP-U11 | Passwortrichtlinie = 8 Zeichen; 30-Tage-Session ohne Idle-Timeout | MITTEL | `auth.py:17,66-67,145-162` |

---

## 9. Anerkannte Stärken

Damit das Bild vollständig ist — diese Eigenschaften sind in einer Inspektion
positiv verwertbar und sollten beim Umbau **nicht** verloren gehen:

- Append-only-Ereignissenke mit Akteur, Modell und Kosten pro Turn
  (`events.py:175-191`, `econ.py:62`)
- Flight Recorder pro Karte plus Bildschirmvideo für desktopsteuernde Treiber
- **Das Gate wird vom Daemon ausgeführt, nicht vom geprüften Agenten**
  (`lanemachine.py:66-71`) — die Architektur einer unabhängigen Prüfstufe ist
  korrekt, nur ihr Inhalt wurde entleert
- Worktree-Isolation als Blast-Radius-Kontrolle für Code-Karten
- Checkpoint-Mechanik mit Diff und selbst wieder gesichertem Restore
- Dokumentierte, mehrstufige OTA-Rollback-Leiter mit anschließender Verifikation
- `--setting-sources project` als gemessene Härtung des Agenten-Spawns
- Kryptografisch sauberes Passwort-Hashing und ein echtes Zero-Knowledge-Relay
- Ein ehrliches, detailliertes Schuldenregister mit 25 offenen Einträgen —
  seltene Transparenz, die als Grundlage eines CAPA-Prozesses direkt taugt
