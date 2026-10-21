package app.helmdeck.wear

import android.app.Activity.RESULT_OK
import android.content.Context
import android.content.Intent
import android.speech.RecognizerIntent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.wear.compose.foundation.lazy.TransformingLazyColumn
import androidx.wear.compose.foundation.lazy.TransformingLazyColumnScope
import androidx.wear.compose.foundation.lazy.rememberTransformingLazyColumnState
import androidx.wear.compose.material3.Button
import androidx.wear.compose.material3.ButtonDefaults
import androidx.wear.compose.material3.Card
import androidx.wear.compose.material3.CardDefaults
import androidx.wear.compose.material3.ChildButton
import androidx.wear.compose.material3.FilledTonalButton
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.ListHeader
import androidx.wear.compose.material3.ListHeaderDefaults
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.OutlinedCard
import androidx.wear.compose.material3.ScreenScaffold
import androidx.wear.compose.material3.SurfaceTransformation
import androidx.wear.compose.material3.Text
import androidx.wear.compose.material3.TitleCard
import androidx.wear.compose.material3.lazy.TransformationSpec
import androidx.wear.compose.material3.lazy.rememberTransformationSpec
import androidx.wear.compose.material3.lazy.transformedHeight
import app.helmdeck.wear.data.DeviceStore
import app.helmdeck.wear.data.RelayClient
import app.helmdeck.wear.data.VoicePlayer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.URLEncoder

/**
 * Generic renderer for a screen the DAEMON describes (spine/ops/wear_screen.py,
 * protocol v1). This file knows HOW to draw a closed set of block types and
 * HOW to run a closed set of actions; WHAT is on a screen, in which order, with
 * which words, is the daemon's - so changing it is a daemon change, not a
 * native release (ops/docs/backlog/native-release-diet). A NEW block type or
 * action is the only thing here that costs a native build, which is why the
 * vocabulary is small and closed.
 *
 * Unknown blocks and actions are skipped, never guessed at: a newer daemon on
 * an older watch degrades to a shorter screen rather than a wrong one.
 */
sealed class ScreenAction {
    data class OpenCard(val id: String) : ScreenAction()
    data class Nav(val to: String) : ScreenAction()
    object Reload : ScreenAction()
    object Back : ScreenAction()
    /** Remember key=value locally; `then` runs right after (single-select = the answer). */
    data class Pick(val key: String, val value: String, val then: ScreenAction?) : ScreenAction()
    /** Generic authed POST. `picksInto` names the body field the picks map is put under. */
    data class Post(
        val path: String, val body: JSONObject, val picksInto: String,
        val busy: String, val ok: String, val fail: String,
    ) : ScreenAction()
    /** Speech -> Henry, about one card. */
    data class Dictate(val prompt: String, val card: String) : ScreenAction()
    /** Client-built only (Henry's suggested next moves); never parsed from the wire. */
    data class Ask(val card: String, val message: String) : ScreenAction()
}

sealed class ScreenBlock {
    data class Header(val text: String) : ScreenBlock()
    data class Body(val text: String, val status: String) : ScreenBlock()
    data class Age(val ts: Long, val prefix: String) : ScreenBlock()
    data class Card(val title: String, val status: String, val action: ScreenAction?) : ScreenBlock()
    /** A short card that opens the FULL text on its own screen. style: title | outlined | surface. */
    data class Preview(
        val title: String, val text: String, val lines: Int, val style: String,
        val detailTitle: String,
    ) : ScreenBlock()
    data class Button(
        val label: String, val icon: String, val style: String, val action: ScreenAction?,
        val selKey: String, val selValue: String, val needs: List<String>,
    ) : ScreenBlock()
}

