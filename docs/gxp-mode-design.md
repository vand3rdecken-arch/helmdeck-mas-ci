# GxP-Modus — technischer Entwurf und UX

Folgedokument zu `docs/gxp-conformity-analysis.md` (Befundregister dort, §8).
Dieses Dokument beantwortet die Frage „wie löst man das technisch und gut über
UX", nicht „was fehlt". Es ist eine Bauanleitung, kein Code.

Stand: 2026-08-23. Alle Zeilenangaben gegen den Stand von `8c8cbfe` verifiziert.

---

# Klartext

Wer nur wissen will, was gebaut wird und wie es sich anfühlt, liest diese Seite
und hört danach auf. Der Rest ist Bauanleitung für den, der es tippt.

**Das Problem.** Heute kann eine Karte fertig werden, sich selbst abnehmen,
nach main mergen und deployen — ohne dass ein Mensch etwas tut. Henry macht
das, Fast-Track macht das, die Auto-Abnahme macht das. Für einen Pharma-Kunden
ist genau das der eine Punkt, an dem alles andere hängt: es muss beweisbar
sein, dass ein Mensch jede Auslieferung freigegeben hat.

**Die Lösung in einem Satz.** Im GxP-Modus kommt keine Karte nach main, solange
kein Mensch mit Passwort unterschrieben hat.

**Warum das erstaunlich wenig Arbeit ist.** Alle Wege, auf denen eine Karte
abgenommen wird — Board-Tap, Henry, Chat, PM, Fast-Track, Auto-Abnahme —
laufen durch eine einzige Funktion. Eine Prüfung dort schließt alle
gleichzeitig. Henry scheitert dabei von selbst: er hat kein Passwort.

**Wie es sich anfühlt.** Die Karte liegt in Review. Du tippst „Freigeben". Ein
Fenster zeigt dir: was nach main gemerged wird, was deployt wird, was das Gate
sagt, welche Dateien sich ändern. Du wählst *Freigegeben* oder *Abgelehnt*,
tippst dein Passwort, fertig. Mehrere Karten gehen auch auf einmal — einmal
Passwort, drei Freigaben.

**Der einzige Trick, der Erklärung braucht.** Deine Unterschrift hängt an der
Commit-Nummer, die du gerade vor dir hast. Vor dem Mergen wird nachgesehen, ob
sie noch stimmt. Hat der Agent inzwischen weitergearbeitet, ist die Unterschrift
ungültig und die Karte bleibt liegen. Heißt: **du hast unterschrieben, was du
gesehen hast** — nicht etwas, das danach noch umgebaut wurde.

**Und das läuft über git.** Die Unterschrift ist ein signiertes git-Tag. Ein
Prüfer kontrolliert sie mit `git verify-tag`, also mit Standardwerkzeug, ohne
uns glauben zu müssen. Git liefert Prüfsumme, Kette und Bindung fertig mit;
selbst bauen müssen wir davon nichts. Details in §2.0 — inklusive der Stelle,
an der git heute **falsche** Angaben macht: Agenten-Commits laufen unter deinem
Namen.

**Was ein Nutzer ohne GxP-Modus davon merkt:** nichts. Der Modus ist aus, das
Board bleibt wie es ist.

---

## Zwei naheliegende Abkürzungen

Beide Fragen kommen sofort. Eine funktioniert, die andere nicht.

### „Alle Karten gleich beim Review abzeichnen" — ja, so ist es gedacht

Es gibt genau **einen** menschlichen Moment, und der liegt in Review. Die Karte
wartet dort, du unterschreibst, und daraufhin passiert alles Weitere: mergen,
deployen, nach `done` legen. `done` ist danach nur noch das Etikett für das
Ergebnis, kein zweiter Arbeitsschritt.

Stapelweise ist ausdrücklich vorgesehen: drei Karten auswählen, ein Fenster,
ein Passwort, drei Unterschriften. Details in §3.3.

### „Den Code schon bei Review nach main mergen" — nein

**Der Grund ist einfach: main ist das, was deployt wird.** Liegt ungeprüfter
Code in main, schiebt ihn die nächste beliebige andere Karte mit raus, sobald
die ihren Deploy auslöst. Dann ist ausgeliefert, was niemand unterschrieben
hat, und niemand merkt es. Das ist nicht nur regulatorisch tödlich, das will
man auch ohne Pharma nicht.

**Aber der Instinkt dahinter stimmt** — beim Freigeben soll man den *echten*
Merge sehen, keine Vorhersage. Und das ist fast geschenkt, weil der echte Merge
heute schon läuft. `_classify_merge` (`lanemachine.py`) macht bei jedem
Review-Schritt:

```
git merge --no-commit --no-ff <branch>     # echter Merge
git diff --name-only --diff-filter=U       # Konflikte einsammeln
git merge --abort                          # und wieder verwerfen
```

Git merged also wirklich und wirft das Ergebnis danach weg. Man muss den Diff
nur **vor** dem `--abort` mitnehmen und im Freigabefenster zeigen. Ein paar
Zeilen, kein Umbau. Ergebnis: du siehst den integrierten Stand, main bleibt bis
zur Unterschrift unberührt.

Wenn später echte Umgebungstrennung dazukommt (GXP-V6, Stufe 2), ist der
saubere Platz für einen frühen Merge ein **Integrations-Branch** — nicht main.
Dann prüft man auf integriertem Code, und die Unterschrift befördert von der
Integration nach main. Das ist eine spätere Ausbaustufe, kein Teil dieses
Entwurfs.

---

## 0. Das Prinzip in drei Sätzen

1. **Die Signatur ist keine Dialogbox vor dem Abnehmen — sie ist eine
   Vorbedingung des Spurwechsels.** Nicht „beim Klick frage ich nach", sondern
   „eine Karte kann `review` ohne gültige, unverbrauchte Signatur nicht
   verlassen". Das ist der Unterschied zwischen einer Höflichkeitsabfrage und
   einer Kontrolle.
