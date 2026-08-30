package app.helmdeck.wear

import android.app.Activity.RESULT_OK
import android.content.Context
import android.content.Intent
import android.speech.RecognizerIntent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.Button
import androidx.wear.compose.material3.Card
import androidx.wear.compose.material3.CardDefaults
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.OutlinedCard
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.Text
import app.helmdeck.wear.data.DeviceStore
import app.helmdeck.wear.data.RelayClient
import app.helmdeck.wear.data.VoicePlayer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

/**
 * One card: the worker's pending question (if any, answered directly via
 * POST /tracks/<id>/answer - the ONE case README.md §4.7 explicitly allows
 * to reach the worker, because it is a structured pick, not authorship) and
 * a "Henry fragen" advisory chat (POST /wear/talk, allow_actions=False).
 *
 * §4.7's line is drawn HERE, in this screen: option taps on the WORKER's own
 * question call /tracks/answer; option "chips" on HENRY's reply never do -
 * tapping one just sends that label as the NEXT message to Henry, continuing
 * the advisory conversation, exactly the semantics an ADVISORY surface
 * requires (Henry's suggested next-moves are his own construction, not tied
 * to any request_id a worker is waiting on).
 */
@Composable
fun CardScreen(context: Context, card: BoardCard, onBack: () -> Unit) {
    // SnapshotStateMap IS the observable object (unlike mutableStateOf's
    // MutableState<T>) - `val`, not `var ... by`, no property-delegate
    // getValue/setValue exists for it.
    val picks = remember { mutableStateMapOf<String, String>() }
    var answerStatus by remember { mutableStateOf<String?>(null) }
    var henryReply by remember { mutableStateOf<String?>(null) }
    var henrySuggestions by remember { mutableStateOf<QuestionBlock?>(null) }
    var henryBusy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    val dictateLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == RESULT_OK) {
            val text = result.data
                ?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)
                ?.firstOrNull()
            if (!text.isNullOrBlank()) askHenry(
                context, scope, card.id, text,
                onBusy = { henryBusy = it },
                onReply = { reply, suggestions -> henryReply = reply; henrySuggestions = suggestions },
            )
        }
    }

    fun submitAnswer(requestId: String) {
        val device = DeviceStore.load(context) ?: return
        answerStatus = "Sende…"
        scope.launch {
            // Built with explicit put() calls, not a JSONObject(Map)
            // constructor - Android's bundled org.json is a stripped-down
            // subset of the reference implementation and that constructor's
            // presence was not confirmed this session; put() in a loop is
            // the same pattern already used (and working) everywhere else
            // in this file.
            val answers = JSONObject()
            for ((header, label) in picks) answers.put(header, label)
            val body = JSONObject().apply {
                put("answers", answers)
                put("request_id", requestId)
            }.toString()
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    RelayClient.authedCall(
                        device.relayUrl, device.room, device.daemonPubB64,
                        device.myPublicKeyB64, device.mySecretKeyB64, device.deviceToken,
                        "POST", "/tracks/${card.id}/answer", body)
                }.getOrNull()
            }
            answerStatus = if (result != null && result.first in 200..299) "Beantwortet" else "Fehlgeschlagen"
        }
    }

    MaterialTheme {
        val columnState = rememberTransformingLazyColumnState()
        // ROUND SCREEN SIDE INSET - same as HenryScreen.kt, same cause:
        // ScreenScaffold's contentPadding keeps the first and last ROW off
        // the bezel, but a full-width card is still cut by the circle at
        // every height except the vertical middle (owner photo,
        // 2026-08-30: whole letters missing at the start of the wrapped
        // lines). 10% of the screen width per side, so it scales with
        // the device instead of being a guess about one.
        val sideInset = (LocalConfiguration.current.screenWidthDp * 0.10f).dp
        // Same reasoning as PairingScreen: ScreenScaffold computes the
        // screen-size-relative content padding and passes it in, instead of a
        // bare Box that leaves the first and last row against the bezel.
        ScreenScaffold(columnState) { contentPadding ->
            TransformingLazyColumn(
                state = columnState,
                contentPadding = contentPadding,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                item {
                    Text(
                        text = card.task.ifBlank { card.id },
                        textAlign = TextAlign.Center,
                        modifier = Modifier.padding(8.dp),
                    )
                }
                // "Zurück" stays directly under the title, ABOVE the content:
                // this screen is reached from a manual `when(screen)` in
                // MainActivity, not a SwipeDismissableNavHost, so the swipe-back
                // gesture does not return to the board here. Putting the only
                // way out below a scrolling wall of text would strand him on a
                // long card.
                item {
                    Button(
                        onClick = { VoicePlayer.stop(); onBack() },
                        modifier = Modifier.padding(4.dp),
                    ) { Text("Zurück") }
                }
                // THE CARD'S OWN CONTENT - the whole reason this screen exists
                // and the one thing it used to be missing. Owner, 2026-08-29:
                // "wenn ich auf Karte gehe ist nichts da." It was literally
                // true: title, Zurück, Henry fragen, and nothing in between.
                //
                // Two lines, in the order a triage read wants them:
                //   1. WHY it wants him (blocker reason + detail), coloured by
                //      the card's own status through WearSemantics - the same
                //      table the phone's statusColor() uses, so red means red
                //      on both. Absent for a pipeline card, which is not stuck.
                //   2. WHAT last happened (body): the machine's last reply.
                val label = reasonLabel(card.reason)
                if (label.isNotEmpty()) {
                    item {
                        Text(
                            text = label,
                            color = WearSemantics.status(
                                card.status.ifBlank { card.reason }),
                            textAlign = TextAlign.Center,
                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 2.dp),
                        )
                    }
                }
                // ...but NOT when `detail` is just the top of `body`. For the
                // reasons 'delivered' and 'failed', blockers.blocker() builds
                // detail FROM last_reply (blockers.py:70,80) - it is literally
                // the first 160 chars of the card below it, and rendering both
                // prints the same sentence twice on a screen with no room for
                // it once. Probed on the text rather than on the reason name so
                // a new reason with the same shape cannot reintroduce it.
                // Compared on a WHITESPACE-FLATTENED form of both sides, not on
                // the raw strings. `detail` arrives with its whitespace already
                // collapsed to single spaces (blockers._blocker_text) while
                // `body` keeps its paragraph breaks - so a reply that opens with
                // a heading produced "DELIVERED  Auf der" against "DELIVERED Auf
                // der" and the prefix test failed on the double space, printing
                // the same sentence twice. Flattening both is the comparison the
                // test always meant to make.
                fun flat(s: String) = s.replace(Regex("\\s+"), " ").trim()
                val detailEchoesBody =
                    flat(card.body).startsWith(flat(card.detail).take(40))
                if (card.detail.isNotBlank() && !detailEchoesBody) {
                    item {
                        OutlinedCard(
                            onClick = {},
                            modifier = Modifier.padding(
                                horizontal = sideInset, vertical = 3.dp),
                        ) {
                            Text(text = card.detail, textAlign = TextAlign.Start)
                        }
                    }
                }
                if (card.body.isNotBlank()) {
                    item {
                        // Same neutral surface HenryScreen gives Henry's own
                        // messages (`layer2` from WearTokens, i.e. from
                        // ops/tools/gen_tokens.py) - because it is the same
                        // thing: the machine talking. Start-aligned; a centred
                        // paragraph has a ragged left edge and the eye loses
                        // the line it was on.
                        Card(
                            onClick = {},
                            colors = CardDefaults.cardColors(
                                containerColor = WearTokens.layer2,
                                contentColor = WearTokens.txtPrimary,
                            ),
                            modifier = Modifier.padding(
                                horizontal = sideInset, vertical = 3.dp),
                        ) {
                            Text(text = card.body, textAlign = TextAlign.Start)
                        }
                    }
                }

                val q = card.question
                if (q != null) {
                    for (item in q.questions) {
                        item { Text(text = item.question, modifier = Modifier.padding(8.dp)) }
                        for (opt in item.options) {
                            val selected = picks[item.header] == opt.label
                            item {
                                Button(
                                    onClick = {
                                        picks[item.header] = opt.label
                                        // Single question, single-select: this IS the
                                        // whole answer - submit immediately, same UX
                                        // as the push notification's option buttons
                                        // (push.ts, W1c). Multi-question needs every
                                        // header filled first (ask.validate_answers'
                                        // own requirement) - a submit button below
                                        // covers that case instead.
                                        if (q.questions.size == 1 && !item.multiSelect) {
                                            submitAnswer(q.id)
                                        }
                                    },
                                    modifier = Modifier.padding(2.dp),
                                ) { Text(text = (if (selected) "> " else "") + opt.label) }
                            }
                        }
                    }
                    if (q.questions.size > 1) {
                        item {
                            Button(
                                onClick = { submitAnswer(q.id) },
                                enabled = q.questions.all { picks.containsKey(it.header) },
                                modifier = Modifier.padding(8.dp),
                            ) { Text("Antworten") }
                        }
                    }
                    if (answerStatus != null) {
                        item { Text(text = answerStatus ?: "", modifier = Modifier.padding(8.dp)) }
                    }
                }

                item { Text(text = "Henry fragen", modifier = Modifier.padding(8.dp)) }
                item {
                    Button(
                        onClick = {
                            val prompt = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                                    RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                                putExtra(RecognizerIntent.EXTRA_PROMPT, "Frage an Henry")
                            }
                            dictateLauncher.launch(prompt)
                        },
                        enabled = !henryBusy,
                        modifier = Modifier.padding(4.dp),
                    ) { Text(if (henryBusy) "…" else "Diktieren") }
                }
                if (henryReply != null) {
                    item { Text(text = henryReply ?: "", modifier = Modifier.padding(8.dp)) }
                }
                henrySuggestions?.questions?.forEach { sug ->
                    for (opt in sug.options) {
                        item {
                            Button(
                                onClick = {
                                    askHenry(context, scope, card.id, opt.label,
                                        onBusy = { henryBusy = it },
                                        onReply = { reply, more -> henryReply = reply; henrySuggestions = more })
                                },
                                modifier = Modifier.padding(2.dp),
                            ) { Text(text = opt.label) }
                        }
                    }
                }
            }
        }
    }
}

