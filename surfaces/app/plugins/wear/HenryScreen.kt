package app.helmdeck.wear

import android.app.Activity.RESULT_OK
import android.content.Context
import android.content.Intent
import android.speech.RecognizerIntent
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
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
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.Button
import androidx.wear.compose.material3.CardDefaults
import androidx.wear.compose.material3.ChildButton
import androidx.wear.compose.material3.OutlinedButton
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.Text
import androidx.wear.compose.material3.TitleCard
import app.helmdeck.wear.data.DeviceStore
import app.helmdeck.wear.data.RelayClient
import app.helmdeck.wear.data.VoicePlayer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

/** One line of the conversation: who said it, what, and when.
 *
 *  `ts` is the daemon's own "HH:mm" (copilot's log stamp, passed through by
 *  wear_chat_get) for a message read back from the server, and the WATCH's
 *  clock for one that was just sent or just answered - /wear/talk returns no
 *  stamp, and the moment the line appears is the honest answer for it. Empty
 *  when neither is available; the chat then shows the name without a time
 *  rather than inventing a minute.
 *
 *  `label`, `card` and `options` are set only on a MIRRORED CARD EVENT (cls
 *  "card" server-side, cells/copilot/card_mirror.py). `label` is the composed
 *  "Frage · Kartenname" that replaces the sender name, so the owner can tell a
 *  worker waiting on a decision from Henry talking; `card` is the id an answer
 *  goes back to; `options` are the worker's own choices when one tap settles
 *  it. All three are empty on an ordinary line, and an older daemon omits them
 *  from the payload entirely - which degrades to exactly the previous
 *  behaviour, never to a blank. */