2. **Es gibt genau einen Ort, an dem das geprüft wird**, weil es genau einen
   Ort gibt, an dem Karten abgenommen werden.
3. **Der Modus ist Code, nicht Policy.** Ein Bool in `policy_live.json` wäre
   wertlos: `policy.swap` schützt nur über einen aufruferseitigen Actor-String
   (`policy.py:99-104`), und der ist keine Authentifizierung.

Alles Weitere ist Ausarbeitung.

---

## 1. Der Fund, der den Entwurf einfach macht

Die Analyse hat vier reviewfreie Produktionspfade als strukturellen Blocker
benannt. Der Reflex wäre, jeden einzeln zu sperren. Das ist nicht nötig:

| Pfad | Aufrufer | landet bei |
|---|---|---|
| Board-Tap / Drag / Kartendetail | `routes_track_actions.py:145` | `sessions.move_lane` |
| Henry (Exception-Broker, autonom) | `henry_broker.py:271-272` | `sessions.move_lane` |
| Policy-Auto-Abnahme (`auto_accept_green`) | `processes.py:293` | `sessions.move_lane` |
| Chat-Verb „move" | `copilot_actions.py:210` | `sessions.move_lane` |
| PM-Zelle | `pm_resolve.py:326` | `sessions.move_lane` |
| Fast-Track | — | *innerhalb* `_move_lane:785-786` |
| Maschinenkarten | — | *innerhalb* `_move_lane:661-663` |

`move_lane` (`lanemachine.py:585`) ist ein reiner Reentrancy-Wrapper um
`_move_lane` (`lanemachine.py:608`). **Ein Guard am Kopf von `_move_lane`
schließt die gesamte Tabelle.** Henry braucht keine Sonderbehandlung: er kann
schlicht keine Signatur erzeugen, weil er kein Passwort hat. Fast-Track ebenso.
Die Auto-Abnahme ebenso.

Das ist auch der Grund, warum dieser Entwurf mit dem Kartenhaus-Gesetz des
Repos vereinbar ist: die Kontrolle sitzt beim **einen Eigentümer** des
Zustandsübergangs und wird **zur Ereigniszeit** verifiziert, nicht aus einem
gespeicherten Flag geschlossen.

---

## 2. Mechanik

### 2.0 Git als Audit-Trail — was es kann, was nicht

Die naheliegende Frage, und sie macht den Entwurf schlanker. Vier Dinge, die
v1 dieses Dokuments von Hand bauen wollte, liefert git fertig:

| Anforderung | handgebaut (v1) | git |
|---|---|---|
| Prüfsumme über den signierten Inhalt | `subject_hash` über kanonisches JSON | **Commit-SHA** |
| Manipulationssichere Kette | `prev`-Feld | **Parent-Kette** |
| Signatur an den Inhalt gebunden (§11.70) | Datensatz + Hash | **signiertes Tag** |
| Prüfwerkzeug für den Auditor | müssten wir bauen | **`git verify-tag`** |

Die letzte Zeile wiegt am schwersten: ein Prüfer verifiziert mit
Standard-Werkzeug, **ohne HelmDeck vertrauen zu müssen**. Selbstgebaute
Kryptografie muss man ihm erst erklären und dann auch noch validieren.

**Heute ist git allerdings schlechter als kein Audit-Trail.** Gemessen am
Arbeitsbaum:

```
f671273 | author=Tien Duy Vo <vo_duy_tien@yahoo.de> | sig=N
87e5e03 | author=Tien Duy Vo <vo_duy_tien@yahoo.de> | sig=N
```

Beides sind Agenten-Commits. `_autocommit` (`lanemachine.py:188-211`) committet
Agentenarbeit unter der Git-Identität des Hosts, unsigniert. Der Verlauf
**behauptet einen menschlichen Autor für Maschinenarbeit**. Das ist falsche
Attribution, kein fehlender Nachweis — der schlechtere von beiden Zuständen.
Erste Maßnahme, unabhängig von allem anderen: Agenten-Commits bekommen eine
eigene Identität (`HelmDeck Agent <agent@helmdeck.local>`), der Mensch bleibt
dem Signatur-Tag vorbehalten.

**Was git nicht abdecken kann:** Logins, Rollenwechsel, Token-Ausgabe,
Policy-Änderungen, Kartenlebenszyklus, Kosten, Fehlversuche. Das sind keine
Code-Änderungen. Wer sie trotzdem in git zwingt, baut einen Event-Store auf
git — dann lieber gleich den Event-Store.

**Die tragende Struktur ist die Kreuzbezeugung.** Git bezeugt den Code, die
Ereignissenke alles andere, und **jede notiert den Anker der anderen**: die
Senke speichert Merge-SHA und Tag-Objekt-SHA, das Tag nennt Karten-ID und
Ereignis-ID. Ein Force-Push widerspricht danach der Senke, eine manipulierte
Senke widerspricht git. Keines von beiden lässt sich still umschreiben. Das ist
belastbarer als jede der beiden Hälften allein — und es entschärft nebenbei
`tools/reset.py:61-77`, das heute den Audit-Trail löscht: git überlebt das.

**Welcher Schlüssel signiert** — die eine offene Entscheidung.

*Option A (Empfehlung): Schlüssel serverseitig, vom Passwort entsperrt.* Pro
Benutzer ein Ed25519-Schlüssel, verschlüsselt mit einem aus dem Passwort
abgeleiteten Schlüssel — **getrennte Ableitung** von der Passwortprüfung, das
PBKDF2 dafür existiert bereits (`auth.py:37-40`). Signieren heißt dann: das
Passwort entschlüsselt den Signierschlüssel. Damit ist das Passwort nicht bloß
gegen einen Hash geprüft, sondern kryptografisch notwendig — eine Signatur
lässt sich **nicht** dadurch fälschen, dass jemand die Passwortprüfung
patcht. Git kann das ohne GPG: `gpg.format = ssh` plus `user.signingkey`.
Ehrlicher Preis: der Server hält den verschlüsselten Schlüssel. Wird der Daemon
genau im Moment des Signierens kompromittiert, liegt der Schlüssel offen. Das
ist der Preis dafür, vom Telefon aus signieren zu können, und gehört so in die
Risikobewertung.

