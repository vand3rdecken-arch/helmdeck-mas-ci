package app.helmdeck.wear

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.wear.compose.material3.AppScaffold
import androidx.wear.compose.material3.MaterialTheme
import app.helmdeck.wear.data.DeviceStore

/**
 * W2a's original milestone (README.md §8 row 4) was an empty screen that
 * builds and starts - that's still exactly what an unpaired watch shows
 * today, via PairingScreen. 2026-08-29: once paired, this now shows the
 * REAL board (BoardScreen, GET /wear/board) instead of the old static
 * placeholder - W2b's board view exists. Card taps go to CardScreen, which
 * is where README.md §4.7's owner decree actually applies: Henry, never the
 * worker, no matter how the card got opened.
 *
 * Navigation is a plain local sealed-class state machine, not
 * androidx.navigation - three screens does not earn a new, unverified
 * dependency on top of everything already unverified in this module (§9.1
 * item 15).
 */
private sealed class WearScreen {
    object Board : WearScreen()
    data class Card(val card: BoardCard) : WearScreen()
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            // AppScaffold is the APP-level half of the Wear scaffold pair
            // (ScreenScaffold, used inside each screen, is the other): it owns
            // the TimeText shown across every screen and the transitions
            // between them. Added 2026-08-28 after the first look at a real
            // watch - without it the app drew into a bare rectangle with no
            // clock, which is not what a Wear app looks like.
            MaterialTheme {
                AppScaffold {
                    // `this@MainActivity`, NOT a bare `this`: AppScaffold's
                    // content lambda is a BoxScope receiver, so inside it a
                    // plain `this` is the BoxScope, not the Activity. The
                    // first compile of this change said exactly that -
                    // "actual type is 'BoxScope', but 'Context' was expected".
                    val ctx = this@MainActivity
                    var paired by remember { mutableStateOf(DeviceStore.load(ctx) != null) }
                    if (!paired) {
                        PairingScreen(context = ctx, onPaired = { paired = true })
                    } else {
                        var screen by remember { mutableStateOf<WearScreen>(WearScreen.Board) }
                        when (val s = screen) {
                            is WearScreen.Board -> BoardScreen(
                                context = ctx,
                                onOpenCard = { c -> screen = WearScreen.Card(c) },
                            )
                            is WearScreen.Card -> CardScreen(
                                context = ctx, card = s.card,
                                onBack = { screen = WearScreen.Board },
                            )
                        }
                    }
                }
            }
        }
    }
}