private fun parseAction(o: JSONObject?): ScreenAction? = when (o?.optString("do")) {
    "open_card" -> ScreenAction.OpenCard(o.optString("id"))
    "nav" -> ScreenAction.Nav(o.optString("to"))
    "reload" -> ScreenAction.Reload
    "back" -> ScreenAction.Back
    "pick" -> ScreenAction.Pick(o.optString("key"), o.optString("value"),
        parseAction(o.optJSONObject("then")))
    "post" -> ScreenAction.Post(
        o.optString("path"), o.optJSONObject("body") ?: JSONObject(), o.optString("picks_into"),
        o.optString("busy"), o.optString("ok"), o.optString("fail"))
    "dictate" -> ScreenAction.Dictate(o.optString("prompt"), o.optString("card"))
    else -> null
}

/** The `screen` object of a response, or null when the daemon is older than
 *  this build (the watch then draws its native screen). */
fun parseScreen(json: String): List<ScreenBlock>? {
    val s = runCatching { JSONObject(json).optJSONObject("screen") }.getOrNull() ?: return null
    if (s.optInt("v", 0) != 1) return null
    val arr = s.optJSONArray("items") ?: return null
    val out = mutableListOf<ScreenBlock>()
    for (i in 0 until arr.length()) {
        val o = arr.optJSONObject(i) ?: continue
        when (o.optString("t")) {
            "header" -> out.add(ScreenBlock.Header(o.optString("text")))
            "text" -> out.add(ScreenBlock.Body(o.optString("text"), o.optString("status")))
            "age" -> out.add(ScreenBlock.Age(o.optLong("ts", 0L), o.optString("prefix")))
            "card" -> out.add(ScreenBlock.Card(
                o.optString("title"), o.optString("status"), parseAction(o.optJSONObject("action"))))
            "preview" -> out.add(ScreenBlock.Preview(
                o.optString("title"), o.optString("text"), o.optInt("lines", 3),
                o.optString("style"), o.optString("detail_title")))
            "button" -> {
                val sel = o.optJSONObject("selected")
                val needs = mutableListOf<String>()
                o.optJSONArray("needs")?.let { n -> for (k in 0 until n.length()) needs.add(n.optString(k)) }
                out.add(ScreenBlock.Button(
                    o.optString("label"), o.optString("icon"), o.optString("style"),
                    parseAction(o.optJSONObject("action")),
                    sel?.optString("key").orEmpty(), sel?.optString("value").orEmpty(), needs))
            }
        }
    }
    return out
}

/**
 * One described screen with all the state its actions need (local picks, post
 * status, the full-text view, Henry's reply to a dictated question). Board and
 * card both run through this; the screen owns only what open_card / nav /
 * reload / back mean, via the callbacks.
 */
