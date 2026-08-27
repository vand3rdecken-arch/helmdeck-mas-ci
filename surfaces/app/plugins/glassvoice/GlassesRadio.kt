package app.helmdeck.glasses

import android.util.Log
import java.util.concurrent.atomic.AtomicReference

/**
 * ONE OWNER for the glasses' Bluetooth radio.
 *
 * THIS IS A MEASURED LAW, NOT A STYLE CHOICE, and it is enforced here in code
 * rather than asked for in a comment - the same reason /glance/talk passes
 * `allow_actions=false` as a parameter instead of requesting it in a prompt: a
 * boundary belongs in the type system, not in prose someone may not read.
 *
 * WHAT THE LAW IS (ops/docs/glasses-reference.md §12.4, re-verified 2026-08-21
 * against Meta's own docs and meta-wearables-dat-android Discussion #130):
 *
 *   The DAT camera feed runs over a Bluetooth data link. Opening the glasses
 *   microphone for speech opens a SECOND link (HFP/SCO), and - quoting the Meta
 *   collaborator on that thread - "SCO reserves fixed, periodic time slots on
 *   the radio, which reduces the throughput available to the video data link."
 *   The glasses then end the session themselves with SESSION_ENDED_BY_DEVICE.
 *
 * It is NOT a bug we can code around. The same code measured a stable ~5.5
 * minute session on a Galaxy A25 and a 200 MILLISECOND session death on a
 * Redmi 10, because handset SoC vendors time-slice Bluetooth differently. And
 * Android gets no escape hatch: DAT 0.8+ moved video to WiFi on iOS ONLY.
 *
 * There is a second, older reason pointing the same way (§3.1): HFP and A2DP
 * are mutually exclusive, so while the mic is open ALL glasses audio output
 * collapses to 8 kHz telephone quality. Meta states this themselves.
 *
 * So: MIC and CAMERA are mutually exclusive MODES. Whoever asks second is
 * refused, and the refusal is a normal return value - never an exception, and
 * never a silent overwrite that would leave two owners believing they hold the
 * radio.
 *
 * WHY AN OBJECT AND NOT A LOCK PER SERVICE. The two consumers are separate
 * Android Services in the same process (GlassVoiceService, GlassCameraService),
 * so a process-wide arbiter is exactly the right scope. It is the same shape -
 * and the same caveat - as the daemon's desktop-control lock (debt
 * `desktop-lock-heuristic`): correct because there is one process. If this app
 * ever runs these in separate processes, this must become a durable claim
 * rather than an in-memory one.
 */
object GlassesRadio {

    private const val TAG = "GlassesRadio"

    enum class Mode { MIC, CAMERA }

    /** Null = free. AtomicReference so the two services never race. */
    private val holder = AtomicReference<Mode?>(null)

    /** Who holds it right now, for a UI that must explain a refusal. */
    val current: Mode? get() = holder.get()

    /**
     * Claim the radio for [mode]. Returns false when the OTHER mode holds it.
     *
     * Re-claiming the mode you already hold SUCCEEDS: a service that is
     * restarted by START_STICKY, or a second listen within one voice session,
     * must not deadlock itself out of a resource it already owns.
     */
    fun acquire(mode: Mode): Boolean {
        // compareAndSet from free is the normal path.
        if (holder.compareAndSet(null, mode)) {
            Log.i(TAG, "acquired by $mode")
            return true
        }
        val held = holder.get()
        if (held == mode) return true          // re-entrant, same owner
        Log.w(TAG, "REFUSED $mode - $held holds the radio (glasses-reference 12.4)")
        return false
    }

    /**
     * Give it back. Only the holder may release, so a late teardown from the
     * mode that already lost the radio cannot free it out from under the new
     * owner - the exact shape of GlassVoiceService.releaseMic()'s own guard,
     * which refuses to clear a communication route it never made.
     */
    fun release(mode: Mode) {
        if (holder.compareAndSet(mode, null)) {
            Log.i(TAG, "released by $mode")
        } else {
            Log.d(TAG, "release($mode) ignored - holder is ${holder.get()}")
        }
    }

    /** Test/teardown escape hatch. Not for production paths. */
    fun forceClear() {
        holder.set(null)
    }
}
