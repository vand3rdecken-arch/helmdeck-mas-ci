# Arbeitsplan Phase A — die Mängel, die heute zählen

> **Status 2026-08-23: alle fünf gebaut und verifiziert.**
> A2 `8d7cdb2` · A0 `b78eff0` · A4 `aba748d` · A5 `ab7975b` · A1 `e3c9ddd`
>
> Jede Karte hat ihre Verifikation aus diesem Dokument tatsächlich durchlaufen;
> A4 und A1 zusätzlich mit Gegenprobe am alten Code, damit der Test nicht
> ungeprüft grün leuchtet. Neue Tests: `daemon/test_events_no_reimport.py`,
> `daemon/test_auth_audit.py`, `app/test_config_hydrate.js`.
>
> Zwei Dinge sind beim Bauen aufgetaucht, die unten im Plan noch fehlen:
> A1 hatte eine **zweite** Tür (das Onboarding mintete ebenfalls einen
> Owner-Token) und brauchte zusätzlich eine Änderung an `config.ts hydrate`,
> ohne die der Fix bei jedem Start einen Login erzwungen hätte. A4 hat einen
> Folgeposten im Schuldenregister hinterlassen
> (`events-two-stores-unreconciled`).
>
> **Nachtrag: der im Plan vergessene sechste Stufe-0-Punkt ist auch gebaut.**
> S4 (Lockout) + S1 (Tokens gehasht at rest) in `a78a233`. S1 war größer als
> gedacht — `GET /users` lieferte jeden Token im Klartext an die Oberfläche.
> Der A5-Test hat dabei einen Fehler gefangen, den ich frisch eingebaut hatte:
> `revoke_token` schrieb seinen Eingabewert ins Audit, und ein Skript darf da
> den Volltoken übergeben.
>
> **Phase B, strukturelle Hälfte: gebaut** (`1049b6e`). `daemon/gxp.py` plus der
> eine Guard in `_move_lane`. „Kein Agent kann ohne Menschen deployen" stimmt
> jetzt. „Jede Auslieferung trägt eine elektronische Unterschrift" stimmt
> **noch nicht** — als Schuldenposten `gxp-mode-has-no-signature-yet` eingetragen,
> damit das niemand verwechselt.
>
> **Phase B, Signaturhälfte: gebaut** (`63c68ab`), ohne das git-Tag wie
> entschieden. Re-Authentifizierung, Bedeutung, Begründung, Bindung an das
> Commit-Paar, Drift-Prüfung, Verbrauch beim Landen, Vier-Augen.
>
> **Wichtig für die Nutzung:** Unterschreiben geht heute nur über die API
> (`POST /sign`). Im Board gibt es dafür noch keinen Knopf — das ist Phase C.
> Wer den Modus einschaltet, ohne C zu bauen, kann Karten im Geltungsbereich
> nicht mehr abnehmen.
>
> **Phase C: gebaut** — C1 `005ac0f` (Daemon zeigt den GxP-Status der Karte),
> C2/C3/C4/C6 `76a3c3c` (API, Freigabefenster, vier Board-Einstiegspunkte,
> i18n de+en), C5 `e746dc0` (Stapelfreigabe). Der Modus ist damit **benutzbar**:
> Karte in Review → „Freigeben" → Prüfstand, Bedeutung, Begründung, Passwort.
>
> Nicht per Klick verifiziert — hier ist kein Browser installiert. Belegt sind
> die Routen gegen ein echtes git-Repo (`test_sign_routes.py`) und tsc; ein
> Screenshot der Maske steht aus und gehört auf deinen Rechner.
>
> Offen: A3 (deine Entscheidung) · das
> signierte git-Tag (braucht die Schlüsselentscheidung) · Phase D · der
> gepackte Drei-Start-Durchlauf der Desktop-App.
>
> **Neu, aus der Diskussion, nicht Teil dieser Karte:** Rohkommando bei
> Sprache mitspeichern — für eine Karte im Geltungsbereich, wenn die Eingabe
> über Sprache statt Tastatur kam (`gxp-mode-design.md` §2.1b). Für die
> Signatur selbst nur Zusatzabsicherung (der Commit-Diff ist der eigentliche
> Beleg). Tragend würde es erst für ein eigenständiges Rolle-A-Vorhaben (KI
> trägt Messwerte/Anweisungen in ein fremdes reguliertes System ein, etwa per
> Sprachdiktat an einem Laborgerät) — dort gibt es kein unabhängiges zweites
> Artefakt, das die Aussage prüfbar macht. Design-Diskussion vorhanden, keine
> Karte angelegt.

