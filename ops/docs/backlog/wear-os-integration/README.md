# Machbarkeitsstudie: HelmDeck auf Wear OS

**Analyse-Stand:** 2026-08-27, Branch-Basis `6af6c16`. Reine Analyse — kein Code.
Grundlage im Baum: `spine/comms/notify.py`, `spine/http/routes/routes_glance.py`,
`surfaces/app/src/data/push.ts`, `surfaces/app/src/app/_layout.tsx`,
`surfaces/glasses/worker/src/routes.js`, `ops/deploy/build_apk.sh`,
`ops/deploy/cloudflare_tunnel.sh`, `ops/deploy/push_glance.sh`, `DEPLOY.md`.
Plattformseite: Primärquellen `developer.android.com` / Play-Console-Hilfe,
abgerufen 2026-08-27 (§10).

Schwesterdokumente, bewusst im selben Format: `ops/docs/ios-watch-feasibility.md`
(Apple Watch), `ops/docs/android-tv-feasibility.md`, `ops/docs/android-auto-feasibility.md`.
Pflichtlektüre vorab: `ops/docs/glasses-reference.md` — die Uhr ist die **zweite
Wearable-Fläche**, und jede Regel, die dort für die Linse gilt, gilt hier erneut.

**Status (aktualisiert 2026-08-27, selbe Karte):** Phase **W1a+W1b sind jetzt
CODE** — `spine/comms/notify.py` (data-only FCM statt der generischen Hülle),
`surfaces/app/src/data/push.ts` (`BACKGROUND_NOTIFICATION_TASK`, 3 feste
Aktionen + Diktat), `app.json`/`package.json` (`expo-task-manager`,
`version` 1.0.22→1.0.23 für die OTA-Sperre gegen alte APKs). **Ungetestet**:
dieser Karten-Worktree kann weder ein APK bauen (`DEPLOY.md:508-515`, NDK-
Pfadlänge) noch eine echte FCM-Zustellung auslösen (`fcm_service_account.json`
ist ein Secret, hier nicht erreichbar) noch `tsc` laufen lassen (kein
`node_modules` in diesem Worktree). Verifikation braucht den Accept-Pfad /
eine kurze reale Maschinenkarte + ein echtes Gerät — siehe §4.3/§9.1 für die
genauen offenen Punkte. **W2 (native Wear-App) ist weiterhin nur Recherche**;
was der Owner dafür entscheiden muss, steht in §9.

> **Warum die Studie als Backlog-Karte liegt und nicht neben ihren
> Schwesterdokumenten:** `.gitignore:88` (`ops/docs/**`) hält **neue** Dokumente
> unter `ops/docs/` per Owner-Beschluss aus git heraus — bereits getrackte
> bleiben getrackt, deshalb liegen `ios-watch-feasibility.md` & Co. dort. Die
> einzige bewusst wieder eingeschlossene Ausnahme ist `ops/docs/backlog/`, *„die
> Karten-Queue … MUSS neue Karten tracken, sonst verliert der Dispatch-Workflow
> sie stillschweigend"*. Ein `git add -f` hätte diesen Beschluss umgangen; der
> Backlog ist der vorgesehene Ort — und macht die Studie zugleich
> dispatch-fähig. Verschieben, falls sie doch neben die Schwesterdokumente soll.

---

## 0. Kurzfazit

Drei Sätze, dann die Belege.

1. **HelmDeck hat die Uhr-API schon gebaut, ohne es zu merken.** `/glance` ist
   eine token-authentifizierte, bewusst beschnittene Lese+Auswahl-Schnittstelle
   mit gerenderter Sprachausgabe — exakt die Form, die eine Uhr braucht. Eine
   Wear-App wäre ein **zweiter Client eines bestehenden, verifizierten
   Vertrags**, nicht eine neue Daemon-Fläche. Für Lesen, Entscheiden und
   Sprechen ist **keine einzige Zeile Daemon-Code** nötig. → §2
2. **„Watch gratis" wie bei der Apple Watch gibt es hier NICHT** — nicht wegen
   Wear OS, sondern wegen unserer eigenen Push-Konstruktion: gebridged wird
   heute die generische Hülle „Neue Meldung – zum Ansehen tippen". Das ist
   **derselbe Defekt, der schon das Telefon-Lockscreen entwertet**, und ihn zu
   beheben ist Telefon-Arbeit, die der Uhr gratis zufällt. → §4
3. **React Native und Expo unterstützen Wear OS nicht.** Eine echte Uhr-UI ist
   Kotlin + Jetpack Compose for Wear OS, zweite Codebasis, dauerhafte
   Pflege-Steuer. Das ist keine Meinung, das steht in den Quellen. → §3

**Empfehlung in einem Satz:** Phase **W1** (Push reparieren → die Uhr bekommt
echten Inhalt, Aktionen und Diktat, ohne jede Zeile Uhr-Code) bauen, weil sie
sich schon ohne Uhr rechnet; **W2** (native Wear-App gegen `/glance`) erst
danach entscheiden — sie ist billiger als bei der Apple Watch, aber sie eröffnet
eine Fleet-Frage, die der Owner 2026-08-16 bewusst geschlossen hat (§6.3).

---

## 1. Gehört das überhaupt auf die Uhr?

Das ist die Frage, die `glasses-reference.md` §1 vor jede Wearable-Karte stellt,
und sie ist hier zuerst zu beantworten:

