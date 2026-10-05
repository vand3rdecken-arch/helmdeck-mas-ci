# Team-Konten: Rolle `member`, Räume, Gedächtnis-Bereiche

Owner-Auftrag (2026-10-04, Chat): Die *** nutzt HelmDeck mit
eigenem Konto, hauptsächlich für Team und Arbeit. Anforderungen aus dem Chat:

- eigenes Konto statt Pairing (ein gekoppeltes Gerät erbt die Rolle des
  Registrierenden, `spine/auth/devices.py`);
- Least Privilege: erst eng, dann gezielt öffnen;
- Team-Chats wie Slack-Channels, Henry antwortet NUR bei `@henry`, auf die
  jeweils letzte Nachricht, mit Namen;
- Nutzer erwähnen (`@name`) und auf Dinge aufmerksam machen;
- Admins dürfen private Chats nur mit Erlaubnis des Nutzers lesen.

## Befund (Ist, code-gelesen 2026-10-04, nichts ausgeführt)

| Thema | Stand | Quelle |
|---|---|---|
| Gedächtnis | global: `memory_all()` ohne WHERE, `account`-Spalte ungenutzt, CLAUDE-CLI-Auto-Memory eingemischt, `overview()` + `recall_block()` in JEDEM Turn | `db.py:877`, `copilot_memory.py:277,437,476,512`, `copilot.py:2724` |
| Push | workspace-global: `push.devices` / `push.fcm_token`, `chat_reply` sendet an ALLE Geräte, kein Konto-Filter | `notify.py:128-181,439`, `routes_system.py:159-174` |
| Chat-Gate | hart `role == "client"` an 6 Stellen, nicht über `chat.use` | `routes_copilot.py:17,33,43,80,195,392` |
| `chat_post` + Karten-ID | prüft `owns_card` selbst nicht (nur `_route_to_card`) | `routes_copilot.py:129,195` |
| Karten-Sicht | nur `owner/operator` (alles) oder `client` (`track.client == name`); kein "geteilt mit" | `auth.py:72-98` |
| Karten-Chat | Autor gespeichert (`by`, `byKind`), Henry sieht nur "human" statt Name; Session pro (Nutzer, Karte), Timeline geteilt | `copilot.py:984,1034,2542` |
| Erwähnung | nur Agenten-Empfänger (`henry`, `worker`) | `card_composer.tsx:30,254`, `card/[id].tsx:380`, `chat.tsx:637` |
| Turn-Lock | pro Nutzer-Key, zweite Nachricht wird "eingereiht"; ein neuer Turn kann den laufenden ersetzen (UNTERBROCHEN-Note, last-wins a36d962) | `copilot.py:2760-2776` |
| Henry-Rechte | Berechtigungsmodus workspace-weit (`henry_pmode`), nicht pro Rolle | `copilot.py:844-887` |

Vorbilder, die wiederverwendet werden (nicht neu erfinden):
- `henry_broker` startet Henry für `client`-Karten mit `perm="plan"` und ohne
  Hände (`henry_broker.py:507`) = Muster "Henry beratend".
- `_client_safe` blendet Henry-Schritte im Karten-Transkript aus
  (`routes_tracks.py:22-32`) = Muster "geteilte Karte zeigt wenig".
- `chat(..., allow_actions=False)` (Brillen-Seam) erzwingt "nur beraten" im Code.
- `permissions.py`-Matrix + `policy.swap` für neue Rolle/Caps.

## Sofort-Check (vor allem anderen, kein Code)

Steht das *** in `push.devices`? Bekommt es Pushes zu Henry-Antworten
des Owners? Das Leck existiert bereits mit `client`. Ergebnis hier notieren.

## Modell

- **Raum** = zusätzlicher Thread-Typ neben Karte und Posteingang
  (`cells/copilot/chat/threads.py`), KEIN zweites Chat-System (Beschluss
  "Threads = Karten", "never two chat UIs"). Felder: `id`, `name`, `members`
  (Konten), `henry_on_mention: true`.
- Eine Henry-Session pro RAUM (`_skey` um Raum-Key erweitern), nicht pro Nutzer.
- Henry antwortet nur auf `@henry`, auf die letzte Nachricht, mit Namen.
- Karten erben die Mitglieder des Raums, aus dem sie entstehen.
- Privater Henry-Chat jedes Nutzers bleibt als Posteingang erhalten.

## Stufen (jede einzeln lieferbar, eine Karte pro Stufe)

1. **Push pro Konto.** Geräte werden einem Konto zugeordnet; `chat_reply` und
   `card_event` adressieren Konten. Test: Gerät von A bekommt keinen Push zu
   B's Chat.
