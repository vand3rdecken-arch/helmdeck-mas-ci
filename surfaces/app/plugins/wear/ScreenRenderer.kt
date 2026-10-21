package app.helmdeck.wear

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.wear.compose.foundation.lazy.TransformingLazyColumnScope
import androidx.wear.compose.material3.ButtonDefaults
import androidx.wear.compose.material3.ChildButton
import androidx.wear.compose.material3.FilledTonalButton
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.ListHeader
import androidx.wear.compose.material3.ListHeaderDefaults
import androidx.wear.compose.material3.SurfaceTransformation
import androidx.wear.compose.material3.Text
import androidx.wear.compose.material3.lazy.TransformationSpec
import androidx.wear.compose.material3.lazy.transformedHeight
import org.json.JSONObject

/**
 * Generic renderer for a screen the DAEMON describes (spine/ops/wear_screen.py,
 * protocol v1). This file knows HOW to draw a closed set of block types; WHAT
 * is on the screen, in which order, with which words, is the daemon's - so
 * changing it is a daemon change, not a native release (ops/docs/backlog/
 * native-release-diet). A NEW block type or action is the only thing here that
 * costs a native build, which is why the vocabulary is small and closed.
 *
 * An unknown block type is skipped, never guessed at: a newer daemon on an older
 * watch degrades to a shorter screen rather than a wrong one.
 */
sealed class ScreenAction {
    data class OpenCard(val id: String) : ScreenAction()
    data class Nav(val to: String) : ScreenAction()
    object Reload : ScreenAction()
}

sealed class ScreenBlock {
    data class Header(val text: String) : ScreenBlock()
    data class Body(val text: String) : ScreenBlock()
    data class Age(val ts: Long, val prefix: String) : ScreenBlock()
    data class Card(val title: String, val status: String, val action: ScreenAction?) : ScreenBlock()
    data class Button(
        val label: String, val icon: String, val style: String, val action: ScreenAction?,
    ) : ScreenBlock()
}

private fun parseAction(o: JSONObject?): ScreenAction? = when (o?.optString("do")) {
    "open_card" -> ScreenAction.OpenCard(o.optString("id"))
    "nav" -> ScreenAction.Nav(o.optString("to"))
    "reload" -> ScreenAction.Reload
    else -> null
}

/** The `screen` object of a /wear/board response, or null when the daemon is
 *  older than this build (the watch then draws its native board). */
fun parseScreen(boardJson: String): List<ScreenBlock>? {
    val s = runCatching { JSONObject(boardJson).optJSONObject("screen") }.getOrNull() ?: return null
    if (s.optInt("v", 0) != 1) return null
    val arr = s.optJSONArray("items") ?: return null
    val out = mutableListOf<ScreenBlock>()
    for (i in 0 until arr.length()) {
        val o = arr.optJSONObject(i) ?: continue
        when (o.optString("t")) {
            "header" -> out.add(ScreenBlock.Header(o.optString("text")))
            "text" -> out.add(ScreenBlock.Body(o.optString("text")))
            "age" -> out.add(ScreenBlock.Age(o.optLong("ts", 0L), o.optString("prefix")))
            "card" -> out.add(ScreenBlock.Card(
                o.optString("title"), o.optString("status"), parseAction(o.optJSONObject("action"))))
            "button" -> out.add(ScreenBlock.Button(
                o.optString("label"), o.optString("icon"), o.optString("style"),
                parseAction(o.optJSONObject("action"))))
        }
    }
    return out
}

/** Emits one lazy-column item per block, with the same list spec the native
 *  screens use. `onAction` belongs to the calling screen: it owns what
 *  open_card / nav / reload mean (this renderer decides nothing). */
fun TransformingLazyColumnScope.renderScreen(
    blocks: List<ScreenBlock>, spec: TransformationSpec,
    cardFor: (String) -> BoardCard?, onAction: (ScreenAction) -> Unit,
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
            is ScreenBlock.Button -> item {
                val mod = Modifier.fillMaxWidth().transformedHeight(this, spec)
                    .minimumVerticalContentPadding(ButtonDefaults.minimumVerticalListContentPadding)
                if (b.style == "child") {
                    ChildButton(
                        onClick = { b.action?.let(onAction) }, modifier = mod,
                        transformation = SurfaceTransformation(spec),
                    ) { Text(b.label, maxLines = 2, overflow = TextOverflow.Ellipsis) }
                } else {
                    FilledTonalButton(
                        onClick = { b.action?.let(onAction) }, modifier = mod,
                        transformation = SurfaceTransformation(spec),
                        icon = if (b.icon == "mic") ({ Icon(WearIcons.Mic, contentDescription = null) })
                               else null,
                    ) { Text(b.label, maxLines = 2, overflow = TextOverflow.Ellipsis) }
                }
            }
        }
    }
}
