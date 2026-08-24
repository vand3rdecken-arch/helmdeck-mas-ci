package app.helmdeck.livemic

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.util.Base64
import android.util.Log
import expo.modules.kotlin.Promise
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import java.io.ByteArrayOutputStream
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.sqrt

/**
 * RAW microphone -> VAD -> utterance segments, for the LIVE voice mode.
 *
 * This is the phone half of the huggingface/speech-to-speech cascade
 * (VAD -> STT -> LLM -> TTS) built on HelmDeck's own transport: the mic is
 * captured HERE (16 kHz mono PCM), an utterance is CUT here (energy VAD), and
 * the finished segment goes to JS as one WAV blob - the daemon transcribes it
 * (faster-whisper) and the existing chat turn does the rest. Nothing streams
 * over the network; segments ride the sealed relay like every other request
 * (the same whole-small-blobs answer as voice_stream.py, in reverse).
 *
 * WHY AudioRecord AND NOT SpeechRecognizer: the platform recognizer owns the
 * mic exclusively and exposes no audio, so an OWN pipeline (own endpointing,
 * own STT, open mic across turns) is impossible with it. This module is what
 * "own pipeline" concretely means on Android.
 *
 * WHY MODE_NORMAL IS NEVER TOUCHED: listening on the PHONE mic must leave the
 * glasses' A2DP route alone (ops/docs/glasses-reference.md:209 scope correction) -
 * that is what makes this mode tap-free WITH the glasses: phone listens,
 * glasses only ever play music-quality answers. `voiceComm=true` selects
 * AudioSource.VOICE_COMMUNICATION, which enables the handset's hardware echo
 * canceller where present - measured per-device, which is why it is a flag.
 *
 * THE VAD, honestly: energy-based (RMS over 20 ms frames against an adaptive
 * noise floor) with pre-roll, hangover and a max-utterance cap. It is the v0
 * every real pipeline started with; Silero-ONNX is the planned upgrade and
 * gets a clean seam here (one function decides speech/not-speech). should_listen
 * gating is `setMuted`: while Henry talks the JS mutes capture, so the phone
 * never transcribes its own speaker - the same gate speech-to-speech uses in
 * place of AEC.
 */
class LiveMicModule : Module() {

  companion object {
    private const val TAG = "LiveMic"
    private const val SR = 16000
    private const val FRAME = 320                 // 20 ms @ 16 kHz
    private const val PREROLL_FRAMES = 15         // 300 ms kept before speech starts
    private const val MIN_SPEECH_FRAMES = 15      // 300 ms to count as speech at all
    private const val END_SILENCE_FRAMES = 35     // 700 ms of quiet closes the utterance
    private const val MAX_UTTERANCE_FRAMES = 750  // 15 s hard cap
    private const val ABS_FLOOR = 250.0           // RMS below this is never speech
    private const val SNR = 2.5                   // speech = rms > noiseFloor * SNR
  }

  @Volatile private var rec: AudioRecord? = null
  @Volatile private var running = false
  @Volatile private var muted = false
  private var worker: Thread? = null

