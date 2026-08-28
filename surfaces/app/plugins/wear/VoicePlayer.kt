package app.helmdeck.wear.data

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.util.Base64
import java.io.File
import java.io.FileOutputStream

/**
 * Plays the inline voice clip POST /wear/talk now returns
 * ({id, mime, b64} - spine/media/voice.py's render_b64(), read this
 * session): the same daemon-renders/client-plays split the phone's own
 * /chat voice:true already uses, and for the SAME reason stated in
 * voice.py's own docstring - the watch talks through the sealed relay
 * (RelayClient.authedCall), one JSON request/response, no second channel to
 * fetch a binary URL from.
 *
 * NOT a data: URI into MediaPlayer.setDataSource(Uri) - unlike the phone's
 * expo-audio/web Audio element (which both accept a data: URI directly,
 * confirmed by reading surfaces/app/src/data/voice.ts's speak() this
 * session), MediaPlayer's own data: URI support is inconsistent across
 * Android versions and was not confirmed for this session's target API
 * levels. Writing the decoded bytes to a cache file first is the
 * unambiguously-documented MediaPlayer path (setDataSource(String)), so
 * that is what this uses.
 */
object VoicePlayer {
    private var current: MediaPlayer? = null

    fun play(context: Context, mime: String, b64: String) {
        stop()
        val bytes = try { Base64.decode(b64, Base64.NO_WRAP) } catch (_: IllegalArgumentException) { return }
        if (bytes.isEmpty()) return
        val ext = if (mime.contains("mpeg") || mime.contains("mp3")) "mp3" else "audio"
        val file = File(context.cacheDir, "henry_${System.currentTimeMillis()}.$ext")
        try {
            FileOutputStream(file).use { it.write(bytes) }
        } catch (_: Exception) {
            return
        }
        val player = MediaPlayer()
        current = player
        try {
            player.setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ASSISTANT)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build()
            )
            player.setDataSource(file.absolutePath)
            player.setOnCompletionListener { mp ->
                mp.release()
                if (current === mp) current = null
                file.delete()
            }
            player.setOnErrorListener { mp, _, _ ->
                mp.release()
                if (current === mp) current = null
                file.delete()
                true
            }
            player.prepareAsync()
            player.setOnPreparedListener { it.start() }
        } catch (_: Exception) {
            player.release()
            if (current === player) current = null
            file.delete()
        }
    }

    fun stop() {
        current?.let { mp ->
            try { if (mp.isPlaying) mp.stop() } catch (_: Exception) { /* already stopped */ }
            mp.release()
        }
        current = null
    }
}
