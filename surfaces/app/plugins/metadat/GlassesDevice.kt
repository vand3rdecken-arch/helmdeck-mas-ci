package app.helmdeck.glasses

import android.content.Context
import android.util.Log
import com.meta.wearable.dat.core.Wearables
import com.meta.wearable.dat.core.types.LinkState
import com.meta.wearable.dat.core.types.WearablesError

/**
 * WHICH glasses are on the owner's face, and what they can do.
 *
 * This exists because HelmDeck now ships for BOTH shapes of Meta eyewear and
 * they are not the same product:
 *
 *   - DISPLAY (Meta Ray-Ban Display): has a lens screen, so GLASS MODE - the
 *     `surfaces/glasses/` webapp, the tappable question, the blocker list - is real.
 *   - NON-DISPLAY (Ray-Ban Meta gen 1/2, Oakley HSTN/Vanguard, Optics): no
 *     screen at all. Everything visual is meaningless; the whole product
 *     surface is AUDIO (spoken blockers, talk to Henry) plus the CAMERA.
 *
 * Both have microphones, speakers and a camera. Only one has a lens. So the
 * split is not "supported vs unsupported" - it is which surface to use.
 *
 * DERIVED FROM THE RUNTIME, NEVER ASSUMED - the Paseo law in CLAUDE.md ("load-
 * bearing state is DERIVED and VERIFIED from the runtime's own signals, never
 * assumed from a stored flag"). The obvious wrong implementation is a hardcoded
 * list of model names, which rots the day Meta ships a new frame. The SDK
 * answers this itself: `Device.isDisplayCapable()` and
 * `DeviceType.isDisplayCapable()` are real methods on DAT 0.9.0 (read out of
 * mwdat-core-0.9.0.aar with javap, not guessed), so we ASK rather than infer.
 * A device type we have never heard of therefore still answers correctly.
 *
 * FAILS TO "NO GLASSES", NEVER TO A GUESS. Every failure - SDK not initialised,
 * nothing paired, an exception from the SDK - returns null. A caller must treat
 * null as "cannot know", not as "no display": announcing to a lens that is not
 * there is a silent dead end, and it is the exact failure shape the glasses
 * work keeps re-learning.
 */
object GlassesDevice {

    private const val TAG = "GlassesDevice"

    /**
     * ⚠ THE OTHER HALF OF THE tools:overrideLibrary DECISION (withMetaDat.js).
     *
     * Both mwdat-core and mwdat-camera 0.9.0 declare minSdkVersion 29, and this
     * app ships minSdk 24. Rather than drop every Android 7-9 user from the
     * whole product for a glasses feature, the manifest merger is overridden -
     * and Android's own warning for that override is "may lead to runtime
     * failures". That warning is correct, and THIS is what makes it untrue for
     * us: no DAT class is ever touched below API 29.
     *
     * It works because ART resolves a class on FIRST USE. As long as every
     * entry point checks here first, an API 24 device never loads a single
     * com.meta.wearable class and cannot fail on one. Any new entry point into
     * the SDK must call [supported] before anything else - that is the whole
     * contract.
     */
    const val MIN_SDK = 29

    /** True when this device can run the DAT SDK at all. */
    fun supported(): Boolean = android.os.Build.VERSION.SDK_INT >= MIN_SDK

    /**
     * @param name          the device's own name, for a UI that should say
     *                      "Ray-Ban Display" rather than "glasses"
     * @param type          the DeviceType enum name (RAYBAN_META,
     *                      META_RAYBAN_DISPLAY, OAKLEY_META_VANGUARD, …)
     * @param displayCapable THE question this class exists to answer
     * @param connected     link state is CONNECTED right now
     */
    data class Info(
        val name: String,
        val type: String,
        val displayCapable: Boolean,
        val connected: Boolean,
    )

    /**
     * The first known device, or null.
     *
     * Deliberately "first" and not "all": DAT sessions are single-device
     * (AutoDeviceSelector picks one eligible device) and HelmDeck is explicitly
     * a ONE-DEVICE product - glasses-reference §11.1, where the multi-device
     * ticket registry was scrapped precisely because there is no fleet. If that
     * ever changes, this returns a list and the callers grow a picker; until
     * then a list would be a fiction with one element.
     */
    /**
     * Bring the SDK up, tolerating the case that it already is.
     *
     * ⚠ THE TRAP, and it is not obvious from the call site. `Wearables.initialize()`
     * returns a DatResult, and `WearablesError` has exactly TWO values:
     * NOT_INITIALIZED and **ALREADY_INITIALIZED**. So the second call in a
     * process - which is the NORMAL case the moment two entry points exist, as
     * they now do (this object and GlassCameraService) - comes back as a
     * FAILURE. Treating `isFailure` as fatal would mean the camera works
     * exactly once per process and then silently refuses, or never works at all
     * if something asked about the device first. Read from the real 0.9.0
     * enum, not assumed.
     *
     * So the only true failure here is a *different* error, or a throw.
     */
    fun ensureInitialized(context: Context): Boolean {
        // BEFORE any DAT symbol is referenced - see MIN_SDK. This early return
        // is what keeps `Wearables` out of the verifier's way on an old device.
        if (!supported()) return false
        return try {
            val r = Wearables.initialize(context.applicationContext)
            r.isSuccess || r.errorOrNull() == WearablesError.ALREADY_INITIALIZED
        } catch (t: Throwable) {
            Log.d(TAG, "initialize: ${t.javaClass.simpleName}: ${t.message}")
            false
        }
    }

    fun current(context: Context): Info? {
        if (!supported()) return null
        return try {
            // Calling this here means a caller that only wants to ASK does not
            // have to know the SDK's lifecycle.
            if (!ensureInitialized(context)) {
                Log.d(TAG, "SDK not available")
                return null
            }
            val meta = Wearables.devicesMetadata
            if (meta.isEmpty()) return null
            val device = meta.values.firstOrNull()?.value ?: return null
            Info(
                name = device.name,
                type = device.deviceType.name,
                // The SDK's OWN answer. Not a model-name match.
                displayCapable = device.isDisplayCapable(),
                connected = device.linkState == LinkState.CONNECTED,
            )
        } catch (t: Throwable) {
            // The DAT app or the Meta AI app can be missing entirely, which
            // surfaces as a linkage error rather than a tidy result.
            Log.d(TAG, "current(): ${t.javaClass.simpleName}: ${t.message}")
            null
        }
    }

    /**
     * Convenience for the one branch most callers actually want.
     *
     * Returns false when there are no glasses OR when they have no lens - both
     * mean "do not route this to a screen". The caller that needs to tell those
     * two apart should use [current] and look at null vs displayCapable.
     */
    fun hasLens(context: Context): Boolean = current(context)?.displayCapable == true
}
