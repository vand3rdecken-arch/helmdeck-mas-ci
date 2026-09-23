package app.helmdeck.wear

import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * Round-bezel-safe horizontal inset, shared by every screen.
 *
 * ScreenScaffold's own contentPadding only protects the FIRST and LAST row of
 * a TransformingLazyColumn from the bezel (it is a rectangular inset around
 * the whole list). A full-width row is still cut by the CIRCLE at every
 * height except the vertical middle - at 25% down a 192dp round screen the
 * chord is only ~154dp wide, so a row spanning the full 192dp loses ~19dp on
 * EACH side (owner photo, 2026-08-30: whole letters missing at the start of
 * wrapped lines). This was fixed per-occurrence (CardScreen's Card/
 * OutlinedCard, HenryScreen's TitleCard, PairingScreen's FieldRow) but Play
 * rejected Wear production 1000006 again on 2026-09-20 under the same
 * font-size guideline - proof that leaving any other Text/Button on a fixed
 * dp inset reproduces the identical clip the moment its content wraps to 2+
 * lines at a large system font scale. Applied everywhere now, not only where
 * a bug had already been photographed.
 *
 * 10% of the screen width per side, not a fixed dp value: the same fraction
 * is correct on a 192dp small round watch and a 227dp large one - it is the
 * only number here that is not a guess about one device.
 */
@Composable
fun wearBezelInset(): Dp = (LocalConfiguration.current.screenWidthDp * 0.10f).dp
