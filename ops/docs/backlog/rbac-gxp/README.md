# RBAC für GxP — Rollen & Berechtigungen auf Compliance-Niveau

Owner-Auftrag (2026-08-26): RBAC so ausbauen, dass HelmDeck in einem
GxP-regulierten Umfeld (21 CFR Part 11, EU Annex 11, GAMP 5, ALCOA+)
bestehen kann. Vorarbeit: Rollen-Audit dieser Session (siehe Befund) und
`settings-ia-redesign` (Korrektur 1: Rollen-Widerspruch Tür „Allgemein").

## Befund (Ist, code-verifiziert 2026-08-26)

**Solide Basis (nicht neu bauen):**
- Append-only Audit existiert und ist ernst gemeint: `spine/auth/auth.py::_audit`
  loggt Login **inkl. Fehlversuchen**, `user.create/delete/password/role`
  (Rollenwechsel MIT Vorher-Wert), Token-Issue/Revoke; ein Test hält
  „kein Secret im Log". Sessions haben TTL (30 Tage, sliding).
- Policy-Änderungen laufen tracked über `policy.swap` (Event-Spiegel).
- Cell-Gate 404t Routen deaktivierter Cells zentral (ein Check im Dispatch).

**Lücken:**
1. **Autorisierung ist verstreute Inline-Prosa:** ~30 `if user["role"] != …`
   -Checks quer durch server.py + route modules, drei hartcodierte Rollen
   (owner/operator/client). Keine zentrale Stelle, die sagt, WER WAS darf —
   für ein Audit müsste man jeden Handler lesen.
2. **Verifizierte Löcher:** `routes_runs.py::runs_get` und `live_jpg_get`
   (Bildschirm-Aufnahmen + Live-Frame des Owner-PCs!) haben KEINEN
   Rollen-Check — jeder authentifizierte Client sieht sie. `/escalations`
   (nennt Repos/Fehlerdetails) ist nur client-blockiert, Operator ok —
   vermutlich gewollt, aber nirgends als Entscheidung dokumentiert.
3. **Nav ≠ Berechtigung:** Client-seitig gibt es nur `teamOnly` (versteckt vor
   client). Operatoren sehen Settings/Automatik/Module-Links, die serverseitig
   owner-only sind → 403-Sackgassen; umgekehrt ist Verstecken im Client kein
   Schutz. Nav-Flags sind Handpflege in DREI Tabellen (tabs.ts, NAV-Fallback,
   TAB_FALLBACK) + more.tsx-GROUPS — Drift ist strukturell.
4. **Keine GxP-Konzepte:** keine Funktionstrennung (der Owner dispatcht UND
   akzeptiert), keine Re-Auth/E-Signatur für kritische Aktionen, keine
   Access-Reviews, Gerätetokens ohne Ablauf, kein Vier-Augen-Modus, keine
   Auditor-Rolle (Audit-Log ist gar nicht per UI einsehbar).

## GxP-Anforderungen → was sie konkret verlangen

| Anforderung (Part 11 / Annex 11) | Konsequenz für HelmDeck |
|---|---|
| Eindeutige Nutzer, kein Shared Account | vorhanden (users + Tokens pro Gerät); Invite-Flow behält das bei |
| Least Privilege + dokumentierte Rollen | zentrale Permission-Matrix als Daten, generiertes Matrix-Dokument |
| Funktionstrennung (SoD) | Doer ≠ Approver erzwingbar (Karte ausführen vs. abnehmen) |
| Audit Trail: wer/was/wann/alt/neu | Settings-Writes müssen old→new-Diff + Actor + Grund loggen |
| E-Signatur: Re-Auth + Bedeutung | kritische Aktionen fordern Passwort + „meaning" (z. B. „approved") |
| Access-Lifecycle + periodischer Review | Provisioning-Events (da), Review-Export, Token-TTL, Inaktivitäts-Logout |
| Validierung / Traceability | Matrix ↔ Routen ↔ Tests maschinell abgeglichen, nicht handgepflegt |

## Zielbild

### 1. Permission-Registry (policy is data, wie alles hier)

