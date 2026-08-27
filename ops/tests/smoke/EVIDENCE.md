# Release-Build-Smoke — Evidence (M3: signiertes, review-festes AAB)

Karte: Pairing über den TLS/Tunnel-Pfad, OTA-Check-on-Resume und Rollback im
**signierten Build** (nicht im Dev-Client) nachweisen.

Datum: 2026-08-06 · Emulator `emulator-5554`, Android 15, 1080x2400

## Warum der Dev-Client dafür nichts beweist

`expo-updates` ist im Dev-Client abgeschaltet (`__DEV__` / `Updates.isEnabled`
false) — OTA und Rollback laufen dort **nie**. Netzwerk-Policy, Minifizierung
und Signatur unterscheiden sich ebenfalls. Alles, was hier geprüft wird, kann
also nur am Release-Artefakt geprüft werden.

## Aufbau (isoliert, nichts Produktives berührt)

```
Emulator (signierte Release-APK, v1.0.2 / Build 38)
   │  HTTPS (echtes Zertifikat)
   ▼
https://gis-bob-aspect-communities.trycloudflare.com   ← cloudflared quick tunnel
   │  http 127.0.0.1:6795
   ▼
surfaces/relay/relay.py  ── /updates/manifest + /updates/assets aus .smoke/updates
   ▲  long-poll (NaCl-sealed frames)
   │
Sandbox-Daemon dieses Worktrees auf **:8145** (eigene users.json/helmdeck.db/
settings.json; der Daemon des Owners auf :8140 bleibt unangetastet)
```

Signatur (`apksigner verify`):
`CN=HelmDeck Release Smoke, O=HelmDeck, C=DE`, SHA-256
`d02a392aa9b8f7e3a9b274be3ff19ee986b7481156059739696a56e7d64e273f`
— also **Release-Signatur, nicht der Android-Debug-Key**. `adb shell run-as`
wird verweigert, was zusätzlich belegt, dass das Paket nicht debuggable ist.

## Ergebnis

| # | Nachweis | Ergebnis |
|---|----------|----------|
| 1 | Pairing über TLS/Tunnel | **bestanden** |
| 2 | OTA-Check-on-Resume | **bestanden** — A/B belegt, plus Fund 1 (Throttle) |
| 3 | Silent Apply beim Hintergrund-Wechsel | **bestanden** |
| 4 | Rollback auf Embedded | **bestanden** |

Zwei Funde, die vor dem Store-Release gehören (beide **nicht** in dieser Karte
gefixt — Nachweis-Auftrag, jeweils eine eigene Karte wert):

- **Fund 1** — ein fehlgeschlagener Resume-Check verbrennt das volle
  10-Minuten-Fenster (`surfaces/app/src/data/ota.ts:42-43`). Kosmetisch, aber es
  verzögert Updates auf Telefonen mit wackligem Netz.
- **Fund 2 (gravierend)** — der Relay prüft `runtimeVersion` nicht, sondern
  spiegelt sie zurück. Damit greift der in DEPLOY.md beschriebene Schutz gegen
  den `Cannot find native module`-Crash-Loop **nie**.

### 1 — Pairing über TLS/Tunnel · bestanden

Deep-Link `helmdeck://pair?c=…` (Payload: Tunnel-URL, Raum, Daemon-Pubkey,
frisches Device-Token aus `/relay/pair`). Der `https`-App-Link ist per
assetlinks an den **Produktions**-Relay-Host gebunden, ein Quick-Tunnel-Host
würde nicht verifizieren — deshalb das Custom-Scheme; identischer Payload.

Beleg: Board wechselt von leer (`shots/10b_after_wait.png`) auf die echten
Sandbox-Karten (`shots/11b_pair_result.png`), More zeigt grün
**„gekoppelt (Relay)"** (`shots/20_more_tab.png`). Damit ist die ganze Kette
belegt: signiertes APK → HTTPS-Tunnel → Relay → sealed frames → Daemon.

### 2 — OTA-Check-on-Resume · bestanden, aber der Throttle ist eine Falle

