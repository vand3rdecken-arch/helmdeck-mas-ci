package app.swarmdeck.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
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
}

/** Lane colours match the board's dots on the desktop. */
fun laneColor(lane: String): Color = when (lane) {
    "backlog" -> Tok.txtTertiary
    "working" -> Tok.accent
    "review"  -> Tok.warn
    "done"    -> Tok.ok
    else      -> Tok.txtTertiary
}

fun statusColor(status: String?): Color = when (status) {
    "running"   -> Tok.accent
    "needs_you" -> Tok.warn
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
