package app.helmdeck.voice

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.media.MediaPlayer
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.util.Log
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.Locale

/**
 * Talk to HENRY through the glasses' microphone.
 *
 * WHY THERE IS NO META SDK HERE. The Ray-Ban Display mic is an ordinary
 * Bluetooth headset mic: android-dat-research.md finding 2, adversarially
 * verified 3-0, says it is "Bluetooth HFP, 8 kHz mono only, routed with standard
 * Android 12+ APIs (setCommunicationDevice(TYPE_BLUETOOTH_SCO) +
 * MODE_IN_COMMUNICATION) - NOT a DAT API". mwdat-core carries zero audio classes
 * and Meta ships no audio artifact at all. So: no DAT, no GitHub PAT, no Meta
 * approval - just AudioManager.
 *
 * THE ONE RULE THAT SHAPES THE WHOLE FLOW: HFP and A2DP are mutually exclusive
 * (finding 3). While the mic is open, ALL glasses audio output collapses to
 * telephone quality. So the loop is strictly
 *
 *     listen  ->  RELEASE the mic  ->  then speak
 *
 * and never both at once. releaseMic() actively tears the SCO route down rather
 * than merely stopping the read, which is why the app holds
 * MODIFY_AUDIO_SETTINGS. Speaking while still routed would technically work and
 * would sound like a bad phone call - the failure would be blamed on the TTS,
 * not on the routing, which is exactly why it is written down here.
 *
 * DEFENSIVE BY DEFAULT (glasses-reference 2.6): every peripheral call is wrapped
 * in safe{} because one bad sensor must never kill the service, and a head-worn
 * surface has no good way to show a stack trace.
 */
class GlassVoiceService : Service() {

    companion object {
        private const val TAG = "GlassVoice"
        private const val CHANNEL = "glass_voice"
        private const val NOTIF_ID = 4711
        const val ACTION_LISTEN = "app.helmdeck.voice.LISTEN"
        const val ACTION_STOP = "app.helmdeck.voice.STOP"
        /**
         * Listen on the PHONE's microphone and leave the glasses on A2DP, so the
         * answer comes back in music quality instead of telephone quality.
         *
         * WHY THIS EXISTS - the correction, 2026-08-21. The rule we wrote down as
         * "HFP and A2DP are mutually exclusive, so listening degrades speaking"
         * is true, but it was recorded with a scope it never had. AOSP says
         * exactly when it applies: audiopolicy `Engine.cpp`, STRATEGY_PHONE,
         * `// Do not use A2DP devices when in call` - and it then REMOVES the
         * A2DP outputs. What counts as "in call" is MODE_IN_COMMUNICATION.
         *
         * Which is a mode this very service asks for, in routeToGlasses(), to
         * reach the GLASSES microphone over SCO. So the quality collapse is the
         * documented consequence of a routing choice we make - not a property of
         * wanting to listen. Ask for neither and both stay: the recogniser takes
         * the built-in mic, and A2DP is never torn down.
         *
         * The trade is real and is the owner's to make, which is why this is a
         * second action rather than a silent change of behaviour: the glasses'
         * 5-mic beamforming array is better than a phone in a pocket. Use this
         * when the phone is in hand or on a desk; use ACTION_LISTEN when it is
         * not.
         */
        const val ACTION_LISTEN_PHONE_MIC = "app.helmdeck.voice.LISTEN_PHONE_MIC"
        /** Written by the RN app (data/config) so the service needs no rebuild to retarget. */
        const val PREFS = "helmdeck_glass_voice"
        const val KEY_BASE = "base_url"
        const val KEY_TOKEN = "glance_token"
    }

    private var recognizer: SpeechRecognizer? = null
    private var player: MediaPlayer? = null
    private var savedMode = AudioManager.MODE_NORMAL
    /** Which microphone the LAST start actually got - derived from the routing
     *  call's own answer, shown to the owner, never guessed from the request. */
    private var micInUse = "Telefon"
    private val main = Handler(Looper.getMainLooper())

    private val audio: AudioManager
        get() = getSystemService(Context.AUDIO_SERVICE) as AudioManager