private data class Line(val mine: Boolean, val text: String, val ts: String = "",
                        val date: String = "", val label: String = "",
                        val card: String = "", val options: List<String> = emptyList())

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
 * ops/docs/glasses-reference.md Â§4, reaffirmed by
 * ops/docs/voice-interaction-design.md, which allows device TTS only as an
 * unapproved offline fallback (Â§8.4). The button below plays what the server
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
    var voiceOn by remember { mutableStateOf(DeviceStore.loadVoiceOn(context)) }
    var suggestions by remember { mutableStateOf<QuestionBlock?>(null) }
    // Cards answered from THIS screen since it opened. The server transcript is
    // the truth, but it is a poll behind: without this the buttons would stay
    // on screen after a tap until the next /wear/chat load, and a second tap is
    // a certain 409. Derived state, never persisted - a restart re-reads the
    // real answer from the transcript rather than trusting a remembered flag.
    var answered by remember { mutableStateOf(setOf<String>()) }
    val scope = rememberCoroutineScope()
    val columnState = rememberTransformingLazyColumnState()

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
            val body = JSONObject().put("message", message).toString()
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
            busy = false
            if (result == null || result.first !in 200..299) {
                // A network answer the owner can act on, not a blank screen.
                // After talk()'s retries this is a real outage, not a slow
                // turn. The turn may STILL land server-side - the transcript
                // poll below is the truth - so promise that instead of a dead
                // Henry.
                record(Line(false, "Henry nicht erreichbar - falls die Antwort noch entsteht, erscheint sie gleich im Verlauf.", nowHm(), nowDate()))
                return@launch
            }
            val o = runCatching { JSONObject(result.second) }.getOrNull()
            val reply = (o?.optString("reply") ?: "").ifBlank { "(keine Antwort)" }
            record(Line(false, reply, nowHm(), nowDate()))
            suggestions = parseQuestionBlock(o?.optJSONObject("question"))
            // `voice` is ABSENT (not null) when server-side rendering failed;
            // the text is already on screen, so a missing clip is silence and
            // never an error.
            val v = o?.optJSONObject("voice")
            if (voiceOn && v != null) {
                VoicePlayer.play(context, v.optString("mime"), v.optString("b64"))
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
            if (!text.isNullOrBlank()) ask(text.trim())
        }
    }

    fun speechIntent() = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
        putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
        putExtra(RecognizerIntent.EXTRA_PROMPT, "Frag Henry")
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
    suspend fun refresh() {
        val device = DeviceStore.load(context) ?: return
        loadingHistory = lines.isEmpty()
        val result = withContext(Dispatchers.IO) {
            runCatching {
                RelayClient.authedCall(
                    device.relayUrl, device.room, device.daemonPubB64,
                    device.myPublicKeyB64, device.mySecretKeyB64,
                    device.deviceToken, "GET", "/wear/chat")
            }.getOrNull()
        }
        loadingHistory = false
        if (result == null || result.first !in 200..299) return
        val arr = runCatching {
            JSONObject(result.second).optJSONArray("messages")
        }.getOrNull() ?: return
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
            fresh.add(Line(o.optBoolean("mine"), text, o.optString("ts"),
                           o.optString("date"), label, o.optString("card"), opts))
        }
        // An EMPTY server history is a real answer (fresh session) - but never
        // let it wipe a cache the owner can still read if the trim above threw
        // everything away for an unexpected reason.
        if (fresh.isNotEmpty() || lines.isEmpty()) {
            lines.clear()
            lines.addAll(fresh)
            DeviceStore.saveChat(context, lines.map { DeviceStore.ChatLine(it.mine, it.text, it.ts, it.date, it.label) })
        }
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

    // The idle ticker. NOT while a turn is in flight: the owner's own
    // message is appended to the server log only when the whole turn
    // completes (copilot.chat -> _append_log), so a mid-turn poll would
    // return a transcript WITHOUT the line he just spoke and wipe it off
    // his screen until Henry finished - his own words vanishing as he
    // watches. talk() already delivers that answer itself; this loop is
    // only for the answers that arrive by any other path.
    LaunchedEffect(Unit) {
        while (true) {
            delay(15_000)
            if (resumed && !busy) refresh()
        }
    }

    // Follow the conversation instead of making him scroll after every reply -
    // but ONLY once there is something to follow. The first version keyed on
    // `busy` as well and scrolled on the very first composition, when the list
    // was still empty: the title and the "tap Sprechen" hint were pushed up
    // under the clock and the screen opened half-cut (seen on the watch,
    // 2026-08-29). An empty chat must open at the TOP.
    LaunchedEffect(lines.size) {
        if (lines.isNotEmpty()) {
            // index 0 is the title, so the newest line sits at lines.size -
            // but scrollToItem puts the target at the TOP edge, where the
            // scaffold's TimeText sits on top of it (seen on the watch,
            // 2026-08-29: the newest line was clipped under the clock). Aiming
            // one item earlier lands the newest line in clear space, with its
            // predecessor as context above it.
            runCatching { columnState.scrollToItem(maxOf(0, lines.size - 1)) }
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
    run {
        ScreenScaffold(scrollState = columnState) { contentPadding ->
            TransformingLazyColumn(
                state = columnState,
                contentPadding = contentPadding,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                item {
                    Text(text = "Henry", textAlign = TextAlign.Center,
                        modifier = Modifier.padding(horizontal = 8.dp))
                }
                if (lines.isEmpty()) {
                    item {
                        Text(
                            // Distinguishable states: still fetching vs. genuinely
                            // nothing said yet. Showing the invitation while the
                            // history is still loading would read as "Henry has
                            // forgotten everything".
                            text = if (loadingHistory) "Verlauf wird geladenâ€¦"
                                   else "Tippe auf Sprechen und stelle deine Frage.",
                            textAlign = TextAlign.Center,
                            modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
                        )
                    }
                }
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
                // DATE SEPARATORS, exactly where the owner's SMS screenshot has
                // them: one centred caption above the first message of each day.
                //
                // Drawn ONLY from a recorded date. copilot._append_log started
                // stamping one on 2026-08-29 and everything older has none, so
                // `date` is "" for the existing transcript - and a line with no
                // date gets no separator and does not close the previous day
                // either. Filing an undated message under whatever day happened
                // to precede it would be a guess rendered as a fact; the whole
                // point of the forward-only stamp is that we do not do that.
                var lastDay = ""
                for (line in lines) {
                    if (line.date.isNotBlank() && line.date != lastDay) {
                        lastDay = line.date
                        item {
                            Text(
                                text = dayLabel(line.date),
                                color = WearTokens.txtTertiary,
                                textAlign = TextAlign.Center,
                                modifier = Modifier.padding(
                                    horizontal = 10.dp, vertical = 6.dp),
                            )
                        }
                    }
                    item {
                        TitleCard(
                            onClick = {},
                            title = { Text(senderOf(line)) },
                            // Omitted, not blanked, when there is no stamp: an
                            // empty `time` slot would still reserve its space
                            // and leave a gap where a time should be. A line
                            // cached before timestamps existed simply shows the
                            // name - see DeviceStore.ChatLine.
                            time = if (line.ts.isBlank()) null
                                   else ({ Text(line.ts) }),
                            colors = CardDefaults.cardColors(
                                containerColor = if (line.mine) WearTokens.glow1
                                                 else WearTokens.layer2,
                                contentColor = WearTokens.txtPrimary,
                            ),
                            modifier = Modifier.padding(
                                horizontal = sideInset, vertical = 3.dp),
                        ) {
                            Text(text = line.text, textAlign = TextAlign.Start)
                        }
                    }
                    // The worker's OWN options, right under the question that
                    // offered them - not collected at the bottom of the screen
                    // like Henry's follow-up suggestions below. Two cards can be
                    // waiting at once, and a pooled list would give the owner no
                    // way to see which card a button belongs to.
                    if (line.card.isNotBlank() && line.card !in answered) {
                        for (opt in line.options) {
                            item {
                                Button(onClick = { answerCard(line.card, opt) },
                                    enabled = !busy,
                                    modifier = Modifier.padding(horizontal = 4.dp, vertical = 2.dp)) {
                                    Text(text = opt)
                                }
                            }
                        }
                    }
                }
                if (busy) {
                    item {
                        Text(text = "Henry denktâ€¦", textAlign = TextAlign.Center,
                            modifier = Modifier.padding(6.dp))
                    }
                }
                // Henry's own follow-up options, when a tap can settle it.
                suggestions?.questions?.firstOrNull()?.options?.forEach { opt ->
                    item {
                        Button(onClick = { ask(opt.label) }, enabled = !busy,
                            modifier = Modifier.padding(4.dp)) { Text(text = opt.label) }
                    }
                }
                item {
                    Button(onClick = { dictate.launch(speechIntent()) }, enabled = !busy,
                        modifier = Modifier.padding(6.dp)) {
                        Text(if (busy) "â€¦" else "Sprechen")
                    }
                }
                // THREE LEVELS OF EMPHASIS, not three identical blue pills.
                // "Sprechen" above is the one thing this screen exists for and
                // keeps the filled accent; the voice switch is a setting
                // (outlined); leaving for the board is navigation (lowest).
                // All three shouting equally is how a small screen stops
                // telling you where to look.
                item {
                    OutlinedButton(
                        onClick = {
                            voiceOn = !voiceOn
                            DeviceStore.saveVoiceOn(context, voiceOn)
                            // Switching off mid-sentence must stop THAT
                            // sentence, not merely the next one.
                            if (!voiceOn) VoicePlayer.stop()
                        },
                        modifier = Modifier.padding(6.dp),
                    ) { Text(if (voiceOn) "Stimme aus" else "Stimme aktivieren") }
                }
                // Lowest emphasis, but NOT invisible. A bare ChildButton draws
                // neither fill nor border, and on the real watch this rendered
                // as the word "Board" floating in black - the only way off the
                // landing screen, looking like a caption. Same hairline the
                // board's own context rows now carry, so "tappable but not your
                // move" looks the same everywhere. borderSubtle is one step
                // below the outline the voice toggle above uses; both from
                // WearTokens, i.e. from ops/tools/gen_tokens.py.
                item {
                    ChildButton(onClick = { VoicePlayer.stop(); onOpenBoard() },
                        border = BorderStroke(1.dp, WearTokens.borderSubtle),
                        modifier = Modifier.padding(6.dp)) { Text("Board") }
                }
            }
        }
    }
}
