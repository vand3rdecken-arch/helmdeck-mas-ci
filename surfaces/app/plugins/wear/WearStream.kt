package app.helmdeck.wear

import android.content.Context
import androidx.compose.runtime.mutableStateOf
import app.helmdeck.wear.data.DeviceStore
import app.helmdeck.wear.data.RelayClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import org.json.JSONObject

/**
 * THE WATCH'S ONE EVENT CHANNEL - the same sealed hanging GET the phone and the
 * desktop run (client.ts's boardWait -> GET /stream/wait?v&c), owned in exactly
 * ONE place for the whole app.
 *
 * This used to live INSIDE HenryScreen, and that was the whole reason the board
 * had no live updates: MainActivity is a `when` over one screen at a time, so
 * navigating to the board DESTROYED the only stream the app had. The board was
 * left with `LaunchedEffect(Unit) { reload() }` - load once, then a manual
 * button - while the chat two taps away was fully event-driven.
 *
 * The fix is NOT a second loop on the board screen. Two loops would hold two
 * open relay requests from one wrist, race each other's cursors, and hand over
 * badly on every navigation (the outgoing screen's coroutine is cancelled while
 * the incoming one starts from a cursor it has to re-derive). Instead the loop
 * is HOISTED to MainActivity, which outlives every screen, and the cursors live
 * here - the single-owner rule CLAUDE.md already applies to drivers.turn_active
 * and sessions.record_bg, applied to a client cursor.
 *
 * Screens are pure SUBSCRIBERS: reading `board.value` / `chat.value` during
 * composition is the whole subscription (same Compose-snapshot idiom as
 * Push.inbound, and the same reason - this module has no Flow anywhere).
 *
 * WHY THE CURSORS SURVIVE THE LOOP: they are properties of this object, not
 * locals of the coroutine. A pause cancels `run()` and a resume starts it
 * afresh, but it resumes FROM the last cursor rather than from 0, so the
 * daemon answers immediately if anything moved while the wrist was down and
 * blocks otherwise. Nothing is lost across a cancellation, which is what makes
 * the reconnect the catch-up path and a timer unnecessary.
 */
object WearStream {
    /** Board data version (`v`) - what /wear/board reads. */
    val board = mutableStateOf(0)

    /** Chat transcript cursor (`c`) - bumped by copilot._append_log, the one
     *  writer of the Henry log (cells/copilot/copilot.py). */
    val chat = mutableStateOf(0)

    /**
     * Hold ONE open sealed request until the daemon says something moved.
     *
     * Suspends forever by design - the caller is a LaunchedEffect keyed on the
     * activity's resumed state, so structured cancellation is the stop button
     * and there is no job to track by hand.
     *
     * readTimeout 40s > the daemon's own 22s wait, deliberately: at the 20s
     * default the client aborts every wait a beat BEFORE the server answers,
     * which turns a working stream into a permanent reconnect loop. Still far
     * below the relay's 120s REPLY_TIMEOUT.
     *
     * Exponential backoff 3s->30s on failure, same as the phone's loop. Cursors
     * are NOT reset on failure, so whatever moved meanwhile is reported on the
     * next success.
     */
    suspend fun run(context: Context) {
        val device = DeviceStore.load(context) ?: return
        var backoff = 3_000L
        while (true) {
            val v = board.value
            val c = chat.value
            val r = withContext(Dispatchers.IO) {
                runCatching {
                    RelayClient.authedCall(
                        device.relayUrl, device.room, device.daemonPubB64,
                        device.myPublicKeyB64, device.mySecretKeyB64,
                        device.deviceToken, "GET", "/stream/wait?v=$v&c=$c", "",
                        readTimeoutMs = 40_000)
                }.getOrNull()
            }
            if (r == null || r.first !in 200..299) {
                delay(backoff)
                backoff = minOf(backoff * 2, 30_000L)
                continue
            }
            backoff = 3_000L
            val o = runCatching { JSONObject(r.second) }.getOrNull() ?: continue
            // ASSIGNED, not accumulated: the daemon returns its CURRENT versions,
            // and writing an unchanged Int to a Compose state is a no-op, so a
            // chat-only bump never recomposes a board subscriber and vice versa.
            board.value = o.optInt("v", v)
            // A daemon older than this build omits `c` entirely - optInt's
            // default keeps the cursor still rather than snapping it to 0 and
            // refreshing on every tick forever.
            chat.value = o.optInt("c", c)
        }
    }
}
