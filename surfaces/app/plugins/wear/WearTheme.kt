package app.helmdeck.wear

import androidx.compose.runtime.Composable
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.dp
import androidx.wear.compose.foundation.lazy.TransformingLazyColumnItemScope
import androidx.wear.compose.foundation.lazy.TransformingLazyColumnScope
import androidx.wear.compose.material3.lazy.TransformationSpec
import androidx.wear.compose.material3.lazy.transformedHeight
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.wear.compose.material3.LocalTextStyle
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text

/**
 * The watch's theme - deliberately almost empty.
 *
 * Owner, 2026-08-29: "Ist Farbe nicht zentralisiert? ... Theme sollte auch
 * zentralisiert sein." Both are, now. This file used to hold two things that
 * did not belong in Kotlin:
 *
 *   1. hex values copied out of tokens.ts - a second source of truth, and
 *   2. the MAPPING of brand tokens onto Material's colour roles - the last
 *      hand-written copy of "which HelmDeck colour is the primary action".
 *
 * Both now live in ops/tools/gen_tokens.py, the same generator that writes the
 * phone's tokens.ts, and arrive here as the generated `HelmDeckWearColors`
 * (WearTokens.kt). Change the palette or the role mapping there, re-run
 *
 *     py -3.12 ops/tools/gen_tokens.py
 *
 * and phone and watch move together. What is left in this file is the only
 * thing that is genuinely watch-specific: applying it once, at the root.
 *
 * Screens must NOT call `MaterialTheme { }` with no arguments - that is exactly
 * how Material's default purple ended up on the watch in the first place.
 */
/**
 * Text that WRAPS and is never clipped. Wear M3 buttons, cards and headers
 * install a LocalTextConfiguration (maxLines 1-3, ellipsis) around their
 * content; at fontScale 2.0 that ellipsis hid characters (Play font-size
 * rejection 2026-09-24). Explicit maxLines/overflow override it. The rows
 * around it grow instead, and the list's SurfaceTransformation keeps them
 * off the round edge.
 */
@Composable
fun FullText(
    text: String,
    modifier: Modifier = Modifier,
    color: Color = Color.Unspecified,
    textAlign: TextAlign? = null,
    style: TextStyle = LocalTextStyle.current,
) {
    Text(
        text = text, modifier = modifier, color = color, textAlign = textAlign,
        maxLines = Int.MAX_VALUE, overflow = TextOverflow.Clip, style = style,
    )
}

/** How many characters one list row may hold: about three wrapped lines, so a
 *  row is never taller than the round viewport at ANY system font scale
 *  (48 chars at 1.0, 24 at 2.0). Long text is emitted as several rows, see
 *  chunkText. */
@Composable
fun rememberChunkChars(): Int =
    (48f / LocalDensity.current.fontScale).toInt().coerceIn(16, 60)

/** Emits `text` as one row per slice, each row already sized by `spec`.
 *  `row` draws one slice inside the item (receiver = the item scope, the
 *  Modifier is fillMaxWidth + transformedHeight). */
fun TransformingLazyColumnScope.chunkedRows(
    text: String, maxChars: Int, spec: TransformationSpec,
    row: @Composable TransformingLazyColumnItemScope.(String, Modifier) -> Unit,
) {
    for (part in chunkText(text, maxChars)) {
        item { row(part, Modifier.fillMaxWidth().transformedHeight(this, spec)) }
    }
}

/** Room after the LAST row: the SurfaceTransformation still crops a row in the
 *  bottom band, so without it the final button rests with its lower edge cut
 *  flat (seen on the Small Round emulator at fontScale 2.0). */
fun TransformingLazyColumnScope.endInset() {
    item { Spacer(Modifier.height(40.dp)) }
}

/** Plain wrapping text rows (no Button/Card around them), with the round-screen inset. */
fun TransformingLazyColumnScope.textRows(
    text: String, maxChars: Int, spec: TransformationSpec,
    textAlign: TextAlign = TextAlign.Center, color: Color = Color.Unspecified,
) = chunkedRows(text, maxChars, spec) { part, m ->
    FullText(text = part, color = color, textAlign = textAlign,
        modifier = m.padding(horizontal = 12.dp, vertical = 4.dp))
}

@Composable
fun HelmDeckWearTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = HelmDeckWearColors, content = content)
}