*Option B: Schlüssel auf dem Gerät.* Kryptografisch sauberer, auf dem Telefon
kaum benutzbar, und die Wiederherstellung bei Geräteverlust ist ein eigenes
Projekt. Für einen Betrieb, der ausschließlich am Desktop freigibt, eine echte
Alternative.

### 2.1 Der Signaturdatensatz

Ein Signaturdatensatz ist unveränderlich und wird an **zwei** Orte geschrieben:
auf den Kartendatensatz (damit er mit dem Record reist) und in die
Ereignissenke (damit er im Audit-Trail auftaucht). `db.track_put` serialisiert
den ganzen Task-Dict als JSON-Blob (`db.py:171-174`) — neue Schlüssel brauchen
keine Migration.

```jsonc
"signatures": [{
  "seq": 1,
  "actor": "duy",                     // §11.50(a)(1) printed name
  "actor_role": "owner",
  "meaning": "approved",              // §11.50(a)(3) approved|reviewed|rejected
  "reason": "Regression gruen, Diff geprueft",
  "signed_at": "2026-08-23T14:02:11Z",// §11.50(a)(2) UTC, Zeitpunkt des Klicks
  "subject": {                        // was der Mensch gesehen hat
    "card": "t-91", "branch": "feat/x",
    "head": "a1b2c3d", "base": "e4f5g6h",   // §11.70 Bindung, s. 2.2
    "gate": "pass", "files": 7, "ins": 240, "del": 12
  },
  "auth": { "method": "password-unlocked-key", "components": ["userid","password"] },
  "git": {                            // die Kreuzbezeugung aus 2.0
    "tag": "approve/t-91",
    "tag_sha": "b7d3…",               // git verify-tag prueft das
    "merge_sha": null                 // nachgetragen, wenn der Merge landet
  },
  "consumed_by": null                 // wird beim Landen gesetzt
}]
```

Zwei Details, die leicht untergehen:

- **`signatures` ist eine Liste, kein Feld.** Eine Karte kann abgelehnt,
  überarbeitet und erneut signiert werden. Die Historie bleibt vollständig.
- **Kein selbstgebauter `prev`-Kettenhash mehr** (§2.0). Die Verkettung leistet
  git: das Signatur-Tag hängt am Commit, der Commit an seinem Parent. Eine
  nachträglich entfernte Signatur fällt auf, weil `git.tag_sha` in der
  Ereignissenke dann ins Leere zeigt — und umgekehrt.

Der Datensatz ist **englisch und technisch**, nicht übersetzt — konsistent mit
der ausdrücklichen Regel in `app/src/i18n/index.ts:1-11`, dass der Audit-Trail
in jedem Workspace identisch und greppbar lesen muss. Übersetzt wird nur die
Oberfläche.

### 2.1b Rohkommando bei Sprache — zurückgestellt, aber eingeplant

Owner-Frage: soll das gesprochene Rohkommando mitgespeichert werden, nicht für
jede Karte, aber für GxP? Antwort: ja, mit einer Einschränkung, die die Regel
schärfer macht als „GxP ja/nein" — sie hängt an **zwei** Bedingungen, nicht an
einer.

**Kanal.** Nur gesprochene Eingabe hat ein Verhör-Risiko. Getippter Text hat
keine Interpretationsschicht dazwischen — was eingetippt wird, ist exakt das,
was gespeichert wird. Das Feld lohnt sich nur für den Sprachpfad.

**Geltungsbereich.** Ob man den Preis dafür zahlt — Speicherung, Aufbewahrung,
und eine Sprachaufnahme ist personenbezogen (DSGVO), nicht nur ein
Speicherplatz-Thema — ist eine Scope-Frage. Für eine beliebige Karte
unverhältnismäßig, für eine GxP-Karte gerechtfertigt.

**Beide zusammen:** bei einer Karte im Geltungsbereich, wenn die Eingabe über
Sprache kam, wird das Rohkommando mitgespeichert. Bei Tastatur nicht nötig.
Außerhalb des Geltungsbereichs nie.

**Wo es trägt, und wo es nur zusätzliche Absicherung ist — das ist der Teil,
der die Antwort ehrlich macht, statt „immer alles aufnehmen" zu sagen:**

- **Begründungsfeld einer Signatur (`reason`): nice-to-have, nicht tragend.**
  Die GxP-Aussage „dieser Code wurde geprüft und freigegeben" hängt am
  Commit-Paar (§2.2), nicht am Wortlaut der Begründung. Verhört sich die KI
  beim Diktieren eines Wortes in der Begründung, bleibt der signierte Diff
  trotzdem unabhängig überprüfbar — er *ist* der eigentliche Beleg.
- **Diktierte Messwerte oder Anweisungen ohne unabhängiges zweites
  Artefakt: tragend.** Sobald es neben der Sprachäußerung nichts gibt, das
  unabhängig davon existiert (kein Diff, kein Commit, nur die Aussage
  selbst), ist das Rohkommando die **einzige** Stelle, an der ein späterer
  Zweifel überhaupt festgemacht werden kann. Das ist der Fall bei
  Sprachdiktat von Messwerten in ein fremdes System (Rolle A, siehe die
  Diskussion zum pH-Meter-Beispiel) — dort trägt die gesamte Kontrolle auf
  diesem einen Feld, nicht nur zusätzlich.

