package app.helmdeck.glassesbridge

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Build
import expo.modules.kotlin.exception.Exceptions
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition

/**
 * The JS -> native seam for the glasses.
 *
 * WHY THIS EXISTS. GlassVoiceService and GlassCameraService were complete,
 * compiled, present in the APK - and DEAD, because nothing in surfaces/app/src could
 * start an Android Service. ops/docs/glasses-reference.md §11.6 recorded that
 * ("never started by anything") for the voice half long before the camera half
 * repeated it. This is the missing half.
 *
 * ⚠ WHY SERVICES ARE STARTED BY ComponentName AND NOT BY CLASS REFERENCE.
 * This is a separate Gradle module. The dependency direction is app -> module,
 * so this module CANNOT see app.helmdeck.voice.GlassVoiceService or
 * app.helmdeck.glasses.GlassCameraService - referencing them would not compile.
 * Naming them as strings on an explicit ComponentName is not a shortcut around
 * that, it is the supported way to address a component in your OWN package from
 * a library module, and it keeps the module free of any dependency on the app.
 *
 * The cost is real and is worth stating: a renamed service class becomes a
 * runtime no-op instead of a compile error. That is why the names live in one
 * const block here, and why withGlassVoice.js / withMetaDat.js declare the very
 * same strings in the manifest - a mismatch is caught by
 * ops/tests/test_meta_dat_plugin.js, which asserts the manifest name and the Kotlin
 * class agree.
 *
 * CAPABILITY IS ANSWERED, NEVER ASSUMED (CLAUDE.md's Paseo law). `supported()`
 * reports the API floor so the JS can hide a control that cannot work, rather
 * than offering a button that silently does nothing - the failure shape this
 * whole layer keeps re-learning.
 */
class GlassesBridgeModule : Module() {

  companion object {
    // Mirrored in app/plugins/withGlassVoice.js and withMetaDat.js. Changing
    // one without the others is a runtime no-op - see the header.
    private const val VOICE_SERVICE = "app.helmdeck.voice.GlassVoiceService"
    private const val CAMERA_SERVICE = "app.helmdeck.glasses.GlassCameraService"

    private const val ACTION_LISTEN = "app.helmdeck.voice.LISTEN"
    private const val ACTION_LISTEN_PHONE_MIC = "app.helmdeck.voice.LISTEN_PHONE_MIC"
    private const val ACTION_VOICE_STOP = "app.helmdeck.voice.STOP"
    private const val ACTION_CAPTURE = "app.helmdeck.glasses.CAPTURE"
    private const val ACTION_CAMERA_STOP = "app.helmdeck.glasses.CAMERA_STOP"

    /** Shared prefs both services read for their daemon target. */
    private const val PREFS = "helmdeck_glass_voice"
    private const val KEY_BASE = "base_url"
    private const val KEY_TOKEN = "glance_token"

    /** DAT's floor - see GlassesDevice.MIN_SDK. The camera needs API 29. */
    private const val DAT_MIN_SDK = 29
  }

  private val context: Context
    get() = appContext.reactContext ?: throw Exceptions.ReactContextLost()

  private fun start(service: String, action: String, extras: Map<String, String> = emptyMap()) {
    val intent = Intent(action).apply {
      component = ComponentName(context.packageName, service)
      extras.forEach { (k, v) -> putExtra(k, v) }
    }
    // Both are foreground services (typed: microphone / connectedDevice), so on
    // O+ they MUST be started with startForegroundService or the system kills
    // the start outright.
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
      context.startForegroundService(intent)
    } else {
      context.startService(intent)
    }
  }

  override fun definition() = ModuleDefinition {
    Name("GlassesBridge")

    /**
     * Where the services should reach the daemon. Written at PAIRING time by
     * the JS, because the services run outside React and cannot read the app's
     * JS-side config - the reason the reference doc listed "nothing writes
     * base_url/glance_token" as its own open gap.
     */
    Function("configure") { baseUrl: String, token: String ->
      context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        .edit()
        .putString(KEY_BASE, baseUrl.trimEnd('/'))
        .putString(KEY_TOKEN, token)
        .apply()
      true
    }

    /** True when the DAT camera can run at all on this handset (API >= 29). */
    Function("cameraSupported") {
      Build.VERSION.SDK_INT >= DAT_MIN_SDK
    }

    /**
     * Listen and send the transcript to Henry.
     *
     * `useGlassMic=false` keeps the phone's own microphone and leaves the
     * glasses on A2DP, so the spoken answer comes back in music quality rather
     * than 8 kHz telephone quality - glasses-reference §3.1. That is a real
     * trade the owner makes per turn, so it is a parameter and not a setting.
     */
    Function("listen") { useGlassMic: Boolean ->
      start(VOICE_SERVICE, if (useGlassMic) ACTION_LISTEN else ACTION_LISTEN_PHONE_MIC)
      true
    }

    Function("stopListening") {
      start(VOICE_SERVICE, ACTION_VOICE_STOP)
      true
    }

    /**
     * One photo from the glasses, attached to [cardId].
     *
     * The card is REQUIRED all the way down: POST /glance/photo refuses without
     * it and GlassCameraService refuses before opening the camera, because
     * silently attaching a photo of the owner's room to the wrong card cannot
     * be undone. Rejected here too so the round trip is not even started.
     */
    Function("capture") { cardId: String ->
      if (cardId.isBlank()) return@Function false
      start(CAMERA_SERVICE, ACTION_CAPTURE, mapOf("card" to cardId))
      true
    }

    Function("stopCamera") {
      start(CAMERA_SERVICE, ACTION_CAMERA_STOP)
      true
    }
  }
}
