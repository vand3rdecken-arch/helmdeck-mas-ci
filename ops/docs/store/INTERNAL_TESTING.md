# HelmDeck — Internal-Testing-Track einreichen (Owner-Runbook)

Alles hier braucht den Google-Play-Account bzw. EAS-Login — deshalb
Owner-Aktion. Die Zuarbeit (Policy-URL, Data-Safety-Antworten, Texte,
Screenshots) liegt fertig in diesem Repo:

| Baustein | Wo |
|---|---|
| Datenschutz-URL (live nach Relay-Deploy) | `https://relay.helmdeck.de/privacy` — vorher einmal `bash ops/deploy/push_relay.sh` |
| Data-Safety-Antworten | `ops/docs/store/DATA_SAFETY.md` (Tabelle §2 abtippen) |
| Kurz-/Langbeschreibung DE+EN | `ops/docs/store/LISTING.md` |
| Screenshots (1080×2400) | `ops/docs/store/screenshots/01…04*.png` |
| Technik-Checkliste (Signing, Cleartext, assetlinks) | `surfaces/app/PLAY_STORE_RELEASE.md` |

## 0. Einmalige Voraussetzungen

1. Google-Play-Entwicklerkonto (25 $ einmalig). Personen-Konten nach
   Nov 2023: Produktion erst nach geschlossenem Test mit **12 Testern über
   14 Tage** — Internal Testing geht sofort, den Closed-Test also früh starten.
2. `ops/deploy/push_relay.sh` einmal ausführen → `/privacy` ist öffentlich.

## 1. AAB bauen (EAS)

```
cd surfaces/app && eas build -p android --profile production
```

- Erster Build: EAS legt den Upload-Keystore an (Standard akzeptieren).
- `google-services.json` liegt nur lokal — vorher als EAS-File-Env
  `GOOGLE_SERVICES_JSON` hinterlegen (Dashboard → Environment variables,
  Typ „file"), sonst schlägt der Cloud-Build fehl.
- Artefakt: `.aab` aus dem EAS-Dashboard herunterladen.

## 2. App-Record anlegen (Play Console)

1. Play Console → **Create app**: Name „HelmDeck", Sprache Deutsch,
   App (kein Spiel), kostenlos.
2. Play App Signing: aktiviert lassen (Standard bei neuen Apps).

## 3. App content ausfüllen (Policy → App content)

In dieser Reihenfolge, alle Antworten liegen bereit:

1. **Privacy policy**: URL oben eintragen.
2. **Data safety**: Tabelle aus `ops/docs/store/DATA_SAFETY.md` §2 übernehmen
   (Overview: collect=Yes, encrypted-in-transit=Yes, deletion=Yes;
   Typen: Messages, Photos, Files and docs, Device or other IDs — alle
   „not shared").
3. **Ads**: No.
4. **Content rating**: Fragebogen, Kategorie Utility; kein öffentlicher UGC
   (privater Chat gegen die eigene Installation) → „Everyone".
5. **Target audience**: 18+, nicht an Kinder gerichtet.
6. **News app**: No · **COVID-app**: No · **Data deletion**: Verweis auf
   Entkoppeln + Uninstall (steht in der Policy), keine Account-URL nötig
   (keine Entwickler-Konten).
7. **Government app**: No.

## 4. Store-Einträge (Grow → Store presence)

1. **Main store listing**: Texte aus `ops/docs/store/LISTING.md` (DE primär,
   EN als Übersetzung anlegen), Screenshots aus `ops/docs/store/screenshots/`
   in der dortigen Reihenfolge, Icon 512×512, Feature-Grafik 1024×500
   (siehe LISTING.md — noch zu bauen).
2. **Store settings**: Kategorie Produktivität, Kontakt-E-Mail.

## 5. Internal Testing einreichen

1. Testing → **Internal testing** → Create new release.
2. AAB aus Schritt 1 hochladen (erste Einreichung ist immer manuell;
   `eas submit` funktioniert erst, wenn der App-Record existiert).
3. Release notes: kurz („Erste interne Testversion").
4. **Testers**: E-Mail-Liste anlegen (Owner + Testgeräte), Opt-in-Link kopieren.
5. Review starten — Internal-Testing-Reviews sind meist in Stunden durch.

## 6. Nach dem ersten Upload (einmalig)

1. Play Console → Setup → **App integrity** → App-Signing-SHA-256 kopieren.
2. Fingerprint in `surfaces/relay/relay.py` `ASSETLINKS` ergänzen (der bestehende
   Eintrag ist der Sideload-Key; der Play-Key kommt DAZU) →
   `bash ops/deploy/push_relay.sh` → `adb shell pm get-app-links app.helmdeck`
   muss `verified` zeigen, sonst öffnen Pair-Links den Browser.
3. `eas submit -p android` für Folge-Uploads: Service-Account-Key anlegen
   (siehe `surfaces/app/PLAY_STORE_RELEASE.md` §8) und in `eas.json` referenzieren.

## 7. Smoke auf dem Internal-Build (vor Promotion)

- [ ] Pairing per QR (Relay-Modus) und direkt (HTTPS) — Achtung: Play-Build
  blockt Cleartext-HTTP, LAN-Empfehlung siehe `surfaces/app/PLAY_STORE_RELEASE.md` §7
- [ ] Karte anlegen mit Foto-Anhang (Kamera + Galerie)
- [ ] Agent-Rückfrage beantworten, Push kommt an und öffnet die Karte
- [ ] Karte abnehmen (Gate-Report sichtbar), OTA-Check zieht ein Update
- [ ] Entkoppeln: App verliert Zugriff sofort

Danach: Promote → Closed testing (12 Tester / 14 Tage bei Personen-Konto)
→ Production mit gestaffeltem Rollout ≤20 %.