**Umsetzung, wenn gebaut** (nicht Teil dieser Karte, siehe §6): ein Feld
`auth.input_channel: "voice" | "typed"` neben dem bereits vorhandenen
`auth.method` (`signatures.py:113`), bei `"voice"` zusätzlich ein Verweis auf
den Audio-Schnipsel — nach demselben Muster, wie Karten schon heute auf ihre
Bildschirm-/Browseraufzeichnung verweisen (`routes_runs.py`). Kein neues
Konzept, nur ein weiteres Feld, vom Geltungsbereich abhängig statt pauschal.

### 2.2 Die Bindung: `subject_hash`

§11.70 verlangt, dass die Signatur so an den Datensatz gebunden ist, dass sie
nicht herauslösbar oder auf einen anderen Datensatz übertragbar ist. Die
Umsetzung ist zugleich die Lösung für ein rein technisches Problem.

**Seit §2.0 braucht es dafür keine eigene Prüfsumme mehr.** Der signierte
Gegenstand ist das Paar aus zwei Commit-SHAs, die git ohnehin führt:

```
subject = (head_sha des Karten-Branch, base_sha von main)
```

Der `head_sha` deckt den gesamten Inhaltszustand ab — das ist die Eigenschaft,
für die git gebaut ist. Der `base_sha` hält fest, gegen welchen Stand von main
integriert wurde. Beides steht später wörtlich im Signatur-Tag und ist mit
`git verify-tag` prüfbar.

Erfasst **beim Öffnen der Freigabemaske**, mitsigniert, und **erneut geprüft**
unmittelbar vor dem Merge in `_move_lane`. Drift → Signatur ist automatisch
ungültig, die Karte bleibt in `review`, `events.emit("signature", tid,
outcome="void", reason="subject drift")`.

Das leistet drei Dinge gleichzeitig:

- **§11.70 ist erfüllt.** Die Signatur passt auf genau einen Inhaltszustand.
- **Der Race ist zu.** Die HTTP-Route antwortet sofort mit `{started, gating:
  true}` und merged erst später im Hintergrundthread
  (`routes_track_actions.py:144-146`). Wenn zwischen Signatur und Merge ein
  weiterer Turn läuft oder der Branch sich bewegt, wird nicht das Signierte
  gemerged. Ohne Hash wäre das ein stiller Fehler.
- **„Du hast unterschrieben, was du gesehen hast."** Das ist der Satz, mit dem
  man die Kontrolle einem Auditor in einem Satz erklärt.

### 2.3 Der eine Enforcement-Punkt

Am Kopf von `_move_lane` (`lanemachine.py:608`, nach `_find` bei `:611-616`,
**vor** dem Idempotenz-Kurzschluss bei `:654-660`):

```
wenn gxp.aktiv() und lane == "done":
    sig = signatures.gueltige_offene(t)     # meaning=approved, hash passt, unverbraucht
    wenn keine:      -> bleib in review, emit("signature", outcome="missing"), return
    wenn vier_augen_verletzt(sig, t): -> bleib, outcome="self_approval"
    ...spaeter, unmittelbar vor _merge_to_main (:808):
    wenn subject_hash != neu_berechnet(t): -> bounce, outcome="void"
```

Zwei Prüfungen, nicht eine: einmal am Eingang (schnell scheitern, nichts
anfassen) und einmal direkt vor dem Merge (Drift während Gate und `_sync_base`
abfangen — dazwischen liegen bis zu 600 s Gate-Laufzeit, `lanemachine.py:743`).

Zusätzlich sperrt `gxp.aktiv()` an genau drei weiteren Stellen:

| Sperre | Stelle | Grund |
|---|---|---|
| Fast-Track-Durchfall | `lanemachine.py:785-786` | landet sonst ohne Mensch |
| Maschinenkarten-Abnahme | `lanemachine.py:661-663` → `dispatch.py:525-570` | eigener Abnahmepfad |
| Henrys Verben `move`/`did`/`rerun_deploy` | `henry_broker.py:258-273` | Agent als Akteur |

### 2.4 Die Signier-Session — NICHT in v1

> **Gestrichen für die erste Ausbaustufe.** Der Abschnitt bleibt als
> Begründung stehen, warum: der Gewinn ist ein eingespartes Textfeld, die
> Kosten sind ein serverseitiger Sitzungsspeicher mit zwei Ablauffristen und
> Token-Bindung. Das Verhältnis stimmt nicht. In v1 wird bei **jeder**
> Signatur Benutzername (fest angezeigt) + Passwort verlangt. Der echte
> UX-Hebel ist die Stapelfreigabe in §2.5, nicht dieser hier.

Hier liegt der Unterschied zwischen einem benutzbaren und einem gehassten
System, und er steht wörtlich in der Vorschrift.

§11.200(a)(1)(i)(A): *bei einer Serie von Signaturen innerhalb einer „single,
continuous period of controlled system access"* braucht **nur die erste**
Signatur alle Komponenten; jede weitere braucht mindestens eine Komponente,
die nur die Person ausführen kann.

Ein 30-Tage-Bearer-Token auf dem Telefon (`auth.py:17`) ist keine solche
Periode — deshalb galt in der Analyse: volle Komponenten bei jeder Abnahme.
Die Lösung ist, die Periode **explizit herzustellen**:

- `POST /sign/session {name, password}` legt einen **Signier-Kontext** an:
  serverseitig, nur im Speicher, an den Auth-Token gebunden, 15 min
  Leerlauf-Ablauf / 60 min absolut, stirbt beim Daemon-Neustart.
- Erste Signatur = Anlage des Kontexts = Benutzerkennung + Passwort. Volle
  Komponenten.
- Jede weitere Signatur im Kontext: **Passwort allein**, keine Kennung.
- Kontext an den Token gebunden heißt: ein gestohlener Token ohne Passwort
  kann nicht signieren. Das schließt den Weg, den GXP-U3 heute offen lässt.

