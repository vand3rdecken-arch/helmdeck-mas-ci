# Wear-OS-Paritäts-Audit: Chat, Board/Karten, Sprachwiedergabe, WebSocket-Zustellung

**Analyse-Stand:** 2026-09-05, Branch-Basis `955f7cc`. Reine Analyse, kein
Code-Change. Referenzdokumente: `ops/docs/backlog/wear-os-integration/README.md`
(Machbarkeitsstudie, 1561 Zeilen, W1-W2c dort als CODE markiert) und
`ops/docs/backlog/wear-voice-stream-playback/README.md` (der Sprach-Bug vom
2026-09-02). Geprüft: `spine/http/routes/routes_wear.py` (ganz),
`surfaces/app/plugins/wear/{HenryScreen,BoardScreen,CardScreen,WearStream,
VoicePlayer,ChatRows,BoardModel}.kt`, `spine/http/server.py` (Routing-Draht),
`spine/storage/db.py` (`wait_any`/`bump_chat`), `git log` seit 2026-09-02,
`ops/tests/test_wear_voice_stream.py` + `ops/tests/wear_chat_rows.py` (beide
real ausgeführt, PASS), `run_gate.py` (PASS, 3 Checks).

**Verifikationsgrenze, offen benannt:** aus diesem Karten-Worktree sind weder
Gradle noch `kotlinc` noch `adb` erreichbar (`which gradle/kotlinc/adb` →
alle drei leer) — derselbe Tool-Guard, der schon `C:\hd\app` blockiert. Alles
unten ist **gelesener Code + echte Python-Tests**, kein Kotlin-Compile und
kein Geräte-Test. Wo die Referenzdokumente selbst eine Geräte-Verifikation als
offen führen, wird das hier übernommen, nicht stillschweigend als erledigt
behandelt.

---

## Kurzfazit

1. **Chat und Board/Karten sind seit `4e1f4e1` (2026-09-02) auf einem echten
   Push-Kanal vereinheitlicht** — ein Cursor-Objekt (`WearStream`), von
   `MainActivity` gehalten, überlebt Navigation zwischen den Screens. Vorher
   hatte nur der Chat einen Kanal; das Board lud einmal und sonst nur auf
   Knopfdruck. Das ist jetzt behoben und stimmt mit dem Plan überein.
2. **Sprachwiedergabe ist seit `8aaf30c` (2026-09-02, selber Tag) auf denselben
   Kanal gezogen** — der in der Vorgänger-Karte dokumentierte Bug ("Stimme
   aktivieren" blieb meist stumm, weil nur der direkte HTTP-Antwortpfad
   sprach) ist im Code behoben: ein Pull-Mechanismus (`GET /wear/voice?key=`)
   fängt jetzt auch Antworten ab, die über den Stream statt über die
   Talk-Antwort ankommen. `ops/tests/test_wear_voice_stream.py` (30 Checks)
   läuft real und bestätigt die Kernlogik serverseitig.
3. **Ein echter Paritäts-Bruch INNERHALB der Uhr-App selbst, nicht gegen das
   Telefon:** `CardScreen.kt`s eigener "Henry fragen"-Dialog (§ Board/Karten
   unten) bekam den 8aaf30c-Fix **nicht**. Er spielt Sprache unconditional
   und ignoriert den `voiceOn`-Schalter, den `HenryScreen` einführt — Stimme
   auf dem Hauptbildschirm ausschalten, dann von einer Karte aus Henry fragen,
   spricht trotzdem.