  override fun definition() = ModuleDefinition {
    Name("LiveMic")
    Events("onSegment", "onState")

    /** Open the mic and start cutting utterances. Idempotent. */
    Function("start") { voiceComm: Boolean ->
      if (running) return@Function true
      startCapture(voiceComm)
    }

    Function("stop") {
      running = false
      true
    }

    /** should_listen gate: while Henry speaks, capture is dropped and the VAD
     *  reset, so the speaker can never talk to the microphone. */
    Function("setMuted") { m: Boolean ->
      muted = m
      true
    }

    // ---- ON-DEVICE STT (sherpa-onnx, owner A/B option 2026-08-23) ---------
    // Every sherpa reference lives INSIDE these methods and behind
    // catch(Throwable): the AAR is wired by app/plugins/withSherpaOnnx.js at
    // APK-build time, and a build without it (EAS/iOS, an old APK) must
    // degrade to "device STT unavailable" - never a class-load crash.

    /** Download files into filesDir/<dir>/. Skips files already present.
     *  Runs off the JS thread; resolves with the absolute directory path. */
    AsyncFunction("downloadFiles") { urls: List<String>, dir: String, promise: Promise ->
      Thread {
        try {
          val base = File(appContext.reactContext!!.filesDir, dir)
          base.mkdirs()
          for (u in urls) {
            val name = u.substringAfterLast('/')
            val dst = File(base, name)
            if (dst.exists() && dst.length() > 0) continue
            val tmp = File(base, "$name.part")
            val c = URL(u).openConnection() as HttpURLConnection
            c.connectTimeout = 20000
            c.readTimeout = 600000
            c.instanceFollowRedirects = true
            c.inputStream.use { i -> tmp.outputStream().use { o -> i.copyTo(o, 1 shl 16) } }
            if (!tmp.renameTo(dst)) throw RuntimeException("rename failed: $name")
          }
          promise.resolve(base.absolutePath)
        } catch (t: Throwable) {
          promise.reject("DOWNLOAD", t.message ?: "download failed", t)
        }
      }.start()
    }

    /** Build a STREAMING transducer recognizer (zipformer et al) from files on
     *  disk. Benchmarked 2026-08-23 (ops/tools/stt_bench.py): the German kroko
     *  zipformer hits WER 11.4% at a third of whisper-tiny's latency, and it
     *  is 8 kHz-robust - the device ear of choice. */
    Function("initLocalTransducer") { encoder: String, decoder: String, joiner: String, tokens: String ->
      try {
        val cfg = com.k2fsa.sherpa.onnx.OnlineRecognizerConfig(
          modelConfig = com.k2fsa.sherpa.onnx.OnlineModelConfig(
            transducer = com.k2fsa.sherpa.onnx.OnlineTransducerModelConfig(
              encoder = encoder, decoder = decoder, joiner = joiner),
            tokens = tokens, modelType = "zipformer", numThreads = 2))
        localRec = com.k2fsa.sherpa.onnx.OnlineRecognizer(null, cfg)
        true
      } catch (t: Throwable) {
        Log.w(TAG, "initLocalTransducer: ${t.javaClass.simpleName}: ${t.message}")
        false
      }
    }

    /** Build the offline recognizer from model files on disk. */
    Function("initLocalStt") { encoder: String, decoder: String, tokens: String, lang: String ->
      try {
        val cfg = com.k2fsa.sherpa.onnx.OfflineRecognizerConfig(
          modelConfig = com.k2fsa.sherpa.onnx.OfflineModelConfig(
            whisper = com.k2fsa.sherpa.onnx.OfflineWhisperModelConfig(
              encoder = encoder, decoder = decoder,
              language = lang, task = "transcribe"),
            tokens = tokens, modelType = "whisper",
            numThreads = 2, debug = false))
        localRec = com.k2fsa.sherpa.onnx.OfflineRecognizer(null, cfg)
        true
      } catch (t: Throwable) {
        Log.w(TAG, "initLocalStt: ${t.javaClass.simpleName}: ${t.message}")
        false
      }
    }

    /** One VAD segment (the module's own WAV shape) -> text, on-device.
     *  Works with whichever recognizer initLocal* built - streaming transducer
     *  (kroko) or offline whisper. */
    AsyncFunction("transcribeLocal") { b64: String, promise: Promise ->
      Thread {
        try {
          val wav = android.util.Base64.decode(b64, android.util.Base64.DEFAULT)
          val n = (wav.size - 44) / 2
          val f = FloatArray(maxOf(n, 0))
          for (i in 0 until n) {
            val lo = wav[44 + 2 * i].toInt() and 0xff
            val hi = wav[45 + 2 * i].toInt()
            f[i] = ((hi shl 8) or lo) / 32768f
          }
          val text = when (val rec = localRec) {
            is com.k2fsa.sherpa.onnx.OnlineRecognizer -> {
              val s = rec.createStream()
              s.acceptWaveform(f, SR)
              // half a second of tail silence, then close: a streaming model
              // only commits its last tokens once the audio provably ended
              s.acceptWaveform(FloatArray(SR / 2), SR)
              s.inputFinished()
              while (rec.isReady(s)) rec.decode(s)
              val out = rec.getResult(s).text
              s.release()
              out
            }
            is com.k2fsa.sherpa.onnx.OfflineRecognizer -> {
              val s = rec.createStream()
              s.acceptWaveform(f, SR)
              rec.decode(s)
              val out = rec.getResult(s).text
              s.release()
              out
            }
            else -> throw RuntimeException("initLocalStt/initLocalTransducer first")
          }
          promise.resolve(text)
        } catch (t: Throwable) {
          promise.reject("STT", "${t.javaClass.simpleName}: ${t.message}", t)
        }
      }.start()
    }

    OnDestroy {
      running = false
      try { (localRec as? com.k2fsa.sherpa.onnx.OfflineRecognizer)?.release() } catch (t: Throwable) { /* absent */ }
      localRec = null
    }
  }

  /** The sherpa recognizer, typed Any so this class loads on builds without
   *  the AAR (references stay inside method bodies - lazy verification). */
  @Volatile private var localRec: Any? = null