`spine/auth/permissions.py`: Capabilities als `resource.action`-Strings
(`settings.read`, `settings.write`, `cards.dispatch`, `cards.accept`,
`recordings.view`, `audit.read`, `users.manage`, …). EINE Matrix
Rolle→Capabilities als Daten, EIN Guard:

```python
def require(user, cap):  # -> None oder 403-Antwort
```

Jede Route DEKLARIERT ihre Capability (Erweiterung der bestehenden
GET_ROUTES/POST_ROUTES-Dispatch-Tabellen um ein Feld bzw. eine parallele
CAPS-Tabelle); server.py enforced zentral direkt nach dem Auth-Gate —
gleiche Stelle und gleiches Muster wie `cells.path_disabled`. Die ~30
Inline-Checks fallen weg (Umstellung byte-nachweisbar: Test vergleicht
effektive Rolle→Route-Erlaubnis vor/nach).

**Matrix-Änderungen sind selbst auditpflichtig:** Änderung nur über den
tracked `policy.swap`-Pfad (Event mit alt→neu), nie per File-Edit.

### 2. Rollenmodell: 3 + 2

Bestehende Rollen bleiben semantisch gleich (kein Migrationsbruch):
- `owner` — Admin (alles außer dem, was SoD ihm nimmt, s. u.)
- `operator` — arbeitet (dispatch, steer, prozesse, connectors-run)
- `client` — files & kommentiert eigene Karten
Neu:
- `quality` — Approver: darf abnehmen/freigeben, NICHT dispatchen (SoD-Gegenstück)
- `auditor` — read-only ALLES inkl. Audit-Trail-Ansicht; keine einzige Schreib-Capability

SoD als Policy-Knob (default AUS, damit Solo-Owner-Betrieb unverändert
bleibt): `policy.sod_accept` = „accept erfordert quality-Rolle UND
Actor ≠ Dispatcher der Karte". Aktivierung selbst ist eine auditierte
Policy-Änderung.

### 3. Nav aus der Matrix generiert (kein viertes Flag-System)

Surface.nav bekommt statt `teamOnly`/neuem `ownerOnly` genau EIN Feld:
`cap?: string` — die Capability, die die Ziel-Route braucht. Der Navigator
(alle drei Tabellen + more.tsx) filtert über `can(me, cap)` gegen die vom
Daemon in `/me` mitgelieferte effektive Capability-Liste. Damit:
- Operator sieht keine owner-only-Links mehr (403-Sackgassen weg),
- Client-Verstecken und Server-Gate speisen sich aus DERSELBEN Quelle,
- eine Matrix-Änderung wirkt sofort in Nav UND Server (kein Drift möglich).
`teamOnly` bleibt übergangsweise als Fallback-Mapping (`teamOnly` ≙
`cap: "team.member"`), stirbt mit der Umstellung.

### 4. Audit-Trail-Härtung (ALCOA+)

