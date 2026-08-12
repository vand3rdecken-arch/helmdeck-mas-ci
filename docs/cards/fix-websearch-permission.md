# Karten-Vorschlag: WebSearch/WebFetch in Worker-Karten freischalten

> **Status:** UMGESETZT (2026-08-12, Karte `chat-fix--websearch-webfetch-`).
> `permissions.allow` enthält jetzt `WebSearch` + `WebFetch`; beide Tools in der
> Fix-Karte live verifiziert (4× WebSearch, 1× WebFetch, kein Permission-Fehler)
> und der §6.3-Vorbehalt in `docs/ios-watch-feasibility.md` per verifiziertem
> Anbieter-Vergleich (§6.4) aufgelöst.

## Problem

In einer HelmDeck-Worker-Karte sind `WebSearch` und `WebFetch` **gesperrt**: der
Aufruf kommt sofort mit „you haven't granted it yet" zurück, und der interaktive
Freigabe-Dialog greift auf einer asynchronen Karte nicht. Konkret aufgetreten bei
der iOS-Machbarkeitsstudie: die Recherche eines aktuellen App-Builder-Vergleichs
(Rork, FlutterFlow, Draftbit … Stand 2026) war nicht möglich — der Worker musste
auf ungeprüften Trainingsstand (Jan 2026) zurückfallen. Jede Karte, die „schau
online nach" braucht, läuft heute in diese Wand.

## Fix

`.claude/settings.json` → `permissions.allow` um die beiden Web-Tools erweitern.
Ist-Zustand (nur drei Deploy-Bash-Einträge):

```json
"permissions": {
  "allow": [
    "Bash(bash deploy/push_ntfy.sh*)",
    "Bash(bash deploy/push_relay.sh*)",
    "Bash(bash deploy/cloudflare_tunnel.sh*)",
    "WebSearch",
    "WebFetch"
  ]
}
```

Optional restriktiver statt `"WebFetch"` pauschal: auf Domains scopen, z. B.
`"WebFetch(domain:docs.expo.dev)"` — für eine offene Recherche-Fähigkeit aber
zu eng; die pauschale Freigabe ist hier die richtige Wahl (beide Tools sind
read-only, kein Schreibzugriff, kein Exfil-Pfad über das Board).

Umsetzung am saubersten über die Skills `update-config` bzw.
`fewer-permission-prompts` (die schreiben genau diese Allowlist), nicht per Hand.

## Akzeptanz / Done-when

1. Eine Folge-Karte kann `WebSearch`/`WebFetch` ohne Permission-Denied aufrufen.
2. Als Nachweis: der in `docs/ios-watch-feasibility.md` §6.3 als „offen" markierte
   **verifizierte** App-Builder-Vergleich (Publish-Wege iOS + Mac-Desktop,
   Preise, Repo-Import ja/nein) wird nachgezogen und der Vorbehalt dort entfernt.

## Scope

- `.claude/settings.json` (die Allowlist).
- danach: `docs/ios-watch-feasibility.md` §6 aktualisieren (Vorbehalt auflösen).

Kein Produktionscode, kein Daemon, keine Migration. Reiner Settings- + Doc-Change.