private fun askHenry(
    context: Context, scope: kotlinx.coroutines.CoroutineScope, cardId: String, message: String,
    onBusy: (Boolean) -> Unit, onReply: (String, QuestionBlock?) -> Unit,
) {
    val device = DeviceStore.load(context) ?: return
    onBusy(true)
    scope.launch {
        val body = JSONObject().apply { put("message", message); put("card", cardId) }.toString()
        // talk() = long timeout + dedupe-safe retries (see RelayClient) -
        // a Henry turn outliving one HTTP request is normal, not an error.
        val result = withContext(Dispatchers.IO) {
            RelayClient.talk(
                device.relayUrl, device.room, device.daemonPubB64,
                device.myPublicKeyB64, device.mySecretKeyB64, device.deviceToken,
                body)
        }
        onBusy(false)
        if (result == null || result.first !in 200..299) {
            onReply("Henry nicht erreichbar.", null)
            return@launch
        }
        val o = runCatching { JSONObject(result.second) }.getOrNull()
        val reply = o?.optString("reply") ?: ""
        val q = parseQuestionBlock(o?.optJSONObject("question"))
        onReply(reply.ifBlank { "(keine Antwort)" }, q)
        // /wear/talk ALWAYS renders voice when TTS is available
        // (routes_wear.py) - the whole point of bringing the owner into
        // chat on a keyboard-less watch is to LISTEN to Henry, not read
        // tiny text on a round screen. `voice` is simply absent (not null)
        // when rendering failed - text is already shown either way, so
        // there is nothing to degrade here beyond "no sound this time".
        val voice = o?.optJSONObject("voice")
        if (voice != null) {
            val mime = voice.optString("mime", "audio/mpeg")
            val b64 = voice.optString("b64")
            if (b64.isNotEmpty()) VoicePlayer.play(context, mime, b64)
        }
    }
}