Der Gewinn ist ehrlich betrachtet klein (man spart das Tippen des
Benutzernamens). Der große Hebel ist der nächste Punkt.

### 2.5 Stapelfreigabe

Prüfer nehmen selten eine Karte ab, sondern drei. §11.200 spricht ausdrücklich
von einer *Serie* von Signaturen; in regulierten Dokumenten- und
LIMS-Systemen ist eine Stapelfreigabe mit einmaliger Credential-Eingabe
etablierte Praxis, solange **jeder** Datensatz seine eigene Manifestation
(Name, Zeit, Bedeutung) bekommt und der Unterzeichner **jeden** Posten zum
Zeitpunkt der Signatur sieht.

Das ist der eigentliche UX-Hebel: drei Karten, ein Ritual, drei
Signaturdatensätze.

> **Vor dem Bau mit QA/Regulatory abklären.** Ich halte die Stapelfreigabe für
> vertretbar und üblich, aber es ist der einzige Punkt in diesem Entwurf, bei
> dem die Auslegung Spielraum hat. Ein konservativer Prüfer kann pro Datensatz
> eine eigene Passworteingabe verlangen. Das Design bleibt gültig — es wird nur
> unbequemer. Die Entscheidung sollte dokumentiert und begründet sein
> (das ist selbst schon ein GxP-Artefakt), nicht implizit im Code liegen.

### 2.6 Vier-Augen

**Ein Schalter, standardmäßig AUS.** Vier-Augen ist keine Voraussetzung dafür,
dass ein Mensch unterschreibt — es ist die Zusatzforderung, dass es ein
*anderer* Mensch ist. Ein Ein-Personen-Betrieb kann sie nicht erfüllen, und
sie zur Pflicht zu machen würde den Modus dort unbenutzbar machen. Also:
`four_eyes: false` im Auslieferungszustand, einschaltbar, wenn ein Kunde es
verlangt.

Eingeschaltet braucht es ein Feld, das es heute nicht gibt: `dispatch.py:62-81`
hält **nicht** fest, wer eine Karte beauftragt hat (`client` ist der Kunde,
nicht der Auftraggeber). Nötig ist `dispatched_by`, gesetzt in `new_track` und
bei jedem Move nach `working`. Dann gilt:

- `signature.actor != task.dispatched_by` für `meaning = approved`.
- Beim Einschalten mit nur einem Konto: sofortige Warnung, kein stilles
  Durchlassen — „Vier-Augen ist aktiv, aber es existiert nur ein Konto."

Die Bedeutung `reviewed` bekommt hier ihren Zweck: A prüft (`reviewed`), B gibt
frei (`approved`). Zwei Signaturen, zwei Personen, ein Kartendatensatz.

### 2.6b Geltungsbereich: pro Repo, nicht global — Owner-Entscheidung

Der erste Entwurf schaltete Fast-Track **global** ab, sobald der Modus lief.
Der Owner hat widersprochen, und zu Recht: eine Kontrolle, die dem ganzen
Betrieb die Geschwindigkeit nimmt, obwohl nur ein Teil der Arbeit reguliert
ist, wird nach zwei Wochen wieder ausgeschaltet. Fast-Track ist kein Mangel,
sondern das Produkt.

Sein Vorschlag war ein Kartenflag. Das trifft die richtige Form — `fast_track`
ist bereits genau das —, hat aber wörtlich genommen ein Loch:

> Karte X ist GxP und wird unterschrieben. Karte Y liegt im selben Repo, ist
> nicht GxP, fährt Fast-Track und deployt. Beide mergen in dasselbe `main`, und
> der Deploy-Hook läuft auf `main`. Im validierten Produkt steckt danach Code,
> den niemand unterschrieben hat — und die Unterschrift auf X sagt nichts mehr
> darüber aus, was ausgeliefert wurde.

Der Geltungsbereich ist also keine Eigenschaft der **Karte**, sondern des
**Artefakts**. In HelmDeck ist die Artefaktgrenze das Repo: ein `main`, ein
Deploy-Hook. Deshalb:

- **`repos: [...]` in der Lock-Datei** — jede Karte, die dorthin zielt, braucht
  eine Unterschrift.
- **`repos` fehlt** — der ganze Workspace ist im Geltungsbereich (die strenge
  Aufstellung für eine Instanz, die nur reguliert arbeitet).
- **Kartenflag `gxp: true`** — holt eine einzelne Karte zusätzlich herein, auch
  aus einem anderen Repo.
- **Nie abwählbar.** `gxp: false` kann keine Karte aus einem regulierten Repo
  herausholen, und `cardadmin` verweigert das Löschen des Flags mit einem
  Fehler statt es stillschweigend zu ignorieren. Andernfalls könnte alles, was
  eine Karte bearbeiten darf, sie aus dem validierten System herausspazieren.
- **Jedes andere Repo bleibt vollständig unberührt** — Fast-Track, Henry,
  Auto-Abnahme, alles wie bisher.

Der Satz für den Prüfer ist damit einzeilig: *„Dieses Repository hält das
regulierte Produkt; alles was dort landet, ist unterschrieben."*

Grenze, die bewusst offen bleibt: liegen reguliertes Produkt und interne
Werkzeuge im **selben** Repo, reicht Repo-Granularität nicht. Dann braucht es
Pfad-Ebene — mehr Komplexität, und erst zu bauen, wenn jemand diesen Fall
wirklich hat. Machinenkarten ohne `repo` sind aus demselben Grund nur über das
Kartenflag erreichbar.

### 2.7 Modus-Aktivierung — und das Restrisiko, offen benannt

```
spine/auth/gxp.py   ->  liest DAEMON_ROOT/gxp.lock bei JEDEM Aufruf frisch
                    (kein Cache, kein Modul-Global -> kein veraltetes Flag)
```

