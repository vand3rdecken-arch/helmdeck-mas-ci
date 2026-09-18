package app.helmdeck.wear

import android.app.Activity.RESULT_OK
import android.content.Context
import android.content.Intent
import android.speech.RecognizerIntent
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.wear.compose.foundation.AmbientMode
import androidx.wear.compose.foundation.LocalAmbientModeManager
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.Button
import androidx.wear.compose.material3.ButtonDefaults
import androidx.wear.compose.material3.CardDefaults
import androidx.wear.compose.material3.ChildButton
// Wear Compose Material3's own small pill - the right size for a transient
// overlay on a 192dp screen, where a full-height Button would be a hole in the
// conversation. Present in the RESOLVED artifact (compose-material3 1.6.2:
// ButtonKt carries CompactButton, ButtonDefaults carries
// filledTonalButtonColors - both read out of the AAR in the Gradle cache, not
// assumed from docs), which is the same check TitleCard above went through.
import androidx.wear.compose.material3.CompactButton
import androidx.wear.compose.material3.OutlinedButton
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.Text
import androidx.wear.compose.material3.TitleCard
import app.helmdeck.wear.data.DeviceStore
import app.helmdeck.wear.data.RelayClient
import app.helmdeck.wear.data.VoicePlayer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import org.json.JSONObject

// `Line`, `Row`, `buildRows` and `newestMessageIndex` live in ChatRows.kt -
// same package, no Compose, no Android. Kept out of this file ON PURPOSE: the
// scroll bug this screen had was an INDEX bug, and an index can only be checked
// against a layout that exists as data. ops/tests/wear_chat_rows.kt compiles
// that file and asserts the arithmetic.

/** "HH:mm", 24h, matching the daemon's time.strftime("%H:%M") exactly - a
 *  locale-defaulted pattern would render some watches as 12h and the two halves
 *  of one conversation would disagree about what 13:05 is called. */
private fun nowHm(): String =
    java.text.SimpleDateFormat("HH:mm", java.util.Locale.GERMANY).format(java.util.Date())

/** "yyyy-MM-dd", matching copilot._append_log's time.strftime("%Y-%m-%d") - the
 *  key the separator groups on. Compared as a STRING, never parsed for that
 *  purpose: two stamps in the same format are equal exactly when the days are. */
private fun nowDate(): String =
    java.text.SimpleDateFormat("yyyy-MM-dd", java.util.Locale.GERMANY).format(java.util.Date())

/** The separator's caption: "Heute", "Gestern", else "dd.MM.yy" - what every
 *  chat app does, and what the owner's own SMS app showed ("06.10.24").
 *  An unparseable stamp is printed verbatim rather than swallowed: seeing the
 *  raw value is how a format drift gets noticed instead of silently grouping
 *  every message under one wrong day. */
private fun dayLabel(date: String): String {
    val fmt = java.text.SimpleDateFormat("yyyy-MM-dd", java.util.Locale.GERMANY)
    val cal = java.util.Calendar.getInstance()
    if (date == fmt.format(cal.time)) return "Heute"
    cal.add(java.util.Calendar.DAY_OF_YEAR, -1)
    if (date == fmt.format(cal.time)) return "Gestern"
    return runCatching {
        val d = fmt.parse(date) ?: return@runCatching date
        java.text.SimpleDateFormat("dd.MM.yy", java.util.Locale.GERMANY).format(d)
    }.getOrDefault(date)
}

/** Who is speaking, as a chat shows it.
 *
 *  A mirrored card event carries its own label ("Frage · Kartenname") and uses
 *  it INSTEAD of a name: the message is a card waiting on the owner, not Henry
 *  speaking, and calling it "Henry" would be a lie he acts on - he would read a
 *  pending decision as advice. */
private fun senderOf(line: Line): String =
    if (line.label.isNotBlank()) line.label else if (line.mine) "Du" else "Henry"

/** The mirror's three kinds, as the wrist names them. Mirrors
 *  cells/copilot/card_mirror.py's KIND_* constants; an unknown kind falls back
 *  to "Karte" rather than rendering a raw identifier at the owner. */
private val KIND_LABEL = mapOf(
    "question" to "Frage", "result" to "Ergebnis", "blocker" to "Blocker")

/**
 * Henry as a TEXT CHAT, and the first thing the app shows.
 *
 * Owner, 2026-08-29: "Stelle sicher man sieht Henry chat also text chat when
 * app offen ist zu erst und dann gibt es eine Taste um voice zu aktivieren."
 * Two things follow from that, and both reverse an earlier assumption of mine:
 *
 *   1. This screen is the LANDING screen (MainActivity), not something reached
 *      by tapping through the board. The board is one tap away instead.
 *   2. Voice is OFF by default and switched on with a button. The daemon still
 *      renders the clip on every reply (routes_wear.py renders it
 *      unconditionally); this side simply does not play it until asked.
 *
 * The transcript is deliberately kept IN MEMORY only. A persisted chat history
 * would be a second, unencrypted copy of whatever Henry said about the owner's
 * cards sitting on a device that leaves the house on his wrist - and nothing
 * about this screen needs yesterday's conversation. It resets when the app
 * does, which is also the honest signal that Henry has no memory of it either.
 *
 * VOICE IS SERVER-RENDERED, never device TTS - the standing owner decision in
 * ops/docs/glasses-reference.md §4, reaffirmed by
 * ops/docs/voice-interaction-design.md, which allows device TTS only as an
 * unapproved offline fallback (§8.4). The button below plays what the server
 * already sent; it never synthesises anything locally.
 */