2. **Gedächtnis mit Bereich.** `memory.scope` (person | room | card) + `scope_id`
   (Migration in `db.py`, Altzeilen = person/owner). Alle Lesepfade
   (`memory_all`, `all_notes`, `recall`, `recall_block`, `overview`, `digest`)
   nehmen Konto + Raum/Karte und filtern. CLI-Auto-Memory für `member` aus.
   Test (echter Pfad, schlägt auf altem Code fehl): ein `member`-Turn sieht keine
   Owner-Notiz im `<harness-memory>`-Block.
3. **Räume + `client` als Gast (Slack-Guest-Modell, KEINE neue Rolle).**
   Rollen bleiben owner / operator / client (Owner-Entscheid 2026-10-05,
   Vergleich Slack/Jira/GitHub: wenige Rollen, Feinsteuerung pro Ressource).
   `owns_card` kennt `geteilt_mit`; Räume mit Mitgliederliste; Autor-Name an
   jeder Nachricht; Chat-Gate von `role == "client"` auf Raum-Mitgliedschaft
   umstellen (client: Raum-Chat ja, privater Henry-Posteingang nein); neue
   Capability `rooms.manage` für owner/operator; `chat_post` prüft Karten-Sicht.
   `auditor`/`quality` bleiben unberührt (`quality` hängt an der Vier-Augen-
   Regel in `lanemachine.py`, ungelesen, daher kein Entfernen in diesem Scope). Sicht auf geteilte Karten nach `_client_safe`-Muster:
   Titel, Status, Ergebnis; Karten-Chat nur wenn geöffnet; Aufzeichnungen und
   Action-Logs nie.
4. **Henry im Raum.** Nur `@henry`; Namen in `_card_context`/Raum-Kontext statt
   "human"; Turn-Lock pro RAUM mit Warteschlange, kein Ersetzen über Autoren
   hinweg (der UNTERBROCHEN-Pfad gilt nur für denselben Autor); Start mit
   `perm="plan"` und `allow_actions=False`; eigener Brief per `extra_system`.
   RISIKO: größter Eingriff in `copilot.chat()`; vorher `HARNESS.md` Abschnitt
   Spawn/Persistent Port lesen.
5. **`@Nutzer`.** Composer-Empfänger um Mitglieder erweitern, Push + Ungelesen
   an das erwähnte Konto; Erwähnung teilt die Karte im Umfang aus Stufe 3.
6. **Raum → Karte.** Henry legt aus dem Raum eine Karte an (vorhandenes
   `direct_task`-Verb), `geteilt_mit` = Raum-Mitglieder.
7. **Chat-Freigabe.** Privater Henry-Chat nur mit Freigabe des Nutzers:
   Record `{konto, fuer, bis, widerrufen}`; "aktiv?" wird bei jedem Lesen
   abgeleitet, nie als Flag gespeichert; neue Admin-Leseroute prüft sie; jeder
   Lesezugriff im append-only Audit; der Nutzer sieht in der App, wann gelesen
   wurde. Raum-Mitglieder sehen Räume ohnehin.

## Schulden (in `spine/registry/debt.py` im selben Commit eintragen)

- Freigabe ist eine Produktregel, keine Verschlüsselung: der Betreiber von
  Daemon und `helmdeck.db` kann technisch immer direkt lesen. Für ein
  rechtliches "Admin kann nicht lesen" wäre Verschlüsselung pro Konto nötig.
- Kosten laufen weiter über den Plan des Owners (`record_spend` ohne
  Konto-Aufteilung), bis eigene Abrechnung existiert.

## Nicht in diesem Scope

- Aktionen für `member` freischalten (Erinnerungen, Recherche, Hände): erst
  nach Stufe 7, einzeln und mit Test.
- Eigenes Claude-Abo / eigenes Gerät pro Person.
- Räume mit Gästen außerhalb des Workspaces.

## Entschieden (Owner, 2026-10-05)

- Mitglieder zu einem Raum hinzufügen dürfen `owner` und `operator`, nicht
  `member`/`client`. Neue Capability `rooms.manage` in `permissions.py`.
- Karten anlegen dürfen alle Rollen inkl. `member` (wie `client` heute über
  `/tracks/new`). Ob Henry selbst aus einem Raum eine Karte anlegt (Stufe 6),
  ist durch "auch Karten anlegen" gemeint, aber nicht eindeutig: bei der
  Umsetzung von Stufe 6 rückfragen.

## Rollenmatrix (Soll)

Quelle Ist: `spine/auth/permissions.py:81-104`. Drei Rollen:

| Rolle | Entspricht | Sicht und Rechte |
|---|---|---|
| owner | Slack Owner | alles, Identität und Einstellungen |
| operator | Slack Admin | alle Karten, Räume und Mitglieder verwalten (`rooms.manage`) |
| client | Slack Guest | eigene und geteilte Karten, Räume in denen Mitglied; Karten anlegen; Henry nur beratend im Raum |

Titel der Karte sagt noch "member": gemeint ist die Gast-Funktion der Rolle
`client`. Optionales Umbenennen (`client` -> `member`/`guest`) ist Kosmetik und
nicht Teil dieser Karte.