Die Lock-Datei trägt den Modus **und** die Feature-Sperren, damit beides nicht
auseinanderlaufen kann:

```jsonc
{ "enabled": true, "activated_at": "…", "activated_by": "duy",
  "repos": ["C:/work/pharma-product"],   // Geltungsbereich, s. 2.6b
  "disable": ["fast_track", "machine", "direct_task", "auto_accept_green",
              "henry_move", "henry_did", "agent_may_swap"],
  "four_eyes": false, "gate_profile": "full" }
```

`repos` weglassen heißt: der ganze Workspace ist im Geltungsbereich.

- **Einschalten:** Owner-Aktion, selbst signiert, in der Ereignissenke.
- **Ausschalten:** braucht Dateisystemzugriff auf dem Host **und** einen
  Daemon-Neustart. Nicht über den Chat, nicht über einen Policy-Swap, nicht aus
  einem Worktree heraus.

**Das Restrisiko, das ein Auditor mit Sicherheit anspricht:** eine
Maschinenkarte oder ein Direct Task läuft mit Shell-Zugriff auf dem Host und
könnte die Datei löschen. Deshalb schaltet die Lock-Datei genau diese Pfade ab
— aber das schließt das Loch nur für Agenten, die *nach* der Aktivierung
starten. Die ehrliche Antwort lautet: **der Modus wird bei der Inbetriebnahme
aktiviert, bevor ein Agent läuft, und die Aktivierung ist Teil der
qualifizierten Installation (IQ).** Diesen Satz sollte man vorbereitet haben,
statt ihn im Audit zu erfinden. Kein reines Software-Mittel kann einen Agenten
aufhalten, der bereits eine Shell hat; das ist keine Schwäche dieses Entwurfs,
sondern eine Eigenschaft des Bedrohungsmodells und gehört so in die
Risikobewertung.

---

## 3. UX

### 3.1 Prinzipien

1. **Wer nicht im GxP-Modus ist, merkt exakt nichts.** Keine neue Schaltfläche,
   kein Hinweis, kein zusätzlicher Tap. Das ist die Bedingung dafür, dass
   HelmDeck HelmDeck bleibt.
2. **Auswählen sendet nie.** Hausdoktrin, wörtlich begründet in
   `card_question.tsx:116-119`: Auto-Submit bei Tap machte einen Fehlgriff
   unumkehrbar. Bei einer Signatur wiegt das ungleich schwerer.
3. **Nie `Alert.alert`.** Auf react-native-web ein No-Op — dreimal im Code
   dokumentiert (`new.tsx:52-55`, `card/[id].tsx:740-742`). Fehler erscheinen
   inline, wie im Login (`login_screen.tsx:105`).
4. **Die Signatur ist ein menschlicher Akt und sieht auch so aus.** Der Token
   `t.human` (`#9B87E8`, `tokens.ts:62`) existiert bereits und wird sonst
   nirgends als Primärfarbe geführt. Die Freigabemaske ist der eine Ort, an dem
   er das ist. Das trennt sie visuell von jeder Maschinenaktion.
5. **Zeigen, was passiert.** Heute merged und deployt ein Tap auf ein
   13 px hohes Geisterpille (`board.tsx:280-285`) ohne jede Rückfrage. Die
   Freigabemaske ist nicht nur Compliance — sie ist das erste Mal, dass das
   System sagt, was es gleich tut.

### 3.2 Der Ablauf

**Schritt 1 — Auslöser.** Im GxP-Modus wird aus „erledigt" ein Knopf
`Freigeben` mit Stift-Icon in `t.human`. Die Drag-and-Drop-Geste auf die
`done`-Spalte (`board.tsx:414-430`) wird **nicht** gesperrt, sondern
umgeleitet: sie öffnet dieselbe Maske. Eine Geste zu verbieten, die es gestern
noch gab, ist schlechtere UX als sie zu übersetzen.

**Schritt 2 — Die Freigabemaske.** Ein echtes Modal (kein Action-Sheet, kein
`Alert`), Struktur nach dem Vorbild von `prompt_host.tsx:44-77`, aber
bildschirmfüllend statt zentriert, weil es scrollbaren Inhalt trägt:

```
┌─ FREIGABE ──────────────────────────── (Stift-Icon, t.human) ─┐
│  t-91  Relay-Reconnect härten                                 │
│                                                               │
│  WAS PASSIERT                                                 │
│   → merge feat/relay-retry nach main                          │
│   → deploy (deploy/push_update.sh)          ← heute unsichtbar│
│                                                               │
│  PRÜFSTAND                                                    │
│   Gate      ✓ bestanden                                       │
│   Änderung  7 Dateien   +240 −12          [Diff ansehen ▾]    │
│   Basis     e4f5g6h → a1b2c3d                                 │
│   Gebaut    claude-opus-5 · 4 Turns · beauftragt von: pm      │
│                                                               │
│  BEDEUTUNG                     (auswählen — sendet noch nicht)│
│   ( ) Freigegeben    landet und deployt            [t.ok]     │
│   ( ) Geprüft        bleibt in Review für Zweitfreigabe [t.human]│
│   ( ) Abgelehnt      zurück nach Working           [t.danger] │
│                                                               │
│  BEGRÜNDUNG                                                   │
│   [___________________________________]  Pflicht bei Ablehnung│
│                                                               │
│  UNTERSCHRIFT                                                 │
│   Unterzeichner  duy (owner)                        (fix)     │
│   Passwort       [•••••••••]                                  │
│   ⓘ Mit dem Signieren bestätigst du die oben gewählte         │
│     Bedeutung. Zeitstempel UTC, Eintrag ist unveränderlich.   │
│                                                               │
│                          [ Abbrechen ]  [ Signieren ]         │
└───────────────────────────────────────────────────────────────┘
```

