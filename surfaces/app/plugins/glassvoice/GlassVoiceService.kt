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
import app.helmdeck.glasses.GlassesRadio
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
    /**
     * CONVERSATION MODE (owner decree 2026-08-23: no tap per turn, least of all
     * on the glasses). Non-null = we are in a hands-free loop and this is the
     * mic choice to re-listen with after Henry finishes speaking; null = idle.
     * The loop is the speech-to-speech `should_listen` gate mapped onto the
     * strict listen -> release -> speak order this class already enforces:
     * SCO is only ever open while the owner talks, so Henry still answers in
     * A2DP quality. Ends on ACTION_STOP, on MAX_EMPTY consecutive turns where
     * nothing was heard (the owner walked away, not a crash), or on a missing
     * pairing config.
     */
    private var loopMic: Boolean? = null
    private var emptyTurns = 0
    private val MAX_EMPTY = 2

    /**
     * How long we keep asking whether the owner has accepted a draft, in total.
     *
     * Mirrors spine/ops/glassturn.DECIDE_TOTAL_S (150s) - and that is a mirror,
     * not a coincidence, so the two halves of the confirm step give up at the
     * same moment. One request only lasts DECIDE_WAIT_S (~25s, an edge limit -
     * see awaitDecision); this is the human budget spent across however many of
     * those it takes. Long enough to read a sentence, look up, think, and tap.
     */
    private val TOTAL_WAIT_MS = 150_000L
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
            ACTION_STOP -> {
                safe("stop") {
                    loopMic = null           // end the conversation, not just this turn
                    releaseMic()
                    player?.release(); player = null
                    // The owner switched the loop off from the phone. Nothing else
                    // will ever report for this conversation, so clearing the lens
                    // is this path's job - the display must not keep claiming a
                    // microphone the owner just closed.
                    report("idle")
                    stopSelf()
                }
            }
            ACTION_LISTEN_PHONE_MIC -> safe("listen-phone") {
                loopMic = false; emptyTurns = 0; startListening(useGlassMic = false)
            }
            else -> safe("listen") {
                loopMic = true; emptyTurns = 0; startListening(useGlassMic = true)
            }
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
        // OUTSIDE the safe{} above, deliberately: if tearing the audio route
        // down throws, the radio must STILL come back, or one bad unroute
        // locks the camera out for the rest of the process's life.
        GlassesRadio.release(GlassesRadio.Mode.MIC)
    }

    // ---- listen -----------------------------------------------------------

    private fun startListening(useGlassMic: Boolean) {
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            say("Spracherkennung nicht verfügbar")
            // No mic will open on this path and nothing downstream will re-report,
            // so clear the lens here. Both of this function's early returns need
            // this: a previous turn may have left the indicator lit, and "the
            // recogniser is gone" must not read on the display as "still
            // listening".
            report("idle")
            return
        }
        // OBSERVED, not assumed (the Paseo rule). routeToGlasses() returned a
        // boolean nobody read, so a silent failure to reach the SCO device was
        // indistinguishable from success - the owner would simply have been
        // recorded by the phone while believing the glasses were listening.
        // Now the notification says which microphone is actually live, which is
        // also the only way this can be checked on a device the developer does
        // not have.
        // THE RADIO LAW (GlassesRadio / glasses-reference 12.4), and note how
        // NARROW it is on purpose: only the GLASSES mic contends with the
        // camera, because only it opens an HFP/SCO link on the glasses' radio.
        // ACTION_LISTEN_PHONE_MIC stays in MODE_NORMAL and never calls
        // setCommunicationDevice, so it touches nothing the camera is using and
        // must NOT be refused - blocking it would be a guard that costs the
        // owner a working feature to prevent a conflict that cannot occur.
        var onGlasses = false
        if (useGlassMic) {
            if (!GlassesRadio.acquire(GlassesRadio.Mode.MIC)) {
                say("Kamera aktiv - Brillen-Mikro nicht möglich")
                report("idle")               // no mic opened - see above
                return
            }
            onGlasses = routeToGlasses()
            if (!onGlasses) {
                // Claimed the radio but never got the route: give it straight
                // back. releaseMic() below cannot do it for us - it keys off
                // micInUse, which is about to say "Telefon" - so without this
                // the radio would be held by a mic that is not on the glasses.
                GlassesRadio.release(GlassesRadio.Mode.MIC)
            }
        }
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
            // AFTER startListening, and after micInUse was set from the routing
            // call's OWN answer - so the lens is told a mic is open only once one
            // actually is, and is told the right one. Reporting before the start
            // (or from the requested mic rather than the obtained one) would put a
            // green "listening on glasses" on the display while the phone was
            // quietly doing the hearing, which is the class of lie this indicator
            // exists to end.
            report("listening", micWire())
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
            emptyTurn()
        }

        override fun onResults(results: Bundle?) {
            val text = results
                ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                ?.firstOrNull()
                .orEmpty()
            // RELEASE BEFORE SPEAKING - the whole reason this class exists.
            releaseMic()
            if (text.isBlank()) { say("Nichts gehört"); emptyTurn(); return }
            emptyTurns = 0
            say("…$text")
            // THE CONFIRM STEP (owner, 2026-09-04: "wie auf watch erstmal per
            // turn ... user kann bestaetigen oder loeschen und neu sprechen").
            // These words are NOT sent from here any more - they are parked on
            // the lens and only `confirmThenAsk` may promote them to a question,
            // and only after the owner says so.
            Thread { confirmThenAsk(text) }.start()   // never network on the main thread
        }
    }

    // ---- the conversation loop -------------------------------------------

    /**
     * A turn where nothing usable was heard. In conversation mode one silence
     * is normal (thinking, ambient noise cutting out) and re-arms the mic;
     * MAX_EMPTY in a row means the owner is gone, and an open microphone with
     * nobody there is a bug, not a feature - end the conversation.
     */
    private fun emptyTurn() {
        val mic = loopMic ?: return
        emptyTurns += 1
        if (emptyTurns >= MAX_EMPTY) {
            loopMic = null
            say("Gespräch beendet (nichts gehört)")
            // The conversation is over and no further turn will re-report. Say so,
            // or the lens keeps a listening indicator lit over a microphone that
            // has been closed - the same lie in the other direction.
            report("idle")
            stopSelf()
            return
        }
        relisten(mic)
    }

    /** Re-arm the microphone for the next turn - main thread, tiny breather so
     *  the audio route has settled (SCO teardown is asynchronous on some
     *  handsets and an instant re-open can grab the phone mic instead). */
    private fun relisten(mic: Boolean) {
        main.postDelayed({
            if (loopMic != null) safe("relisten") { startListening(useGlassMic = mic) }
        }, 350)
    }

    // ---- the confirm step -------------------------------------------------

    /**
     * SHOW THE WORDS, WAIT FOR THE OWNER, ONLY THEN ASK.
     *
     * Owner decision 2026-09-04: "am besten einfach wie auf watch erstmal per
     * turn. Also user spricht, es wird als text Transkript user kann bestaetigen
     * oder loeschen und neu sprechen."
     *
     * WHY THIS IS BUILT HERE AND IS FREE ON THE WATCH. Wear gets the confirm step
     * from the PLATFORM: HenryScreen launches ACTION_RECOGNIZE_SPEECH and the
     * system dictation UI shows the transcript and takes the accept before ever
     * handing the words back (plugins/wear/HenryScreen.kt:288-302). There is no
     * such activity for the glasses - the display is a webview served by the
     * Worker and this recogniser runs headless in a background service - so the
     * same interaction has to be assembled from the pieces we own: park the words
     * in the turn state, let the lens render them, block until the lens reports
     * a verdict.
     *
     * ⚠ THIS SUPERSEDES THE 2026-08-23 "no tap per turn" DECREE, on the owner's
     * own instruction and only for the SEND. The loop is still hands-free in the
     * sense that mattered - he never taps to START listening and never taps to
     * continue the conversation - but a sentence going to Henry in his name now
     * costs one deliberate tap, because the recogniser is the one part of this
     * chain that can be confidently wrong.
     *
     * FAILS CLOSED, everywhere. The only path that reaches ask() is an explicit
     * "send". A timeout, a superseded turn, an unreachable daemon and a dropped
     * connection all end the turn WITHOUT speaking in the owner's name - the
     * whole point of the step. Losing a sentence costs him a repeat; sending one
     * he did not confirm cannot be taken back.
     */
    private fun confirmThenAsk(transcript: String) {
        val base = prefs.getString(KEY_BASE, "").orEmpty().trimEnd('/')
        val token = prefs.getString(KEY_TOKEN, "").orEmpty()
        if (base.isEmpty() || token.isEmpty()) {
            loopMic = null      // a loop that can never reach Henry must not re-arm
            main.post { say("Nicht verbunden - in HelmDeck koppeln") }
            return
        }
        val seq = postDraft(base, token, transcript)
        if (seq <= 0) {
            // The lens will never show these words, so the owner cannot possibly
            // confirm them. Dropping the turn is the only honest move: sending
            // anyway would be the confirm step failing OPEN.
            main.post { say("Entwurf nicht angekommen - nochmal sprechen") }
            endConversation()
            return
        }
        when (awaitDecision(base, token, seq)) {
            "send" -> ask(transcript)
            "redo" -> {
                // He rejected the transcript. Straight back to the microphone -
                // "loeschen und neu sprechen" is ONE gesture, not two.
                val mic = loopMic
                main.post { say("Nochmal…") }
                if (mic != null) relisten(mic) else endConversation()
            }
            // The turn moved on under us (ACTION_STOP, or a newer draft). Whoever
            // moved it owns what happens next - re-arming here would race them.
            "superseded" -> {}
            // Timed out, or the wait itself failed. Say so and stop: an open
            // conversation nobody is tending is the state this service already
            // refuses to leave behind (see emptyTurn).
            else -> {
                main.post { say("Nicht bestätigt - verworfen") }
                endConversation()
            }
        }
    }

    /** End the conversation and leave NOTHING lit on the lens. Factored out
     *  because three different give-up paths need exactly this pair, and a
     *  give-up that forgot the report is how the display ends up claiming a
     *  microphone that is closed. */
    private fun endConversation() {
        loopMic = null
        report("idle")
        main.post { stopSelf() }
    }

    /**
     * Park the recognised words on the lens. Returns the turn seq they were
     * published as, or 0 when they never landed.
     *
     * The seq is the whole reason this is a separate call from `report`: the wait
     * that follows must be addressed to THIS draft. Without it, a verdict the
     * owner gave about a sentence he rejected could be consumed by the next one -
     * sending words he had just thrown away (spine/ops/glassturn.py `_decision`).
     *
     * Longer timeouts than `report` because this one is LOAD-BEARING: a dropped
     * status ping costs a stale indicator, a dropped draft costs the turn.
     */
    private fun postDraft(base: String, token: String, transcript: String): Int {
        var seq = 0
        safe("draft") {
            val c = (URL("$base/glance/state").openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                doOutput = true
                connectTimeout = 15000
                readTimeout = 15000
                setRequestProperty("Content-Type", "application/json")
            }
            val body = JSONObject()
                .put("token", token)
                .put("state", "draft")
                .put("mic", micWire())
                .put("text", transcript)
                .toString()
            c.outputStream.use { it.write(body.toByteArray()) }
            val code = c.responseCode
            if (code in 200..299) {
                val raw = c.inputStream?.bufferedReader()?.use { it.readText() }.orEmpty()
                seq = JSONObject(raw).optInt("seq", 0)
            }
            c.disconnect()
        }
        return seq
    }

    /**
     * Block until the owner rules on draft [seq].
     *
     * ⚠ RE-ARMED IN A LOOP, and the reason is an EDGE limit rather than a taste.
     * This request goes through the Cloudflare Worker, which abandons an origin
     * response at ~100s with a 524 - so the daemon holds each wait for only
     * glassturn.DECIDE_WAIT_S (~25s, sized against the /glance/chat hanging GET
     * that is already proven through the deployed Worker) and hands back an empty
     * decision. Human patience is therefore OUR budget, spent here: keep asking
     * until TOTAL_WAIT_MS, which is the same shape app.js's chatLoop uses.
     *
     * An empty answer means "not yet" and is retried; only running out of budget
     * is a timeout, and a timeout never sends.
     */
    private fun awaitDecision(base: String, token: String, seq: Int): String {
        val deadline = System.currentTimeMillis() + TOTAL_WAIT_MS
        while (System.currentTimeMillis() < deadline) {
            // ACTION_STOP while we were waiting - stop waiting.
            if (loopMic == null) return "superseded"
            var answer: String? = null
            safe("decision") {
                val c = (URL("$base/glance/decision?token=$token&seq=$seq")
                    .openConnection() as HttpURLConnection).apply {
                    requestMethod = "GET"
                    connectTimeout = 15000
                    // comfortably past the daemon's own hold, so the SERVER is
                    // what ends this wait rather than a client-side stopwatch
                    readTimeout = 60000
                }
                val code = c.responseCode
                val raw = (if (code in 200..299) c.inputStream else c.errorStream)
                    ?.bufferedReader()?.use { it.readText() }.orEmpty()
                c.disconnect()
                if (code in 200..299) answer = JSONObject(raw).optString("decision")
            }
            // safe{} swallowed a network failure: `answer` is still null. Treat
            // that as fatal rather than spinning - a lens we cannot reach is a
            // verdict we will never hear, and retrying a dead route until the
            // budget runs out just delays the same drop.
            if (answer == null) return ""
            if (!answer.isNullOrBlank()) return answer!!
        }
        return ""
    }

    // ---- ask Henry, then play his answer ---------------------------------

    private fun ask(transcript: String) {
        val base = prefs.getString(KEY_BASE, "").orEmpty().trimEnd('/')
        val token = prefs.getString(KEY_TOKEN, "").orEmpty()
        if (base.isEmpty() || token.isEmpty()) {
            loopMic = null      // a loop that can never reach Henry must not re-arm
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
            val mic = loopMic
            if (voiceUrl != null) {
                // conversation mode: the moment Henry finishes talking is the
                // moment to listen again - the same event, one owner (the
                // player's completion), never a timer guessing at clip length.
                speak(base + voiceUrl!!) { if (mic != null) relisten(mic) }
            } else if (mic != null) {
                // no audio this time (offline edge-tts etc.) - the answer is in
                // the notification; re-arm anyway or the conversation dead-ends.
                relisten(mic)
            }
        }
    }

    /** The microphone name the DAEMON speaks, derived from the one this class
     *  already got from the routing call's own answer. `micInUse` is the
     *  owner-facing German shown in the notification; the wire vocabulary is
     *  fixed and English (glassturn.MICS). Translating here rather than widening
     *  the daemon's accepted words keeps that endpoint's vocabulary closed,
     *  which is the reason it is closed. */
    private fun micWire(): String = if (micInUse == "Brille") "glasses" else "phone"

    /**
     * TELL THE LENS SOMETHING IS LISTENING.
     *
     * This is the ONE fact in the whole glasses loop the daemon cannot observe
     * for itself. Everything else happens inside that process - the words arrive
     * at /glance/talk, Henry is called there, the answer is rendered there - so
     * the display can be driven from the server for all of it. But only this
     * class knows a microphone is open, because only this class opens one.
     *
     * Until now that fact went nowhere except this service's own Android
     * notification, which sits on the phone in the owner's pocket while he is
     * wearing the display. He had no way to tell the glasses were hearing him.
     *
     * Deliberately fire-and-forget, on its own thread, with SHORT timeouts and
     * wrapped in safe{}: a status ping must never delay the microphone or take
     * the conversation down with it. A dropped report costs one stale indicator
     * until the next turn re-reports it; a blocking one would cost the turn.
     * Same contract the notification path already has.
     *
     * It reads the same two prefs `ask` does, so on an unpaired device it
     * returns before touching the network - which is also why an unpaired device
     * can never light a "listening" indicator it would then be unable to clear.
     */
    private fun report(state: String, mic: String = "") {
        val base = prefs.getString(KEY_BASE, "").orEmpty().trimEnd('/')
        val token = prefs.getString(KEY_TOKEN, "").orEmpty()
        if (base.isEmpty() || token.isEmpty()) return
        Thread {
            safe("report") {
                val c = (URL("$base/glance/state").openConnection() as HttpURLConnection).apply {
                    requestMethod = "POST"
                    doOutput = true
                    connectTimeout = 5000
                    readTimeout = 5000
                    setRequestProperty("Content-Type", "application/json")
                }
                val body = JSONObject()
                    .put("token", token)
                    .put("state", state)
                    .put("mic", mic)
                    .toString()
                c.outputStream.use { it.write(body.toByteArray()) }
                c.responseCode                     // drives the exchange
                c.disconnect()
            }
        }.start()
    }

    /**
     * Henry, out loud. The lens has no speechSynthesis (measured on-device), so
     * the daemon renders the sentence and this just plays the clip - the same
     * split ops/docs/glasses-reference 11.6 describes.
     */
    private fun speak(url: String, onDone: () -> Unit = {}) = safe("play") {
        player?.release()
        player = MediaPlayer().apply {
            setDataSource(url)
            setOnCompletionListener {
                safe("play-done") { it.release() }; player = null
                safe("play-next") { onDone() }
            }
            setOnErrorListener { mp, _, _ ->
                safe("play-err") { mp.release() }; player = null
                // a failed playback still ends the speak phase - without this
                // the conversation loop would die on one bad clip
                safe("play-err-next") { onDone() }
                true
            }
            prepareAsync()
            setOnPreparedListener { it.start() }
        }
    }
}
