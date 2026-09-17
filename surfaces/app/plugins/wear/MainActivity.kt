package app.helmdeck.wear

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.wear.compose.foundation.LocalAmbientModeManager
import androidx.wear.compose.foundation.rememberAmbientModeManager
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
    // 2026-08-29: Henry without a card. He used to live only INSIDE a card, so
    // an empty board left the owner with nothing to talk to - see
    // HenryScreen.kt's header.
    object Henry : WearScreen()
}

class MainActivity : ComponentActivity() {
    /** W2d: POST_NOTIFICATIONS is a runtime permission from API 33 on. Asked
     *  once at launch - a denied grant makes every notify() a silent no-op, so
     *  push would look "broken" with nothing in the logs to say why. */
    private val askNotify = registerForActivityResult(
        ActivityResultContracts.RequestPermission()) { /* result handled by the OS UI */ }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Push.ensureChannel(this)
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED) {
            askNotify.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        // Covers the token that Firebase minted BEFORE this device was paired
        // (the common case on first launch) and any registration that failed
        // while the watch was offline. No-op while unpaired.
        Push.syncToken(this)
        setContent {
            // AppScaffold is the APP-level half of the Wear scaffold pair
            // (ScreenScaffold, used inside each screen, is the other): it owns
            // the TimeText shown across every screen and the transitions
            // between them. Added 2026-08-28 after the first look at a real
            // watch - without it the app drew into a bare rectangle with no
            // clock, which is not what a Wear app looks like.
            // ONE theme for the whole app - HelmDeck's canonical palette from
            // surfaces/app/src/theme/tokens.ts, not Material's purple baseline.
            HelmDeckWearTheme {
                AppScaffold {
                    // `this@MainActivity`, NOT a bare `this`: AppScaffold's
                    // content lambda is a BoxScope receiver, so inside it a
                    // plain `this` is the BoxScope, not the Activity. The
                    // first compile of this change said exactly that -
                    // "actual type is 'BoxScope', but 'Context' was expected".
                    val ctx = this@MainActivity

                    // AMBIENT MODE (owner bug report 2026-09-14: "die Uhr geht
                    // nach 2-3 Sekunden in Standby, sieht daher nie
                    // Live-Nachrichten von Henry"). Without this, HenryScreen
                    // had no opt-in to the platform's Ambient state machine at
                    // all, so the OS fell back to its default screen timeout -
                    // the app's own Compose tree stopped being what the wrist
                    // shows, not merely dimmed. Wired once here, at the top of
                    // the whole navigation tree (AppScaffold's content, above
                    // the `when` below), so Board/Card/Henry all see the SAME
                    // ambient state rather than each screen re-deriving it.
                    //
                    // LocalAmbientModeManager, not the older Fragment-based
                    // AmbientModeSupport / AmbientLifecycleObserver: this is
                    // Google's own current guidance for a Compose-first Wear
                    // app (androidx.wear.compose.foundation, already resolved
                    // here via compose-foundation:1.6.2 - stable since 1.6.0,
                    // 2026-03-25 - so no new Gradle dependency), confirmed
                    // 2026-09-14 against the android/skills wear-compose-m3
                    // guide (dated 2026-09-03): "Ambient mode - Use
                    // LocalAmbientModeManager instead of
                    // AmbientLifecycleObserver." rememberAmbientModeManager()
                    // resolves the Activity via LocalActivity internally as of
                    // 1.6.0-alpha10, so it takes no Activity parameter.
                    // GUARDED, not called unconditionally (found 2026-09-17 while
                    // testing the font-scale fix below): rememberAmbientModeManager()
                    // constructs AmbientComponentState from com.google.wear:wear-sdk,
                    // a PROPRIETARY system class shipped only inside a real watch's
                    // system image - not present on the generic AOSP Wear emulator
                    // (confirmed: ClassNotFoundException, app force-closed on every
                    // launch, google/sdk_gwear_x86 API 30). It throws in the
                    // constructor, before any composition-local wiring - a try/catch
                    // around the composable call itself would not help. Checked once,
                    // not on every recomposition (`remember`); HenryScreen's existing
                    // `LocalAmbientModeManager.current?.currentAmbientMode` is already
                    // null-safe, so simply not providing the local when unsupported is
                    // the correct fallback, not a new special case to maintain.
                    val supportsAmbient = remember {
                        runCatching {
                            Class.forName("com.google.wear.services.ambient.AmbientComponentState")
                        }.isSuccess
                    }
                    val content: @Composable () -> Unit = {
                    var paired by remember { mutableStateOf(DeviceStore.load(ctx) != null) }

                    // THE APP'S ONE EVENT CHANNEL, started HERE rather than
                    // inside a screen. MainActivity outlives every screen (the
                    // `when` below composes exactly one at a time), so a stream
                    // owned by a screen dies on every navigation - which is
                    // precisely why the board had no live updates while the
                    // chat did. See WearStream.kt.
                    //
                    // RESUMED, not merely composed: the composition outlives
                    // onStop, so an unconditional loop would keep an open relay
                    // request alive from the owner's wrist with the screen off,
                    // and a watch has neither the battery nor the radio budget
                    // for that. Read off the Activity's own lifecycle rather
                    // than pulling in lifecycle-runtime-compose for one boolean
                    // (§9.1 item 15). FCM is the screen-off half.
                    var resumed by remember { mutableStateOf(true) }
                    DisposableEffect(Unit) {
                        val obs = LifecycleEventObserver { _, e ->
                            when (e) {
                                Lifecycle.Event.ON_RESUME -> resumed = true
                                Lifecycle.Event.ON_PAUSE -> resumed = false
                                else -> {}
                            }
                        }
                        lifecycle.addObserver(obs)
                        onDispose { lifecycle.removeObserver(obs) }
                    }
                    // Structured cancellation IS the stop button: leaving the
                    // screen cancels this coroutine and with it the open
                    // request. The cursors live on WearStream, not in the
                    // coroutine, so the resume picks up exactly where this left
                    // off instead of re-reading from 0.
                    LaunchedEffect(paired, resumed) {
                        if (paired && resumed) WearStream.run(ctx)
                    }
                    if (!paired) {
                        PairingScreen(context = ctx, onPaired = {
                            paired = true
                            // Only NOW is there a daemon to send the token to.
                            Push.syncToken(ctx)
                        })
                    } else {
                        // HENRY IS THE LANDING SCREEN (owner, 2026-08-29). The
                        // board used to be, which meant the thing the watch
                        // exists for - saying something to Henry - was two taps
                        // deep and invisible on an empty board. The board is now
                        // the one tap away, not the other way round.
                        var screen by remember { mutableStateOf<WearScreen>(WearScreen.Henry) }
                        when (val s = screen) {
                            is WearScreen.Board -> BoardScreen(
                                context = ctx,
                                onOpenCard = { c -> screen = WearScreen.Card(c) },
                                onAskHenry = { screen = WearScreen.Henry },
                            )
                            is WearScreen.Card -> CardScreen(
                                context = ctx, card = s.card,
                                onBack = { screen = WearScreen.Board },
                            )
                            is WearScreen.Henry -> HenryScreen(
                                context = ctx,
                                onOpenBoard = { screen = WearScreen.Board },
                            )
                        }
                    }
                    }
                    if (supportsAmbient) {
                        val ambientModeManager = rememberAmbientModeManager()
                        CompositionLocalProvider(
                            LocalAmbientModeManager provides ambientModeManager,
                            content = content,
                        )
                    } else {
                        content()
                    }
                }
            }
        }
    }
}