- `save_settings` loggt pro Write ein Event mit Actor, Pfad(en), old→new-Diff
  (Secrets maskiert — gleiche „kein Secret im Log"-Testpflicht wie auth.py).
- Kritische Events tragen ein optionales `reason`-Feld (UI fragt bei
  E-Sign-Aktionen danach, s. 5).
- Audit-Review-Screen (Rolle auditor + owner): filterbare Ansicht des
  Audit-Logs, read-only, exportierbar (CSV) für den periodischen Review.
- Gerätetokens bekommen optionale TTL + `last_used` (letzteres existiert
  als `last_seen` bei Devices) → Review-Export markiert „>90 Tage unbenutzt".

### 5. E-Signatur & Vier-Augen

Signaturpflichtige Aktionen (per Matrix markiert, initial): Karte
**abnehmen** (accept), **Gate-Override/Fast-Track-Flip**, **policy.swap**
(inkl. Matrix/SoD/Cell-Flags), **Nutzer anlegen/Rolle ändern**.
Ablauf = Part-11-Minimum: Re-Auth (Passwort der handelnden Person) +
explizite Bedeutung („approved" / „rejected" / Freitext-Grund) → ein
Signatur-Event (wer, was, wann, Bedeutung) im append-only Log. Als
Policy-Knob schaltbar (`policy.esign` default AUS — Solo-Betrieb bleibt
reibungslos), Aktivierung auditiert.

### 6. Sofort-Fixes (unabhängig vom Zielbild, VOR allem anderen)

- `/runs`, `/live.jpg`, `/runs/<id>/*` gaten (mind. client-blockiert;
  Capability `recordings.view`).
- `/escalations`-Operator-Zugriff als bewusste Entscheidung dokumentieren
  oder auf owner engen.
- Nav: owner-only-Ziele für Operatoren ausblenden (Interim: `ownerOnly`-Flag,
  wird in 3 durch `cap` ersetzt).

## Karten

| # | Karte | Inhalt | Akzeptanz |
|---|---|---|---|
| 1 | `rbac-quick-gates` | Sofort-Fixes aus 6 | /runs & /live.jpg 403 für client (Test); Operator-Nav ohne 403-Sackgassen (Screenshot) |
| 2 | `rbac-permission-registry` | permissions.py + Guard + Routen-Deklaration + zentrale Enforcement-Stelle; Inline-Checks ersetzt | Paritäts-Test alt=neu für alle 3 Bestandsrollen; jede Route hat genau 1 Capability (Test zählt) |
| 3 | `rbac-roles-quality-auditor` | neue Rollen + SoD-Knob `policy.sod_accept` | quality kann accepten aber nicht dispatchen (Test); SoD an: Dispatcher-Accept wird 403 + Audit-Event |
| 4 | `rbac-nav-from-matrix` | `/me` liefert Capabilities; Nav-`cap`-Feld in allen 3 Tabellen + more.tsx; teamOnly-Ablösung | Rolle×Screen-Matrix-Test: sichtbar ⇔ Route erlaubt; Screenshots owner/operator/client/quality/auditor gejudged |
| 5 | `rbac-audit-hardening` | settings-Diff-Events, reason-Feld, Audit-Screen + CSV-Export, Token-TTL/Stale-Markierung | Settings-Write erzeugt old→new-Event ohne Secrets (Test); auditor sieht Log, kann nichts schreiben (Test) |
| 6 | `rbac-esign` | Re-Auth + meaning für signaturpflichtige Aktionen, `policy.esign`-Knob | esign an: accept ohne Re-Auth unmöglich (Test); Signatur-Event vollständig (wer/was/wann/Bedeutung) |
| 7 | `rbac-validation-doc` | generiertes Matrix-Dokument (ops/docs/), Traceability Part11/Annex11-Punkt → Code → Test | Doc wird aus permissions.py GENERIERT (Gate-Check: Doc stale = rot); jede Tabellenzeile oben hat Verweis |

Reihenfolge: 1 sofort; 2 → 3 → 4 sequenziell; 5–7 danach, 5 und 6 parallelisierbar.

## Wechselwirkungen

- **settings-ia-redesign:** Korrektur 1 dort (Sprache für Nicht-Owner) wird
  hier sauber: `me.prefs.write` als Capability jeder Rolle auf whitelisted
  Personal-Keys — kein Sonderweg mehr nötig. Tür „Team & Geräte" zeigt
  künftig Rollen aus der Matrix statt Freitext. Die Hub-Türen tragen `cap`.
- **Charter-Gesetz** „never weaken auth": alles hier VERSCHÄRFT nur; die
  einzige Lockerung (client sieht /runs nicht mehr: keine) existiert nicht.
- **NO MONKEY PATCHES:** effektive Rechte werden IMMER aus `/me` +
  Matrix abgeleitet (eine Quelle), nie im Client dupliziert oder gecacht
  über Rollenwechsel hinweg (Query-Invalidierung auf ["me"] wie bei lang).
- **Henry:** signaturpflichtig=ja/nein ist Code (Matrix), aber GRENZFÄLLE
  (z. B. „accept eigener Karte im Solo-Betrieb trotz SoD-Wunsch") eskalieren
  an Henry statt hart zu verbieten — Judgement zu Henry, Invarianten in Code.

## Nicht-Ziele

- Kein SSO/LDAP/OIDC in dieser Ausbaustufe (Einzel-Instanz, lokale Nutzer).
- Keine Änderung der Ökonomie-/Quota-Logik.
- Kein Umbau der Session-/Token-Transportschicht (E2E-Relay bleibt wie ist).
- `client` bleibt bewusst minimal — GxP-Tiefe gilt dem Team, nicht Endkunden.
