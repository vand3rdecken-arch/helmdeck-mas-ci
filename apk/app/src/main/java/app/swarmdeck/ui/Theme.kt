package app.swarmdeck.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

/**
 * SwarmDeck's design tokens, ported 1:1 from web/app/globals.css (dark theme).
 * The CSS uses OKLCH; these are the exact sRGB conversions, so the phone renders
 * the same palette as the desktop instead of stock Material colours.
 */
object Tok {
    val canvas      = Color(0xFF0E0F10)   // --bg-canvas
    val surface1    = Color(0xFF141515)   // --bg-surface-1
    val surface2    = Color(0xFF181A1B)   // --bg-surface-2
    val layer1      = Color(0xFF181A1B)
    val layer2      = Color(0xFF1D1F20)
    val layer2Hover = Color(0xFF222425)
    val borderSubtle= Color(0xFF222425)   // --border-subtle
    val borderStrong= Color(0xFF36393A)   // --border-strong

    val txtPrimary  = Color(0xFFE4E6E6)   // --txt-primary
    val txtSecondary= Color(0xFFCACDCE)
    val txtTertiary = Color(0xFFAFB3B6)
    val txtPlaceholder = Color(0xFF959A9D)

    val accent      = Color(0xFF2893CC)   // --accent (brand)
    val accentSoft  = Color(0xFF66B6E1)
    val accent2     = Color(0xFF967AF0)
    val ok          = Color(0xFF4CB86A)   // --ok
    val warn        = Color(0xFFFC9A10)   // --warn
    val danger      = Color(0xFFFF6467)   // --danger
    val ai          = Color(0xFF5B9FD9)   // --ai
    val human       = Color(0xFFC99B2E)   // --human

    val glassBorder = Color(0x17FFFFFF)   // --glass-border (white 9%)
    // --glass: a translucent panel fill (dark theme oklch(.21 .003 230/62%)).
    // Semi-opaque so the ambient glow backdrop shows through = the desktop's
    // frosted look, approximated without a real backdrop blur (not available
    // pre-Android-12). Panels/cards/bars paint with this over the glow.
    val glass       = Color(0xB81C1E1F)   // ~72% alpha over #1C1E1F
    val glassStrong = Color(0xD11A1C1D)   // ~82% for bars that need more cover
}

/** The desktop's ambient backdrop (globals.css body::before): three soft radial
 *  glows - accent-blue top-left, purple top-right, blue bottom - over the canvas.
 *  This is the single biggest reason the flat phone looked unlike the desktop. */
fun androidx.compose.ui.Modifier.glowBackdrop() = this.drawBehind {
    drawRect(Tok.canvas)
    val d = maxOf(size.width, size.height)
    // Glass needs something to refract: on pure black the frosted nav shows
    // nothing. Now that the nav does a REAL blur (which keeps colour from going
    // muddy), the ambient glow can be present - three richer radial glows,
    // including one low-centre so the glass bar has colour to blur.
    fun glow(color: androidx.compose.ui.graphics.Color, a: Float, x: Float, y: Float, r: Float) =
        drawRect(androidx.compose.ui.graphics.Brush.radialGradient(
            listOf(color.copy(alpha = a), androidx.compose.ui.graphics.Color.Transparent),
            center = androidx.compose.ui.geometry.Offset(size.width * x, size.height * y), radius = d * r))
    glow(Tok.accent,  .26f, .06f, -.04f, .60f)   // blue, top-left
    glow(Tok.accent2, .22f, .98f,  .04f, .52f)   // purple, top-right
    glow(Tok.accent2, .26f, .30f, 1.04f, .55f)   // purple, bottom-left  -> under the glass nav
    glow(Tok.accent,  .24f, .80f, 1.02f, .50f)   // blue, bottom-right   -> under the glass nav
}

/** Lane colours match the desktop board dots 1:1 (web/lib/store.tsx:81-84):
 *  working is --ai (blue), review is --human (gold) - NOT accent/warn. */
fun laneColor(lane: String): Color = when (lane) {
    "backlog" -> Tok.txtTertiary
    "working" -> Tok.ai
    "review"  -> Tok.human
    "done"    -> Tok.ok
    else      -> Tok.txtTertiary
}

/** Who does the work - same rule as the desktop (web board.tsx:37-40):
 *  returns "ai" | "human" | "both" from the card's mode. */
fun executor(mode: String?): String = when (mode) {
    "human", "teach" -> "human"
    "cowork"         -> "both"
    else             -> "ai"
}

fun executorLabel(mode: String?) = when (executor(mode)) {
    "human" -> "You"; "both" -> "AI + You"; else -> "AI"
}

fun executorColor(mode: String?) = when (executor(mode)) {
    "human" -> Tok.human; "both" -> Tok.ai; else -> Tok.ai
}

/** Status colours match the desktop 1:1 (web/lib/store.tsx:87-89). */
fun statusColor(status: String?): Color = when (status) {
    "queued"    -> Tok.txtTertiary
    "running"   -> Tok.ai
    "needs_you" -> Tok.warn
    "submitted" -> Tok.human
    "accepted"  -> Tok.ok
    "bounced"   -> Tok.danger
    "done"      -> Tok.ok
    "failed"    -> Tok.danger
    else        -> Tok.txtTertiary
}

private val scheme = darkColorScheme(
    primary = Tok.accent,
    onPrimary = Color.White,
    secondary = Tok.accent2,
    background = Tok.canvas,
    onBackground = Tok.txtPrimary,
    surface = Tok.surface1,
    onSurface = Tok.txtPrimary,
    surfaceVariant = Tok.surface2,
    onSurfaceVariant = Tok.txtSecondary,
    outline = Tok.borderSubtle,
    error = Tok.danger,
)

private val typo = Typography(
    titleLarge  = TextStyle(fontSize = 20.sp, fontWeight = FontWeight.SemiBold, color = Tok.txtPrimary),
    titleMedium = TextStyle(fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = Tok.txtPrimary),
    bodyLarge   = TextStyle(fontSize = 15.sp, color = Tok.txtPrimary),
    bodyMedium  = TextStyle(fontSize = 13.5.sp, color = Tok.txtSecondary),
    bodySmall   = TextStyle(fontSize = 12.sp, color = Tok.txtTertiary),
    labelSmall  = TextStyle(fontSize = 11.sp, color = Tok.txtTertiary, fontFamily = FontFamily.Monospace),
)

@Composable
fun SwarmTheme(content: @Composable () -> Unit) {
    @Suppress("UNUSED_EXPRESSION") isSystemInDarkTheme()   // app is dark-only, like the desktop
    MaterialTheme(colorScheme = scheme, typography = typo, content = content)
}