    private val prefs: SharedPreferences
        get() = getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    /** One bad peripheral call must never take the service down. */
    private inline fun safe(what: String, block: () -> Unit) {
        try {
            block()
        } catch (t: Throwable) {
            Log.w(TAG, "safe($what): ${t.javaClass.simpleName}: ${t.message}")
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    /**
     * Do we hold the microphone permission RIGHT NOW?
     *
     * This is not a nicety, it is the other half of the narrow-FGS decision.
     * glasses-reference 3.4 states the rule as "either grant everything before
     * Start, or declare narrowly - pick one and write it down". This service
     * declares narrowly (foregroundServiceType=microphone), and the price of
     * that choice is that on Android 14+ `startForeground` with a microphone
     * type THROWS SecurityException when RECORD_AUDIO is not held. Unguarded,
     * the very first launch before the owner grants the permission would take
     * the service down with a crash, which is precisely the class of failure
     * commit a722c49 chased in the reference project.
     *
     * Verified-by-absence caveat, stated honestly: the service is
     * exported="false" (correct - no other app may start a mic service), so
     * this path could NOT be exercised from adb. It is defended by construction
     * rather than by test, and the first real on-device start is what will
     * confirm it.
     */
    private fun hasMicPermission(): Boolean =
        checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) ==
            android.content.pm.PackageManager.PERMISSION_GRANTED

    override fun onCreate() {
        super.onCreate()
        if (!hasMicPermission()) {
            // Stop cleanly instead of crashing. The owner grants the permission
            // in the app, then starts voice mode again.
            Log.w(TAG, "RECORD_AUDIO not granted - refusing to start the mic service")
            stopSelf()
            return
        }
        safe("foreground") { startForeground(NOTIF_ID, notification("Bereit")) }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // Re-checked here too, not just in onCreate: START_STICKY means Android
        // can restart this service later, by which time the owner may have
        // revoked the permission in Settings.
        if (!hasMicPermission()) { stopSelf(); return START_NOT_STICKY }
        when (intent?.action) {
            ACTION_STOP -> { safe("stop") { releaseMic(); stopSelf() } }
            ACTION_LISTEN_PHONE_MIC -> safe("listen-phone") { startListening(useGlassMic = false) }
            else -> safe("listen") { startListening(useGlassMic = true) }
        }
        // START_STICKY: the point of a foreground service is surviving the moment
        // the owner looks at the lens instead of the phone.
        return START_STICKY
    }

    override fun onDestroy() {
        safe("destroy-mic") { releaseMic() }
        safe("destroy-rec") { recognizer?.destroy(); recognizer = null }
        safe("destroy-play") { player?.release(); player = null }
        super.onDestroy()
    }

    // ---- notification -----------------------------------------------------

    private fun notification(text: String): Notification {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            safe("channel") {
                nm.createNotificationChannel(
                    NotificationChannel(CHANNEL, "Henry (Sprache)",
                        NotificationManager.IMPORTANCE_LOW)
                )
            }
        }
        val b = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
            Notification.Builder(this, CHANNEL) else @Suppress("DEPRECATION") Notification.Builder(this)
        return b.setContentTitle("Henry")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setOngoing(true)
            .build()
    }

    private fun say(text: String) = safe("notify") {
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.notify(NOTIF_ID, notification(text))
    }

    // ---- the microphone route --------------------------------------------

