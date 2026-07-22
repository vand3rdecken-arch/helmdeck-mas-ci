package app.swarmdeck

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
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
            HubStore.runIndex = idx   // hub caches the index - reviewable offline
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

    suspend fun playbook(runId: String): String? = withContext(Dispatchers.IO) {
        http.newCall(req("/runs/$runId/playbook")).execute().use { r ->
            if (r.isSuccessful) r.body!!.string() else null
        }
    }

    // ---- control: mobile has the same verbs as the desktop CLI ----

    private suspend fun post(path: String, body: JSONObject = JSONObject()): JSONObject =
        withContext(Dispatchers.IO) {
            val rb = body.toString().toRequestBody("application/json".toMediaType())
            http.newCall(Request.Builder().url(HubStore.daemonUrl + path).post(rb).build())
                .execute().use { r -> JSONObject(r.body!!.string()) }
        }

    suspend fun teachStart(title: String): JSONObject =
        post("/control/teach/start", JSONObject().put("title", title))

    suspend fun teachStop(): JSONObject = post("/control/teach/stop")

    suspend fun distill(runId: String): JSONObject =
        post("/control/distill", JSONObject().put("id", runId))

    suspend fun demoTask(): JSONObject = post("/control/demo")

    suspend fun state(): JSONObject = withContext(Dispatchers.IO) {
        http.newCall(req("/control/state")).execute().use { r ->
            JSONObject(r.body!!.string())
        }
    }

    // ---- the board: branches as resumable sessions, kanban on top ----

    suspend fun tracks(): JSONArray = withContext(Dispatchers.IO) {
        http.newCall(req("/tracks")).execute().use { r -> JSONArray(r.body!!.string()) }
    }

    suspend fun trackHistory(id: String): JSONArray = withContext(Dispatchers.IO) {
        http.newCall(req("/tracks/$id/history")).execute().use { r -> JSONArray(r.body!!.string()) }
    }

    suspend fun steerTrack(id: String, text: String): JSONObject =
        post("/tracks/$id/steer", JSONObject().put("text", text))

    suspend fun moveLane(id: String, lane: String): JSONObject =
        post("/tracks/$id/lane", JSONObject().put("lane", lane))

    suspend fun newTrack(repo: String, branch: String, task: String): JSONObject =
        post("/tracks/new", JSONObject().put("repo", repo).put("branch", branch)
            .put("task", task).put("lane", "backlog"))
}