> **„Die Brille verdient ihren Platz *nur*, wenn der KONSUMIERENDE Moment
> hands-busy / eyes-up ist."** … *„Eingabe passiert weiter auf dem Telefon —
> das ist in Ordnung, weil Autoren und Konsumieren verschiedene Momente sind."*

Für HelmDeck ist das eine saubere Passung **und** eine saubere Grenze. Was auf
der Uhr Sinn ergibt:

| Gehört auf die Uhr | Gehört nicht auf die Uhr |
|---|---|
| *„Eine Karte wartet auf dich"* — die Unterbrechung | das Board |
| Die anstehende **Entscheidung** + die vom Worker geschriebenen Optionen | das Transcript |
| **Ein Tipp** = Antwort; **ein Diktat** = Steer | Freitext-Autorenschaft, Code, Gate-Reports |
| Gesprochene Zusammenfassung (2 Sätze, `GLASS_BRIEF`) | Kartentitel/Kundennamen in proaktiven Meldungen (§3.1 `voice-interaction-design.md`) |

Google sagt dasselbe von der Plattformseite her: *„Don't port your entire mobile
app to Wear OS"* — such dir die eine Aufgabe, die Sekunden dauert
([Principles](https://developer.android.com/training/wearables/principles)).
Beide Regeln zeigen auf dieselbe Fläche, und es ist exakt die Fläche, die
`ios-watch-feasibility.md` §3.3 für die Apple Watch schon festgelegt hat:
**ein Quittungs- und Ein-Tipp-Gerät.** Diese Studie schlägt keine andere vor.

---

## 2. Der Befund, der alles verbilligt: `/glance` IST die Uhr-API

`spine/http/routes/routes_glance.py` wurde für die Ray-Ban-Linse gebaut. Die
Anforderungsliste einer Uhr ist dieselbe Liste — kleiner Schirm, keine Tastatur,
Ausgabe + Auswahl, ein geteiltes Token statt einer Anmeldung:

| Route | Handler | Was sie der Uhr gibt |
|---|---|---|
| `GET /glance?token=` | `:113-130` | Board-Stand + die anstehende Frage (`question`), sonst `null` |
| `POST /glance/answer` | `:262-313` | die EINE Schreiboperation — Optionsauswahl |
| `POST /glance/talk` | `:133-193` | Text rein → `{reply, question, refused, voice: <mp3-URL>}` |
| `GET /glance/voice/<id>.mp3` | `:44-71` | die fertig gerenderte Sprachausgabe |
| `GET /glance/banner?n=` | `:74-110` | *„3 new cards need you."* — geklemmt auf 1–99 |

Vier Eigenschaften machen das für eine Uhr besser als alles, was man neu bauen
würde:

1. **Kein NaCl-Port.** `/glance` ist Bearer-Token über HTTPS, nicht der
   E2EE-Relay. Der Apple-Watch-Weg hätte XSalsa20-Poly1305 in Swift nachbauen
   müssen (`ios-watch-feasibility.md` §3.2); hier entfällt das ersatzlos.
2. **Kein Passwort auf der Uhr.** Play-Qualitätsregel **WO-P6** verbietet
   Login-Eingabe auf dem Handgelenk. Ein Token, per QR oder vom Telefon
   übergeben, erfüllt das von selbst — genau wie bei der Linse
   (`push_glance.sh`: Token im URL-Fragment, landet nie in Cloudflares Logs).
3. **Die Schreibseite ist schon eingezäunt.** `glance_answer` erzwingt vier
   Grenzen (`:268-280`): eigener Schalter `glance_decide`, **Freitext wird
   abgewiesen**, `request_id` muss zur aktuellen Frage passen, und es sind nur
   Optionen wählbar, **die der Worker selbst geschrieben hat**. Das ist die
   richtige Blast-Radius-Grenze für ein Gerät, das man verlieren kann.
4. **Sprechen ist bereits Serverarbeit.** `spine/media/voice.py` rendert MP3 mit
   Cache; die Uhr muss nur eine URL abspielen. Kein Geräte-TTS, keine zweite
   Stimme, kein zweiter Ort für das Vorlese-Register
   (`voice-interaction-design.md` §1).

### 2.1 Und die Erreichbarkeit ist bereits gelöst — das Dokument ist veraltet

`glasses-reference.md:1177-1185` nennt Erreichbarkeit *„das eine, was zwischen
`surfaces/glasses/` und einer dauerhaften Installation steht"* und stuft sie als
**offene Design-Entscheidung** ein. **Das stimmt nicht mehr.** Im Baum liegt:

- `surfaces/glasses/worker/src/routes.js` — ein Cloudflare Worker, der **genau
  fünf** `/glance`-Pfade zum Daemon proxyt und nichts sonst (`:15`, `:26-38`),
  mit Methoden-Whitelist, Pfad-Regex für die Voice-Clips (`:24`) und
  Body-Caps je Route (`:53-62`). Bewusst keine generische Weiterleitung, *„weil
  ein generic pass-through alles hinter einem Query-String-Token
  veröffentlichen würde"* (`:18`).
- `ops/deploy/cloudflare_tunnel.sh` — publiziert `localhost:8140` über einen
  kostenlosen Tunnel, ausgehend gewählt, kein Port-Forwarding.
- `ops/deploy/push_glance.sh` — deployt den Worker und beweist danach die
  Live-Origin.

Das heißt: **eine öffentliche HTTPS-Origin für `/glance` existiert als Code.**
Was offen ist, ist die *Inbetriebnahme* (`DAEMON_URL`-Secret setzen, deployen) —
und nach eigenem Kenntnisstand ist der Glance-Worker noch nicht deployt. Das ist
ein Skript-Lauf, keine Architekturentscheidung. **Diese Studie beantragt, den
Absatz in `glasses-reference.md` §11.9 als erledigt zu markieren.**

⚠ Belegt ist hier der Code, **nicht** ein laufender Endpunkt: aus einem
Karten-Worktree ohne Secrets lässt sich nicht prüfen, ob der Worker live ist.

---

## 3. React Native / Expo auf Wear OS — die harte Antwort

**Es gibt keine offizielle Wear-OS-Unterstützung in React Native oder Expo.**
Belege, alle direkt an der Quelle geprüft:

- Wear OS steht **nicht** auf RNs Liste der offiziellen *und* nicht auf der der
  Out-of-Tree-Plattformen (dort: macOS, Windows, visionOS, OpenHarmony, tvOS,
  Web, Skia). [reactnative.dev/docs/out-of-tree-platforms]
- `facebook/react-native#25580` („React native doesn't work in android wear") ist
  **geschlossen und gesperrt**, ohne Maintainer-Lösung.
- Die aktivste Community-Bibliothek sagt es im eigenen README: *„React Native
  does not officially support WearOS, some essential components like
  CircularScrollView are not available."* (`react-native-wear-connectivity`)
- **Expo: null.** Keine Wear-Dokumentation, kein `expo-wear`, kein Wear-Formfaktor
  in EAS. Dazu bekannte Brüche: `expo-location` stürzt auf Wear ab (expo#27098).
- Einzige belastbare Fallstudie, die genau unsere Lage beschreibt (RN-Telefon-App
  + Uhr): **Arvo** — *„Wear OS doesn't support React Native — building a real
  companion app means writing native Kotlin + Jetpack Compose, a separate
  codebase."* Preis, den sie beziffern: **die Wear-App hängt dauerhaft ~1 Monat
  hinter der Feature-Entwicklung her.**

Was auf der Uhr technisch gar keinen RN-Pfad hat: `ScalingLazyColumn` /
`TransformingLazyColumn` / `EdgeButton` / Krone-Scroll / Swipe-to-dismiss
(Compose-for-Wear-only), Tiles bzw. ab Wear OS 7 Widgets (ProtoLayout / Jetpack
Glance, Kotlin), Complications (Kotlin-Service) — und **Watch Faces sind seit
Januar 2026 zwingend Watch Face Format: deklaratives XML ohne ausführbaren
Code.** Ein „lebendiger Kartenstand auf dem Zifferblatt" ist damit kategorisch
kein App-Code, sondern eine **Complication**, die eine App speist.

Zusatzfalle für uns: **`android.webkit` (inkl. `CookieManager`) existiert auf
Wear OS nicht.** Jede Annahme „wir zeigen halt eine WebView" — der Reflex, der
bei der Brille funktioniert hat — ist auf der Uhr tot. Die Linse ist eine
Webapp; die Uhr kann das nicht sein.

**Urteil:** Wear-UI = Kotlin + Compose. Es gibt keinen Mittelweg, und die
Suche nach einer produktiven RN-Uhr-App blieb ergebnislos.

---

## 4. „Watch gratis" — was hier wirklich ankommt, und warum das ein Telefon-Bug ist

Der Apple-Watch-Weg (`ios-watch-feasibility.md` §3.3) lautete: Mirroring +
Action-Buttons + Diktat = voller Nutzen, null Watch-Code. **Auf Android ist das
Bridging sogar besser dokumentiert und garantierter** — nur liefert HelmDeck ihm
derzeit nichts Brauchbares.

### 4.1 Was Wear OS zusagt (Primärquelle)

- *„By default, notifications from your phone app are automatically bridged to
  the watch"* — kein Uhr-Code nötig
  ([Blog 2025-08](https://android-developers.googleblog.com/2025/08/building-experiences-for-wear-os.html)).
  Bridging ist eine Eigenschaft der **geposteten Notification**, nicht von FCM —
  eine *lokale* Notification des Telefons bridged also genauso.
- **Actions bridgen mit**, inklusive `RemoteInput` — und `RemoteInput` ist auf
  der Uhr genau das Diktat-UI (Mikro / Voice-to-text / Standardantworten).
- Muss `NotificationCompat` sein, nicht das Framework-`Notification`, sonst
  greifen die Wear-Features stillschweigend nicht.

### 4.2 Was HelmDeck heute tatsächlich sendet — der Befund

`spine/comms/notify.py:100-104` schickt eine **Hybrid-Nachricht**:

```python
msg = {"message": {"token": device,
                   "data": {"cipher": cipher},
                   "notification": {"title": "HelmDeck",
                                    "body": "Neue Meldung – zum Ansehen tippen"},
                   "android": {"priority": "high", ...}}}
```

Die Begründung steht daneben (`:95-99`): *„a data-only message needs an in-app
background handler, **which we don't ship**"*. Folge, Kette sauber durchgezogen:

1. App im **Hintergrund oder tot** → Android rendert den generischen
   `notification`-Block → **genau der bridged auf die Uhr.** Am Handgelenk steht
   „HelmDeck – Neue Meldung – zum Ansehen tippen". Inhaltsleer.
2. Die **informative** Notification entsteht nur in `presentDecrypted`
   (`push.ts:47-55`), aufgerufen aus `addNotificationReceivedListener`
   (`_layout.tsx:132-135`) — und der Listener ist **Vordergrund-only**. Also
   genau dann, wenn die App schon offen vor einem liegt und niemand auf die Uhr
   schaut.
3. **Kein Background-Handler existiert**: `TaskManager`,
   `registerTaskAsync`, `BackgroundFetch`, Headless-JS — repoweit null Treffer;
   `expo-task-manager` ist nicht einmal Dependency.
4. **Keine Categories, keine Action-Buttons, kein `RemoteInput`** — repoweit
   null Treffer.

⚠ **Doku-Drift, hier gefunden UND behoben, in derselben Karte:** der Docstring
von `presentDecrypted` (`push.ts:45`, Stand vor diesem Commit) behauptete *„the
background data-message task (Android) is device-verified separately"*.
Diesen Task gab es zu dem Zeitpunkt nicht — repoweite Suche nach
`TaskManager` / `registerTaskAsync` / `BackgroundFetch` ergab null Treffer, und
`expo-task-manager` fehlte in `package.json`. **Seit diesem Commit existiert er
wirklich** (§4.3), der Docstring wurde entsprechend neu geschrieben — aber
„existiert im Code" ≠ „geräteverifiziert"; siehe §9.1 für das, was noch offen
ist. (Zweite Drift derselben Klasse, unverändert: mehrere Kommentare verweisen
noch auf `daemon/notify.py` — die Datei heißt seit dem Vier-Ordner-Umbau
`spine/comms/notify.py`.)

**Das ist kein Wear-OS-Problem. Das ist ein Telefon-Defekt, den die Uhr nur
sichtbar macht** — auf dem Sperrbildschirm des Telefons steht heute exakt
dieselbe leere Hülle. `ios-watch-feasibility.md:88-95` hat für iOS
ausgerechnet, dass Hintergrund-Entschlüsselung dort eine **Notification Service
Extension** in Swift bräuchte. **Auf Android existiert diese Grenze nicht** —
Android darf Data-Only-Nachrichten im Hintergrund verarbeiten. Der Fix ist hier
also ehrlich billiger als auf iOS, und er zahlt auf drei Flächen gleichzeitig
ein: Telefon-Lockscreen, Uhr, und (später) jede weitere gebridgete Fläche.

### 4.3 Was der Fix konkret ist (= Phase W1)

1. **Hintergrund-Entschlüsselung**: Data-Only senden (oder hybrid lassen und die
   Hülle ersetzen) + einen Background-Handler shippen. Die Schlüssel liegen
   schon passend — `decryptPush` (`push.ts:38-42`) liest `mySec`/`daemonPub`
   **synchron** aus dem Store, braucht also kein aufgewecktes UI.
2. **Reiche lokale Notification** via `NotificationCompat`: echter Titel/Body
   (den `notify.py:208-219` bereits baut, inkl. Frage-Zusammenfassung auf 120
   Zeichen) statt der Hülle.
3. **Aktionen + `RemoteInput`**: ein fester, generischer Satz — „Weiter",
   „Stopp", „Antworten…" (Diktat) — plus Deep-Link in die App für die echte
   Optionsauswahl. Rückweg ist bereits vollständig vorhanden:
   `POST /tracks/<id>/steer {text}` bzw.
   `POST /tracks/<id>/answer {answers, request_id}`
   (`cells/engineer/routes_track_actions.py:71-119`).

✅ **1–3 sind jetzt Code** (dieselbe Karte, 2026-08-27):
`spine/comms/notify.py` (data-only) + `surfaces/app/src/data/push.ts`
(`BACKGROUND_NOTIFICATION_TASK`, Kategorie `helmdeck.card` mit den drei
Aktionen). „Stopp" ruft `POST /tracks/<id>/cancel`, nicht nur einen
Steer-Text — ein präziserer Rückweg, als dieser Absatz ursprünglich annahm.
„Weiter"/Diktat rufen `steer`. **Bewusst NICHT gebaut:** echte Options-Buttons
(`answer` + `request_id`) — siehe die Grenze direkt darunter, unverändert
gültig; diese Karte hat den Umfang der Apple-Watch-Studie übernommen, nicht
erweitert.

⚠ **Grenze, die man kennen muss:** die versiegelte Nutzlast ist heute exakt
`{title, body, track, kind}` (`notify.py:90-93`) — **die Optionen und die
`request_id` sind nicht drin**. Echte Options-Buttons am Handgelenk verlangen
deshalb eine kleine Erweiterung der Nutzlast. Ohne sie bleibt es bei generischen
Aktionen + Diktat — was die Apple-Watch-Studie aus demselben Grund empfohlen hat.

⚠ **Falle:** `setOngoing(true)`-Notifications **bridgen nie**. Ein künftiger
„Agent arbeitet"-Dauerindikator erreicht die Uhr nicht. Ebenso wenig
Full-Screen-Intents; `RemoteViews` werden auf Text+Icon eingedampft.

---

## 5. Sprachsteuerung auf der Uhr

Quelle: [Wear OS Voice input](https://developer.android.com/training/wearables/user-input/voice).

| Fähigkeit | Auf Wear OS | Für HelmDeck |
|---|---|---|
| Diktat-Intent `ACTION_RECOGNIZE_SPEECH` | ✅ dokumentierter Weg; *„Every Wear OS device comes with a microphone"* | **das ist der Ohr-Ersatz.** Ergebnis → `POST /glance/talk` |
| Rohes Mikro (`RECORD_AUDIO`) | ✅ *„works the same way as it would on a phone"* (Sample: `WearSpeakerSample`) | nur nötig, wenn wir eigene VAD wollen — **wollen wir nicht** (§5.1) |
| TTS / Lautsprecher | ✅ vorhanden, aber Google: *„Avoid using built-in speaker for media"*; kurze Ansagen sind ausdrücklich gesegnet | passt exakt: unser Register ist **2 Sätze** |
| Wake-Word / always-on für Dritte | ❌ **existiert nicht.** Dazu: Hintergrund-Apps dürfen off-charger keine Alarme/Jobs starten | Einstieg ist **immer** nutzerinitiiert: Notification-Aktion, Tile-/App-Tap, Complication |
| Assistant / Gemini-Hooks | ❌ *„Voice Actions and Assistant App Actions aren't supported at this time except for … China"*; AppFunctions ist Private Preview | **nicht einplanen für 2026** |

### 5.1 Warum die Uhr-Sprache fast gratis ist, wenn W2 einmal steht

Der Vertrag ist im Repo bereits ausformuliert (`glasses-reference.md:1063`):

> capture → STT → `POST /glance/talk {message}` → `{reply, voice, question}` →
> `voice` abspielen.

Auf der Uhr wird daraus: `ACTION_RECOGNIZE_SPEECH` liefert den Text (System-STT,
**wir brauchen weder `livemic` noch `parakeet` noch sherpa auf dem Gerät**) →
POST → `MediaPlayer` auf die zurückgegebene MP3-URL. `GLASS_BRIEF`
(`routes_glance.py:23-41`) erzwingt dabei serverseitig das Antwortformat und den
`<helmdeck-ask>`-Block, sodass die Uhr Optionen zum Antippen bekommt, ohne einen
zweiten Konversationsmotor.

Und die Brillen-Regel, die hier **nicht** gilt: HFP/A2DP schließen einander aus,
deshalb muss `GlassVoiceService.kt` streng `listen → releaseMic → speak`
sequenzieren (`:40-50`). Die Uhr hat **eigenes** Mikro und **eigenen**
Lautsprecher — dieses ganze Radio-Arbitrierungsproblem (`GlassesRadio.kt`)
entfällt ersatzlos.

⚠ Nicht verifiziert: dass `ACTION_RECOGNIZE_SPEECH` auf **jeder** OEM-Uhr
auflöst. Samsung- und Pixel-Belege sind nutzerseitig, nicht API-seitig. Mit
`resolveActivity()` absichern und `ActivityNotFoundException` behandeln — dieselbe
Klasse Fehler wie das `<queries>`-Element in `withGlassVoice.js:88-93`, ohne das
`isRecognitionAvailable()` für immer `false` meldet („korrekter Code, stilles
totes Mikrofon").

---

## 6. Eigenständig vs. Companion — die Transportfrage

Drei ehrlich bewertete Optionen für eine native Wear-App:

| | Weg | Krypto | Infrastruktur | Hausrecht |
|---|---|---|---|---|
| **T1** | Uhr → **Data Layer** → Telefon → Relay | keine neue | keine | ⚠ **verletzt** die Hub-Regel (§6.1) |
| **T2** | Uhr → **Glance-Worker** (HTTPS) → Tunnel → Daemon | keine neue (Token) | Worker deployen (existiert) | ✅ passt |
| **T3** | Uhr → **Relay** direkt, volles E2EE | **NaCl-Port nach Kotlin** | keine | ✅ passt, teuerste Variante |

### 6.1 Warum T2 und nicht T1

`glasses-reference.md` §1 ist die schärfste Regel dieses Hauses:

> *„Es gibt **keine direkte Telefon↔Brille-Verbindung** — sie treffen sich am
> Worker."* … *„Führe keinen Gerät-zu-Gerät-Pfad ein. Er wurde dort erwogen und
> nie gebaut."*

Die Wear Data Layer API (`MessageClient`/`DataClient`) **ist** genau dieser
Gerät-zu-Gerät-Pfad. Bemerkenswert: Google selbst rät davon ab, sie als
primären Netzwerkweg zu nutzen (*„Don't use the Data Layer API as the primary
way to communicate with a network"*), und sie funktioniert nicht, wenn die Uhr
an einem iPhone hängt. Hausregel und Plattformrat zeigen in dieselbe Richtung.

**T2 ist damit nicht nur die billigste, sondern die einzige, die zur
Architektur passt** — und sie macht die Uhr nebenbei eigenständig: Wear OS macht
eigenes HTTPS und routet transparent über BT-Proxy → WLAN → LTE.

Zwei Auflagen aus der Plattform, die das Design festlegen:
- **Kein Long-Poll auf der Uhr.** Hintergrund-Jobs off-charger sind gesperrt,
  Ambient aktualisiert im Minutentakt, Battery-Saver schaltet Funk ab.
  `boardWait` (22 s Long-Poll) darf **nicht** auf die Uhr portiert werden.
  Richtig ist: `GET /glance` beim Öffnen/Aufwachen + FCM als Weckruf.
- **BT-Proxy kann ~4 KB/s sein.** `/glance` ist klein; die Voice-MP3s sind der
  einzige nennenswerte Posten und sollten kurz bleiben — was `GLASS_BRIEF`
  ohnehin erzwingt.

### 6.2 Standalone-Flag und Play

`<uses-feature android:name="android.hardware.type.watch" />` (**nicht**
`required="false"`) plus `com.google.android.wearable.standalone`. Bei T2 ist die
App echt standalone. Weiteres in §7.

### 6.3 ⚠ Die Entscheidung, die dieses Dokument nicht treffen darf

Am **2026-08-16** hat der Owner die Companion-App gestrichen
(`glasses-reference.md:833-846`):

> *„Where did idea with ticket comes from .. scrap it."* → *„No companion app,
> no fleet, no second surface ⇒ **no tickets**."* `daemon/companion.py`, seine
> Tests und fünf Routen wurden in derselben Karte gelöscht, die sie anlegte.

Eine Wear-App ist **genau ein zweites Gerät**. Und §11.1 hält fest, dass die
Ticket-Frage damals nur deshalb entfiel, weil *„es hier keines gab"* — die
Vorbedingung, unter der sie geschlossen wurde, wäre mit einer Uhr **wieder
erfüllt**. Konkret: `settings.glance_token` ist ein einziges geteiltes Geheimnis
ohne Widerruf und ohne Geräte-Identität (`glasses-reference.md` §2.1). Linse
**und** Uhr auf demselben Token heißt: Uhr verloren ⇒ Token rotieren ⇒ Linse
stirbt mit.

**Das ist eine Owner-Entscheidung, keine technische.** Sie steht in §9.

---

## 7. Bau- und Ausliefer-Weg

### 7.1 Ein `withWearApp.js` — das Muster steht schon sechsmal im Baum

`surfaces/app/android` ist **git-ignoriert** (`surfaces/app/.gitignore:41-43`)
und wird bei jedem Build von `expo prebuild --platform android --clean`
neu erzeugt (`ops/deploy/build_apk.sh:63`). Danach setzen **sechs** Plugin-CLIs
die nativen Fakten wieder ein (`:75-158`): `withLanCleartext`,
`withReleaseSigning`, `withGlassVoice`, `withMetaDat`, `withSherpaOnnx`,
`withUpdateUrl`.

Ein `:wear`-Gradle-Modul ist damit **kein Sonderfall, sondern der siebte
Eintrag derselben Liste**: `settings.gradle` erweitern, Compose-Compiler-Plugin
setzen, Kotlin-Quellen einkopieren. Das Risiko „Build-Plumbing" ist in diesem
Repo also deutlich kleiner als bei einem Team, das dieses Muster erst erfinden
muss. Eine dokumentierte Falle direkt übernehmen: **das Compose-Compiler-Plugin
gehört in die ROOT-`build.gradle`**, nicht ins Modul.

⚠ **Die Studie kann ihre eigene Empfehlung nicht bauen.** `DEPLOY.md:508-515`:
ein APK-Build aus einem Karten-Worktree stirbt reproduzierbar
(`ninja: manifest 'build.ninja' still dirty`), weil die NDK-Objektpfade die
Windows-Grenze reißen — und **`subst` hilft nicht**, Gradle/CMake kanonisieren
zurück. Gebaut werden muss aus einem kurzen echten Pfad wie `C:\hd\app`.
Jede Wear-Karte, die ein APK erzeugen soll, ist damit **keine reine
Worktree-Karte**.

### 7.2 Play Store oder Sideload

| | Sideload (adb over Wi-Fi) | Play, Wear-Track |
|---|---|---|
| Aufwand | minutenschnell, kein Review | **eigener Wear-Track + menschliches Review**, opt-in in der Console |
| Updates | manuell, jedes Mal | automatisch |
| Regeln | keine | gleicher Package-Name **und** gleicher Signing-Key (WO-G7), **eindeutiger `versionCode`** über alle Formfaktoren, ≥1 Wear-Screenshot |
| Qualitätsbar | — | WO-V2/V3/V13/V14/V16 (48dp-Ziele, Swipe-back, **schwarzer Hintergrund**, ≥12sp, passt in 192dp-Kreis) |
| Frist | — | **2026-09-15: 64-bit + 16 KB Page Size Pflicht** |

Für den Eigenbedarf (die Uhr des Owners) ist **Sideload richtig** — wie das
Relay-APK heute. Zwei Vorbehalte: `build_apk.sh:194-195` baut bewusst nur
`arm64-v8a`, was für Wear 4+ (64-bit-only) passt; und Googles
**Developer-Verification** greift ab 2026-09-30 regional und 2027 global auf
zertifizierten Geräten — Sideload auf *eigene* Geräte bleibt laut Google möglich,
aber als Verteilstrategie an Dritte hat es eine Uhr.

⚠ **Wear OS 7 ersetzt Tiles durch Widgets** (Jetpack Glance + RemoteCompose).
Wer heute ein Tile baut, baut auf eine Fläche, die Google gerade ablöst. Für v1:
**kein Tile.** Complication ja (billig, und der einzige Weg auf das Zifferblatt).

---

## 8. Aufwand und Phasenplan

Personentage, ehrlich inkl. Gerätetest. Wear-Emulator gibt es unter Windows
vollständig (Android Studio → Device Manager → Wear OS, dazu der
Pair-Wearable-Assistent) — anders als bei iOS ist Verifikation hier **nicht**
gerätegebunden.

| # | Schritt | Aufwand | Anmerkung |
|---|---|---|---|
| 0 | **Wahrheitstest**: Glance-Worker deployen (`cloudflare_tunnel.sh` + `push_glance.sh`), Wear-AVD mit Telefon koppeln, bestehendes APK installieren, `adb exec-out screencap` — *was bridged heute wirklich?* | **0,5 T** | bestätigt §4.2 am Gerät statt am Code; deployt nebenbei die Linse |
| 1 | ~~**W1a** — Background-Entschlüsselung + reiche lokale Notification~~ **CODE GESCHRIEBEN** 2026-08-27 (`notify.py` data-only, `push.ts` `BACKGROUND_NOTIFICATION_TASK`) | ~~2–3 T~~ **verbleibt: Build+Gerätetest** | nativ ⇒ APK-Rebuild, kein OTA aus diesem Worktree möglich (§7.1); **behebt zugleich den Telefon-Lockscreen** |
| 2 | ~~**W1b** — Categories/Actions + `RemoteInput`-Diktat~~ **CODE GESCHRIEBEN** 2026-08-27 (3 feste Aktionen, „Stopp"→`cancel`) | ~~1,5–2 T~~ **verbleibt: Killed-State-Test** | Rückweg-API existiert vollständig; Diktat-Rückweg zum Telefon **[MED]**, nicht wörtlich dokumentiert (§9.1) |
| 3 | **W1c** *(weiterhin offen, bewusst ausgelassen)* — Optionen + `request_id` in die versiegelte Nutzlast, echte Options-Buttons | **1 T** | kleine Änderung an `notify.py:90-93`; ohne sie bleibt es bei den 3 generischen Aktionen |
| | **Summe W1 — Uhr ohne eine Zeile Uhr-Code** | **Code: 0 T (fertig) · Verifikation: ≈ 1–2 T** | rechnet sich schon ohne Uhr; **Build/Gerätetest kann diese Karte selbst nicht ausführen** (§9.1) |
| 4 | **W2a** — `withWearApp.js` + `:wear`-Modul, leere Compose-App baut und startet | **1,5–2,5 T** | Muster steht 6× im Baum; Build **nicht** aus dem Worktree (§7.1) |
| 5 | **W2b** — Uhr-UI gegen `/glance` + `/glance/answer`: Blocker-Liste, Frage, Optionen antippen | **3–4 T** | **null Daemon-Code**; WO-V13/V16-Konformität einpreisen |
| 6 | **W2c** — Sprache: `ACTION_RECOGNIZE_SPEECH` → `/glance/talk` → MP3 abspielen | **1,5–2 T** | billig, weil der Vertrag steht (§5.1) |
| 7 | **W2d** — Complication („N Karten warten"), FCM-Weckruf auf die Uhr | **1,5–2 T** | **kein Tile** (§7.2) |
| | **Summe W2 — native Wear-App** | **≈ 8–11 T** | plus dauerhafte Pflege-Steuer (Arvo: ~1 Monat Parität-Rückstand) |

**Reihenfolge, falls „jetzt":** 0 → 1 → 2, dann **zwei Wochen Alltag**, dann
entscheiden, ob W2 überhaupt noch fehlt. Genau dieselbe Beweislast-Regel, die
`ios-watch-feasibility.md` §4.2 für W2 aufgestellt hat: *erst wenn Mirroring +
Aktionen im Alltag nachweislich zu wenig sind.*

**Gar nicht bauen:** Vollboard auf der Uhr (falscher Formfaktor); RN/Expo auf
der Uhr (§3); Data-Layer als Primärtransport (§6.1); Long-Poll auf der Uhr
(§6.1); ein Tile vor Wear OS 7 (§7.2); eigenes VAD/on-device-STT auf der Uhr,
wo `ACTION_RECOGNIZE_SPEECH` reicht (§5.1); ein Wake-Word (existiert nicht).

---

## 9. Offene Entscheidungen (Owner)

1. **Zweite Fläche überhaupt?** Der Beschluss vom 2026-08-16 („no second
   surface") ist gegen eine Uhr zu prüfen, nicht stillschweigend zu umgehen.
2. **Token-Modell**, falls ja: Uhr und Linse auf **einem** `glance_token`
   (einfach, aber Verlust der Uhr rotiert die Linse mit) — oder die
   Valet-Tickets aus `glasses-reference.md` §2.1 wiederbeleben, deren
   Vorbedingung mit einem zweiten Gerät wieder erfüllt wäre (§6.3).
3. **W1c**: Optionen in die Push-Nutzlast? Das ist der Unterschied zwischen
   „Diktat + generische Aktionen" und „echte Entscheidung am Handgelenk".

## 9.1 Nicht verifiziert — was ein Bau erst schließt

1. Ob der Glance-Worker **live** ist (aus dem Worktree ohne Secrets nicht
   prüfbar, §2.1).
2. Ob der `RemoteInput`-Rückweg von der Uhr **verbatim** im
   `PendingIntent` der Telefon-App landet. Stark impliziert (Play lehnt
   Wear-Apps wegen fehlendem `RemoteInput` ab), aber nirgends wörtlich
   dokumentiert — **Gerätetest vor Schritt 2.**
3. Ob `ACTION_RECOGNIZE_SPEECH` auf **jeder** OEM-Uhr auflöst (§5).
4. Zuverlässigkeit der Notification-Aktionen aus dem **Killed-State** — dieselbe
   Unbekannte, die `ios-watch-feasibility.md` §3.1 offenlässt.
5. Die genaue Deprecation-Liste von `NotificationCompat.WearableExtender`.

### Zusätzlich, seit W1a/W1b als Code existieren (2026-08-27)

Dieser Karten-Worktree hat weder `node_modules` noch die Secrets, die diese
Punkte selbst schließen könnten — sie sind mit bestem Wissen aus den
versionierten Expo-57-Docs geschrieben, nicht am echten Paket verifiziert:

6. **Die exakte Form von `NotificationTaskPayload`** — `push.ts`s
   `BACKGROUND_NOTIFICATION_TASK` liest `data.data.dataString` (JSON-String
   des FCM-`data`-Objekts) für den "Nachricht angekommen"-Zweig. Das stammt aus
   einer Doku-Zusammenfassung, nicht aus dem installierten `.d.ts`
   (`expo-notifications@~57.0.8`) — **gegen die echten Typen prüfen, sobald
   `node_modules` existiert** (Build-Umgebung / Maschinenkarte). Der Code fällt
   defensiv auf die alte generische Meldung zurück, falls der Zugriffspfad
   nicht passt — kein Crash, aber ggf. stumm die falsche (leere) Meldung.
7. **`expo-task-manager@~57.0.14`** — Versionsnummer aus
   `github.com/expo/expo` Branch `sdk-57`, `packages/expo/bundledNativeModules.json`
   (Primärquelle, nicht geraten) — aber nie gegen `npm ci` in diesem Repo
   getestet.
8. **OTA-Sperre**: `app.json`s `version` wurde 1.0.22→1.0.23 gebumpt, damit
   `runtimeVersion.policy: appVersion` alte APKs (ohne Background-Task) von
   diesem JS-Bundle fernhält (`relay.py`s `_bundle_rtv`-Check). Die LOGIK ist
   dieselbe, die `push_update.sh`/`build_apk.sh` heute schon fahren — aber
   **nicht an einem echten Manifest-Round-Trip verifiziert**, weil dafür ein
   laufender Relay + zwei echte App-Versionen nötig wären.
9. **Rollout-Reihenfolge ist eine Betriebsanweisung, kein Code-Gate**: Punkt 8
   schützt den JS/OTA-Kanal; sie schützt NICHT davor, dass ein Daemon-Neustart
   auf dem neuen `notify.py` VOR einem APK-Rebuild die aktuell installierte
   (alte) App auf data-only Pushes umstellt, für die sie keinen Handler hat
   (§4.3-Kommentar in `notify.py`). Der Owner muss die Reihenfolge einhalten;
   nichts im Code erzwingt sie.

---

## 10. Quellen (Plattform, abgerufen 2026-08-27)

[Wear OS 7](https://android-developers.googleblog.com/2026/05/whats-new-wear-os-7.html) ·
[WO7 changes](https://developer.android.com/training/wearables/versions/7/changes) ·
[WO6 changes](https://developer.android.com/training/wearables/versions/6/changes) ·
[Watch Face Format](https://developer.android.com/training/wearables/wff) ·
[Standalone apps](https://developer.android.com/training/wearables/apps/standalone-apps) ·
[Packaging](https://developer.android.com/training/wearables/packaging) ·
[Wear app quality](https://developer.android.com/develop/adaptive-apps/quality-guidelines/wear-app-quality) ·
[Form-factor tracks](https://support.google.com/googleplay/android-developer/answer/13295490) ·
[Play technical quality](https://support.google.com/googleplay/android-developer/answer/17492799) ·
[Notifications](https://developer.android.com/training/wearables/notifications) ·
[Bridging](https://developer.android.com/training/wearables/notifications/bridger) ·
[Voice input](https://developer.android.com/training/wearables/user-input/voice) ·
[Audio](https://developer.android.com/training/wearables/apps/audio) ·
[Network access](https://developer.android.com/training/wearables/data/network-access) ·
[Data Layer](https://developer.android.com/training/wearables/data/data-layer) ·
[Principles](https://developer.android.com/training/wearables/principles) ·
[Building experiences](https://android-developers.googleblog.com/2025/08/building-experiences-for-wear-os.html) ·
[Emulator](https://developer.android.com/training/wearables/get-started/emulator) ·
[Developer verification](https://developer.android.com/developer-verification) ·
[RN out-of-tree platforms](https://reactnative.dev/docs/out-of-tree-platforms) ·
[react-native#25580](https://github.com/facebook/react-native/issues/25580) ·
[react-native-wear-connectivity](https://github.com/fabOnReact/react-native-wear-connectivity) ·
[expo#27098](https://github.com/expo/expo/issues/27098) ·
[Arvo-Fallstudie](https://arvo.guru/blog/wear-os-strength-training-gap) ·
[WearSpeakerSample](https://github.com/android/wear-os-samples/tree/main/WearSpeakerSample)
