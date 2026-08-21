package app.helmdeck.glasses

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.os.Build
import android.os.IBinder
import android.util.Base64
import android.util.Log
import com.meta.wearable.dat.camera.Camera
import com.meta.wearable.dat.camera.addCamera
import com.meta.wearable.dat.camera.removeCamera
import com.meta.wearable.dat.camera.types.PhotoData
import com.meta.wearable.dat.camera.types.StreamConfiguration
import com.meta.wearable.dat.camera.types.VideoQuality
import com.meta.wearable.dat.core.Wearables
import com.meta.wearable.dat.core.selectors.AutoDeviceSelector
import com.meta.wearable.dat.core.session.DeviceSession
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer

/**
 * The GLASSES CAMERA, via Meta's Device Access Toolkit.
 *
 * WRITTEN AGAINST THE REAL 0.9.0 API, NOT AGAINST THE DOCS. Every symbol used
 * here was read out of the actual AARs (`javap` over mwdat-core-0.9.0.jar and
 * mwdat-camera-0.9.0.jar, fetched 2026-08-21) rather than copied from a
 * tutorial, because Meta's published samples move faster than their docs and
 * the docs were already wrong about the token (§12.1b). The shape is:
 *
 *     Wearables.initialize(context): DatResult<Unit, WearablesError>
 *     Wearables.createSession(DeviceSelector): DatResult<DeviceSession, DeviceSessionError>
 *     session.start() / session.stop() / session.state: StateFlow<DeviceSessionState>
 *     session.addCamera(StreamConfiguration): DatResult<Camera, DeviceSessionError>   // extension
 *     camera.stream: Stream
 *     stream.start(): DatResult<Unit, StreamError>
 *     stream.capturePhoto(): DatResult<PhotoData, CaptureError>                        // suspend
 *     PhotoData is SEALED: PhotoData.Bitmap(bitmap) | PhotoData.HEIC(data: ByteBuffer)
 *
 * ⚠ UNCOMPILED. An APK cannot be built from a card worktree (DEPLOY.md §2, NDK
 * path length), so this has never been through kotlinc. The API surface is
 * measured and the control flow is deliberately small, but treat the first real
 * build as the first test.
 *
 * WHY A PHOTO AND NOT A VIDEO STREAM. HelmDeck's use for the camera is "what am
 * I looking at" attached to a card - a single frame, on demand. Continuous
 * video is where every failure in Discussion #130 lives (sustained Bluetooth
 * throughput, thermals, battery, SESSION_ENDED_BY_DEVICE), and it buys a board
 * assistant nothing over one good frame. `capturePhoto()` is therefore the
 * primary verb; the stream is started only because the SDK requires a running
 * stream to capture from, and is stopped immediately afterwards.
 *
 * THE RADIO LAW. This service takes GlassesRadio.CAMERA before it touches the
 * SDK and gives it back in every exit path. If the microphone holds the radio,
 * this REFUSES rather than racing it - see GlassesRadio for why that is a
 * measured constraint and not caution.
 */
class GlassCameraService : Service() {

    companion object {
        private const val TAG = "GlassCamera"
        private const val CHANNEL = "glass_camera"
        private const val NOTIF_ID = 4712

        /** Capture one photo from the glasses and hand it to the daemon. */
        const val ACTION_CAPTURE = "app.helmdeck.glasses.CAPTURE"
        const val ACTION_STOP = "app.helmdeck.glasses.CAMERA_STOP"

        /** Shared with the voice service - written by the RN app at pairing. */
        const val PREFS = "helmdeck_glass_voice"
        const val KEY_BASE = "base_url"
        const val KEY_TOKEN = "glance_token"

        /**
         * LOW / 15 fps, and compressed. Straight from the Discussion #130
         * mitigations: the lower the video demand, the less it starves the
         * Bluetooth link. We only need one frame, so there is nothing to gain
         * from HIGH and a measured amount to lose.
         */
        private val STREAM_CONFIG = StreamConfiguration(VideoQuality.LOW, 15, true)

        /** A DAT session that has not produced a photo in this long is stuck. */
        private const val CAPTURE_TIMEOUT_MS = 30_000L
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var session: DeviceSession? = null
    private var camera: Camera? = null

    override fun onBind(intent: Intent?): IBinder? = null

    /** One bad SDK call must never take the service down (§2.6). */
    private inline fun safe(what: String, block: () -> Unit) {
        try {
            block()
        } catch (t: Throwable) {
            Log.w(TAG, "safe($what): ${t.javaClass.simpleName}: ${t.message}")
        }
    }

    override fun onCreate() {
        super.onCreate()
        safe("foreground") { startForeground(NOTIF_ID, notification("Bereit")) }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> { teardown(); stopSelf() }
            else -> scope.launch { capture() }
        }
        // NOT sticky, unlike the voice service: a photo is a one-shot the owner
        // asked for. Silently re-running a capture after the OS restarts this
        // service would take a picture nobody requested - on a head-worn camera
        // that is a privacy event, not a retry.
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        teardown()
        safe("scope") { scope.cancel() }
        super.onDestroy()
    }

