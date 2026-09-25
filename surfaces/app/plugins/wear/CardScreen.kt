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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.Button
import androidx.wear.compose.material3.ButtonDefaults
import androidx.wear.compose.material3.FilledTonalButton
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.ListHeaderDefaults
import androidx.wear.compose.material3.ListHeader
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.wear.compose.material3.SurfaceTransformation
import androidx.wear.compose.material3.lazy.rememberTransformationSpec
import androidx.wear.compose.material3.lazy.transformedHeight
import androidx.wear.compose.material3.Card
import androidx.wear.compose.material3.ChildButton
import androidx.wear.compose.material3.TitleCard
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
    var detail by remember { mutableStateOf<Pair<String, String>?>(null) }
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

    val columnState = rememberTransformingLazyColumnState()
    // The full text of anything long (task, detail, body, question, Henry's
    // answer) is read on its own TextDetailScreen; the list only carries short,
    // ellipsised previews (Google's list pattern, see PairingScreen).
    val shown = detail
    if (shown != null) {
        TextDetailScreen(title = shown.first, text = shown.second, onBack = { detail = null })
        return
    }
    MaterialTheme {
        val spec = rememberTransformationSpec()
        ScreenScaffold(columnState) { contentPadding ->
            TransformingLazyColumn(
                state = columnState,
                contentPadding = contentPadding,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                item {
                    ListHeader(
                        modifier = Modifier
                            .fillMaxWidth()
                            .transformedHeight(this, spec)
                            .minimumVerticalContentPadding(ListHeaderDefaults.minimumTopListContentPadding),
                        transformation = SurfaceTransformation(spec),
                    ) { Text("Karte", maxLines = 1, overflow = TextOverflow.Ellipsis) }
                }
                // "Zurück" stays directly under the title, ABOVE the content: this
                // screen is reached from a manual `when(screen)` in MainActivity, not
                // a SwipeDismissableNavHost, so the swipe-back gesture does not
                // return to the board here.
                item {
                    ChildButton(
                        onClick = { VoicePlayer.stop(); onBack() },
                        modifier = Modifier
                            .fillMaxWidth()
                            .transformedHeight(this, spec)
                            .minimumVerticalContentPadding(ButtonDefaults.minimumVerticalListContentPadding),
                        transformation = SurfaceTransformation(spec),
                    ) { Text("Zurück", maxLines = 1, overflow = TextOverflow.Ellipsis) }
                }
                // The card's task, as a preview that opens in full.
                val task = card.task.ifBlank { card.id }
                item {
                    TitleCard(
                        onClick = { detail = "Aufgabe" to task },
                        title = { Text("Aufgabe", maxLines = 1, overflow = TextOverflow.Ellipsis) },
                        modifier = Modifier
                            .fillMaxWidth()
                            .transformedHeight(this, spec)
                            .minimumVerticalContentPadding(CardDefaults.minimumVerticalListContentPadding),
                        transformation = SurfaceTransformation(spec),
                    ) { Text(task, maxLines = 3, overflow = TextOverflow.Ellipsis) }
                }
                // THE CARD'S OWN CONTENT (owner, 2026-08-29: "wenn ich auf Karte gehe
                // ist nichts da"). Two lines, in the order a triage read wants them:
                //   1. WHY it wants him (blocker reason + detail), coloured by the
                //      card's own status through WearSemantics - the same table the
                //      phone's statusColor() uses. Absent for a pipeline card.
                //   2. WHAT last happened (body): the machine's last reply.
                val label = reasonLabel(card.reason)
                if (label.isNotEmpty()) {
                    item {
                        Text(
                            text = label, textAlign = TextAlign.Center,
                            color = WearSemantics.status(card.status.ifBlank { card.reason }),
                            maxLines = 2, overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.fillMaxWidth().transformedHeight(this, spec),
                        )
                    }
                }
                // ...but NOT when `detail` is just the top of `body` (for the reasons
                // 'delivered' and 'failed', blockers.blocker() builds detail FROM
                // last_reply). Compared on a WHITESPACE-FLATTENED form of both
                // sides: `detail` arrives with its whitespace already collapsed
                // while `body` keeps its paragraph breaks.
                fun flat(s: String) = s.replace(Regex("\\s+"), " ").trim()
                val detailEchoesBody =
                    flat(card.body).startsWith(flat(card.detail).take(40))
                if (card.detail.isNotBlank() && !detailEchoesBody) {
                    item {
                        OutlinedCard(
                            onClick = { detail = "Grund" to card.detail },
                            modifier = Modifier
                                .fillMaxWidth()
                                .transformedHeight(this, spec)
                                .minimumVerticalContentPadding(CardDefaults.minimumVerticalListContentPadding),
                            transformation = SurfaceTransformation(spec),
                        ) { Text(card.detail, maxLines = 3, overflow = TextOverflow.Ellipsis) }
                    }
                }
                if (card.body.isNotBlank()) {
                    // Same neutral surface HenryScreen gives Henry's own messages
                    // (`layer2` from WearTokens): it is the machine talking.
                    item {
                        Card(
                            onClick = { detail = "Antwort" to card.body },
                            colors = CardDefaults.cardColors(
                                containerColor = WearTokens.layer2,
                                contentColor = WearTokens.txtPrimary,
                            ),
                            modifier = Modifier
                                .fillMaxWidth()
                                .transformedHeight(this, spec)
                                .minimumVerticalContentPadding(CardDefaults.minimumVerticalListContentPadding),
                            transformation = SurfaceTransformation(spec),
                        ) { Text(card.body, maxLines = 3, overflow = TextOverflow.Ellipsis) }
                    }
                }

                val q = card.question
                if (q != null) {
                    for (qi in q.questions) {
                        item {
                            TitleCard(
                                onClick = { detail = "Frage" to qi.question },
                                title = { Text("Frage", maxLines = 1, overflow = TextOverflow.Ellipsis) },
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec)
                                    .minimumVerticalContentPadding(CardDefaults.minimumVerticalListContentPadding),
                                transformation = SurfaceTransformation(spec),
                            ) { Text(qi.question, maxLines = 3, overflow = TextOverflow.Ellipsis) }
                        }
                        if (qi.options.isNotEmpty()) {
                            item {
                                ListHeader(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .transformedHeight(this, spec)
                                        .minimumVerticalContentPadding(ListHeaderDefaults.minimumTopListContentPadding),
                                    transformation = SurfaceTransformation(spec),
                                ) { Text("Antworten", maxLines = 1, overflow = TextOverflow.Ellipsis) }
                            }
                        }
                        for (opt in qi.options) {
                            val selected = picks[qi.header] == opt.label
                            item {
                                Button(
                                    onClick = {
                                        picks[qi.header] = opt.label
                                        // Single question, single-select: this IS the
                                        // whole answer - submit immediately, same UX
                                        // as the push notification's option buttons
                                        // (push.ts, W1c). Multi-question needs every
                                        // header filled first (ask.validate_answers'
                                        // own requirement) - a submit button below
                                        // covers that case instead.
                                        if (q.questions.size == 1 && !qi.multiSelect) {
                                            submitAnswer(q.id)
                                        }
                                    },
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .transformedHeight(this, spec)
                                        .minimumVerticalContentPadding(ButtonDefaults.minimumVerticalListContentPadding),
                                    transformation = SurfaceTransformation(spec),
                                ) { Text((if (selected) "> " else "") + opt.label, maxLines = 2, overflow = TextOverflow.Ellipsis) }
                            }
                        }
                    }
                    if (q.questions.size > 1) {
                        item {
                            Button(
                                onClick = { submitAnswer(q.id) },
                                enabled = q.questions.all { picks.containsKey(it.header) },
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec)
                                    .minimumVerticalContentPadding(ButtonDefaults.minimumVerticalListContentPadding),
                                transformation = SurfaceTransformation(spec),
                            ) { Text("Senden", maxLines = 1, overflow = TextOverflow.Ellipsis) }
                        }
                    }
                    if (answerStatus != null) {
                        item {
                            Text(
                                text = answerStatus ?: "", textAlign = TextAlign.Center,
                                maxLines = 2, overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.fillMaxWidth().transformedHeight(this, spec),
                            )
                        }
                    }
                }

                item {
                    ListHeader(
                        modifier = Modifier
                            .fillMaxWidth()
                            .transformedHeight(this, spec)
                            .minimumVerticalContentPadding(ListHeaderDefaults.minimumTopListContentPadding),
                        transformation = SurfaceTransformation(spec),
                    ) { Text("Henry fragen", maxLines = 1, overflow = TextOverflow.Ellipsis) }
                }
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
                        modifier = Modifier
                            .fillMaxWidth()
                            .transformedHeight(this, spec)
                            .minimumVerticalContentPadding(ButtonDefaults.minimumVerticalListContentPadding),
                        transformation = SurfaceTransformation(spec),
                        icon = { Icon(WearIcons.Mic, contentDescription = null) },
                    ) { Text(if (henryBusy) "…" else "Sprechen", maxLines = 1, overflow = TextOverflow.Ellipsis) }
                }
                val reply = henryReply
                if (reply != null) {
                    item {
                        Card(
                            onClick = { detail = "Henry" to reply },
                            colors = CardDefaults.cardColors(
                                containerColor = WearTokens.layer2,
                                contentColor = WearTokens.txtPrimary,
                            ),
                            modifier = Modifier
                                .fillMaxWidth()
                                .transformedHeight(this, spec)
                                .minimumVerticalContentPadding(CardDefaults.minimumVerticalListContentPadding),
                            transformation = SurfaceTransformation(spec),
                        ) { Text(reply, maxLines = 3, overflow = TextOverflow.Ellipsis) }
                    }
                }
                henrySuggestions?.questions?.forEach { sug ->
                    for (opt in sug.options) {
                        item {
                            FilledTonalButton(
                                onClick = {
                                    askHenry(context, scope, card.id, opt.label,
                                        onBusy = { henryBusy = it },
                                        onReply = { r, more -> henryReply = r; henrySuggestions = more })
                                },
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .transformedHeight(this, spec)
                                    .minimumVerticalContentPadding(ButtonDefaults.minimumVerticalListContentPadding),
                                transformation = SurfaceTransformation(spec),
                            ) { Text(opt.label, maxLines = 2, overflow = TextOverflow.Ellipsis) }
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
        if (result !is RelayClient.TalkResult.Ok) {
            onReply("Henry nicht erreichbar.", null)
            return@launch
        }
        val o = runCatching { JSONObject(result.body) }.getOrNull()
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