Fünf Karten. Jede ist ohne die anderen baubar und ohne GxP begründbar. Alles
unten ist am Arbeitsbaum nachgelesen, Stand `838985c` — keine Schätzung aus dem
Gedächtnis.

Phase B/C/D (GxP-Modus, Signaturen, App) stehen in `docs/gxp-mode-design.md`
und sind hier absichtlich nicht enthalten.

**Reihenfolge:** A2 → A0 → A4 → A5 → A1. Erst die Einzeiler, dann die
Ereignissenke, zuletzt der Desktop-Login (der größte Brocken).

| Karte | Was | Aufwand |
|---|---|---|
| A2 | Checkpoint-Diff gibt Secrets an jeden Nutzer | 10 min |
| A0 | git bucht Maschinenarbeit auf den Owner | 1 h |
| A4 | Ereignisse verdoppeln sich, Archiv wird überschrieben | 3 h |
| A5 | Benutzer- und Rechteänderungen erzeugen null Audit | 4 h |
| A1 | Desktop-App meldet sich ohne Passwort als Owner an | 1–2 Tage |

Summe rund 2,5 Tage. A3 (Datenschutzerklärung vs. PostHog) bleibt wie
entschieden liegen.

---

## A2 — Checkpoint-Diff ohne Rollenprüfung

**Ist.** `daemon/spine/http/routes/routes_checkpoints.py:21-26`:

```python
def checkpoints_diff_get(self, user, cid):
    from daemon.spine.ops import checkpoints
    try:
        return self._send(200, json.dumps(checkpoints.diff(cid)))
```

Die Funktion nimmt `user` entgegen und sieht die Rolle **nie** an. Drei Zeilen
darunter macht `checkpoints_restore_post:29-31` es richtig:

```python
if user["role"] != "owner":
    return self._send(403, json.dumps({"error": "owner only"}))
```

Der Diff liefert Settings-Werte vorher/nachher — darunter `relay.sk`,
`glance_token`, `registration.invite_code`. Der generische 401 in `server.py`
lässt jeden angemeldeten Nutzer durch, also auch `client`.

**Soll.** Dieselbe Rollenprüfung wie bei `restore`, direkt an den Funktionskopf.

**Verifikation.** Mit einem `client`-Token `GET /checkpoints/<cid>/diff` →
muss 403 sein. Mit Owner-Token → 200. Beides ausführen, nicht nur eines.

**Risiko.** Keins. Prüfen, ob die App den Diff irgendwo für Nicht-Owner
anzeigt — dann fällt dort eine Ansicht weg (vermutlich nicht, aber nachsehen).

---

## A0 — Agenten-Commits laufen unter der Identität des Owners

**Ist.** Gemessen am Arbeitsbaum:

```
838985c | author=Tien Duy Vo <vo_duy_tien@yahoo.de> | sig=N
f671273 | author=Tien Duy Vo <vo_duy_tien@yahoo.de> | sig=N
```

Beides Commits eines Agenten. Zwei Stellen committen im Daemon:

- `lanemachine.py:209` — `_autocommit`, schließt Kartenarbeit ab
- `lanemachine.py:975` — parkt einen dreckigen Baum auf `wip-*`

Beide gehen über `_git_try` / `_git` (`daemon/spine/git/gitutil.py:17-27`), und
die rufen `subprocess.run(["git", "-C", repo, *args])` **ohne `env`** — also
erbt git die Identität des Hosts.

Der Verlauf behauptet damit einen menschlichen Autor für Maschinenarbeit. Das
ist falsche Zuschreibung, nicht fehlende — der schlechtere der beiden Zustände,
und der Grund, warum git heute als Audit-Trail nicht taugt (siehe
`gxp-mode-design.md` §2.0).

**Soll.** An beiden Aufrufstellen die Identität mitgeben. `-c` steht als
git-Option vor dem Unterbefehl, `_git_try` reicht Argumente unverändert durch:

```python
_git_try(wt, "-c", "user.name=HelmDeck Agent",
             "-c", "user.email=agent@helmdeck.local",
             "commit", "-m", ...)
```

Nicht global konfigurieren und nicht `env` im Daemon setzen — beides würde auch
Commits treffen, die ein Mensch auslöst. Nur diese zwei Stellen.