Der Signieren-Knopf ist `disabled` bis Bedeutung gewählt, Passwort nicht leer
und — bei Ablehnung — eine Begründung vorhanden. Muster und Opazität wie der
Login-CTA (`login_screen.tsx:107-114`). Weiße Schrift auf `t.human`-Füllung,
**nicht** `t.accentTxt` — die dokumentierte Falle aus
`card_question.tsx:254-257`, wo eine Beschriftung genau daran verschwand.

**Schritt 3 — Nach dem Signieren.** Der Toast bleibt wie heute
(`board.tsx:528-532`), aber mit dem Signaturvermerk statt „Abgenommen":
`Freigegeben von duy · 14:02 UTC · landet…`. Auf der Karte erscheint dauerhaft
ein Signaturabzeichen, antippbar, das die vollständige Manifestation zeigt.

### 3.3 Stapelfreigabe

Aus der Review-Spalte: Langdruck aktiviert einen Auswahlmodus (Checkboxen),
Kopfzeile zeigt `Freigeben (3)`. Die Maske listet die drei Karten je mit
eigener Bedeutungswahl und eigenem, eingeklapptem Prüfstand — aufklappbar, aber
standardmäßig zu, sonst scrollt niemand bis zum Passwortfeld. Eine
Passworteingabe, drei Signaturdatensätze, drei `subject_hash`.

Fällt eine Karte durch die Hash-Prüfung, werden die anderen trotzdem
verarbeitet; das Ergebnis ist eine Liste, kein Alles-oder-nichts.

### 3.4 Ablehnung

`Abgelehnt` ist gleichwertig neben `Freigegeben`, nicht als Nebenausgang
versteckt. Begründung ist Pflicht, die Karte geht nach `working`, und die
Begründung landet als Steer-Nachricht beim Agenten — die Ablehnung wird damit
zur Arbeitsanweisung statt zu einer Sackgasse. Das ist der Punkt, an dem
Compliance und Produktivität ausnahmsweise dasselbe wollen.

### 3.5 Was sich sonst am Board ändert

| Ort | heute | im GxP-Modus |
|---|---|---|
| NextUp-Pille (`board.tsx:280-285`) | „erledigt", ein Tap | „Freigeben", öffnet Maske |
| Drag auf `done` (`board.tsx:414-430`) | verschiebt sofort | öffnet Maske |
| Move-Sheet (`board.tsx:563-577`) | Eintrag „done" | Eintrag öffnet Maske |
| Kartendetail (`card/[id].tsx:707-725`) | `moveTo("done")` | öffnet Maske |
| Kopfzeile | — | dezenter `GxP`-Chip in `t.human` |
| Erledigte Karte | Status-Pille | zusätzlich Signaturabzeichen |

Ein Detail, das heute schon ein Defekt ist und hier mitfällt: der
Abnahme-Handler setzt kein `setBusy` (`board.tsx:593-598`, im Gegensatz zu
`onMove` bei `:570-573`), der Knopf ist also doppelt antippbar. In der neuen
Maske ist das nicht mehr möglich.

### 3.6 Fehler- und Randfälle

| Fall | Verhalten |
|---|---|
| Falsches Passwort | Inline-Fehler in `t.danger`, Maske bleibt offen, Zähler für Lockout (GXP-S4) |
| Inhalt driftete seit Öffnen | „Die Karte hat sich geändert, seit du sie geöffnet hast." Prüfstand neu laden, erneut signieren |
| Signatur gültig, Merge scheitert | **Signatur bleibt gültig und protokolliert.** Karte bounct nach `review`, `consumed_by` bleibt `null`. Der Mensch hat freigegeben; die Maschine ist gescheitert. Diese beiden Dinge zu vermischen wäre falsch protokolliert |
| Vier-Augen verletzt | Bedeutung `Freigegeben` ist ausgegraut mit Begründung; `Geprüft` bleibt wählbar |
| Daemon nicht erreichbar | Kein Offline-Signieren. Eine Signatur, die der Server nicht verifiziert hat, ist keine |
| Nur ein Benutzerkonto | Warnung beim Aktivieren des Modus, nicht erst beim ersten Signieren |

### 3.7 i18n

Neue Zeichenketten gehören nach `app/src/i18n/dict/` und brauchen **beide**
Sprachen (`core.ts:71-73`). Der Signatur*datensatz* wird nicht übersetzt (§2.1).
Nicht das `"Abbrechen"` aus `action_sheet.tsx:46` nachahmen — das ist ein
bekannter Verstoß, kein Vorbild.

---

## 4. Bauanleitung

### Daemon

