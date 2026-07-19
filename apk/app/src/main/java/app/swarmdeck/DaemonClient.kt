package app.swarmdeck

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * LAN client to the desktop daemon (server.py). The daemon is hands + capture; this client
 * pulls what the hub archives: the run index, timelines, videos, the live glance frame.
 */
object DaemonClient {
    private val http = OkHttpClient.Builder()
        .connectTimeout(4, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .build()

    private fun req(path: String): Request =
        Request.Builder().url(HubStore.daemonUrl + path).build()

    suspend fun runs(): JSONArray = withContext(Dispatchers.IO) {
        http.newCall(req("/runs")).execute().use { r ->
            val idx = JSONArray(r.body!!.string())
            HubStore.runIndex = idx   // hub caches the index — reviewable offline
            idx
        }
    }

    suspend fun timeline(runId: String): JSONArray = withContext(Dispatchers.IO) {
        http.newCall(req("/runs/$runId/timeline")).execute().use { r ->
            JSONArray(r.body!!.string())
        }
    }

    suspend fun liveFrame(): ByteArray? = withContext(Dispatchers.IO) {
        http.newCall(req("/live.jpg")).execute().use { r ->
            if (r.isSuccessful) r.body!!.bytes() else null
        }
    }

    /** Pull a recording into phone storage (the archive of record per the APK rule). */
    suspend fun downloadVideo(runId: String): File? = withContext(Dispatchers.IO) {
        http.newCall(req("/runs/$runId/video")).execute().use { r ->
            if (!r.isSuccessful) return@withContext null
            val ext = if (r.header("Content-Type")?.contains("webm") == true) "webm" else "mp4"
            val f = HubStore.recordingFile(runId, "video.$ext")
            f.outputStream().use { out -> r.body!!.byteStream().copyTo(out) }
            f
        }
    }
}