**Verifikation.** Eine Karte durchlaufen lassen, danach
`git log -3 --format="%h %an <%ae>"` auf dem Kartenbranch: der Finalize-Commit
muss `HelmDeck Agent` zeigen. Ein von Hand gemachter Commit im selben Baum muss
weiter den Owner zeigen.

**Risiko.** Gering. Prüfen, ob irgendetwas auf den Autornamen filtert
(`git log --author`), bevor umgestellt wird.

**Nicht in dieser Karte:** Signieren. Das ist Phase B.

---

## A4 — Ereignisse verdoppeln sich bei jedem Start, das Archiv wird überschrieben

**Ist.** `daemon/spine/storage/db.py:110-130`, aufgerufen aus `init()` bei
`:74`, also bei jedem Daemon-Start:

```python
ej = os.path.join(ROOT, "events.jsonl")
if os.path.exists(ej):
    for line in f:
        c.execute("INSERT INTO events(ts,kind,track,data) VALUES(?,?,?,?)", …)
    os.replace(ej, ej + ".imported")
```

`db.py:10` ist `from daemon.paths import DAEMON_ROOT as ROOT` — dieselbe Datei,
in die `events.emit` (`events.py:175-191`) laufend anhängt, **zusätzlich** zum
Write-Through in dieselbe Tabelle.

Der Ablauf ist damit:

1. Start 1: importiert, benennt nach `events.jsonl.imported` um.
2. Betrieb: `emit` legt `events.jsonl` neu an und schreibt jedes Ereignis
   **doppelt** — einmal in die Datei, einmal per Write-Through in die Tabelle.
3. Start 2: findet die Datei wieder, importiert **alles noch einmal**. Kein
   UNIQUE, kein `INSERT OR IGNORE` → jedes Ereignis der letzten Sitzung liegt
   nun zweimal in der Tabelle.
4. `os.replace` **überschreibt dabei das `.imported` aus Schritt 1.**

Zwei Fehler, nicht einer. Der Docstring bei `db.py:5-7` verspricht *„originals
preserved, per the safeguard rule"* — ab dem zweiten Start stimmt das nicht.

Praktische Folge: alle Kennzahlen, die über `events` aggregieren, sind zu hoch.
Die Kostenanzeige im Dashboard zählt jede vergangene Sitzung mehrfach.

**Soll.** Zwei kleine, getrennte Korrekturen:

1. Nur importieren, wenn die Tabelle `events` **leer** ist. Das war die
   Absicht („imported on first start"), nur nie so geschrieben.
2. Ein vorhandenes `.imported` nie überschreiben — Zeitstempel anhängen oder
   den Umzug auslassen.

**Bewusst nicht in dieser Karte:** die beiden Speicher wieder in Einklang
bringen. Datei und Tabelle haben keinen gemeinsamen Schlüssel, also lassen sich
Dubletten nachträglich nicht sauber erkennen. Wer das will, braucht eine
Ereignis-ID — eigene Karte, gehört zu Phase D.

**Verifikation.** Daemon starten, ein paar Ereignisse erzeugen,
`SELECT count(*) FROM events` merken, neu starten, erneut zählen: die Zahl darf
nur um die Ereignisse des zweiten Starts wachsen. Zusätzlich: nach zwei Starts
muss das erste `.imported` noch existieren.

**Risiko.** Mittel — es geht an den Ereignisspeicher. Vorher `helmdeck.db`
sichern. Die Altdaten sind bereits verdoppelt; diese Karte stoppt das
Weiterwachsen, sie repariert die Vergangenheit nicht.

---

## A5 — Benutzer-, Rollen- und Token-Änderungen erzeugen keinerlei Audit

**Ist.** `daemon/spine/auth/auth.py` importiert `events` **gar nicht**;
`grep -c emit` liefert `0`. Damit hinterlässt keine dieser Operationen eine
Spur:

| Funktion | Zeile |
|---|---|
| `create_user` | :61 |
| `delete_user` | :76 |
| `set_password` | :85 |
| `set_role` | :96 |
| `issue_token` | :109 |
| `revoke_token` | :121 |
| `login` (Erfolg **und** Fehlschlag) | :131 |
| `logout` | :142 |

Der Fehlschlag ist der wichtigste Fall und heute ein stilles `return None`
(`auth.py:134-135`) — es gibt keine Aufzeichnung fehlgeschlagener Anmeldungen,
also auch keine Grundlage für Sperren nach zu vielen Versuchen.

**Soll.** Eine Ereignisart `auth` mit `op`-Feld, gesendet aus jeder der acht
Funktionen. Passwörter, Hashes und Token-Werte gehören **nicht** hinein —
Tokens nur als Label plus letzte vier Zeichen.

Beim Ereignis nicht die lokale Zeit von `events.emit:176` übernehmen, sondern
UTC. Das ist der erste Schritt der UTC-Umstellung, die in Phase D vollständig
kommt, und hier billig mitzunehmen.

**Verifikation.** Alle acht Operationen einmal ausführen (inklusive einer
Anmeldung mit falschem Passwort), danach `events.jsonl` durchsehen: acht Arten
vorhanden, kein Passwort und kein vollständiger Token darin. Zweites Auge: die
Datei nach dem eigenen Passwort durchsuchen, es darf nicht auftauchen.

**Risiko.** Gering. `auth.py` importiert `events` bislang nicht — auf
Importzyklen achten und im Zweifel innerhalb der Funktion importieren, wie es
`policy.py:120-121` vormacht.

---

## A1 — Desktop-App meldet sich ohne Passwort als Owner an

**Ist.** `desktop/main.js`, `mintDesktopToken()`:

```js
spawnSync(py.cmd, [...py.args, "-m", "daemon.mint_token", "owner", "desktop"], …)
if (r.status === 0 && r.stdout) desktopToken = r.stdout.trim();
```

Läuft bei jedem Start und legt den Token in die SPA-URL. **Die App zu öffnen
ist damit eine Owner-Anmeldung ohne jedes Credential.** Wer an den entsperrten
Rechner kommt, hat volle Owner-Rechte, ohne etwas zu wissen.

Das ist zugleich der Grund, warum diese Karte vor Phase B liegen muss: eine
Unterschriftenzeremonie über einer Oberfläche, die sich ohne Passwort als Owner
anmeldet, ist Theater.

**Soll — und das ist mehr als eine Löschung.** Ersatzlos streichen hieße: bei
jedem Start Benutzername und Passwort tippen. Das benutzt niemand. Der
Ersatz ist ein richtiger Anmeldeweg:

1. `mintDesktopToken` entfällt.
2. Beim ersten Start zeigt die App den vorhandenen Login-Screen
   (`app/src/ui/login_screen.tsx` — existiert, wird nur nicht erreicht).
3. Nach erfolgreicher Anmeldung wird der Token im Benutzerprofil des
   Betriebssystems abgelegt, nicht im Repo und nicht in der URL.
4. Weitere Starts nutzen den gespeicherten Token. Abmelden verwirft ihn.

Damit ist es genau ein Login statt keinem, und der Alltag bleibt wie er ist.

**Verifikation.** Frischer Rechner beziehungsweise gelöschter Profileintrag →
App zeigt den Login. Anmelden, App schließen, neu öffnen → direkt am Board.
Abmelden, neu öffnen → wieder Login. Alle drei durchspielen, nicht nur den
mittleren. Screenshot vom Login-Screen und beurteilen, nicht nur bestätigen,
dass er rendert (Hausregel für UI).

**Risiko.** Am höchsten von den fünf. Das ist eine Desktop-Änderung, also
Paketierung und Auto-Update betroffen — `DEPLOY.md` vorher lesen. Wenn der
gespeicherte Token nicht sauber gelesen wird, sperrt sich der Owner
möglicherweise selbst aus der eigenen App aus. Deshalb zuletzt, und deshalb mit
einem funktionierenden Rückweg (alte Version bleibt installierbar).

---

## Was danach offen ist

- **A3** — Datenschutzerklärung gegen PostHog/Loops. Wartet auf deine
  Entscheidung, kein Bauauftrag.
- **Phase B/C/D** — GxP-Modus, Signaturen, App-Oberfläche, Audit-Härtung.
  Beschrieben in `docs/gxp-mode-design.md`. Der offene Punkt dort ist der
  Signierschlüssel (§2.0), vertagt bis B ansteht.
- **Ereignis-ID und Abgleich der beiden Speicher** — aus A4 herausgeschnitten,
  gehört zu Phase D.

Entsteht beim Bauen eine tragende Abkürzung, gehört sie im selben Commit nach
`daemon/spine/registry/debt.py`.