    // ---- notification -----------------------------------------------------

    private fun notification(text: String): Notification {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            safe("channel") {
                nm.createNotificationChannel(
                    NotificationChannel(CHANNEL, "Henry (Kamera)", NotificationManager.IMPORTANCE_LOW)
                )
            }
        }
        val b = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
            Notification.Builder(this, CHANNEL) else @Suppress("DEPRECATION") Notification.Builder(this)
        return b.setContentTitle("Henry")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .setOngoing(true)
            .build()
    }

    private fun say(text: String) = safe("notify") {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.notify(NOTIF_ID, notification(text))
    }

    // ---- the capture ------------------------------------------------------

    private suspend fun capture() {
        // API FLOOR FIRST, before even the radio: DAT needs API 29 and the
        // manifest merger is overridden to allow this app's minSdk 24 (see
        // GlassesDevice.MIN_SDK). Touching any com.meta.wearable class below 29
        // is exactly the "runtime failure" that override is warned about, so
        // this check comes before anything that could load one.
        if (!GlassesDevice.supported()) {
            say("Brillen-Kamera braucht Android 10")
            stopSelf()
            return
        }
        // THE RADIO LAW SECOND - before a single SDK call, so a refusal costs
        // nothing and cannot half-open a session.
        if (!GlassesRadio.acquire(GlassesRadio.Mode.CAMERA)) {
            say("Mikrofon aktiv - Kamera nicht möglich")
            stopSelf()
            return
        }
        try {
            // NOT `if (initialize().isFailure)` - ALREADY_INITIALIZED is one of
            // only two WearablesError values, so the second call in a process
            // legitimately "fails". See GlassesDevice.ensureInitialized.
            if (!GlassesDevice.ensureInitialized(applicationContext)) {
                fail("SDK-Init fehlgeschlagen")
                return
            }
            // AutoDeviceSelector picks the eligible paired device. NO_ELIGIBLE_DEVICE
            // here is the ordinary "glasses not connected" case, not an error to
            // report as a crash.
            val made = Wearables.createSession(AutoDeviceSelector())
            val s = made.getOrNull()
            if (s == null) {
                fail(describe(made.errorOrNull()?.description))
                return
            }
            session = s
            s.start()

            val added = s.addCamera(STREAM_CONFIG)
            val cam = added.getOrNull()
            if (cam == null) {
                fail(describe(added.errorOrNull()?.description))
                return
            }
            camera = cam

            val stream = cam.stream
            val started = stream.start()
            if (started.isFailure) {
                fail("Stream: ${started.errorOrNull()?.description ?: "?"}")
                return
            }
            say("Aufnahme…")

            // BOUNDED. A DAT session can sit in STARTING forever when the link
            // is bad (§3.1: "the API never tells you WHY a transition
            // happened"), and a foreground service that waits forever is a
            // battery bug the owner will blame on the glasses.
            val shot = withTimeoutOrNull(CAPTURE_TIMEOUT_MS) { stream.capturePhoto() }
            if (shot == null) {
                fail("Zeitüberschreitung")
                return
            }
            val photo = shot.getOrNull()
            if (photo == null) {
                fail("Aufnahme: ${shot.errorOrNull()?.description ?: "?"}")
                return
            }
            val jpeg = encode(photo)
            if (jpeg == null) {
                fail("Bild nicht lesbar")
                return
            }
            say("Senden…")
            post(jpeg)
        } catch (t: Throwable) {
            Log.w(TAG, "capture: ${t.javaClass.simpleName}: ${t.message}")
            fail(t.javaClass.simpleName)
        } finally {
            teardown()
            stopSelf()
        }
    }

    /**
     * SESSION_ENDED_BY_DEVICE deserves its own sentence. It is the single most
     * likely failure here and it is NOT a bug in this code - it is the glasses
     * refusing the combination (§12.4). Saying so is the difference between the
     * owner retrying usefully and the owner filing a ghost bug.
     */
    private fun describe(raw: String?): String = when {
        raw == null -> "Unbekannter Fehler"
        raw.contains("NO_ELIGIBLE_DEVICE") -> "Keine Brille verbunden"
        raw.contains("SESSION_ENDED_BY_DEVICE") ->
            "Brille hat die Sitzung beendet (Funk überlastet)"
        raw.contains("CAPABILITY_DENIED") || raw.contains("PERMISSION") ->
            "Kamera-Freigabe fehlt (Meta AI App)"
        raw.contains("THERMAL") -> "Brille zu warm"
        raw.contains("BATTERY") -> "Brille-Akku zu schwach"
        else -> raw.take(80)
    }

    private fun fail(msg: String) {
        Log.w(TAG, "capture failed: $msg")
        say(msg)
    }

    /**
     * PhotoData is a SEALED interface with exactly two shapes in 0.9.0.
     * Both are handled; an unknown third (a future SDK) returns null rather
     * than guessing, which surfaces as "Bild nicht lesbar" instead of a crash.
     */
    private fun encode(photo: PhotoData): ByteArray? = when (photo) {
        is PhotoData.Bitmap -> bitmapToJpeg(photo.bitmap)
        is PhotoData.HEIC -> bufferToBytes(photo.data)
        else -> null
    }

    private fun bitmapToJpeg(bmp: Bitmap): ByteArray? = try {
        ByteArrayOutputStream().use { out ->
            bmp.compress(Bitmap.CompressFormat.JPEG, 85, out)
            out.toByteArray()
        }
    } catch (t: Throwable) {
        Log.w(TAG, "jpeg: ${t.message}"); null
    }

    private fun bufferToBytes(buf: ByteBuffer): ByteArray? = try {
        val b = buf.duplicate()          // never disturb the SDK's own position
        val out = ByteArray(b.remaining())
        b.get(out)
        out
    } catch (t: Throwable) {
        Log.w(TAG, "heic: ${t.message}"); null
    }

    // ---- hand it to the daemon -------------------------------------------

    /**
     * POSTs the frame to the daemon as base64. Deliberately the SAME
     * prefs/token pair GlassVoiceService already uses, so pairing configures
     * both capabilities at once and there is one credential, not two (§11.1:
     * one device, one glance_token - do NOT re-add a ticket registry).
     *
     * ⚠ The daemon endpoint this targets does NOT exist yet. It is named here
     * so the contract is explicit and reviewable; wiring it is the daemon half
     * of this feature and belongs in the card that can build and test both
     * ends together.
     */
    private fun post(jpeg: ByteArray) {
        val prefs = getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val base = prefs.getString(KEY_BASE, "").orEmpty().trimEnd('/')
        val token = prefs.getString(KEY_TOKEN, "").orEmpty()
        if (base.isEmpty() || token.isEmpty()) {
            say("Nicht verbunden - in HelmDeck koppeln")
            return
        }
        val b64 = Base64.encodeToString(jpeg, Base64.NO_WRAP)
        safe("post") {
            val c = (java.net.URL("$base/glance/photo").openConnection()
                as java.net.HttpURLConnection).apply {
                requestMethod = "POST"
                doOutput = true
                connectTimeout = 15000
                readTimeout = 60000
                setRequestProperty("Content-Type", "application/json")
            }
            val body = org.json.JSONObject()
                .put("token", token)
                .put("mime", "image/jpeg")
                .put("b64", b64)
                .toString()
            c.outputStream.use { it.write(body.toByteArray()) }
            val code = c.responseCode
            say(if (code in 200..299) "Gesendet" else "Fehler $code")
        }
    }

    // ---- teardown ---------------------------------------------------------

    /**
     * Idempotent, and it ALWAYS gives the radio back. The whole point of the
     * arbiter is defeated by one path that forgets - which is exactly the bug
     * GlassVoiceService.releaseMic() exists to prevent on the audio side.
     */
    private fun teardown() {
        safe("camera-stop") { camera?.stop() }
        camera = null
        safe("remove-camera") { session?.removeCamera() }
        safe("session-stop") { session?.stop() }
        session = null
        GlassesRadio.release(GlassesRadio.Mode.CAMERA)
    }
}