@Composable
fun ScreenHost(
    context: Context, blocks: List<ScreenBlock>,
    cardFor: (String) -> BoardCard?, onOpenCard: (BoardCard) -> Unit,
    onNav: (String) -> Unit, onReload: () -> Unit, onBack: () -> Unit,
) {
    val picks = remember { mutableStateMapOf<String, String>() }
    var postStatus by remember { mutableStateOf<String?>(null) }
    var detail by remember { mutableStateOf<Pair<String, String>?>(null) }
    var henryReply by remember { mutableStateOf<String?>(null) }
    var henrySuggestions by remember { mutableStateOf<QuestionBlock?>(null) }
    var henryBusy by remember { mutableStateOf(false) }
    var dictateCard by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()

    fun ask(card: String, message: String) = askHenry(
        context, scope, card, message,
        onBusy = { henryBusy = it },
        onReply = { reply, more -> henryReply = reply; henrySuggestions = more })

    val dictateLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == RESULT_OK) {
            val text = result.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()
            if (!text.isNullOrBlank()) ask(dictateCard, text)
        }
    }

    fun run(a: ScreenAction) {
        when (a) {
            is ScreenAction.OpenCard -> cardFor(a.id)?.let(onOpenCard)
            is ScreenAction.Nav -> onNav(a.to)
            ScreenAction.Reload -> onReload()
            ScreenAction.Back -> { VoicePlayer.stop(); onBack() }
            is ScreenAction.Pick -> { picks[a.key] = a.value; a.then?.let { run(it) } }
            is ScreenAction.Post -> {
                val device = DeviceStore.load(context) ?: return
                postStatus = a.busy.ifEmpty { null }
                val body = JSONObject(a.body.toString())
                if (a.picksInto.isNotEmpty()) {
                    val picked = JSONObject()
                    for ((k, v) in picks) picked.put(k, v)
                    body.put(a.picksInto, picked)
                }
                scope.launch {
                    val result = withContext(Dispatchers.IO) {
                        runCatching {
                            RelayClient.authedCall(
                                device.relayUrl, device.room, device.daemonPubB64,
                                device.myPublicKeyB64, device.mySecretKeyB64, device.deviceToken,
                                "POST", a.path, body.toString())
                        }.getOrNull()
                    }
                    postStatus = if (result != null && result.first in 200..299) a.ok else a.fail
                }
            }
            is ScreenAction.Dictate -> {
                dictateCard = a.card
                dictateLauncher.launch(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                    putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                    putExtra(RecognizerIntent.EXTRA_PROMPT, a.prompt)
                })
            }
            is ScreenAction.Ask -> ask(a.card, a.message)
        }
    }

    // The full text of anything long is read on its own screen; the list only
    // carries short, ellipsised previews (Google's list pattern).
    val shown = detail
    if (shown != null) {
        TextDetailScreen(title = shown.first, text = shown.second, onBack = { detail = null })
        return
    }
    val extra = mutableListOf<ScreenBlock>()
    postStatus?.let { extra.add(ScreenBlock.Body(it, "")) }
    henryReply?.let { extra.add(ScreenBlock.Preview("", it, 3, "surface", "Henry")) }
    henrySuggestions?.questions?.forEach { sug ->
        for (opt in sug.options) extra.add(ScreenBlock.Button(
            opt.label, "", "tonal", ScreenAction.Ask(dictateCard, opt.label), "", "", emptyList()))
    }
    MaterialTheme {
        val columnState = rememberTransformingLazyColumnState()
        val spec = rememberTransformationSpec()
        ScreenScaffold(columnState) { contentPadding ->
            TransformingLazyColumn(
                state = columnState, contentPadding = contentPadding,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                renderBlocks(blocks + extra, spec, picks, henryBusy, cardFor,
                    onDetail = { t, x -> detail = t to x }, onAction = { run(it) })
            }
        }
    }
}

/** Emits one lazy-column item per block, with the same list spec the native
 *  screens use. Decides nothing: every tap goes to `onAction`. */
