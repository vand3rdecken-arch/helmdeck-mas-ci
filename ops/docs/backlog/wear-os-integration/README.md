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

**Status (aktualisiert 2026-08-28, Folgekarte „Phase 2"):** **W1c ist jetzt
ebenfalls CODE** — die versiegelte Nutzlast trägt die Frage
(`notify.ask_payload()`), und die Notification-Buttons SIND die Optionen, die
der Worker selbst geschrieben hat (`push.ts`, dynamische Kategorie je Karte).
Damit ist **W1 komplett**; §9.3 ist unten beantwortet. Wichtiger Unterschied zu
W1a/b: W1c bringt **keine neue native Abhängigkeit** mit, ist also ein reines
**OTA** auf das vorhandene 1.0.24-APK — die `version` wurde deshalb bewusst
NICHT gebumpt (ein Bump würde `runtimeVersion` verschieben und das Update vom
installierten APK gerade fernhalten). Details in §4.4.

**Status (2026-08-28, selbe Folgekarte, zweiter Auftrag „ich will W2"):** Der
Owner hat den 2026-08-16-Beschluss gegen eine zweite Fläche für die Uhr
AUFGEHOBEN (§6.3) und W2 direkt beauftragt. **W2a ist jetzt CODE** —
`withWearApp.js` + das `:wear`-Gradle-Modul + eine leere Compose-Seite, die
laut Plan startet und nichts sonst tut (§4.5). **Ungetestet, anders als bei
W1**: kein Android-SDK/Gradle in diesem Worktree erreichbar, also KEIN
Gradle-Lauf, nicht einmal ein Syntax-Check des Kotlin. Siehe §9.1 Punkte 15–19
für die vollständige offene Liste.

**Status (2026-08-28, dritter Schritt derselben Karte):** Die vermeintlich
blockierende Token-Entscheidung (§9 Punkt 2) war eine FALSCH GESTELLTE FRAGE
— der Owner wies richtig darauf hin, dass HelmDeck schon ein Pro-Gerät-Modell
hat. Am Code verifiziert (§4.6): `relay.phone_pubs[]` + `auth.issue_token`/
`revoke_token` sind bereits das, was die Uhr braucht — kein neues
Auth-Konzept nötig. Die Prüfung deckte die WIRKLICH offene Lücke auf: der
einzige Kopplungsweg heute ist QR-Scan, und die meisten Wear-OS-Uhren haben
keine Kamera. **Neu, verifiziert, in derselben Karte:** ein
Diktier-Code-Kopplungspfad (`spine/comms/relay_client.py`s
`mint_claim_code`/`claim_code`, `POST /relay/pair/code`,
`GET /relay/pair/claim` — Details + Testabdeckung in §4.6). Reiner
Daemon-Code, vollständig aus diesem Worktree heraus prüfbar und geprüft
(`run_gate.py`: PASS). **Noch offen:** der Kotlin-Pairing-Client selbst
(NaCl-Krypto + Diktier-UI) — bewusst NICHT blind geschrieben, siehe §9.1
Punkte 20–23 für die Begründung und die Empfehlung (`lazysodium-android`).

**Status (2026-08-27, Vorgängerkarte):** Phase **W1a+W1b sind jetzt
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
„Weiter"/Diktat rufen `steer`. ~~**Bewusst NICHT gebaut:** echte Options-Buttons
(`answer` + `request_id`)~~ — **in der Folgekarte am 2026-08-28 nachgezogen,
siehe §4.4.** Das Diktat ruft auf einer offenen Frage jetzt `answer` (Freitext
ist laut `ask.py` eine gültige Antwort) statt `steer`, sonst hinge die Frage
neben einer losen Bemerkung weiter offen.

~~⚠ **Grenze, die man kennen muss:** die versiegelte Nutzlast ist heute exakt
`{title, body, track, kind}`~~ — **diese Grenze ist mit W1c gefallen** (§4.4).

### 4.4 W1c — die Optionen des Workers werden die Buttons (2026-08-28)

Die Nutzlast heißt jetzt `{title, body, track, kind, ask?}`. `ask` ist der
Block, den `notify.ask_payload()` aus der anstehenden Frage baut:
`{id, header, options[], more}` — er reist **im versiegelten Kasten**, Google
lernt also weiterhin nichts, und er ist auf **beiden** Seiten optional (eine
ältere App parst die Nutzlast und ignoriert einen unbekannten Key; ein älterer
Daemon schickt kein `ask`, die App fällt auf die 3 generischen Aktionen zurück).

Vier Entscheidungen, die nicht offensichtlich sind:

1. **Buttons nur, wenn EIN Tipp die Frage wirklich schließt.** `ask_payload()`
   liefert `None` bei mehr als einer Frage (`ask.validate_answers` verlangt eine
   Antwort auf **jede**, ein Button könnte sie also gar nicht settlen) und bei
   `multiSelect` (ein Tipp kann „diese beiden" nicht ausdrücken). In beiden
   Fällen bleibt es exakt beim bisherigen Verhalten.
2. **Labels reisen WÖRTLICH, niemals gekürzt.** `validate_answers` vergleicht
   das Label per **Gleichheit**; ein gekürztes Label wäre still kein
   Preset-Pick mehr, sondern `custom`-Freitext — der Worker läse einen
   Button-Druck als die eigenen Worte des Owners. Kürzen fürs Display ist Sache
   der Notification-UI, nicht der Nutzlast. *(Gegenprobe unten mitgetestet.)*
3. **Höchstens 3 Buttons**, weil Android genau so viele anzeigt (*„A
   notification can offer up to three action buttons"*). Bei mehr Optionen
   reisen die ersten **zwei** plus ein Diktat-Slot — Freitext ist laut `ask.py`
   eine gültige Antwort, eine gekürzte Liste ist am Handgelenk also nie eine
   Sackgasse.
4. **Kategorie je KARTE (`helmdeck.q.<track>`), nicht je Frage.** Zwei Karten
   können gleichzeitig auf den Owner warten; ein Schlüssel je Frage hätte bei
   jeder neuen Frage die noch sichtbaren Buttons der *anderen* Karte gelöscht.
   Das Label wird beim Tippen aus den Daten **dieser** Notification gelesen, nie
   aus der Kategorie — die kann längst die Optionen einer neueren Frage tragen.

Zwei Defekte aus W1b fallen dabei mit:

- **Eine fehlgeschlagene Aktion war unsichtbar.** Die Aktionen laufen mit
  `opensAppToForeground:false`; ein 409 („Frage schon beantwortet/ersetzt") oder
  ein totes Relay verschwand ins Leere, und die Karte lief weiter, als hätte der
  Owner nie getippt. Jetzt meldet sich der Fehler als eigene Notification —
  dieselbe Fläche, auf der getippt wurde, und sie bridged wie jede andere.
- **Die beantwortete Notification blieb stehen** und lud zum zweiten Tipp ein,
  den der Daemon zu Recht mit 409 abgelehnt hätte — eine erfolgreiche Antwort
  hätte sich also selbst als Fehlschlag gemeldet. Sie wird nach einer
  akzeptierten Aktion verworfen (`dismissNotificationAsync`).

⚠ **Falle:** `setOngoing(true)`-Notifications **bridgen nie**. Ein künftiger
„Agent arbeitet"-Dauerindikator erreicht die Uhr nicht. Ebenso wenig
Full-Screen-Intents; `RemoteViews` werden auf Text+Icon eingedampft.

### 4.5 W2a — der native Uhr-Modul-Rumpf (2026-08-28, Owner-Beschluss „ich will W2")

Der Owner hat den 2026-08-16-Beschluss („no second surface") am 2026-08-28
ausdrücklich für die Uhr aufgehoben. Damit ist §6.3 beantwortet; der einzige
Teil von W2, der aus einem Karten-Worktree ohne Android-SDK/Gradle überhaupt
entstehen kann, ist der Modul-**Rumpf** — Gradle-Verdrahtung, Manifest, eine
leere Compose-Seite, die laut Plan (§8 Zeile 4) startet und nichts sonst tut.
Neu im Baum:

- `surfaces/app/plugins/withWearApp.js` — siebter Eintrag in dieselbe Liste
  wie `withMetaDat.js` & Co. (§7.1), aber ANDERER Fall: die sechs bestehenden
  Plugins PATCHEN das vorhandene `app`-Modul; dieses ERZEUGT ein komplett
  neues, separat installierbares (`:wear`). Folgerichtig NICHT in
  `app.json`s `plugins`-Array registriert — keines der sechs Vorbilder ist
  das (geprüft), sie laufen ausschließlich über die CLI in `build_apk.sh`.
  Dieselbe Konvention übernommen statt eine ungeprüfte zweite Hälfte
  (`withDangerousMod`, `expo prebuild`) dazuzuerfinden, die aus diesem
  Worktree ohnehin nicht auszuführen wäre.
- `surfaces/app/plugins/wear/{build.gradle,AndroidManifest.xml,MainActivity.kt}`
  — die statischen Quellen, die die CLI in den generierten Baum kopiert.
- `ops/deploy/build_apk.sh` ruft das Plugin jetzt als siebten Schritt auf
  (immer, wenn `android/` neu entsteht — sonst verschwindet `:wear` beim
  nächsten `--clean`-Prebuild wieder, dieselbe Logik wie bei den anderen
  sechs). **Der bestehende Telefon-Build ist bewusst UNVERÄNDERT**: die
  `gradlew assembleRelease`-Zeile wurde auf `:app:assembleRelease` verengt,
  weil ein nackter `assembleRelease`-Task ab jetzt sonst STILLSCHWEIGEND auch
  `:wear` mitbauen würde (kein Release-Keystore dafür, nie gebaut) — exakt
  die „Build geht grün, Artefakt ist falsch"-Klasse, die dieses Repo schon
  mehrfach getroffen hat.
- `ops/deploy/build_wear_apk.sh` — NEUES, eigenständiges Skript für den
  Uhr-Build (`:wear:assembleDebug` + `adb install`). Bewusst NICHT in
  `ship.sh`/den Fast-Track verdrahtet: anders als das Telefon-Modul ist
  `:wear` noch nie durch Gradle gelaufen, darf also nie unbeaufsichtigt vom
  Accept-Hook losgeschickt werden. Owner-Handlauf.

**Vier Entscheidungen, mit Zitat, nicht aus dem Gedächtnis:**

1. **`TransformingLazyColumn` statt `ScalingLazyColumn`** — aktuell
   empfohlene Wear-Compose-Liste, Material 3, Krone-scrollbar
   (developer.android.com/training/wearables/compose/lists, geprüft
   2026-08-28). §3 dieses Dokuments nennt beide als Compose-für-Wear-only;
   dies ist die, die Google heute empfiehlt.
2. **`<uses-feature>` ohne `required`-Attribut**, exakt wie
   developer.android.com/training/wearables/apps/standalone-apps es zeigt —
   der Plattform-Default ist dann `true`, was §6.2 explizit verlangt („NICHT
   `required=\"false\"`").
3. **`compose-compiler-gradle-plugin:$kotlinVersion`** in der ROOT
   `buildscript.dependencies`, nicht im Modul — die dokumentierte Falle
   (§7.1) wörtlich vermieden; die Version reitet auf demselben
   `kotlinVersion`, den das Template schon für den Kotlin-Compiler selbst
   trägt (2.1.20, gemessen in `voice-interaction-design.md:475`), statt eine
   zweite, separat zu pflegende Versionsnummer einzuführen.
4. **`applicationId "app.helmdeck.wear"`**, NICHT dieselbe wie das
   Telefon-Modul (`app.helmdeck`). Play verlangt gleichen Package-Namen +
   gleichen Signing-Key nur für den gebündelten Wear-Track (WO-G7, §7.2) —
   bei Sideload (die für den Eigenbedarf vorgesehene Verteilung, §7.2) gilt
   das nicht, und ein eigener Name hält die Uhr strukturell von den
   Telefon-Build-Artefakten (Signing, versionCode-Fortlauf) getrennt, bis
   das wirklich gebraucht wird.

**Was das NICHT ist:** ein Build-Beweis. Kein Android-SDK, kein Gradle, kein
`expo`-CLI ist aus diesem Karten-Worktree erreichbar (derselbe Tool-Guard, der
schon `C:\hd\app` blockiert). Geprüft wurde, was hier prüfbar war: die
Text-Patch-Funktionen in `withWearApp.js` gegen synthetische Fixtures, die
der REALEN `settings.gradle`/Root-`build.gradle`-Form dieses Baums
nachempfunden sind (Anker, Idempotenz, „landet in `buildscript.dependencies`,
nicht in `allprojects.repositories`" — die Falle aus Punkt 3, als Gegenprobe
mitgetestet); die generierte `AndroidManifest.xml` gegen einen echten
XML-Parser (wohlgeformt, exakt die beiden zitierten Zeilen). Für
`MainActivity.kt`/`build.gradle` gibt es in diesem Worktree **kein**
Kotlin-/Gradle-Werkzeug — nicht einmal einen Syntax-Check wie
`node --experimental-strip-types --check` bei der TS-Hälfte von W1c. Der
einzige Netz, der lief (balancierte Klammern), ist bewusst NICHT als
Verifikation gezählt. Alles Weitere in §9.1, Punkte 15–19.

### 4.6 Die Token-Frage war falsch gestellt — der Owner hatte recht (2026-08-28)

Auf die Rückfrage „Uhr: geteilter `glance_token` oder Valet-Tickets?" kam vom
Owner zurück: *„Isn't each device desktop, android etc. each gets a
token?"* — eine Prämisse, die zuerst am Code geprüft wurde, nicht einfach
übernommen. Sie stimmt, und sie ist der bessere Entwurf:

- `spine/comms/relay_client.py`: `settings.relay.phone_pubs[]` ist bereits
  eine LISTE gepinnter Geräte-Schlüssel, kein einzelnes Feld — *„No cap on
  TOTAL paired devices"* (Kommentar im Code, `:24-29`). Jedes Gerät bringt
  sein eigenes NaCl-Schlüsselpaar mit; ein einmaliger Pairing-Code (`POST
  /relay/pair`, `PAIR_TTL` = 15 min) lässt genau ein neues Gerät zu.
- `spine/auth/auth.py`: `issue_token`/`revoke_token` vergeben und widerrufen
  **pro Gerät** einen eigenen, benannten Bearer-Token. Verlust eines Geräts
  = ein `revoke_token`-Aufruf für GENAU dieses Gerät; alle anderen bleiben
  unberührt — exakt die Eigenschaft, die die Valet-Ticket-Idee aus
  `glasses-reference.md` §2.1 für `glance_token` einforderte, hier für das
  Telefon **bereits existiert**.
- `glance_token` ist folglich kein allgemeines HelmDeck-Geräte-Modell,
  sondern ein Sonderfall NUR für die Linse — gebaut, weil die Ray-Ban-WebView
  keine echte NaCl-Client-Krypto ausführen kann (`glasses-reference.md`,
  wiederholt betont). Ein natives Kotlin-Programm wie `:wear` unterliegt
  dieser Einschränkung nicht.

**Entscheidung:** Die Uhr koppelt als **echtes, eigenständiges Gerät** über
den bestehenden `/relay/pair`-Mechanismus — eigener NaCl-Schlüssel in
`phone_pubs[]`, eigener benannter Token. Kein neues Backend-Auth-Konzept,
kein geteiltes Geheimnis, keine Valet-Tickets als Neubau.

**Die eine echte Lücke, die diese Prüfung aufdeckte** (nicht die, die zuerst
vermutet wurde): der einzige heute existierende Kopplungsweg ist ein
QR-Scan (`surfaces/app/src/app/scan.tsx`, `config.ts`s `applyPairing()`
decodiert `base64({u,r,k,t})` — ein Live-Bearer-Token sitzt direkt im Code).
Das setzt eine Kamera voraus. **Die meisten Wear-OS-Uhren haben keine**, und
eine Tastatur zum Abtippen des Links hat keine. Import daher (statt des
Token-Themas) das, was `glasses-reference.md` §2.2 schon empfahl, aber nie
gebaut wurde — wörtlich zitiert dort: *„the confusable-free alphabet and the
single-use hand-over are the details worth importing"*:

- `spine/comms/relay_client.py`: `mint_claim_code(payload)` /
  `claim_code(code)` — ein sechsstelliges, aussprechbares Code (Alphabet
  ohne I/O/0/1/L, damit ein verhörter/verschriebener Code nie in einen ANDEREN
  gültigen kippt, sondern höchstens ins Leere läuft), 15 Minuten TTL, einmal
  verwendbar, **rein im Speicher** (nie `settings.json` — die Nutzlast trägt
  einen Live-Token, der keinen Neustart überleben muss).
- `POST /relay/pair/code` (owner-only, wie `/relay/pair`) — mintet dieselbe
  Nutzlast, gibt aber den Code zurück statt des rohen Krypto-Blobs. Der
  Owner liest den Code vom Telefon/Desktop ab.
- `GET /relay/pair/claim?code=` — **bewusst unauthentifiziert**
  (`server.py`s `OPEN`-Tupel, dieselbe Klasse wie `/glance`), weil das
  koppelnde Gerät per Definition noch keine Session hat. Tauscht den Code
  GENAU EINMAL gegen dieselbe Nutzlast, die `/relay/pair` sonst direkt
  zurückgäbe.
- Unbekannt/abgelaufen/schon eingelöst antworten **ununterscheidbar** mit
  404 — anders als der QR-Pfad (wo das Gerät bereits einen gepinnten
  Schlüssel bewiesen hat), ist dieser Pfad für jeden erreichbar, der einen
  6-Zeichen-Code errät; ein Fehlertext, der „falsch" von „abgelaufen"
  unterscheidet, wäre ein Orakel.

Die Uhr würde den Code über ihr eigenes Mikrofon diktieren
(`ACTION_RECOGNIZE_SPEECH`, bereits in §5 belegt) — noch nicht gebaut, siehe
§9.1 Punkt 20.

**Verifiziert, nicht nur geschrieben:** `mint_claim_code`/`claim_code` liefen
gegen echten Python-Code — Rundlauf, Einmaligkeit (zweiter Claim liefert
`None`), Ablauf, Groß-/Kleinschreibung (ein diktierter Code muss nicht
exakt treffen), Alphabet-Grenzen, UND die tatsächliche `server.py`-Verdrahtung
(`routes_relay.GET_ROUTES`/`POST_ROUTES` exportieren die neuen Pfade,
`server.H.OPEN` enthält `/relay/pair/claim`, `do_GET` ruft
`routes_relay.GET_ROUTES` wirklich auf — nicht nur „die Datei importiert
sauber"). `run_gate.py`: PASS (3 Checks). Wegwerf-Testdatei, nicht
eingecheckt (Gate ist LEICHT).

### 4.7 Wearables sprechen mit Henry, nie mit dem Worker — Owner-Entscheidung 2026-08-29, für die Uhr, die Linse erfüllt sie schon

Owner-Vorgabe: auf Uhr UND Linse soll ein Tap direkt zu **Henry** führen,
nicht zum Worker-Tab, den `card/[id].tsx` auf dem Telefon standardmäßig
zeigt, wenn eine Karte gerade eine laufende Session hat.

**Die Linse erfüllt das bereits, seit `glance_talk` existiert — keine
Änderung nötig, nur geprüft:** `routes_glance.py:167-170` ruft
`cells.copilot.copilot.chat(..., allow_actions=False, ...)` — denselben
Agenten, den die Board-Chat-Ansicht auch nutzt (**Henry**), mit
`allow_actions=False` fest verdrahtet. Es gibt auf der Linse gar keinen
Umschalter „Worker oder Henry" — `/glance/talk` erreicht den Worker
strukturell nie. `/glance/answer` ist etwas anderes und bleibt bewusst
unverändert: es beantwortet eine PENDING QUESTION, die der Worker selbst
gestellt hat (die einzige Aktion, die zwangsläufig zu SEINER Session
zurückmuss, kein „Default-Tab", sondern eine eigene, engere Handlung).

**Für die Uhr ist das eine Design-Entscheidung, kein Code-Fix** — es gibt
noch keine Board-/Karten-Ansicht dort (§9.1 Punkt 26: „Gekoppelt. Board
folgt." ist alles, was `MainActivity` zeigt). Festgehalten für den Bau von
W2b: die Uhr bekommt **dasselbe Muster wie die Linse**, nicht das Tab-Paar
des Telefons —
- ein „mit Henry sprechen"-Pfad (Text/Diktat → Henry, beratend, keine
  Board-Aktionen), analog zu `/glance/talk`;
- Options-Buttons zum Beantworten einer offenen Frage (analog
  `/glance/answer`), weil das strukturell zum Worker zurückmuss;
- **kein** Worker-Live-Session-Tab. Das deckt sich mit der Hausregel aus
  `glasses-reference.md` §1, die schon für die Linse galt und für ein
  zweites Wearable genauso gilt: „Freitext-Autorenschaft, Code,
  Gate-Reports" gehören nicht auf ein Wearable — nur das Worker-`answer`
  selbst (eine strukturierte Auswahl, keine Autorenschaft) ist die
  Ausnahme, die schon in W1c gebaut ist.

Da die Uhr (anders als die Linse) über die volle, per-Gerät authentifizierte
Relay-Verbindung geht (§4.6), KÖNNTE sie technisch auch `/tracks/<id>/steer`
direkt gegen den Worker aufrufen — die Owner-Entscheidung hier ist, das
bewusst NICHT zu tun, auch wenn es technisch ginge.

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

### 6.3 ⚠ Die Entscheidung, die dieses Dokument nicht treffen durfte — **am 2026-08-28 vom Owner selbst getroffen: „ich will W2"**

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

~~**Das ist eine Owner-Entscheidung, keine technische.** Sie steht in §9.~~ —
**Entschieden am 2026-08-28.** Die Vorbedingung, die 2026-08-16 die Ticket-
Frage schloss, ist damit tatsächlich wieder offen: **Punkt 2 unten
(Token-Modell) ist jetzt eine ECHTE, blockierende Entscheidung für W2b** (die
`/glance`-UI selbst, die einen Netzwerk-Call braucht) — W2a (dieser Commit)
umgeht sie vollständig, weil eine leere Compose-Seite noch keine Anfrage an
den Daemon stellt.

---

## 7. Bau- und Ausliefer-Weg

### 7.1 `withWearApp.js` — das Muster steht jetzt siebenmal im Baum

`surfaces/app/android` ist **git-ignoriert** (`surfaces/app/.gitignore:41-43`)
und wird bei jedem Build von `expo prebuild --platform android --clean`
neu erzeugt (`ops/deploy/build_apk.sh:63`). Danach setzen **sieben** Plugin-CLIs
die nativen Fakten wieder ein (`:75-170`): `withLanCleartext`,
`withReleaseSigning`, `withGlassVoice`, `withMetaDat`, `withSherpaOnnx`,
`withUpdateUrl`, seit 2026-08-28 auch `withWearApp` (§4.5) — als einziges der
sieben kein Patch auf `app`, sondern ein komplett neues Modul (`:wear`).

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
| 3 | ~~**W1c** — Optionen + `request_id` in die versiegelte Nutzlast, echte Options-Buttons~~ **CODE GESCHRIEBEN** 2026-08-28 (`notify.ask_payload()`, dynamische Kategorie je Karte, §4.4) | ~~1 T~~ **verbleibt: Gerätetest** | **kein natives Delta ⇒ reines OTA**, kein APK-Rebuild, kein `version`-Bump |
| | **Summe W1 — Uhr ohne eine Zeile Uhr-Code** | **Code: 0 T (komplett) · Verifikation: ≈ 1–2 T** | rechnet sich schon ohne Uhr; **Build/Gerätetest kann diese Karte selbst nicht ausführen** (§9.1) |
| 4 | ~~**W2a** — `withWearApp.js` + `:wear`-Modul, leere Compose-App baut und startet~~ **CODE GESCHRIEBEN** 2026-08-28 (Modul + Manifest + `MainActivity.kt`, §4.5) | ~~1,5–2,5 T~~ **verbleibt: erster echter Gradle-Lauf** | Muster steht jetzt 7× im Baum; Build **weiterhin nicht** aus dem Worktree (§7.1) |
| 5 | ~~**W2b** — Uhr-UI gegen `/glance` + `/glance/answer`~~ **CODE GESCHRIEBEN** 2026-08-29 — gegen NEUE, Bearer-authentifizierte `/wear/board`+`/wear/talk` (nicht `/glance`, §4.6 verwarf den glance_token für die Uhr), Blocker-Liste + Frage-Buttons + Henry-Diktat (§4.8) | ~~3–4 T~~ **verbleibt: echter Gerätetest** | War NICHT „null Daemon-Code" — `routes_wear.py` ist neu, aber klein und wiederverwendet `glance_payload()`; WO-V13/V16-Konformität weiterhin ungeprüft |
| 6 | **W2c** — Sprache: `ACTION_RECOGNIZE_SPEECH` → `/glance/talk` → MP3 abspielen | **1,5–2 T** | billig, weil der Vertrag steht (§5.1) |
| 7 | **W2d** — Complication („N Karten warten"), FCM-Weckruf auf die Uhr | **1,5–2 T** | **kein Tile** (§7.2) |
| | **Summe W2 — native Wear-App** | **≈ 8–11 T** | plus dauerhafte Pflege-Steuer (Arvo: ~1 Monat Parität-Rückstand) |

~~**Reihenfolge, falls „jetzt":** 0 → 1 → 2, dann **zwei Wochen Alltag**, dann
entscheiden, ob W2 überhaupt noch fehlt.~~ **Überholt durch den
2026-08-28-Beschluss** — der Owner hat W2 direkt beauftragt, ohne den
Alltagstest abzuwarten. W2a (§4.5) ist der Teil davon, der ohne Owner-Gerät
entstehen konnte; W2b braucht jetzt zuerst §9 Punkt 2 (Token-Modell), dann
einen echten Gradle-Lauf (§9.1 Punkt 15) — beides außerhalb dessen, was ein
Karten-Worktree entscheiden oder ausführen kann. Die Beweislast-Regel aus
`ios-watch-feasibility.md` §4.2 (*„erst wenn Mirroring + Aktionen im Alltag
nachweislich zu wenig sind"*) war die Empfehlung DIESES Dokuments, nicht eine
Vorbedingung, die der Owner einhalten muss — seine Entscheidung sticht.

**Gar nicht bauen:** Vollboard auf der Uhr (falscher Formfaktor); RN/Expo auf
der Uhr (§3); Data-Layer als Primärtransport (§6.1); Long-Poll auf der Uhr
(§6.1); ein Tile vor Wear OS 7 (§7.2); eigenes VAD/on-device-STT auf der Uhr,
wo `ACTION_RECOGNIZE_SPEECH` reicht (§5.1); ein Wake-Word (existiert nicht).

---

## 9. Offene Entscheidungen (Owner)

1. ~~**Zweite Fläche überhaupt?**~~ **Entschieden: JA, am 2026-08-28** („ich
   will W2"). Der Beschluss vom 2026-08-16 („no second surface") ist damit für
   die Uhr ausdrücklich aufgehoben, nicht stillschweigend umgangen — siehe §6.3.
2. ~~**Token-Modell**: `glance_token` teilen oder Valet-Tickets?~~ **Falsch
   gestellte Frage — vom Owner selbst korrigiert** (*„Isn't each device
   desktop, android etc. each gets a token?"*), am Code verifiziert, am
   2026-08-28 gebaut. **Keins von beiden.** `glance_token` ist ein
   Spezialfall, gebaut NUR weil die Ray-Ban-Linse eine WebView ohne echte
   NaCl-Client-Krypto ist (`routes_glance.py`: ein einzelnes geteiltes Secret
   im Query-String). Das ist NICHT HelmDecks allgemeines Geräte-Modell.
   Tatsächlich existiert das schon — geprüft an `spine/comms/relay_client.py`
   und `spine/auth/auth.py`, nicht aus dem Gedächtnis behauptet:
   `settings.relay.phone_pubs[]` pinnt beliebig viele eigene Geräte-Schlüssel
   (kein Cap, jedes Gerät sein eigenes NaCl-Schlüsselpaar), und
   `auth.issue_token`/`revoke_token` vergibt/widerruft **pro Gerät** einen
   eigenen, benannten Bearer-Token — Verlust eines Geräts widerruft NUR
   dessen Token, Telefon/Desktop bleiben unberührt. Die Uhr ist ein natives
   Kotlin-Programm, keine WebView — sie unterliegt der Linsen-Einschränkung
   gar nicht und kann als **echtes drittes Gerät** über den bestehenden
   `/relay/pair`-Mechanismus koppeln. Kein neues Backend-Konzept nötig.
   Details, inkl. der EINEN echten Lücke, die das aufdeckte (Kopplung
   braucht heute eine Kamera, die die meisten Wear-OS-Uhren nicht haben), in
   §4.6.
3. ~~**W1c**: Optionen in die Push-Nutzlast?~~ **Gebaut am 2026-08-28** (§4.4) —
   die Folgekarte war ausdrücklich beauftragt, „Notification-Actions zu
   verfeinern", und W1c war der einzige Schritt des Plans, der ohne Hardware,
   Emulator oder Secrets aus einem Karten-Worktree überhaupt baubar ist. Die
   Entscheidung, die *offen bleibt*, ist damit nicht mehr „ob", sondern nur
   noch: **Reicht das?** Genau dafür ist der Zwei-Wochen-Alltagstest aus §8
   gedacht — er ist jetzt vollständig durchführbar, weil W1 komplett ist.

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

### Was W1c dagegen WIRKLICH verifiziert hat (2026-08-28)

Die Daemon-Hälfte ist aus dem Worktree heraus vollständig ausführbar, und sie
wurde ausgeführt — kein „sieht richtig aus": echte `ask.parse()`-Ausgabe durch
`ask_payload()` und dann durch `ask.validate_answers()` zurück, also exakt der
Vertrag, den ein Wrist-Button erfüllen muss. Bestätigt: 2/3/6 Optionen ergeben
2/3/2+Diktat Buttons; `multiSelect` und Mehrfachfragen werden verweigert; jeder
gesendete Label validiert als **Preset-Pick** (`labels`, nicht `custom`); die
`request_id` entspricht der Frage-ID; ein Diktat auf gekürzter Liste ist eine
gültige Freitext-Antwort; die Worst-Case-Nutzlast (6 maximal lange Labels) liegt
bei **509 B** gegen ein Budget von 3000 B (FCM-Grenze 4 KB). Als **Gegenprobe**
mitgeprüft: ein *gekürztes* Label fällt tatsächlich auf `custom` zurück — die
Wörtlichkeit aus §4.4/2 ist damit gemessen, nicht behauptet. Der Test war
bewusst ein Wegwerf-Lauf und wurde nicht eingecheckt (Beschluss „das Gate ist
LEICHT", `ops/docs/…` / `run_gate.py`). `run_gate.py`: PASS (3 Checks).

### Offen, seit W1c als Code existiert (2026-08-28)

10. **Die App-Hälfte ist weiterhin nur syntaktisch geprüft.** `node
    --experimental-strip-types --check push.ts` läuft sauber, das ist aber ein
    Parser, **kein Typechecker** — `npx tsc` braucht `node_modules`, die es in
    diesem Worktree nicht gibt (Zugriff auf einen Baum außerhalb der Karte wird
    vom Tool-Guard blockiert, also auch die `C:\hd\app`-Junction aus dem
    App-Verify-Rezept). Die Action-Liste ist deshalb mit
    `Parameters<typeof setNotificationCategoryAsync>[1][number]` typisiert
    statt mit einem benannten Export: so kann die Annotation nicht an einem
    Typnamen scheitern, den hier niemand nachschlagen kann.
11. **Ob ein Options-Button vom Handgelenk aus wirklich `answer` auslöst** —
    dieselbe Klasse offener Punkt wie Nr. 2 (der `RemoteInput`-Rückweg), nur
    für gebridgete Action-Buttons. Plattformseitig zugesagt, hier nicht am
    Gerät gesehen.
12. **Ob Wear OS mehr als drei Buttons zeigt.** Die Drei-Button-Grenze ist die
    des **Telefons**; die Uhr listet Aktionen scrollbar und könnte mehr
    vertragen. Wir senden bewusst höchstens drei, weil das die einzige Zahl
    ist, die für beide Flächen belegt ist. Falls der Gerätetest zeigt, dass die
    Uhr mehr darstellt, ist `PUSH_MAX_OPTIONS` die eine Stellschraube.
13. **Kategorie-Rückstand.** Eine Karten-Kategorie wird bei der *erfolgreichen*
    Antwort gelöscht (Event-Zeit, ein Owner). Eine Frage, die nie am
    Handgelenk beantwortet wird, lässt ihre Kategorie stehen — begrenzt durch
    die Zahl der Karten, die je gefragt haben, also klein. Bewusst **kein**
    periodischer Sweep: der müsste raten, welche Kategorie tot ist, und das
    wäre genau die heuristische Rekonstruktion, die `CLAUDE.md` („NO MONKEY
    PATCHES") verbietet.
14. **Rollout: W1c ist ein reines OTA** (`bash ops/deploy/push_update.sh`),
    weil keine native Abhängigkeit dazukommt. **Nicht** die `version` bumpen —
    `runtimeVersion.policy` ist `appVersion`, ein Bump würde das Update vom
    installierten 1.0.24-APK gerade fernhalten. Die Daemon-Seite (`notify.py`)
    und die App-Seite gehören trotzdem zusammen ausgerollt: ein neuer Daemon
    mit alter App schickt `ask`, das die alte App ignoriert (harmlos,
    generische Aktionen) — die Reihenfolge ist hier also unkritisch, anders als
    bei W1a/b (Punkt 9).

### Offen, seit W2a als Code existiert (2026-08-28)

15. **Nullter Gradle-Lauf steht noch aus.** Jede Zeile Kotlin/Gradle in
    `surfaces/app/plugins/wear/` ist entweder aus developer.android.com
    zitiert (siehe die Kommentare in `build.gradle`/`MainActivity.kt` für
    die genauen, an diesem Tag geprüften Fundstellen) oder aus vorhandener
    Repo-Evidenz gefolgert (Kotlin ist am Root verdrahtet, weil das
    Telefon-Modul schon produktiv Kotlin-Dateien enthält) — aber KEIN Teil
    davon ist je durch Gradle gelaufen. Geprüft wurde nur, was ohne
    Android-SDK prüfbar war: `withWearApp.js`s Text-Patch-Funktionen gegen
    Fixtures, die der echten `settings.gradle`/Root-`build.gradle`-Form
    dieses Baums nachempfunden sind (Anker, Idempotenz, korrekte
    Ziel-Block-Auswahl — inkl. Gegenprobe, dass die Falle aus §4.5 Punkt 3
    tatsächlich vermieden wird), und die generierte `AndroidManifest.xml`
    gegen einen echten XML-Parser. `ops/deploy/build_wear_apk.sh` ist der
    Weg zum ersten echten Lauf, sobald Android Studio + ein Wear-Emulator
    bereitstehen (§8: unter Windows vollständig verfügbar).
16. **`androidx.activity:activity-compose:1.9.3` ist der einzige unzitierte
    Versions-Pin** in `wear/build.gradle` — keine Doku-Abfrage diese Sitzung
    hat ihn gegen Kotlin 2.1.20 bestätigt. Vor dem ersten Gradle-Lauf gegen
    Android Studios eigene Wear-OS-Compose-Vorlage prüfen.
17. **Kein Launcher-Icon.** Das Manifest deklariert bewusst keins — in
    diesem Worktree existiert kein Bild-Werkzeug, das eins erzeugen könnte.
    Android fällt auf ein System-Icon zurück; das reicht für „startet und
    zeigt Text", nicht für ein Gerät, das der Owner täglich ansieht.
18. **Kein Release-Signing für `:wear`.** `ops/deploy/build_wear_apk.sh` baut
    bewusst nur `assembleDebug` — es gibt noch keinen Keystore-Pfad für das
    Uhr-Modul (anders als `app`, siehe `withReleaseSigning.js`). Für
    Sideload auf das eigene Gerät reicht ein Debug-Build; eine Play-Wear-Track-
    Verteilung bräuchte WO-G7 (gleicher Signing-Key wie das Telefon-Modul,
    §7.2) und ist hier nicht vorgesehen.
19. **`build_apk.sh`s Telefon-Pfad wurde ABSICHTLICH mitgeändert** (`gradlew
    assembleRelease` → `gradlew :app:assembleRelease`), obwohl diese Karte
    nur die Uhr bauen sollte — nicht optional: sobald `:wear` in
    `settings.gradle` steht, hätte der alte, unscoped Task-Name beim
    NÄCHSTEN Telefon-Release-Build stillschweigend versucht, `:wear`
    mitzubauen (kein Release-Keystore dafür — Bruch oder falsches Artefakt,
    beides schlimmer als die Scope-Änderung selbst). Nicht am Gerät
    geprüft, nur an der Gradle-Task-Semantik (ein qualifizierter Task-Name
    baut exakt ein Modul) — aber das ist dieselbe Art Beleg, auf der auch
    die anderen sechs Plugins in dieser Datei beruhen.

### Offen, seit die Claim-Code-Kopplung (§4.6) als Code existiert (2026-08-28)

20. ~~**Der Kotlin-Client für die Kopplung fehlt noch vollständig**~~ **CODE
    GESCHRIEBEN 2026-08-29** — auf Nachfrage des Owners, warum das nicht
    gebaut wird: die ursprüngliche Zurückhaltung verwechselte zwei
    verschiedene Risikoklassen. Eigene Krypto-Primitive hand-rollen wäre
    fahrlässig gewesen; `crypto_box` über `lazysodium-android`
    (`HelmDeckBox.kt`) aufzurufen ist etwas anderes — eine falsche
    Methodensignatur ist dort ein KOMPILIERFEHLER, kein stiller Bug.
    **Was das nicht abdeckt:** ob Nonce/Schlüssel-Reihenfolge (my_sk,
    peer_pk — nie vertauscht) tatsächlich stimmt, prüft der Compiler nicht;
    das braucht einen echten Rundlauf gegen den Daemon. Gebaut + geprüft in
    dieser Karte, ohne jedes Kotlin-Werkzeug hier verfügbar:
    - `HelmDeckBox.kt` — `crypto_box`/curve25519-xsalsa20-poly1305 über
      `lazysodium-android:5.2.0`, Frame-Format `nonce(24) || ciphertext`
      base64-kodiert, **gegengeprüft gegen `e2ee.py`s eigenes Docstring UND
      `e2ee.ts`** (beide diese Session gelesen, nicht aus dem Gedächtnis).
    - `DeviceStore.kt` — `EncryptedSharedPreferences` für relayUrl/room/
      daemonPub/eigenes Schlüsselpaar/Device-Token (das Kotlin-Äquivalent zu
      `expo-secure-store` auf dem Telefon).
    - `RelayClient.kt` — `claim()` (unverschlüsselter Aufruf gegen
      `/relay/pair/claim`) + `authedCall()`/`completePairing()`, die exakt
      dieselbe Umschlag-Form wie `relayReq()` in `client.ts` bauen (diese
      Session gelesen, nicht angenommen) und `GET /me` als
      Pairing-Abschluss-Probe nutzen — dieselbe Route, die
      `pairing_gate.tsx` selbst nach `applyPairing()` aufruft.
    - `PairingScreen.kt` — zwei Felder (Adresse, Code), je mit
      Diktier-Button (`ACTION_RECOGNIZE_SPEECH`, `<queries>`-Falle aus
      `withGlassVoice.js` wortwörtlich übernommen statt neu hergeleitet).
    - `MainActivity.kt` — zeigt `PairingScreen` bis `DeviceStore.load()`
      etwas liefert, danach den alten W2a-Platzhaltertext.

    **Neu entdeckt beim Bauen, nicht vorher gesehen:** `/relay/pair/claim`
    ist NICHT über den bestehenden Glance-Worker erreichbar — dessen eigener
    Test (`ops/tests/test_glance_worker.py`) erzwingt explizit
    `("/relay/pair", "POST", None)`, und der Worker STRIPT Cookie/
    Authorization vor dem Weiterreichen, was `/relay/pair/code` (Owner-Session)
    ohnehin unmöglich machen würde. Den Worker zu erweitern hätte eine
    bewusst gezogene Grenze verletzt. Empfehlung stattdessen: den
    ohnehin schon vorhandenen `ops/deploy/cloudflare_tunnel.sh` (voller
    Daemon-Zugriff) nur für die paar Minuten der Kopplung laufen lassen —
    kein neuer Worker-Code nötig. `PairingScreen.kt` fragt die Basis-URL
    deshalb bewusst ab, statt sie fest zu verdrahten.

    **Verifiziert, nicht nur geschrieben:** Paket-Pfad jeder `.kt`-Datei
    gegen `withWearApp.js`s Installer-Liste geprüft (ein Mismatch wäre ein
    Compile-Fehler); das Krypto-Schema in `HelmDeckBox.kt`s Kommentar gegen
    `e2ee.py`s Docstring verglichen (Curve25519, `crypto_box`, 24-Byte-Nonce,
    UND dass `crypto_box_seal` — die falsche, anonyme Variante — explizit
    ausgeschlossen wird). Kein Kotlin-Compiler verfügbar — das bleibt die
    reale Grenze, siehe §9.1 Punkt 15.
21. ~~**Die diktierte Code-Eingabe auf der Uhr ist nicht gebaut.**~~ **CODE
    GESCHRIEBEN** — `PairingScreen.kt`, siehe Punkt 20.
22. **Kein Rate-Limit auf `/relay/pair/claim`.** Der Sicherheitsanker ist
    bewusst derselbe wie beim Vorbild (glass-crud-harness' Device-Code-Pattern,
    §2.2 der Referenz, dort zitiert und hier übernommen): 6 Zeichen aus einem
    32-Symbol-Alphabet (≈10^9 Kombinationen), 15 Minuten TTL, einmal
    verwendbar. Dieser leichte Daemon hat repoweit KEIN Rate-Limiting — sollte
    das je gebraucht werden, ist es kein Sonderfall dieser Route, sondern eine
    Infrastrukturfrage.
23. **`/relay/pair/code` hat keinen UI-Aufruf.** Ein Endpunkt ohne Bildschirm,
    der ihn zeigt — die Telefon/Desktop-Seite, die den Code für den Owner
    anzeigt (Pendant zu `scan.tsx`/`qrgen.web.ts`), ist noch nicht gebaut.
24. **`lazysodium-android`s exakte Methodensignatur ist unverifiziert.** Nur
    die Gradle-Koordinate (`5.2.0`) und das allgemeine Box-API-Schema sind
    belegt — die Wiki-Codebeispiele lieferten diese Session keinen
    verwertbaren Quelltext. `HelmDeckBox.kt`s eigener Kommentar nennt das
    explizit als „erstes zu prüfen, falls die Datei nicht kompiliert".
25. **Kein Rundlauf-Test.** `HelmDeckBox.kt`s `sealB64`/`openB64` wurden nie
    gegen ein echtes NaCl-Testvektor oder gegen `e2ee.py`/`e2ee.ts` selbst
    laufen gelassen — das braucht entweder einen Kotlin-Compiler oder ein
    echtes Gerät, beides hier nicht vorhanden.
26. ~~**Kein Board, keine `/glance`-Ansicht.**~~ **CODE GESCHRIEBEN
    2026-08-29** (§4.8) — `MainActivity` zeigt nach der Kopplung jetzt das
    echte Board, kein Platzhalter mehr.
27. **`FieldRow` hat kein echtes Text-Eingabefeld**, nur Diktat + Anzeige der
    zuletzt diktierten Zeichenkette — Wear Compose Material3s
    Text-Eingabe-Komponenten wurden diese Session nicht bestätigt (§9.1
    Punkt 15 gilt hier verschärft). Ein getippter Fallback fehlt bewusst
    dokumentiert, nicht still weggelassen.
28. **Kein Navigation-Zurück über die System-Geste/Krone** — `CardScreen`s
    „Zurück"-Button ist ein normaler Button in der Liste, kein systemeigenes
    Swipe-to-dismiss (Play-Qualitätsregel WO-V2, §7.2). Funktioniert, ist aber
    nicht die plattformübliche Geste.
29. **`items(count) { }` bewusst vermieden, nicht bestätigt.** `BoardScreen`/
    `CardScreen` bauen ihre Listen aus einzelnen `item { }`-Aufrufen in
    normalen Kotlin-Schleifen statt der `items(count) { }`-Sammelform — Letztere
    wurde diese Session nie gegen `TransformingLazyColumnScope` geprüft, Ersteres
    schon (§4.5). Funktional identisch, nur mehr Zeilen.
30. **Henrys vorgeschlagene Optionen (`henrySuggestions`) senden beim Tippen
    das Label als NÄCHSTE Nachricht an Henry** — bewusst NICHT
    `/tracks/answer`, weil Henrys eigener `<helmdeck-ask>`-Block keine
    `request_id` einer echten Worker-Frage trägt, nur seine eigene beratende
    Empfehlung ist. Dieselbe Unterscheidung, die §4.7 zwischen
    „Options-Buttons auf der Worker-Frage" und „Henry-Chips" trifft.
31. **`GET /wear/board` und `POST /wear/talk` sind neu, Bearer-authentifiziert,
    nie am echten Relay-Kanal geprüft** — nur an echtem Python
    (`routes_wear.py`s Komposition mit `glance_payload()`/`ask.parse()`,
    Rollen-Check, Dispatch-Verdrahtung), nicht Ende-zu-Ende über einen
    gekoppelten Uhr-Client. Das braucht ein reales Gerät.

### 4.8 W2b — das echte Board auf der Uhr (2026-08-29, „start building")

Auf Owner-Anfrage „Do you need any other info. Else start building" gebaut,
nachdem §4.7 die Henry-nicht-Worker-Entscheidung geklärt hatte:

- `spine/http/routes/routes_wear.py` — `GET /wear/board` (ruft
  `glance_payload()` UNVERÄNDERT auf, nur Bearer- statt glance_token-gated)
  und `POST /wear/talk` (spiegelt `glance_talk` fast wörtlich:
  `allow_actions=False`, dieselbe `ask.parse()`-Extraktion, damit die Uhr nie
  selbst einen `<helmdeck-ask>`-Block parsen muss — nur ein eigener
  `WEAR_BRIEF` statt `GLASS_BRIEF`, weil dessen Text linsenspezifische
  Tatsachen behauptet, die für die Uhr schlicht falsch wären).
- `BoardModel.kt` — Kotlin-Spiegel von `_glance_question()`s Form, EIN Parser
  für beide Aufrufer (`/wear/board` pro Karte, `/wear/talk`s eigene
  Henry-Vorschläge).
- `BoardScreen.kt` — Liste der `needs_you`-Karten, Tap öffnet `CardScreen`.
- `CardScreen.kt` — genau die Grenze aus §4.7 im Code: Options-Buttons auf
  der WORKER-Frage rufen `/tracks/<id>/answer` (die eine erlaubte Ausnahme —
  strukturierte Auswahl, keine Autorenschaft); Henrys eigene Vorschläge
  senden nur die nächste Chat-Nachricht. Diktier-Button für freie Fragen an
  Henry, exakt dasselbe `ACTION_RECOGNIZE_SPEECH`-Muster wie `PairingScreen`.
- `MainActivity.kt` — lokale `WearScreen`-Zustandsmaschine (Board/Card),
  bewusst ohne `androidx.navigation` — drei Bildschirme rechtfertigen keine
  weitere unverifizierte Abhängigkeit obendrauf.

**Zwei echte Bugs beim Schreiben gefunden und behoben, nicht erst beim
(nicht vorhandenen) Compiler:** `mutableStateMapOf()` liefert die
beobachtbare Map direkt (`SnapshotStateMap`), keinen `MutableState<T>` — ein
`var picks by remember { mutableStateMapOf(...) }` hätte nicht kompiliert,
korrigiert zu `val picks = remember { ... }`. Und `JSONObject(Map)` wurde
durch eine Schleife aus `.put()`-Aufrufen ersetzt, weil Androids
mitgeliefertes `org.json` eine abgespeckte Teilmenge der Referenz-
Implementierung ist und dieser Konstruktor diese Session nicht bestätigt
wurde — `.put()` ist dagegen im ganzen Modul bereits erwiesen funktionierend.

**Verifiziert, ohne jedes Kotlin-Werkzeug:** `routes_wear.py` lief gegen
echten Python-Code — `wear_board_get` mit einer Fixture, die
`sessions.owner_blockers`/`manual_backlog`/`events.metrics` ersetzt (die
Optionen der Worker-Frage kommen UNVERÄNDERT durch, `glance_payload()` wird
wiederverwendet, nicht neu erfunden), `client`-Rolle wird abgelehnt;
`wear_talk_post` mit einem gefälschten `copilot.chat`, der PRÜFT, dass
`allow_actions=False` und der Brief „WATCH" erwähnt, UND dass der
`<helmdeck-ask>`-Block aus der Antwort verschwindet, bevor sie den
Client erreicht. Zusätzlich: jede `.kt`-Datei-`package`-Zeile gegen
`withWearApp.js`s Installer-Pfad geprüft, UND Cross-File-Aufrufe
(`CardScreen` → `BoardModel.parseQuestionBlock`, `→ RelayClient.authedCall`,
die exakten `/wear/talk`- und `/tracks/<id>/answer`-Pfade) als reine
String-Übereinstimmung — kein Kotlin-Compiler, aber mehr als „importiert
sauber". `run_gate.py`: PASS (3 Checks). Kein echter Rundlauf über den
Relay-Kanal — das bleibt die reale Grenze (§9.1 Punkt 31).

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