@Composable
fun HenryScreen(context: Context, onOpenBoard: () -> Unit) {
    // Seeded from the encrypted cache, so re-opening the app resumes the
    // conversation instead of starting at a blank screen every time.
    val lines = remember {
        mutableStateListOf<Line>().apply {
            // `label` is restored so a cached card event keeps its "Frage ·
            // Kartenname" header; `card`/`options` deliberately are not, so no
            // button is offered against a question whose current state has not
            // been re-read from the server (see DeviceStore.ChatLine).
            addAll(DeviceStore.loadChat(context).map {
                Line(it.mine, it.text, it.ts, it.date, it.label) })
        }
    }
    // Every append goes through here so no path can add a line and forget to
    // persist it - the bug that would look like "the cache randomly loses the
    // last answer".
    fun record(line: Line) {
        lines.add(line)
        DeviceStore.saveChat(
            context, lines.map { DeviceStore.ChatLine(it.mine, it.text, it.ts, it.date, it.label) })
    }
    var busy by remember { mutableStateOf(false) }
    var loadingHistory by remember { mutableStateOf(false) }
    // Same NN Group thresholds as the phone's showCatchup/long (chat.tsx,
    // data/stream.ts): `loadingVisible` delays the Loading row by ~900ms so a
    // refresh that resolves inside a second never flashes it, and `loadingLong`
    // flips once refresh() has been retrying for >=10s so the row can name the
    // attempt instead of sitting unchanged - a plain "loading" that never moves
    // reads as stuck past that point, not as "still working".
    var loadingVisible by remember { mutableStateOf(false) }
    var loadingAttempt by remember { mutableStateOf(0) }
    var loadingLong by remember { mutableStateOf(false) }
    LaunchedEffect(loadingHistory) {
        if (loadingHistory) { delay(900); loadingVisible = true } else loadingVisible = false
    }
    var voiceOn by remember { mutableStateOf(DeviceStore.loadVoiceOn(context)) }
    // WHAT HAS ALREADY BEEN SAID OUT LOUD - one variable, and the only thing
    // that decides whether a clip is played. It holds the server's key for the
    // newest speakable line this screen has accounted for (routes_wear's
    // _wear_msg_key); both playback paths write it, so neither can speak what
    // the other already spoke:
    //   - ask() claims the key POST /wear/talk hands back with its inline clip,
    //   - refresh() claims the newest key it sees, and speaks it when it moved.
    //
    // null means NOT PRIMED YET, and that distinction is the "no reciting the
    // history" guard: the first refresh after the app opens adopts whatever is
    // newest WITHOUT speaking it. Never persisted, for the same reason - a key
    // restored from disk would make yesterday's answer look unplayed.
    var spokenKey by remember { mutableStateOf<String?>(null) }
    var suggestions by remember { mutableStateOf<QuestionBlock?>(null) }
    // Cards answered from THIS screen since it opened. The server transcript is
    // the truth, but it is a poll behind: without this the buttons would stay
    // on screen after a tap until the next /wear/chat load, and a second tap is
    // a certain 409. Derived state, never persisted - a restart re-reads the
    // real answer from the transcript rather than trusting a remembered flag.
    var answered by remember { mutableStateOf(setOf<String>()) }
    // QUEUE-WHILE-BUSY - the same parity the phone's Composer already has
    // (ui/card_composer.tsx: "send stays enabled while busy — the message is
    // queued instead of dropped"). Owner bug report 2026-09-18: the watch's
    // "Sprechen" button was DISABLED while `busy`, so dictating a second
    // message while Henry was still answering did nothing at all - no error,
    // no queue, literally no reaction to the tap. Held here, not sent
    // immediately, and flushed the moment the running turn frees up; last
    // dictation wins if the owner re-records before that happens, same as
    // the phone's setQueued().
    var queued by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    val columnState = rememberTransformingLazyColumnState()

    // AMBIENT MODE - the manager MainActivity provides at the top of the
    // whole navigation tree (see its own comment). Read here, not derived
    // locally, so this screen and any other agree on the same ambient state.
    // Wear's own guidance for an always-on display ("Keep 85%+ of screen
    // black in ambient mode") is why the message cards below drop their
    // brand fills for a near-black/muted-grey pair while ambient: this is
    // the screen that must stay legible AND battery-safe on a dimmed OLED
    // instead of quietly going dark, which is the bug this exists to fix.
    val isAmbient = LocalAmbientModeManager.current?.currentAmbientMode is AmbientMode.Ambient

    // KEEP THE SCREEN ON WHILE A REPLY IS PENDING (owner bug report
    // 2026-09-18: "Display geht aus, bevor die Antwort kommt"). Ambient mode
    // above (and MainActivity's own fix, 2026-09-14) only changes WHAT is
    // drawn once the system has already decided to dim or sleep - it opts the
    // app INTO ambient, it does not stop the OS reaching for it in the first
    // place. FLAG_KEEP_SCREEN_ON is the actual "stay awake" signal, scoped
    // tightly to `busy` (a sent message with no answer yet) so the watch is
    // never held awake outside a running turn - a permanent flag would be
    // the battery bug this one explicitly must not become.
    DisposableEffect(busy) {
        val window = (context as? ComponentActivity)?.window
        if (busy) window?.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        onDispose { window?.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON) }
    }

    // `speak()` and `refresh()` sit ABOVE `ask()` on purpose: `ask()`'s own
    // failure branch calls `refresh()` (the "belegte Fehlbedingung" check,
    // see there), and Kotlin local functions - unlike top-level or member
    // ones - are only visible from their declaration point onward in the
    // enclosing block, so the forward reference would not compile otherwise.

    /** Fetch and play the clip for ONE transcript line, named by its server key.
     *
     *  THE CATCH-UP HALF OF THE VOICE TOGGLE, and the whole reason this file
     *  changed (owner, 2026-09-02: "Stimme aktivieren ist ziemlich broken").
     *  POST /wear/talk's inline clip only ever covered a reply that came back
     *  inside its own HTTP request; an answer that outlived it, an answer to a
     *  turn started on the phone or the glasses, and an answer that landed with
     *  the display off all arrive through refresh() instead - the paths the
     *  event channel made the NORMAL case - and that half was silent.
     *
     *  The daemon renders the clip and refuses anything but the NEWEST
     *  speakable line (routes_wear.wear_voice_get), so a stale key is answered
     *  with silence rather than with the history: this side cannot make the
     *  watch recite yesterday's conversation even by mistake. Voice stays
     *  SERVER-rendered throughout - nothing here synthesises anything
     *  (ops/docs/glasses-reference.md §4, standing owner decision).
     *
     *  60s read timeout, not the 20s default: rendering a clip is a live round
     *  trip to the speech service on a cold cache, and aborting it a beat early
     *  would look exactly like the silence this change exists to fix. Still far
     *  below the relay's own 120s REPLY_TIMEOUT, same as WearStream's 40s.
     */
    suspend fun speak(key: String) {
        val device = DeviceStore.load(context) ?: return
        val result = withContext(Dispatchers.IO) {
            runCatching {
                RelayClient.authedCall(
                    device.relayUrl, device.room, device.daemonPubB64,
                    device.myPublicKeyB64, device.mySecretKeyB64,
                    device.deviceToken, "GET", "/wear/voice?key=$key", "",
                    readTimeoutMs = 60_000)
            }.getOrNull()
        }
        if (result == null || result.first !in 200..299) return
        val v = runCatching {
            JSONObject(result.second).optJSONObject("voice")
        }.getOrNull() ?: return
        // ASKED AGAIN AFTER THE WAIT. The clip took a real render to arrive and
        // the owner may have tapped "Stimme aus" meanwhile - starting it now
        // would be the toggle failing in the one direction that matters.
        if (!voiceOn) return
        VoicePlayer.play(context, v.optString("mime"), v.optString("b64"))
    }

    // THE SERVER TRANSCRIPT IS THE TRUTH. GET /wear/chat returns the same
    // copilot session the phone renders (routes_wear.wear_chat_get), so the
    // watch shows ONE Henry conversation with the phone instead of a separate,
    // amnesiac one - which is what it looked like before, even though messages
    // sent here always did land in that same session.
    //
    // The encrypted cache above is NOT the source of truth; it exists so the
    // screen is already populated while this call is in flight. On success the
    // server list replaces it wholesale (the daemon may have compacted or
    // rotated the session) and is written back.
    //
    // ONE refresh, called from THREE places (owner report 2026-08-30: "Chat
    // auf der Uhr ist verzoegert - die Antwort kommt spaeter oder gar nicht"):
    // the first load, every resume, and an idle ticker. Before this it ran
    // exactly ONCE per composition, so a reply that landed anywhere but in
    // this one in-flight call was invisible until the app was closed and
    // reopened - and talk()'s own timeout message PROMISES the opposite
    // ("falls die Antwort noch entsteht, erscheint sie gleich im Verlauf").
    // Three real paths reach the wrist only through this:
    //   - a turn that outlived talk()'s 4x150s patience (the message above),
    //   - a turn the owner started on the PHONE or the GLASSES,
    //   - an answer that landed while the watch screen was off.
    //
    // Returns whether the /wear/chat FETCH ITSELF succeeded (regardless of
    // whether it found anything new) - added 2026-09-18 so ask() can use a
    // failed refresh as the "belegte Fehlbedingung" for a real, confirmed
    // outage instead of guessing from talk()'s own timeout.
    suspend fun refresh(): Boolean {
        val device = DeviceStore.load(context) ?: return false
        // ALWAYS true while this call is in flight, not just on a cold start.
        // A wake-triggered refresh used to leave `loadingHistory` false
        // because `lines` was already populated, so the old transcript sat
        // there with nothing marking it possibly stale (owner 2026-09-14).
        // buildRows renders this as Row.Hint when the list is empty and as
        // Row.Loading otherwise, so both cases now say "loading" out loud.
        loadingHistory = true
        loadingAttempt = 0
        loadingLong = false
        val loadStart = System.currentTimeMillis()
        // RETRY, not return: the wake-up (WearStream's chat cursor) and this
        // load are two requests, and the cursor is already consumed by the
        // time we get here. One failed load - a relay timeout, a socket the
        // watch dropped in ambient mode - used to leave the transcript stuck
        // until the NEXT chat write (owner 2026-09-12: "auf keinem Geraet
        // sehe ich die Antwort direkt"). Same shape as the phone's
        // ensureChatFresh (data/stream.ts): capped backoff, bounded.
        var result: Pair<Int, String>? = null
        var wait = 2_000L
        for (attempt in 0 until 5) {
            result = withContext(Dispatchers.IO) {
                runCatching {
                    RelayClient.authedCall(
                        device.relayUrl, device.room, device.daemonPubB64,
                        device.myPublicKeyB64, device.mySecretKeyB64,
                        device.deviceToken, "GET", "/wear/chat")
                }.getOrNull()
            }
            if (result != null && result.first in 200..299) break
            loadingAttempt = attempt + 1
            loadingLong = System.currentTimeMillis() - loadStart >= 10_000L
            delay(wait)
            wait = minOf(wait * 2, 15_000L)
        }
        loadingHistory = false
        loadingAttempt = 0
        loadingLong = false
        if (result == null || result.first !in 200..299) return false
        val arr = runCatching {
            JSONObject(result.second).optJSONArray("messages")
        }.getOrNull() ?: return false
        val fresh = ArrayList<Line>(arr.length())
        for (i in 0 until arr.length()) {
            val o = arr.optJSONObject(i) ?: continue
            val text = o.optString("text")
            if (text.isBlank()) continue
            // A mirrored card event ships its label as PARTS (kind + cardName),
            // never pre-rendered: the phone draws them as a transcript sender
            // line and the watch as a TitleCard title, and a server that had
            // guessed one layout would be wrong on the other surface.
            val kind = o.optString("kind")
            val label = if (kind.isBlank()) "" else
                (KIND_LABEL[kind] ?: "Karte") + " · " +
                    o.optString("cardName").ifBlank { o.optString("card") }
            // Only a QUESTION gets buttons. A result or a blocker is news, and
            // offering a tap on it would invite an answer to nothing.
            val opts = ArrayList<String>()
            if (kind == "question") {
                val qs = o.optJSONObject("question")?.optJSONArray("questions")
                val first = qs?.optJSONObject(0)
                val oa = first?.optJSONArray("options")
                if (oa != null) for (j in 0 until oa.length()) {
                    val lbl = oa.optJSONObject(j)?.optString("label") ?: ""
                    // VERBATIM: validate_answers matches a label by equality, so
                    // trimming one here would turn a button press into free text
                    // and the worker would read it as the owner's own words.
                    if (lbl.isNotBlank()) opts.add(lbl)
                }
            }
            // `key` is present on exactly the lines the daemon is willing to
            // speak (Henry's own voice - "bot" and "pm"), absent everywhere
            // else, so its presence IS the speakable flag. An older daemon
            // sends none at all, which degrades to today's silence rather than
            // to a wrong guess about what may be read aloud.
            fresh.add(Line(o.optBoolean("mine"), text, o.optString("ts"),
                           o.optString("date"), label, o.optString("card"), opts,
                           o.optString("key")))
        }
        // An EMPTY server history is a real answer (fresh session) - but never
        // let it wipe a cache the owner can still read if the trim above threw
        // everything away for an unexpected reason.
        if (fresh.isNotEmpty() || lines.isEmpty()) {
            lines.clear()
            lines.addAll(fresh)
            DeviceStore.saveChat(context, lines.map { DeviceStore.ChatLine(it.mine, it.text, it.ts, it.date, it.label) })

            // SPEAK THE ONE ANSWER THAT IS NEW - the half of the voice toggle
            // that was missing. Every delivery that is not talk()'s own HTTP
            // reply lands here: a turn that outlived the request, a turn the
            // owner started on the phone or the glasses, a reply that arrived
            // with the display off.
            //
            // Compared by IDENTITY, never by count. This list was just replaced
            // wholesale, so "one more line than before" is not a fact about
            // this conversation - the daemon compacts and rotates, and the same
            // trap already forced the auto-scroll below onto a content key.
            val newestVoice = fresh.lastOrNull { it.key.isNotBlank() }?.key
            val claimed = spokenKey
            if (claimed == null) {
                // FIRST LOAD: adopt, do not speak. Opening the app, coming back
                // from the board, or reconnecting must never make the watch
                // read back a conversation the owner has already had. "" when
                // there is nothing speakable yet, so this primes exactly once.
                spokenKey = newestVoice ?: ""
            } else if (newestVoice != null && newestVoice != claimed) {
                // Claimed BEFORE the fetch, not after: speak() suspends for a
                // real render, and a second refresh landing meanwhile would
                // otherwise see the same key still unclaimed and say it twice.
                spokenKey = newestVoice
                // Advanced even with voice off, so switching it on later starts
                // with the NEXT answer instead of replaying the last one.
                if (voiceOn) speak(newestVoice)
            }
        }
        return true
    }

    fun ask(message: String) {
        val device = DeviceStore.load(context)
        if (device == null) {
            record(Line(false, "Nicht gekoppelt.", nowHm(), nowDate()))
            return
        }
        record(Line(true, message, nowHm(), nowDate()))
        busy = true
        suggestions = null
        scope.launch {
            // `voice` tells the daemon whether this wrist is LISTENING. It used
            // to render a clip on every single turn regardless, which meant a
            // speech round trip per answer for a toggle that defaults to OFF.
            // An older daemon ignores the field and behaves exactly as before.
            val body = JSONObject()
                .put("message", message).put("voice", voiceOn).toString()
            // talk() = long timeout + dedupe-safe retries (see RelayClient) -
            // a Henry turn outliving one HTTP request is normal, not an error.
            // answerCard below deliberately stays on a single authedCall: its
            // reply_to_card path has no dedupe claim, and the daemon's own 409
            // on a doubled answer is its correctness backstop, not a retry.
            val result = withContext(Dispatchers.IO) {
                RelayClient.talk(
                    device.relayUrl, device.room, device.daemonPubB64,
                    device.myPublicKeyB64, device.mySecretKeyB64,
                    device.deviceToken, body)
            }
            // THE "NICHT VERFUEGBAR" FALSE POSITIVE (owner bug report
            // 2026-09-18). `talk()` used to collapse EVERY failure - a plain
            // 150s socket timeout after ~10 minutes of its own retries
            // included - into the same "Henry nicht erreichbar" chat line,
            // permanently written into the transcript even though the turn
            // was still running and its real answer landed moments later via
            // the stream below. `TalkResult` now tells the two apart:
            when (result) {
                is RelayClient.TalkResult.Offline -> {
                    // The relay ITSELF confirmed the desktop is unreachable
                    // (503) - a real, evidenced outage, not a guess.
                    busy = false
                    record(Line(false, "Henry nicht erreichbar - Verbindung zum Desktop verloren.", nowHm(), nowDate()))
                }
                is RelayClient.TalkResult.Unknown -> {
                    // No confirmed cause. The turn may well still be running
                    // server-side, so ONE read of the much lighter /wear/chat
                    // endpoint (refresh(), with its own 5x backoff) is the
                    // "belegte Fehlbedingung" the owner asked for: if THAT
                    // also fails, the connection itself is down; if it
                    // succeeds, the transcript is the truth - the answer is
                    // either already in it, or the stream below will deliver
                    // it the moment it lands, and no claim is needed either
                    // way. `busy` stays true (keeps the screen on and the
                    // waiting state showing) until this settles.
                    val reachable = refresh()
                    busy = false
                    if (!reachable) {
                        record(Line(false, "Henry nicht erreichbar - Verbindung verloren.", nowHm(), nowDate()))
                    }
                }
                is RelayClient.TalkResult.Ok -> {
                    busy = false
                    val o = runCatching { JSONObject(result.body) }.getOrNull()
                    val reply = (o?.optString("reply") ?: "").ifBlank { "(keine Antwort)" }
                    record(Line(false, reply, nowHm(), nowDate()))
                    suggestions = parseQuestionBlock(o?.optJSONObject("question"))
                    // CLAIM FIRST, THEN PLAY. `voiceKey` names the line this
                    // reply became in the server's transcript, and the same
                    // answer is about to arrive again over refresh() (the
                    // chat cursor moved when the daemon logged it). Recording
                    // it here is what stops the watch saying the same
                    // sentence twice - claimed even when nothing is played,
                    // so switching voice on later does not replay an answer
                    // that was already read on screen.
                    //
                    // A blank key means the daemon did not name the line:
                    // either an older build (which also sends no keys on
                    // /wear/chat, so the refresh path stays silent and this
                    // inline clip is the only voice there is) or a talk()
                    // RETRY collecting a settled turn (which carries no clip
                    // either, and refresh() then speaks it). Both degrade to
                    // exactly one utterance.
                    val vk = o?.optString("voiceKey") ?: ""
                    if (vk.isNotBlank()) spokenKey = vk
                    // `voice` is ABSENT (not null) when server-side rendering
                    // failed; the text is already on screen, so a missing
                    // clip is silence and never an error.
                    val v = o?.optJSONObject("voice")
                    if (voiceOn && v != null) {
                        VoicePlayer.play(context, v.optString("mime"), v.optString("b64"))
                    }
                }
            }
        }
    }

    /** Answer a MIRRORED card question from the wrist.
     *
     *  Same POST as `ask`, plus `reply_to_card` - which is what makes it reach
     *  that card's worker (routes_wear routes it through sessions.reply_door)
     *  instead of Henry's advisory session. Sending it as an ordinary message
     *  would put a bare "A" in front of Henry, who cannot settle another
     *  agent's question, while the card went on waiting.
     *
     *  `answered` clears the buttons immediately: the daemon rejects a second
     *  answer to the same request_id with a 409, so leaving them tappable would
     *  invite a guaranteed error. */
    fun answerCard(card: String, label: String) {
        val device = DeviceStore.load(context)
        if (device == null) {
            record(Line(false, "Nicht gekoppelt.", nowHm(), nowDate()))
            return
        }
        record(Line(true, label, nowHm(), nowDate()))
        answered = answered + card
        busy = true
        scope.launch {
            val body = JSONObject()
                .put("message", label).put("reply_to_card", card).toString()
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    RelayClient.authedCall(
                        device.relayUrl, device.room, device.daemonPubB64,
                        device.myPublicKeyB64, device.mySecretKeyB64,
                        device.deviceToken, "POST", "/wear/talk", body)
                }.getOrNull()
            }
            busy = false
            if (result == null || result.first !in 200..299) {
                // Say so, and put the buttons BACK: an answer that never landed
                // must not look like one that did, or the owner walks away from
                // a card still waiting on him.
                answered = answered - card
                record(Line(false, "Antwort nicht angekommen.", nowHm(), nowDate()))
            }
        }
    }

    val dictate = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == RESULT_OK) {
            val text = result.data
                ?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)
                ?.firstOrNull()
            if (!text.isNullOrBlank()) {
                // QUEUE, DON'T DROP: dictating while Henry is still answering
                // used to be impossible (the button was disabled), which read
                // as the tap doing nothing at all. Held here and flushed by
                // the effect below the moment `busy` frees - same shape as
                // the phone's Composer (ui/card_composer.tsx: "send stays
                // enabled while busy — the message is queued instead of
                // dropped"). Last dictation wins if the owner re-records.
                if (busy) queued = text.trim() else ask(text.trim())
            }
        }
    }

    // THE QUEUED MESSAGE FIRES THE MOMENT THE RUNNING TURN FREES UP. `queued`
    // as a key (not just `busy`) means a plain busy->false with nothing held
    // is a no-op, and a dictation that arrives AFTER busy already went false
    // (the flush already ran) still fires on its own via the `else ask(...)`
    // branch above - this effect only ever has to catch the case where the
    // owner spoke WHILE busy was true.
    LaunchedEffect(busy, queued) {
        if (!busy) {
            val q = queued
            if (q != null) { queued = null; ask(q) }
        }
    }

    fun speechIntent() = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
        putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
        putExtra(RecognizerIntent.EXTRA_PROMPT, "Frag Henry")
    }

    // RESUMED, not merely composed. A LaunchedEffect keeps running while
    // the activity is stopped (the composition outlives onStop), so an
    // unconditional ticker would keep polling the relay from the owner's
    // wrist with the screen off - a watch has neither the battery nor the
    // radio budget for that. Read off the Activity's own lifecycle rather
    // than pulling in lifecycle-runtime-compose for one boolean (§9.1
    // item 15: no new unverified dependency for something already reachable).
    val activity = context as? ComponentActivity
    var resumed by remember { mutableStateOf(true) }
    DisposableEffect(activity) {
        val lc = activity?.lifecycle
        if (lc == null) return@DisposableEffect onDispose { }
        val obs = LifecycleEventObserver { _, e ->
            when (e) {
                Lifecycle.Event.ON_RESUME -> resumed = true
                Lifecycle.Event.ON_PAUSE -> resumed = false
                else -> {}
            }
        }
        lc.addObserver(obs)
        onDispose { lc.removeObserver(obs) }
    }

    // First load AND every return to the screen. Coming back to the watch
    // is exactly when the owner expects to see what Henry answered while
    // his wrist was down, so a resume must not wait for the ticker.
    LaunchedEffect(resumed) {
        if (resumed && !busy) refresh()
    }

    // THE BACKGROUND EVENT PATH. The stream below is the foreground channel and
    // carries everything while the screen is on; this is the half that survives
    // the screen going OFF, which is the one thing a hanging GET cannot do on a
    // watch - Wear suspends the radio and the coroutine dies with the resume.
    // FCM is the platform's own answer to exactly that, so the two are not
    // duplicate transports: screen on -> stream, screen off -> push.
    //
    // Push.inbound is bumped by PushService the instant a sealed FCM push is
    // opened on this device, which the daemon sends from the one line that makes
    // a Henry answer exist (notify.chat_reply, hung off copilot._append_log).
    // Reading .value here subscribes this composable, so a push that arrives
    // while the screen is still on refreshes the transcript immediately.
    //
    // Nothing new is being sent for this: that push has been arriving at this
    // watch since the reverse mirror shipped (2026-08-29) and was being spent
    // entirely on a notification. This just stops throwing the event away.
    //
    // Same guards as the stream, and `busy` above all: the owner's own line only
    // reaches the server log at TURN END, so a refresh mid-turn would wipe his
    // message off his own screen.
    val ping = Push.inbound.value
    LaunchedEffect(ping) {
        if (ping > 0 && resumed && !busy) refresh()
    }

    // THE STREAM - the watch on the SAME event channel as the phone and the
    // desktop, over the SAME sealed relay. The 15s ticker that used to sit here
    // is gone; this is a HANGING GET, not a poll (owner decree 2026-08-30:
    // "einheitlich wie Paseo, kein Polling, verschluesselter Transport").
    //
    // The LOOP itself moved to WearStream, started by MainActivity (2026-09-02).
    // It ran here for two days and that placement was the board's whole problem:
    // MainActivity composes ONE screen at a time, so opening the board destroyed
    // the app's only stream and the board fell back to load-once-plus-a-button.
    // Hoisting it to the activity gives both screens the same channel without a
    // second open request, and the cursors survive navigation because they live
    // on WearStream rather than in this composition.
    //
    // Reading `.value` here IS the subscription - this composable recomposes
    // when the chat cursor moves, exactly as it did when it owned the loop.
    val chatCursor = WearStream.chat.value

    // The cursor moved -> re-read the transcript. `busy` is a KEY, not just a
    // guard: a turn in flight must not refresh (the owner's own line only
    // reaches the server log at TURN END, so a mid-turn read would wipe his
    // message off his own screen), and keying on it means the refresh he was
    // owed happens the moment the turn ends instead of being dropped.
    //
    // The first successful stream reply also lands here, so opening the screen
    // costs one extra read. Deliberate: priming the cursor silently would open
    // a window where an answer arriving between the initial load and the first
    // stream call is adopted as "already seen" and never shown. A duplicate GET
    // is cheap; a lost answer is the bug this whole change exists to kill.
    LaunchedEffect(chatCursor, busy) {
        if (chatCursor > 0 && resumed && !busy) refresh()
    }

    // THE LIST, built once per composition. Everything below - what is drawn,
    // where the auto-scroll aims, and whether the "Neueste" button is offered -
    // reads THIS, so the three can never disagree about what is on screen.
    val rows = buildRows(
        lines, answered, busy,
        // Distinguishable states: still fetching vs. genuinely nothing said
        // yet. Showing the invitation while the history is still loading would
        // read as "Henry has forgotten everything". Gated on `loadingVisible`
        // (not `loadingHistory` directly) so a refresh that resolves inside
        // ~900ms never flashes this at all.
        if (loadingVisible) {
            if (loadingLong) "Verlauf wird geladen… (Versuch $loadingAttempt)"
            else "Verlauf wird geladen…"
        } else "Tippe auf Sprechen und stelle deine Frage.",
        // Henry's own follow-up options, when a tap can settle it.
        suggestions?.questions?.firstOrNull()?.options?.map { it.label } ?: emptyList(),
        loading = loadingVisible,
    )
    val newest = newestMessageIndex(rows)

    // Follow the conversation instead of making him scroll after every reply.
    //
    // Keyed on the newest message's own IDENTITY, not on `lines.size`. refresh()
    // replaces the whole list with the server's (`lines.clear()` +
    // `addAll(fresh)`), and a replacement that happens to be the same length -
    // the daemon compacted one line away while adding a reply - moved no count
    // and therefore scrolled nowhere, even though the newest message had
    // changed. `newest` alone is not enough for the same reason.
    val newestKey = lines.lastOrNull()?.let { "${it.date}|${it.ts}|${it.text.length}|${it.text.take(32)}" } ?: ""
    LaunchedEffect(newest, newestKey) {
        if (newest >= 0) runCatching { columnState.scrollToItem(newest) }
    }

    // IS THE NEWEST MESSAGE ACTUALLY ON SCREEN? Asked of the column's own
    // layout - the list of items it is currently showing - rather than tracked
    // in a flag this screen would have to remember to update on every scroll,
    // every refresh and every relayout. `derivedStateOf` so it only recomposes
    // when the ANSWER flips, not on every pixel of a scroll.
    // KEYED on `newest`: a bare `remember { }` would capture the index from the
    // FIRST composition and go on comparing against it forever, so the button
    // would answer a question about a message that is no longer the newest one.
    val atNewest by remember(newest) {
        derivedStateOf {
            newest < 0 || columnState.layoutInfo.visibleItems.any { it.index >= newest }
        }
    }

    // No MaterialTheme wrapper here on purpose: MainActivity wraps the whole
    // app in HelmDeckWearTheme once. A nested `MaterialTheme { }` with no
    // arguments is exactly how Material's default PURPLE got onto this screen.
    // ROUND SCREEN SIDE INSET. Owner, 2026-08-30, with a photo of
    // the watch: "Auf dem runden Wear-Screen ist die linke Kante der
    // Textblase abgeschnitten - es fehlen ganze Buchstaben am
    // Zeilenanfang."
    //
    // The cards fill the column's width and the column is only inset by
    // ScreenScaffold's own contentPadding, which is what keeps the FIRST
    // and LAST row off the bezel - it is not a horizontal safe area. On a
    // ROUND display a full-width card is cut by the circle everywhere
    // except the vertical middle: at 25% down from the top of a 192dp
    // screen the chord is only ~154dp wide, so a card spanning the full
    // 192 loses ~19dp on EACH side - whole letters, exactly as
    // photographed.
    //
    // Screen-relative rather than a fixed dp value: the same 10% is right
    // on a 192dp small round watch and a 227dp large one, and it is the
    // only number here that is not a guess about one device. Applied to
    // the CARDS rather than to the column, so the date separators and the
    // title stay centred on the full width.
    val sideInset = (LocalConfiguration.current.screenWidthDp * 0.10f).dp
    // Box so the "Neueste" button below can float OVER the list. ScreenScaffold
    // keeps its own scroll indicator on the right edge, so the button sits
    // bottom-CENTRE and the two never fight for the same pixels.
    Box(modifier = Modifier.fillMaxSize()) {
        ScreenScaffold(scrollState = columnState) { contentPadding ->
            TransformingLazyColumn(
                state = columnState,
                contentPadding = contentPadding,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                // ONE `item` PER ROW, in the order buildRows put them - so the
                // index the auto-scroll and the "Neueste" button aim at is the
                // index the column actually lays out. This used to be an
                // imperative build (a `for` over `lines` with conditional
                // separators and buttons inlined), which is precisely why the
                // scroll target could not be computed correctly: the layout
                // existed only as control flow, and nothing could ask it where
                // the newest message had ended up.
                //
                // ONE MESSAGE = ONE TITLECARD: sender top-left, time top-right,
                // text below. Owner, 2026-08-29, with a screenshot of the
                // watch's own SMS app: "Kannst du die Nachrichten genau wie im
                // sms oder andere Chats bauen. Mit Name und Zeitstempel."
                //
                // TitleCard is Wear Compose Material3's OWN component for
                // exactly this shape - it has a `title` slot and a dedicated
                // `time` slot (verified against the real API in the resolved
                // AAR, compose-material3 1.6.2, not guessed from docs). Hand-
                // building a header Row inside a plain Card would re-implement
                // Google's own messaging card and get its type scale and its
                // top-right time placement subtly wrong. Same reason the board
                // uses Button/OutlinedButton/ChildButton rather than three
                // hand-tinted boxes.
                //
                // The colour split stays as the owner asked for it earlier the
                // same day ("Noch zu schwer zu lesen"): your messages carry
                // HelmDeck's translucent accent veil `glow1`, Henry stays
                // neutral `layer2`. Both come from WearTokens, i.e. from
                // ops/tools/gen_tokens.py - no hex is typed in here. Name and
                // time now carry the turn boundary too, so the colour is no
                // longer the ONLY thing saying whose line this is.
                //
                // Text is START-aligned: centring is right for a one-line
                // status, wrong for prose - a centred paragraph has a ragged
                // left edge and the eye loses the line it was on.
                //
                // THREE LEVELS OF EMPHASIS on the trailing buttons, not three
                // identical blue pills. "Sprechen" is the one thing this screen
                // exists for and keeps the filled accent; the voice switch is a
                // setting (outlined); leaving for the board is navigation
                // (lowest). All three shouting equally is how a small screen
                // stops telling you where to look.
                for (row in rows) {
                    item {
                        when (row) {
                            is Row.Title -> Text(
                                text = "Henry", textAlign = TextAlign.Center,
                                modifier = Modifier.padding(horizontal = 8.dp))

                            is Row.Hint -> Text(
                                text = row.text, textAlign = TextAlign.Center,
                                modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp))

                            // The wake-catch-up banner: transcript already has
                            // content, a refresh is in flight, and that must
                            // stay visible rather than silent (see ChatRows.kt).
                            is Row.Loading -> Text(
                                text = if (loadingLong) "Verlauf wird aktualisiert… (Versuch $loadingAttempt)"
                                       else "Verlauf wird aktualisiert…",
                                color = WearTokens.txtTertiary,
                                textAlign = TextAlign.Center,
                                modifier = Modifier.padding(horizontal = 12.dp, vertical = 4.dp))

                            is Row.Day -> Text(
                                text = dayLabel(row.date),
                                color = WearTokens.txtTertiary,
                                textAlign = TextAlign.Center,
                                modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp))

                            is Row.Msg -> TitleCard(
                                onClick = {},
                                title = { Text(senderOf(row.line)) },
                                // Omitted, not blanked, when there is no stamp:
                                // an empty `time` slot would still reserve its
                                // space and leave a gap where a time should be.
                                // A line cached before timestamps existed simply
                                // shows the name - see DeviceStore.ChatLine.
                                time = if (row.line.ts.isBlank()) null
                                       else ({ Text(row.line.ts) }),
                                colors = CardDefaults.cardColors(
                                    containerColor = if (isAmbient) WearTokens.canvas
                                                     else if (row.line.mine) WearTokens.glow1
                                                     else WearTokens.layer2,
                                    contentColor = if (isAmbient) WearTokens.txtTertiary
                                                   else WearTokens.txtPrimary,
                                ),
                                modifier = Modifier.padding(
                                    horizontal = sideInset, vertical = 3.dp),
                            ) {
                                Text(text = row.line.text, textAlign = TextAlign.Start)
                            }

                            is Row.Option -> Button(
                                onClick = { answerCard(row.card, row.label) },
                                enabled = !busy,
                                modifier = Modifier.padding(horizontal = 4.dp, vertical = 2.dp),
                            ) { Text(text = row.label) }

                            is Row.Busy -> Text(
                                text = "Henry denkt …", textAlign = TextAlign.Center,
                                modifier = Modifier.padding(6.dp))

                            is Row.Suggest -> Button(
                                onClick = { ask(row.label) }, enabled = !busy,
                                modifier = Modifier.padding(4.dp)) { Text(text = row.label) }

                            // ALWAYS enabled, even while `busy`: a tap while
                            // Henry is still answering DICTATES a follow-up
                            // and queues it (see `dictate` above) rather than
                            // doing nothing, which is what a disabled button
                            // looked like to the owner (bug report
                            // 2026-09-18: "passiert sichtbar nichts").
                            is Row.Speak -> Button(
                                onClick = { dictate.launch(speechIntent()) },
                                modifier = Modifier.padding(6.dp),
                            ) { Text(if (queued != null) "Wartet …" else if (busy) "…" else "Sprechen") }

                            is Row.VoiceToggle -> OutlinedButton(
                                onClick = {
                                    voiceOn = !voiceOn
                                    DeviceStore.saveVoiceOn(context, voiceOn)
                                    // Switching off mid-sentence must stop THAT
                                    // sentence, not merely the next one.
                                    if (!voiceOn) VoicePlayer.stop()
                                },
                                modifier = Modifier.padding(6.dp),
                            ) { Text(if (voiceOn) "Stimme aus" else "Stimme aktivieren") }

                            // Lowest emphasis, but NOT invisible. A bare
                            // ChildButton draws neither fill nor border, and on
                            // the real watch this rendered as the word "Board"
                            // floating in black - the only way off the landing
                            // screen, looking like a caption. Same hairline the
                            // board's own context rows carry; borderSubtle is
                            // one step below the voice toggle's outline. Both
                            // from WearTokens, i.e. ops/tools/gen_tokens.py.
                            is Row.Board -> ChildButton(
                                onClick = { VoicePlayer.stop(); onOpenBoard() },
                                border = BorderStroke(1.dp, WearTokens.borderSubtle),
                                modifier = Modifier.padding(6.dp)) { Text("Board") }
                        }
                    }
                }
            }
        }

        // JUMP TO THE NEWEST MESSAGE - the wrist's half of the same affordance
        // the phone chat carries as its "↓ Neueste" pill (ui/chat_scroll.tsx).
        // Offered ONLY while the newest message is off screen, because on a
        // 192dp watch a permanent floating button is a permanent hole in the
        // conversation. Scrolls to the same index the auto-follow above uses,
        // animated: this one is a deliberate jump by the owner and the movement
        // is what tells him where he landed.
        if (!atNewest) {
            CompactButton(
                onClick = { scope.launch { runCatching { columnState.animateScrollToItem(newest) } } },
                colors = ButtonDefaults.filledTonalButtonColors(),
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .padding(bottom = 6.dp),
            ) { Text(text = "↓ Neueste") }
        }
    }
}