fun TransformingLazyColumnScope.renderBlocks(
    blocks: List<ScreenBlock>, spec: TransformationSpec, picks: Map<String, String>,
    busy: Boolean, cardFor: (String) -> BoardCard?,
    onDetail: (String, String) -> Unit, onAction: (ScreenAction) -> Unit,
) {
    for (b in blocks) {
        when (b) {
            is ScreenBlock.Header -> item {
                ListHeader(
                    modifier = Modifier.fillMaxWidth().transformedHeight(this, spec)
                        .minimumVerticalContentPadding(ListHeaderDefaults.minimumTopListContentPadding),
                    transformation = SurfaceTransformation(spec),
                ) { Text(b.text, maxLines = 2, overflow = TextOverflow.Ellipsis) }
            }
            is ScreenBlock.Body -> item {
                Text(
                    b.text, textAlign = TextAlign.Center, maxLines = 2,
                    color = if (b.status.isBlank()) Color.Unspecified else WearSemantics.status(b.status),
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.fillMaxWidth().transformedHeight(this, spec))
            }
            is ScreenBlock.Age -> {
                val age = freshness(b.ts, System.currentTimeMillis() / 1000L)
                if (age.isNotEmpty()) item {
                    Text(
                        b.prefix + age, textAlign = TextAlign.Center, maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.fillMaxWidth().transformedHeight(this, spec))
                }
            }
            is ScreenBlock.Card -> item {
                val id = (b.action as? ScreenAction.OpenCard)?.id.orEmpty()
                val card = cardFor(id) ?: BoardCard(
                    id = id, task = b.title, reason = "", question = null, status = b.status)
                CardEntry(card, spec) { b.action?.let(onAction) }
            }
            is ScreenBlock.Preview -> item {
                val mod = Modifier.fillMaxWidth().transformedHeight(this, spec)
                    .minimumVerticalContentPadding(CardDefaults.minimumVerticalListContentPadding)
                val open = { onDetail(b.detailTitle.ifBlank { b.title }, b.text) }
                when (b.style) {
                    "outlined" -> OutlinedCard(
                        onClick = open, modifier = mod, transformation = SurfaceTransformation(spec),
                    ) { Text(b.text, maxLines = b.lines, overflow = TextOverflow.Ellipsis) }
                    "surface" -> Card(
                        onClick = open,
                        colors = CardDefaults.cardColors(
                            containerColor = WearTokens.layer2, contentColor = WearTokens.txtPrimary),
                        modifier = mod, transformation = SurfaceTransformation(spec),
                    ) { Text(b.text, maxLines = b.lines, overflow = TextOverflow.Ellipsis) }
                    else -> TitleCard(
                        onClick = open,
                        title = { Text(b.title, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                        modifier = mod, transformation = SurfaceTransformation(spec),
                    ) { Text(b.text, maxLines = b.lines, overflow = TextOverflow.Ellipsis) }
                }
            }
            is ScreenBlock.Button -> item {
                val mod = Modifier.fillMaxWidth().transformedHeight(this, spec)
                    .minimumVerticalContentPadding(ButtonDefaults.minimumVerticalListContentPadding)
                val selected = b.selKey.isNotEmpty() && picks[b.selKey] == b.selValue
                val label = (if (selected) "> " else "") + if (busy && b.icon == "mic") "…" else b.label
                val enabled = b.needs.all { picks.containsKey(it) } && !(busy && b.icon == "mic")
                val icon: (@Composable BoxScope.() -> Unit)? =
                    if (b.icon == "mic") ({ Icon(WearIcons.Mic, contentDescription = null) }) else null
                val go = { b.action?.let(onAction); Unit }
                val text = @Composable { Text(label, maxLines = 2, overflow = TextOverflow.Ellipsis) }
                when (b.style) {
                    "child" -> ChildButton(
                        onClick = go, enabled = enabled, modifier = mod,
                        transformation = SurfaceTransformation(spec)) { text() }
                    "tonal" -> FilledTonalButton(
                        onClick = go, enabled = enabled, modifier = mod,
                        transformation = SurfaceTransformation(spec), icon = icon) { text() }
                    else -> Button(
                        onClick = go, enabled = enabled, modifier = mod,
                        transformation = SurfaceTransformation(spec), icon = icon) { text() }
                }
            }
        }
    }
}

/**
 * The card screen: fetched from the daemon as a screen description
 * (GET /wear/card?id=). Falls back to the native screen only when the daemon
 * has no such route (older than this build); refetches whenever the board
 * moves so it never shows a card state the list no longer has.
 */
@Composable
fun CardScreen(context: Context, card: BoardCard, onBack: () -> Unit) {
    var blocks by remember(card.id) { mutableStateOf<List<ScreenBlock>?>(null) }
    var tried by remember(card.id) { mutableStateOf(false) }
    LaunchedEffect(card.id, WearStream.board.value) {
        val device = DeviceStore.load(context)
        if (device != null) {
            val r = withContext(Dispatchers.IO) {
                runCatching {
                    RelayClient.authedCall(
                        device.relayUrl, device.room, device.daemonPubB64,
                        device.myPublicKeyB64, device.mySecretKeyB64, device.deviceToken,
                        "GET", "/wear/card?id=" + URLEncoder.encode(card.id, "UTF-8"))
                }.getOrNull()
            }
            if (r != null && r.first in 200..299) parseScreen(r.second)?.let { blocks = it }
        }
        tried = true
    }
    val described = blocks
    when {
        described != null -> ScreenHost(
            context, described, cardFor = { null }, onOpenCard = {},
            onNav = {}, onReload = {}, onBack = onBack)
        !tried -> MaterialTheme {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text("Lade…", textAlign = TextAlign.Center)
            }
        }
        else -> LegacyCardScreen(context, card, onBack)
    }
}