Sauber isoliert: Update erst **verfügbar gemacht, während die App schon lief**
(vorher 404, `shots/21_footer_embedded.png` = „Basis-Build (eingebettet, kein
OTA)"). Kein Kaltstart — die PID blieb über jeden Zyklus identisch, und
`MainActivity` ist `singleTask`, `am start` liefert also `onResume` statt eines
Neustarts. Ein Kaltstart würde wegen `EXPO_UPDATES_CHECK_ON_LAUNCH=ALWAYS`
ohnehin prüfen und nichts beweisen.

**Fund.** Ein Resume löste zunächst *gar nichts* aus, obwohl das Manifest
HTTP 200 lieferte. Ursache ist nicht ein toter Handler, sondern
`surfaces/app/src/data/ota.ts`:

```js
lastCheck.current = now;          // wird VOR dem Check gesetzt
checkAndFetch().catch(() => {});  // Fehler wird verschluckt, Zeitstempel bleibt
```

Ein **fehlgeschlagener** Check (hier: Manifest 404 → `CheckError`) verbrennt
damit das volle 10-Minuten-Fenster (`MIN_CHECK_MS`). Belegt per A/B am selben
Prozess (PID 8483), bei durchgehend verfügbarem Update:

- **A**, Resume sofort → keinerlei Update-Aktivität (throttled)
- **Gegenprobe** manueller Button „Jetzt auf Update prüfen" im selben Moment →
  `Check → CheckCompleteAvailable → Download`

Der native Pfad und die Verfügbarkeit waren also nachweislich gesund; nur der
Resume-Pfad schwieg. (Der Throttle-Zweig kehrt vor `lastCheck.current = now`
zurück, ein geblockter Resume verlängert das Fenster also nicht.)

- **B**, Resume nach Ablauf des Fensters (~12 min später, gleicher Prozess) →
  `Check → CheckCompleteAvailable → Download → DownloadComplete`, danach zeigt
  der Footer `HelmDeck v1.0.2 · OTA-R3` / `OTA d5324d8d · 8/6/2026, 8:54:51 PM`

Damit ist **Check-on-Resume belegt** (A/B am selben Prozess, ohne Kaltstart):
innerhalb des Fensters schweigt er, danach prüft, lädt und wendet er an.

Bewertung: der 10-Minuten-Throttle als solcher ist Absicht und in Ordnung. Die
Falle ist, dass ein *erfolgloser* Versuch genauso zählt wie ein erfolgreicher —
ein Telefon, das beim Resume kurz kein Netz hat (oder der Relay ist gerade weg),
wartet danach volle 10 Minuten, obwohl nie etwas geprüft wurde. Fix wäre, den
Zeitstempel erst nach erfolgreichem Check zu setzen bzw. ihn im `catch`
zurückzudrehen. **Nicht in dieser Karte gefixt** (Nachweis-Auftrag) — gehört als
eigene Karte gefilt.

### 3 — Silent Apply beim Hintergrund-Wechsel · bestanden

Mit heruntergeladenem Update im Hintergrund: `Updates state change: Restart →
reset`, **PID unverändert (8483)** — also JS-Reload im laufenden Prozess, genau
das „unsichtbare" Anwenden. Danach zeigt der Footer
`HelmDeck v1.0.2 · OTA-RESUME` / `OTA 1513f7e4 · 8/6/2026, 6:15:26 PM`
(`shots/31_ota_resume_applied.png`) — Marker und Manifest-ID stimmen mit dem
ausgelieferten Bundle überein.

Der Marker ist Absicht: stille Updates haben keinen Dialog, also ist ein
sichtbarer String im Footer der einzige ehrliche Beleg, *welches* Bundle läuft.

### 4 — Rollback auf Embedded · bestanden

`rollback.json` mit `commitTime` = jetzt in die Updates-Dir gelegt — derselbe
Marker, den `ops/deploy/rollback_update.sh --embedded` auf dem echten Relay
schreibt, also der Produktionspfad und keine Test-Abkürzung. Der Relay liefert
daraufhin statt eines Manifests eine multipart-Directive:

```
{"type": "rollBackToEmbedded", "parameters": {"commitTime": "2026-08-06T19:38:37.000Z"}}
```

Ablauf auf dem Gerät (Ausgangslage: OTA-R3 / `d5324d8d` lief):

1. Check → `CheckCompleteAvailable → Download → DownloadComplete`; das Panel
   meldet **„Rollback geladen – zurück zum eingebetteten Build"**
   (`shots/40_rollback_fetched.png`).
2. Hintergrund-Wechsel → `Restart → reset`, **PID unverändert (8483)**.
3. Footer danach: `HelmDeck v1.0.2 · Build 38` /
   **„Basis-Build (eingebettet, kein OTA)"** (`shots/41_rollback_applied.png`)
   — der `OTA-R3`-Marker ist weg, die App läuft wieder auf dem Bundle des APK.

Zusatzbefund (Idempotenz, positiv): nach dem Anwenden liefert derselbe, weiter
armierte Marker `CheckCompleteUnavailable` — der Client wendet dieselbe
`commitTime` kein zweites Mal an. Genau so ist es spezifiziert.

## Adversarial-Tests (wie bricht ein unachtsamer/böswilliger Nutzer das?)

| Fall | Erwartung | Ergebnis |
|------|-----------|----------|
| Kein Update publiziert (Manifest 404) beim Resume | still, kein UI-Fehler, kein Crash | **pass** — `CheckError`, App unbeeindruckt |
| Path-Traversal auf `/updates/assets` (`../../../../etc/passwd`, `..%2f`, absolut, `_expo/../../relay.py`) | 404 | **pass** — alle vier 404 (`_norm` greift) |
| Unbekannter / hostiler Channel-Name (inkl. `../updates`, 200 Zeichen) | kein Verzeichnis-Ausbruch | **pass** — fällt auf production zurück (dokumentiert). *Anmerkung:* ein vertippter Beta-Channel bekommt damit still Produktions-Updates — bewusst, aber eine Fußangel. |
| Request ohne Token / mit gefälschtem Token gegen den Daemon | 401 | **pass** — 401 / 401, gültiger Token 200 |
| Sandbox-Token gegen den Owner-Daemon (:8140) | Ablehnung (Worktree-Isolation) | **pass** — 401 |
| Rollback-Directive mit alter `commitTime` | wird als multipart-Directive ausgeliefert, Client entscheidet | **pass** — korrekt geliefert; solange ein Rollback armiert ist, wird *kein* Manifest ausgeliefert (Directive gewinnt) |
| Pairing-Code doppelt verwenden | single use, Code nach Gebrauch verbraucht | **pass** — `pair_pending: None` nach dem Pairing, Gerät gepinnt (`phone_pubs: 2`, pro Installation ein frisches Keypair); Ablauf-/Gerätelimit-Pfade sind in `relay_client.py` abgedeckt |
| **Manifest mit fremder `runtimeVersion` anfordern** | Bundle darf nicht ausgeliefert werden | **FAIL — siehe Fund 2** |

### Fund 2 (gravierend): der Relay prüft `runtimeVersion` nicht, er echot sie

`surfaces/relay/relay.py`, `_build_manifest()`:

```python
return {"id": uid, ..., "runtimeVersion": runtime_version, ...}
```

`runtime_version` kommt direkt aus dem `expo-runtime-version`-Header des
Clients. Es gibt keinen Abgleich mit dem, wofür das Bundle gebaut wurde —
`metadata.json` enthält diese Information gar nicht (`"version": 0` ist die
Format-Version, nicht die App-Version).

Gemessen, dasselbe Bundle für jede Anfrage:

```
asked rtv=1.0.2         -> served rtv 1.0.2 | bundle …69d551dd5c427fae.hbc
asked rtv=1.0.3         -> served rtv 1.0.3 | bundle …69d551dd5c427fae.hbc
asked rtv=9.9.9         -> served rtv 9.9.9 | bundle …69d551dd5c427fae.hbc
asked rtv=not-a-version -> served rtv not-a-version | bundle …69d551dd5c427fae.hbc
```

**Warum das zählt:** DEPLOY.md beschreibt den Versions-Bump in `ship.sh` als
genau die Schutzmaßnahme gegen den `Cannot find native module`-Crash-Loop — ein
altes APK soll neues JS *ablehnen*. Diese Ablehnung passiert clientseitig durch
Vergleich der Manifest-`runtimeVersion` mit der eigenen. Da der Server aber die
Version des Clients zurückspiegelt, **stimmt sie immer überein** — der Schutz
greift nie. Ein APK 1.0.2 bekommt anstandslos ein Bundle, das für einen anderen
Native-Stand gebaut wurde. Das ist genau der Crash-Loop, den die Policy
verhindern soll.

Fix-Vorschlag (klein): `ops/deploy/push_update.sh` leitet die RTV heute schon ab
(`RTV="$(… ["expo"]["version"])"`) — nur um sie zu *verifizieren*. Sie sollte
beim Publish mitgeschrieben werden (z. B. `runtime.txt` neben `metadata.json`),
und `_build_manifest` sollte bei Abweichung `None` liefern (→ 404 „no update
available"). **Nicht in dieser Karte gefixt** (Nachweis-Auftrag); gehört als
eigene Karte gefilt, und zwar vor dem Store-Release.

## Traps, die Zeit gekostet haben (gehören ins DEPLOY.md)

- **`ninja: manifest 'build.ninja' still dirty after 100 tries`** in
  react-native-screens/-worklets: der Worktree-Pfad ist ~40 Zeichen länger als
  das Hauptrepo, CMake warnt wörtlich („object file path cannot be safely
  placed under this directory"). **`subst S:` hilft nicht** — Gradle/CMake
  kanonisieren das Laufwerk auf den langen Pfad zurück. Was hilft: Build aus
  einem echten Kurzpfad (`C:\hd\app`). Danach 0 ninja-Fehler.
- **`robocopy -XD dist build`** schließt Verzeichnisse **nach Namen an jeder
  Stelle** aus und hat damit `dist/` aus hunderten npm-Paketen entfernt →
  `Cannot find module '@jridgewell/gen-mapping/dist/…'`, Autolinking bricht ab.
  Ausschlüsse müssen voll qualifiziert sein.
- **Git Bash frisst `/sdcard/…`** (`uiautomator dump /sdcard/ui.xml` landet unter
  `/Files/Git/sdcard/…`) → `MSYS_NO_PATHCONV=1` davorsetzen.
- **Der Emulator ist geteilte Infrastruktur.** Mitten im Lauf hat eine fremde
  Pipeline (`ops/deploy/build_apk.sh` macht `adb uninstall` + `adb install` als
  Smoke) das Smoke-APK durch ein anderes ersetzt (versionCode 39, Neuinstall
  20:34). Wer hier misst, muss die installierte Version gegenprüfen, sonst misst
  er fremde Artefakte.
- Tab-Trefferflächen sind knapp: das „Mehr"-Label endet bei y=2333, ein Tap auf
  2339 geht ins Leere. Koordinaten per `uiautomator dump` holen, nicht schätzen.

## Grenzen dieses Nachweises

- **Signatur:** `smoke-release.jks`, nicht der Produktions-Keystore (Secret, für
  Karten-Sessions unerreichbar). Der Release-*Codepfad* ist identisch
  (minifiziert, `__DEV__` false, expo-updates aktiv, nicht debuggable); nur die
  Zertifikatsidentität unterscheidet sich. Ein Store-Upload ist damit **nicht**
  abgenommen.
- **Artefakt:** Die Quick-Tunnel-URL ist im APK eingebrannt und ephemer →
  dieses APK ist reines Testmaterial und darf nicht verteilt werden.
  `app/app.json` wird vor dem Commit auf die Produktions-Relay-URL
  zurückgedreht.
- **Plattform:** nur Android/Emulator, x86_64. iOS ist nicht Teil dieser Karte.
- Der Build lief mit `-PreactNativeArchitectures=x86_64` (Emulator-Ziel); das
  ändert nichts an Bundle, Signatur oder Update-Verhalten, ein Store-Artefakt
  braucht aber alle ABIs.