| Datei | Änderung |
|---|---|
| `spine/auth/gxp.py` | **neu.** `aktiv()`, `sperren()`, `vier_augen()` — Lock-Datei bei jedem Aufruf frisch lesen |
| `spine/auth/signatures.py` | **neu.** `subject(t)` (head/base-SHA), `create(...)` inkl. signiertem Tag, `gueltige_offene(t)`, `consume(...)` |
| `spine/auth/signkeys.py` | **neu.** Ed25519 pro Benutzer, passwortentsperrt (§2.0 Option A); `gpg.format=ssh` |
| `cells/engineer/lanemachine.py` | `_autocommit:188-211`: Agenten-Commits unter Agenten-Identität, nicht unter der des Hosts |
| `spine/auth/auth.py` | `verify_password(name, pw) -> bool` ergänzen — existiert nicht; `_check_pw` (`:42-48`) ist privat, und `login()` (`:131-140`) taugt nicht als Re-Auth, weil es bei jedem Aufruf eine Session **und** über die Route (`routes_auth.py:87`) ein Dauertoken mintet |
| `spine/http/routes/routes_sign.py` | **neu.** `POST /sign`, `GET /sign/subject/<tid>` |
| `cells/engineer/lanemachine.py` | Guard bei `:611`, Drift-Prüfung vor `:808`, Fast-Track-Sperre bei `:785`, `actor` auf das `done`-Ereignis bei `:843-845` |
| `cells/engineer/lanemachine.py` | `_classify_merge`: den echten Diff **vor** `merge --abort` mitnehmen, statt ihn zu verwerfen — liefert dem Freigabefenster den integrierten Stand statt einer Vorhersage (s. „Zwei naheliegende Abkürzungen") |
| `cells/engineer/dispatch.py` | `dispatched_by` in `new_track` (`:62-81`); Maschinen-Abnahme-Sperre (`:525-570`) |
| `cells/copilot/henry_broker.py` | `move`/`did` im GxP-Modus verweigern (`:258-273`) |

### App

| Datei | Änderung |
|---|---|
| `app/src/ui/sign_off.tsx` | **neu.** Die Maske. Vorbild `card_question.tsx` (Stepper, a11y, Select-then-confirm), Rahmen `prompt_host.tsx:44-77` |
| `app/src/data/client.ts` | `signSubject`, `signSession`, `sign` — Muster `answer()` (`:426-430`, Request-ID-Echo). `skipAuthGate=true` bei der Passwortprüfung, sonst wirft ein 401 den Benutzer zum Login (`:104-113`) |
| `app/src/ui/board.tsx` | Auslöser `:280-285`, `:414-430`, `:563-577`, `:593-598`; Auswahlmodus |
| `app/src/app/card/[id].tsx` | `moveTo` (`:707-725`); Signaturabzeichen |
| `app/src/i18n/dict/` | de + en |

Kein neuer Token nötig — `t.human`, `t.ok`, `t.danger`, `t.surface1`,
`t.backdrop` decken alles ab.

---

## 5. Was dieser Entwurf nicht löst

Damit die Erwartung stimmt. Stand nach `docs/gxp-plan.md`: Stufe 0 ist
geschlossen (A0–A5, A3, S4, S1 — alle sechs), der strukturelle Blocker ist zu
(kein Agent kann ohne Menschen landen), die Signatur liefert §11.50, §11.70
(auf das Commit-Paar gebunden), §11.200 (Re-Authentifizierung) sowie
Vier-Augen, das Freigabefenster ist gebaut (Phase C), und **Phase D — die
Audit-Härtung — ist vollständig gebaut**: jedes Ereignis trägt `at_utc`,
Datei und Tabelle können nicht mehr unbemerkt auseinanderlaufen
(`events-two-stores-unreconciled`, bezahlt), `tools/reset.py` verweigert bei
aktivem Modus statt Beweise zu löschen, und `GET /audit` liefert Filter plus
CSV-Export. Offen bleiben:

- ~~Das signierte git-Tag~~ — **gebaut** (`spine/auth/signkeys.py`, Schuld
  bezahlt). Jede Freigabe landet als GPG-signiertes Tag
  `gxp/approve/<karte>-<seq>`; ein Prüfer verifiziert mit Stock-git plus
  exportiertem Public Key. Abweichung vom Entwurf, gemessen statt gewünscht:
  GPG statt `gpg.format=ssh`, weil das git dieses Hosts (2.27) SSH-Tags nicht
  kann — gleiche Auditor-Geschichte, anderes Schlüsselformat. Zwei Funde beim
  Bauen: der MSYS-gpg braucht für alle Agent-Operationen Gits eigene bash,
  und der gpg-agent-Passphrase-Cache musste hart abgeschaltet werden, weil
  sonst nach einer Signatur ~10 Minuten lang **jedes** Passwort signierte.
- **Rohkommando bei Sprache** (§2.1b) — designed, nicht gebaut. Für Rolle B
  (dieser Entwurf) ein Nice-to-have am Begründungsfeld. Für einen möglichen
  Rolle-A-Zweig (KI trägt Messwerte/Anweisungen in ein fremdes reguliertes
  System ein, z. B. per Sprachdiktat) wäre es tragend — dort gibt es kein
  unabhängiges zweites Artefakt wie einen Commit, gegen das man prüfen könnte.
  Das ist ein eigenständiges Vorhaben, kein Teil dieser Karte.
- **Stufe 2 / CSV** — Validierungsplan, URS/FS/DS, RTM, IQ/OQ/PQ, Gate mit
  echtem Regressionstest, Umgebungstrennung, OTA-Code-Signing. Davon berührt
  dieser Entwurf nichts.
- **Verifikation auf echter Hardware** — der gepackte Drei-Start-Durchlauf der
  Desktop-App (A1) und ein Screenshot der Freigabemaske (Phase C) brauchen
  einen Rechner mit Electron/Browser, den dieser Worktree nicht hat.

---

## 6. Aufwand

Grobschätzung, keine Zusage.

| Block | Schätzung |
|---|---|
| Stufe 0 (Voraussetzung) | 1–2 Tage |
| Daemon: Modus, Signaturen, Re-Auth, Routen, Guard | 2 Tage |
| App: Maske, Stapel, Board-Umleitungen, i18n | 3–4 Tage |
| Audit-Härtung (UTC, Auth-Ereignisse, Review-Route) | 2–3 Tage |
| **Summe bis „ein Mensch signiert nachweisbar jede Auslieferung"** | **8–11 Tage** |

Nicht in v1 und daher nicht eingerechnet: Signier-Session (§2.4, gestrichen),
Vier-Augen (§2.6, Schalter — ca. ein halber Tag, wenn ein Kunde ihn will),
Integrations-Branch statt main (Stufe 2).

Das ist die Strecke bis zu einer Aussage, die in einer Lieferantenprüfung
trägt. Die volle CSV-Strecke (Stufe 2) ist ein Vielfaches davon und
größtenteils Dokumentation, nicht Code.

Wenn beim Bau eine tragende Abkürzung entsteht, gehört sie nach
`spine/registry/debt.py` — im selben Commit.
