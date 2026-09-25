package app.helmdeck.wear

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
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

@Composable
fun HelmDeckWearTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = HelmDeckWearColors, content = content)
}
