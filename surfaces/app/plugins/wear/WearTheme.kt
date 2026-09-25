package app.helmdeck.wear

import androidx.compose.runtime.Composable
import androidx.wear.compose.material3.MaterialTheme

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
@Composable
fun HelmDeckWearTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = HelmDeckWearColors, content = content)
}