    /**
     * Point the input at the GLASSES rather than the phone.
     *
     * API 31+ has setCommunicationDevice; below that the only route is the
     * deprecated startBluetoothSco(). minSdk here is 24, so both paths exist -
     * dropping the old one would silently record from the PHONE mic on an older
     * device, which is worse than failing, because it works just badly enough
     * that nobody investigates.
     */
    private fun routeToGlasses(): Boolean {
        var ok = false
        safe("route") {
            savedMode = audio.mode
            audio.mode = AudioManager.MODE_IN_COMMUNICATION
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val sco = audio.availableCommunicationDevices.firstOrNull {
                    it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO
                }
                if (sco != null) ok = audio.setCommunicationDevice(sco)
                if (!ok) Log.w(TAG, "no BLUETOOTH_SCO comm device - are the glasses paired?")
            } else {
                @Suppress("DEPRECATION")
                run { audio.isBluetoothScoOn = true; audio.startBluetoothSco(); ok = true }
            }
        }
        return ok
    }

    /**
     * THE half that is easy to forget. Not "stop reading" - actually give the
     * route back, or A2DP never returns and Henry answers in 8 kHz telephone
     * quality (see the class comment).
     */
    private fun releaseMic() {
        safe("rec-cancel") { recognizer?.cancel() }
        // Only undo a route we actually made. clearCommunicationDevice() and a
        // mode write are GLOBAL: calling them after a phone-mic turn would yank
        // the audio route out from under whatever else on the device happens to
        // be in a call, to undo something we never did.
        if (micInUse != "Brille") return
        micInUse = "Telefon"
        safe("unroute") {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                audio.clearCommunicationDevice()
            } else {
                @Suppress("DEPRECATION")
                run { audio.stopBluetoothSco(); audio.isBluetoothScoOn = false }
            }
            audio.mode = savedMode
        }
    }

    // ---- listen -----------------------------------------------------------

    private fun startListening(useGlassMic: Boolean) {
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            say("Spracherkennung nicht verfügbar")
            return
        }
        // OBSERVED, not assumed (the Paseo rule). routeToGlasses() returned a
        // boolean nobody read, so a silent failure to reach the SCO device was
        // indistinguishable from success - the owner would simply have been
        // recorded by the phone while believing the glasses were listening.
        // Now the notification says which microphone is actually live, which is
        // also the only way this can be checked on a device the developer does
        // not have.
        val onGlasses = if (useGlassMic) routeToGlasses() else false
        micInUse = if (onGlasses) "Brille" else "Telefon"
        safe("recognizer") {
            recognizer?.destroy()
            recognizer = SpeechRecognizer.createSpeechRecognizer(this).apply {
                setRecognitionListener(listener)
            }
            val i = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                          RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                .putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault().toLanguageTag())
                .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, false)
            recognizer?.startListening(i)
            say("Hört zu… (Mikro: $micInUse)")
        }
    }

    private val listener = object : RecognitionListener {
        override fun onReadyForSpeech(params: Bundle?) {}
        override fun onBeginningOfSpeech() {}
        override fun onRmsChanged(rmsdB: Float) {}
        override fun onBufferReceived(buffer: ByteArray?) {}
        override fun onEndOfSpeech() {}
        override fun onEvent(eventType: Int, params: Bundle?) {}
        override fun onPartialResults(partialResults: Bundle?) {}

        override fun onError(error: Int) {
            // A denial is a RESULT, not a crash - release the route either way,
            // otherwise a failed recognition leaves the glasses stuck in HFP.
            releaseMic()
            say("Nicht verstanden ($error)")
        }

        override fun onResults(results: Bundle?) {
            val text = results
                ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                ?.firstOrNull()
                .orEmpty()
            // RELEASE BEFORE SPEAKING - the whole reason this class exists.
            releaseMic()
            if (text.isBlank()) { say("Nichts gehört"); return }
            say("…$text")
            Thread { ask(text) }.start()      // never network on the main thread
        }
    }

    // ---- ask Henry, then play his answer ---------------------------------

    private fun ask(transcript: String) {
        val base = prefs.getString(KEY_BASE, "").orEmpty().trimEnd('/')
        val token = prefs.getString(KEY_TOKEN, "").orEmpty()
        if (base.isEmpty() || token.isEmpty()) {
            main.post { say("Nicht verbunden - in HelmDeck koppeln") }
            return
        }
        var reply = ""
        var voiceUrl: String? = null
        safe("post") {
            val c = (URL("$base/glance/talk").openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                doOutput = true
                connectTimeout = 15000
                readTimeout = 120000          // an agent turn is not a web request
                setRequestProperty("Content-Type", "application/json")
            }
            val body = JSONObject()
                .put("token", token)
                .put("message", transcript)
                .toString()
            c.outputStream.use { it.write(body.toByteArray()) }
            val code = c.responseCode
            val stream = if (code in 200..299) c.inputStream else c.errorStream
            val raw = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            val j = JSONObject(raw)
            if (code !in 200..299) {
                reply = j.optString("error", "Fehler $code")
            } else {
                reply = j.optString("reply")
                if (j.has("voice") && !j.isNull("voice")) voiceUrl = j.optString("voice")
            }
        }
        main.post {
            say(if (reply.isBlank()) "Keine Antwort" else reply.take(60))
            voiceUrl?.let { speak(base + it) }
        }
    }

    /**
     * Henry, out loud. The lens has no speechSynthesis (measured on-device), so
     * the daemon renders the sentence and this just plays the clip - the same
     * split docs/glasses-reference 11.6 describes.
     */
    private fun speak(url: String) = safe("play") {
        player?.release()
        player = MediaPlayer().apply {
            setDataSource(url)
            setOnCompletionListener { safe("play-done") { it.release() }; player = null }
            setOnErrorListener { mp, _, _ -> safe("play-err") { mp.release() }; player = null; true }
            prepareAsync()
            setOnPreparedListener { it.start() }
        }
    }
}