  @SuppressLint("MissingPermission")   // RECORD_AUDIO is requested by the JS before start()
  private fun startCapture(voiceComm: Boolean): Boolean {
    val minBuf = AudioRecord.getMinBufferSize(
      SR, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
    if (minBuf <= 0) return false
    val source = if (voiceComm) MediaRecorder.AudioSource.VOICE_COMMUNICATION
                 else MediaRecorder.AudioSource.MIC
    val r = try {
      AudioRecord(source, SR, AudioFormat.CHANNEL_IN_MONO,
                  AudioFormat.ENCODING_PCM_16BIT, maxOf(minBuf, FRAME * 8 * 2))
    } catch (t: Throwable) {
      Log.w(TAG, "AudioRecord: ${t.message}"); return false
    }
    if (r.state != AudioRecord.STATE_INITIALIZED) { r.release(); return false }
    rec = r
    running = true
    r.startRecording()
    worker = Thread { pump(r) }.apply { isDaemon = true; start() }
    return true
  }

  /** The capture loop. One thread, one owner of every VAD variable. */
  private fun pump(r: AudioRecord) {
    val frame = ShortArray(FRAME)
    val preroll = ArrayDeque<ShortArray>()
    var utterance: ByteArrayOutputStream? = null
    var speechFrames = 0
    var silenceFrames = 0
    var totalFrames = 0
    var noiseFloor = 600.0                        // adapts downward fast, upward slowly
    var state = "listening"

    fun emitState(s: String) {
      if (s != state) { state = s; sendEvent("onState", mapOf("state" to s)) }
    }

    fun reset() {
      utterance = null; speechFrames = 0; silenceFrames = 0; totalFrames = 0
      preroll.clear()
      emitState("listening")
    }

    fun finish(min: Boolean) {
      val u = utterance
      // MIN_SPEECH_FRAMES of actual speech, or it was a door slam - drop it.
      if (u != null && min && speechFrames >= MIN_SPEECH_FRAMES) {
        val pcm = u.toByteArray()
        sendEvent("onSegment", mapOf(
          "b64" to Base64.encodeToString(wav(pcm), Base64.NO_WRAP),
          "ms" to (pcm.size / 2 * 1000 / SR)))
      }
      reset()
    }

    while (running) {
      val n = try { r.read(frame, 0, FRAME) } catch (t: Throwable) { -1 }
      if (n <= 0) break
      if (muted) { if (utterance != null) finish(true); continue }
      var sum = 0.0
      for (i in 0 until n) sum += frame[i].toDouble() * frame[i]
      val rms = sqrt(sum / n)
      // Adaptive floor: sink quickly toward quiet, rise only slowly, so a long
      // speech never teaches the floor that talking is silence.
      noiseFloor = if (rms < noiseFloor) noiseFloor * 0.95 + rms * 0.05
                   else noiseFloor * 0.999 + rms * 0.001
      val isSpeech = rms > ABS_FLOOR && rms > noiseFloor * SNR

      if (utterance == null) {
        preroll.addLast(frame.copyOf(n))
        while (preroll.size > PREROLL_FRAMES) preroll.removeFirst()
        if (isSpeech) {
          utterance = ByteArrayOutputStream().also { out ->
            for (p in preroll) out.write(pcmBytes(p))
          }
          speechFrames = 1; silenceFrames = 0; totalFrames = preroll.size
          emitState("speech")
        }
      } else {
        utterance!!.write(pcmBytes(frame.copyOf(n)))
        totalFrames += 1
        if (isSpeech) { speechFrames += 1; silenceFrames = 0 }
        else silenceFrames += 1
        if (silenceFrames >= END_SILENCE_FRAMES || totalFrames >= MAX_UTTERANCE_FRAMES) {
          finish(true)
        }
      }
    }
    try { r.stop() } catch (t: Throwable) { /* already stopped */ }
    r.release()
    if (rec === r) rec = null
    running = false
  }

  private fun pcmBytes(s: ShortArray): ByteArray {
    val b = ByteBuffer.allocate(s.size * 2).order(ByteOrder.LITTLE_ENDIAN)
    for (v in s) b.putShort(v)
    return b.array()
  }

  /** Minimal PCM16 mono WAV wrapper - what faster-whisper eats without ffmpeg. */
  private fun wav(pcm: ByteArray): ByteArray {
    val h = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
    h.put("RIFF".toByteArray()); h.putInt(36 + pcm.size); h.put("WAVE".toByteArray())
    h.put("fmt ".toByteArray()); h.putInt(16); h.putShort(1); h.putShort(1)
    h.putInt(SR); h.putInt(SR * 2); h.putShort(2); h.putShort(16)
    h.put("data".toByteArray()); h.putInt(pcm.size)
    return h.array() + pcm
  }
}
