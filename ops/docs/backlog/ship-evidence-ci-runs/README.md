# Ship-Evidenz kennt GitHub Actions nicht — Mac-Build-Failures erreichen Henry nie

**Anlass (Owner-Report, 2026-09-12 23:10):** Mail "[Tienduyvo/helmdeck]
desktop-mac: All jobs have failed". Owner: "Warum ship problem nicht bei
Henry? Der shipping process sollte doch intelligent sein."

## Befund (gh api, Tienduyvo-Token)

Alle sechs desktop-mac-Runs seit 2026-09-11 (f12db2c … 70567af) und beide
desktop-mac-mas-Runs vom 10.09. sind mit derselben einzigen Annotation
gescheitert, der Job wurde nie gestartet:

```
The job was not started because recent account payments have failed or your
spending limit needs to be increased. Please check the 'Billing & plans'
section in your settings
```

Das Repo ist privat, macOS-Runner-Minuten zählen 10x gegen das Kontingent.
Behebung liegt beim Owner (github.com/settings/billing). Bis dahin löst jeder
Push auf main, der `surfaces/app/**`, `surfaces/desktop/**` oder `daemon/**`
berührt, weiter einen Failure aus (Push-Trigger in `.github/workflows/desktop-mac.yml`).

## Warum Henry blind ist — drei Lücken, keine davon Dummheit

1. **Der Ship-Prozess kennt nur Android.** `cells/copilot/harness/agents/ship-advisor.md`
   erlaubt genau `none | ota | native`, alle drei meinen das Telefon; `desktop`
   fällt laut Brief explizit unter "none". Der Mac-Build ist im HelmDeck-Ship
   kein Kanal, er hängt als loser GitHub-Push-Trigger nebenher.
2. **Niemand liest das Ergebnis.** `ops/tools/ship_facts.py` liefert nur lokale
   Fakten (Diff-Klassifikation, app.json/APK/Relay-Versionen, Ressourcen).
   Kein Code in `spine/`, `cells/`, `daemon/` fragt je einen Run-Status ab.
   Die Ship-Decision von 22:48 ("nichts erreicht ein Gerät") war für das
   Telefon korrekt; der Billing-Stopp stand in keiner Evidenz, die Henry bekommt.
3. **Token-Falle.** Das aktive gh-Konto auf der Box ist `vand3rdecken-arch`
   (kein Zugriff auf Tienduyvo/helmdeck, 404). Der Run-Status ist nur mit
   `gh auth token -u Tienduyvo` lesbar.

## Fix (eine Karte, drei Schritte)

1. **`ship_facts.py` bekommt einen `ci`-Block:** pro Workflow (desktop-mac,
   desktop-mac-mas, watchos-app) letzter Run für HEAD bzw. den letzten Push:
   conclusion, createdAt, Annotation-Text (via `gh api repos/…/check-runs/<job>/annotations`).
   Token: `gh auth token -u Tienduyvo`, fail-soft (Block fehlt mit Grund, nie ein Crash).
2. **Ship-Advisor-Brief: vierter Kanal `desktop`.** Frage 1 wird "erreicht die
   Änderung Telefon ODER Desktop"; ein roter CI-Run für den gerade gelandeten
   Commit ist die Headline, wie heute ein Versions-Mismatch. Billing/Runner-
   Probleme sind `next steps` an den Owner, kein Retry.
3. **Rückkanal nach dem Push:** nach `request_ship_decision` bzw. dem
   Push, der den Workflow triggert, pollt der Daemon den Run (Push-Event,
   ~7s bis Billing-Fail, ~20min bis Build-Ende) und öffnet bei `failure` eine
   Eskalation `ci-failed` an Henry, Track = die Karte, Detail = Annotation.
   Nie mehr als eine offene pro (workflow, sha). Ohne das bleibt es eine Mail.

**Nicht ändern:** Henrys Rechte sind seit 2026-09-12 nicht der Grund
(auto-Mode, Deny nur Secrets); die Lücke ist Evidenz, nicht Erlaubnis.

**Beweis:** Test, der `ship_facts --json` mit einem gemockten
`gh api`-Ergebnis (billing-Annotation) laufen lässt und den `ci`-Block prüft;
Test, dass ein failure-Run genau EINE `ci-failed`-Eskalation erzeugt und ein
zweiter Poll keine zweite.

## Status 2026-09-12 23:40 — Schritte 1+2 durch die Karten-Architektur erledigt (4e4f5cc)

Owner-Korrektur: nicht `ship_facts.py` erweitern, sondern die ENTSCHEIDUNG
als Karte laufen lassen, die selbst recherchiert. Umgesetzt: jede Landung
legt eine `decide`-Ship-Karte an (`ship-worker.md`, Phase DECIDE liest
GitHub-Actions-Runs mit dem Tienduyvo-Token, Relay, git diff), entscheidet
none|ota|native, führt aus, verifiziert, schließt sich mit SHIP: OK|NONE.
Henry bleibt Exception-Broker für hängende Karten.

**Offen bleibt nur Schritt 3** (Rückkanal für einen Run, der ERST NACH dem
Push rot wird, z.B. ein 20-Minuten-Build, der bei Minute 15 scheitert):
Daemon pollt den Run nach dem Push und öffnet bei `failure` eine Eskalation
`ci-failed` an Henry. Kleine Karte, kein Blocker.

## Status 2026-09-12 23:55 — Schritt 3 GESCHLOSSEN, in der Karte statt im Daemon

Owner: "Sollte das nicht in Karte sein? Er shippt und stellt sicher, dass
alles geshippt ist." Genau so: kein Daemon-Poller, keine Extra-Eskalation.
Die Ship-Karte begleitet jeden Run, den sie anstößt, mit `gh run watch
--exit-status` bis zum Ende (Turns sind silence-bounded, nicht wall-clock;
watch liefert laufend Output) und sagt SHIP: OK erst, wenn der Run grün ist
und das Artefakt existiert. Rot mittendrin = klassifizieren, max. ein Retry,
sonst FAILED mit dem Schritt, und die Karte parkt sichtbar bei Henry.
Brief ship-worker.md (Verify) + HelmDeck-Prozess-Zeile in der DB angepasst.