4. **"WebSocket-Zustellung" ist eine ungenaue Bezeichnung für das, was im Baum
   existiert.** Es gibt kein WebSocket irgendwo im Repo. Zustellung läuft
   fleet-weit (Handy, Desktop, Brille, Uhr) über EIN sealed long-polling GET
   (`/stream/wait`), bewusst so gewählt (Owner-Dekret 2026-08-30: "einheitlich
   wie Paseo, kein Polling, verschlüsselter Transport") — funktional
   äquivalent zu Server-Push, aber technisch kein WS-Handshake/-Frame.
5. **Kein einziger der vier Bereiche ist auf einem echten Wear-OS-Gerät
   Ende-zu-Ende verifiziert**, laut den Commit-Notizen selbst (`8aaf30c`: "auf
   der ECHTEN Uhr noch nicht gefahren"). `4e1f4e1` hat immerhin
   `:wear:assembleDebug` real gebaut (BUILD SUCCESSFUL, 34M APK); danach kein
   Gradle-Lauf mehr protokolliert.

---

## 1. Chat

**Referenz:** `wear-os-integration/README.md` §4.9/§4.8/§9.1 Punkt 30 — EIN
Henry-Gespräch, dieselbe `copilot`-Session wie das Telefon, kein separates
Uhr-Gedächtnis.

**Ist-Zustand:**
- Senden: `HenryScreen.ask()` → `RelayClient.talk()` → `POST /wear/talk`
  (`HenryScreen.kt:179-244`), lang laufend mit Dedupe-sicheren Retries.
- Lesen: `HenryScreen.refresh()` → `GET /wear/chat`
  (`routes_wear.wear_chat_get`, `routes_wear.py:330-455`) liest **dieselbe**
  `copilot.history()` wie das Telefon — kein Uhr-eigener Log.
- Mirror-Klassen `card`/`pm`/`act` sind seit 2026-08-29 im Filter
  (`routes_wear.py:383`) — Karten-Fragen, Henrys proaktive Zeilen und
  Aktions-Quittungen laufen alle in DIESEM einen Posteingang zusammen
  ("One-Inbox-Dekret").
- Drei unabhängige Trigger halten den Chat aktuell (`HenryScreen.kt:487-546`):
  Resume, FCM-Push (`Push.inbound`), und der `WearStream.chat`-Cursor.
- Auto-Scroll und Dedup sind **identitätsbasiert**, nicht positionsbasiert
  (`_wear_msg_key` serverseitig, `newestKey`-String clientseitig) — eine
  bekannte Falle (Log wird auf 80 Einträge gekürzt) ist damit umgangen.

**Befund:** Parität mit dem Plan gegeben, Code-seitig vollständig. Einzige
offene Frage ist die generelle Geräte-Verifikation (§ Kurzfazit Punkt 5), kein
Chat-spezifischer Gap.

---

## 2. Board / Karten

**Referenz:** `wear-os-integration/README.md` §4.7/§4.8 — Board ist reiner
Lesezugriff (`glance_payload()` unverändert), Options-Buttons auf einer
WORKER-Frage rufen `/tracks/<id>/answer`, Henry-Vorschläge sind nur
Chat-Fortsetzung, nie eine Worker-Aktion.

**Ist-Zustand:**
- `BoardScreen.kt` lädt über `GET /wear/board`
  (`wear_board_get`, `routes_wear.py:164-200`), getriggert von
  `LaunchedEffect(WearStream.board.value) { reload() }` (`BoardScreen.kt:112`)
  — seit `4e1f4e1` live, vorher nur einmalig + manueller Reload-Button.
- Zusätzliche Buckets ggü. der Linse: `pipeline.working`/`pipeline.backlog`
  (`_wear_pipeline`, `routes_wear.py:121-161`) — bewusst NUR für die Uhr,
  weil `glance_payload` von der Brille geteilt wird und nicht erweitert
  werden soll.
- `CardScreen.kt`: Options-Buttons rufen `POST /tracks/<id>/answer`
  (`submitAnswer`, `CardScreen.kt:79-105`) — die vom Plan vorgesehene
  Ausnahme, korrekt verdrahtet. Henry-Vorschläge (`askHenry`,
  `CardScreen.kt:296-334`) senden nur die nächste Chat-Nachricht, keine
  Worker-Aktion — ebenfalls plankonform.
- **Gap, hier neu gefunden:** `CardScreen`s `askHenry`-Antwort ist NICHT Teil
  des einen Henry-Chats. Sie lebt in lokalem State (`henryReply`,
  `henrySuggestions`), geht bei Verlassen des Screens verloren, hat kein
  `WearStream`-Abonnement und wird nicht in `/wear/chat` gespiegelt (die
  Karten-Frage selbst schon, über den `card`-Mirror — aber Henrys freie
  Antwort auf der Karte nicht). Wer den Bildschirm wechselt und
  zurückkommt, hat die Antwort nicht mehr — anders als im Haupt-Chat, wo die
  Server-Historie die Quelle der Wahrheit ist.

**Befund:** Board selbst ist plankonform und jetzt live. Der Karten-eigene
Henry-Dialog ist eine zweite, schwächere Chat-Implementierung ohne die
Garantien des Haupt-Chats (kein Persistenz, kein Stream, siehe auch §3).

---

## 3. Sprachwiedergabe

**Referenz:** `wear-voice-stream-playback/README.md` — der Owner-Befund vom
2026-09-02: "Stimme aktivieren" blieb meist stumm, weil nur der direkte
Talk-Antwortpfad sprach; Antworten über Stream/Poll (der seit dem
WebSocket-Umbau der NORMALFALL sind) blieben tonlos.

**Ist-Zustand (Fix `8aaf30c`, selber Tag):**
- Serverseitig neu: `GET /wear/voice?key=` (`wear_voice_get`,
  `routes_wear.py:616-653`) rendert den Clip für GENAU EINE Zeile, und nur
  wenn sie noch die jüngste sprechbare ist (`_wear_newest_speakable`,
  `only=("bot","pm")`) — eine ältere/verfallene Anfrage bekommt Stille, nie
  Historie.
- Identität statt Position: `_wear_msg_key` hasht `cls|date|ts|text`
  (`routes_wear.py:229-252`), auf beiden Routen (`/wear/chat`, `/wear/voice`)
  identisch abgeleitet.
- Clientseitig (`HenryScreen.kt`): EIN Besitzer für "was wurde schon gesagt"
  — `spokenKey` (`HenryScreen.kt:168`). `ask()` übernimmt den `voiceKey` der
  Talk-Antwort, `refresh()` übernimmt den jüngsten gesehenen Key und spricht
  ihn nach, wenn er sich bewegt hat (`HenryScreen.kt:441-457`). `null` =
  noch nicht geprimt → erster Refresh übernimmt stumm, spricht also nie die
  Historie nach.
- Verifiziert: `ops/tests/test_wear_voice_stream.py`, real ausgeführt in
  dieser Session, 30/30 Checks PASS (Key nur auf sprechbaren Zeilen, gleicher
  Key auf beiden Routen, veralteter Key rendert nichts, `voice:false` kostet
  keinen Render, `pm`-Zeile wird von einer Talk-Antwort nicht mitverschluckt).

**Gap (bestätigt § Kurzfazit Punkt 3):** `CardScreen.askHenry()`
(`CardScreen.kt:296-334`) sendet **kein** `voice`-Feld im Body — der Server
defaultet dann auf `body.get("voice", True)` (`routes_wear.py:608`) und
rendert **immer**. Der Client spielt den Clip ab, sobald `b64` nicht leer ist
(`CardScreen.kt:327-332`) — ohne jede Prüfung eines Toggles. `HenryScreen`s
`voiceOn`-Zustand existiert nur dort, wird nicht an `CardScreen` weitergereicht
und hat auch kein zweites, card-eigenes Äquivalent. Praktischer Effekt: der
Owner schaltet auf dem Hauptbildschirm "Stimme aus", geht auf eine Karte,
diktiert eine Frage an Henry — die Uhr spricht die Antwort trotzdem. Das ist
kein Rückfall in den ALTEN Bug (Stream-Zustellung ist hier nicht betroffen,
weil `CardScreen` sowieso nur die direkte Talk-Antwort verwendet, nie
Nachzügler), sondern eine Inkonsistenz des Schalters selbst.

**Befund:** Kernmechanismus (Haupt-Chat) ist robust und getestet. Der
Karten-Dialog ist eine ältere, nicht nachgezogene Kopie desselben Musters vor
`8aaf30c` — funktional (spricht immer), aber nicht am selben Schalter wie der
Rest der App.

---

## 4. "WebSocket-Zustellung"

**Referenz:** Karten-Beschreibung nennt "WebSocket-Zustellung" als eigenen
Bereich. Im Baum existiert dafür kein wörtliches WebSocket.

**Ist-Zustand:**
- `WearStream.kt` (`surfaces/app/plugins/wear/WearStream.kt:66-97`): EIN
  Objekt, zwei Cursor (`board`=`v`, `chat`=`c`), EINE hängende
  `GET /stream/wait?v=&c=` mit 40s Read-Timeout, exponentielles Backoff
  3s→30s bei Fehlern. Cursor überleben Pause/Resume (liegen auf dem Objekt,
  nicht in der Korotine) — derselbe Ein-Besitzer-Grundsatz wie
  `drivers.turn_active`.
- Serverseitig: `spine/http/server.py` Route `/stream/wait` →
  `spine/storage/db.py`s `wait_any(v, c, timeout=22)`, blockiert auf einer
  `threading.Condition`, bis `_version` oder `_chat_version` sich ändert oder
  22s vergehen. Antwort ist NUR `{"v": int, "c": int}` — zwei Zahlen, kein
  Nachrichteninhalt, kein Voice-Clip.
- `_chat_version` wird EINZIG von `copilot._append_log` gebumpt
  (`cells/copilot/chat/copilot.py`), direkt nach dem atomaren
  `os.replace()` der Chat-Log-Datei.
- Derselbe Kanal bedient Handy, Desktop, Brille UND Uhr — bewusst EIN
  hängendes GET für die ganze Flotte, dokumentiert in `routes_wear.py:34-40`:
  ein Voice-Clip auf diesem Cursor hätte JEDEM Client bei JEDEM Chat-Ereignis
  Audio geschickt und einen TTS-Render erzwungen, selbst wenn kein Handgelenk
  zuhört — deshalb die Pull-Route `/wear/voice` statt eines Push-Feldes hier.

**Befund:** Die Zustellung ist real, robust und fleet-weit einheitlich — aber
technisch ein **sealed long-polling GET über den bestehenden Relay**, kein
WebSocket-Protokoll (kein Upgrade-Handshake, keine WS-Frames, keine
bidirektionale Persistent-Connection). Das ist eine bewusste
Architekturentscheidung (Owner-Dekret 2026-08-30, "kein Polling" meint kein
FESTES Intervall-Polling, nicht "kein HTTP") und funktional gleichwertig zu
Server-Push für diesen Zweck. Die Karten-Bezeichnung "WebSocket-Zustellung"
sollte als **Funktionsbeschreibung** (Echtzeit-Zustellung ohne festes
Polling-Intervall), nicht als Technologie-Aussage gelesen werden — falls der
Owner eine wörtliche WebSocket-Verbindung erwartet hatte, ist das eine
Erwartungslücke, kein Implementierungsfehler.

---

## Offene Punkte (nicht in dieser Karte behoben)

1. **CardScreen-Voice-Gap** (§3): `askHenry()` sollte entweder den
   `voiceOn`-Zustand von `HenryScreen` erben (State müsste eine Ebene höher,
   z. B. nach `MainActivity`/`DeviceStore`, wandern) oder bewusst als
   Ausnahme dokumentiert werden, falls Immer-Sprechen auf der Karte Absicht
   ist. Aktuell wirkt es wie ein vergessener Nachzug von `8aaf30c`, nicht wie
   eine Entscheidung.
2. **CardScreen-Chat-Persistenz** (§2): Henrys Antwort auf einer Karte
   überlebt keinen Screen-Wechsel und läuft nicht über den Stream. Kleiner
   Bruch mit dem "die Server-Historie ist die Wahrheit"-Prinzip, das der
   Haupt-Chat durchhält.
3. **Geräteverifikation weiterhin offen** für alle vier Bereiche (§ Kurzfazit
   Punkt 5) — dieselbe Grenze, die `wear-os-integration/README.md` schon
   durchgängig benennt. `:wear:assembleDebug` lief zuletzt bei `4e1f4e1`
   erfolgreich; kein Bericht über einen erneuten Build oder Install nach
   `8aaf30c` in der Git-Historie.
4. **W2d (Complication + FCM-Weckruf)** bleibt laut `wear-os-integration`
   §Status die einzige komplett ungebaute Phase — hier nicht neu geprüft,
   nur zur Vollständigkeit übernommen.

## Empfehlung

Punkt 1 (Voice-Toggle-Konsistenz) ist der einzige Fund hier, der wie ein
echter, kleiner Bug aussieht statt wie eine offene Geräteverifikation — klein
genug für eine eigene Karte, falls gewünscht. Die anderen drei Punkte sind
Verifikations-Schulden, keine Code-Defekte.
