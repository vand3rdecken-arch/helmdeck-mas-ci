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
 * Full client to the desktop daemon (server.py) - deliberately covering the same
 * operations the desktop card surface offers, so the phone is not a cut-down
 * remote. Two transports, chosen per call:
 *   - E2EE relay (relayUrl + room set): each request is NaCl-box sealed and
 *     POSTed to the relay, which only ever shuttles ciphertext.
 *   - direct LAN (relayUrl empty): plain HTTP to daemonUrl.
 * Auth is a device token carried as Authorization: Bearer, inside the sealed
 * envelope when relayed.
 */
object DaemonClient {
    private val http = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .build()

    class ApiError(val status: Int, val body: String) : Exception("HTTP $status: ${body.take(200)}")

    private fun relayMode() = HubStore.relayUrl.isNotEmpty() && HubStore.room.isNotEmpty()
    fun configured() = relayMode() || HubStore.daemonUrl.isNotEmpty()

    private suspend fun exec(method: String, path: String, body: String?): Pair<Int, String> =
        withContext(Dispatchers.IO) {
            if (relayMode()) {
                val headers = JSONObject().put("Content-Type", "application/json")
                if (HubStore.deviceToken.isNotEmpty())
                    headers.put("Authorization", "Bearer " + HubStore.deviceToken)
                val inner = JSONObject().put("method", method).put("path", path)
                    .put("headers", headers).put("body", body ?: "")
                val cipher = E2ee.seal(inner.toString().toByteArray(), HubStore.ownSk, HubStore.daemonPub)
                val frame = JSONObject().put("pub", HubStore.ownPub).put("cipher", cipher)
                val req = Request.Builder()
                    .url(HubStore.relayUrl + "/relay?room=" + HubStore.room)
                    .post(frame.toString().toRequestBody("application/json".toMediaType())).build()
                http.newCall(req).execute().use { r ->
                    val txt = r.body?.string() ?: ""
                    if (!r.isSuccessful) return@withContext Pair(r.code, txt)
                    val outCipher = JSONObject(txt).optString("cipher", "")
                    if (outCipher.isEmpty())
                        return@withContext Pair(504, "{\"error\":\"relay: no response - is the daemon running?\"}")
                    val resp = JSONObject(String(E2ee.open(outCipher, HubStore.ownSk, HubStore.daemonPub)))
                    return@withContext Pair(resp.optInt("status", 200), resp.optString("body", ""))
                }
            } else {
                val bld = Request.Builder().url(HubStore.daemonUrl + path)
                if (HubStore.deviceToken.isNotEmpty())
                    bld.header("Authorization", "Bearer " + HubStore.deviceToken)
                if (body != null) bld.post(body.toRequestBody("application/json".toMediaType()))
                http.newCall(bld.build()).execute().use { r ->
                    return@withContext Pair(r.code, r.body?.string() ?: "")
                }
            }
        }

    private suspend fun req(method: String, path: String, body: String? = null): String {
        val (code, txt) = exec(method, path, body)
        if (code !in 200..299) throw ApiError(code, txt)
        return txt
    }

    /** Raw GET body - for tests and callers that parse a one-off shape. */
    suspend fun rawGet(path: String): String = req("GET", path)

    private suspend fun getArr(p: String) = JSONArray(req("GET", p))
    private suspend fun getObj(p: String) = JSONObject(req("GET", p))
    private suspend fun post(p: String, b: JSONObject = JSONObject()) = JSONObject(req("POST", p, b.toString()))

    // ---- board / cards -----------------------------------------------------
    suspend fun tracks(): List<Track> = Track.list(getArr("/tracks"))
    /** capacity + economics; /dashboard/data is what the desktop header uses. */
    suspend fun metrics(): Metrics = Metrics.from(getObj("/dashboard/data"))
    suspend fun transcript(id: String): List<Step> = Step.list(getArr("/tracks/$id/transcript"))
    suspend fun history(id: String): List<HistoryRow> = HistoryRow.list(getArr("/tracks/$id/history"))
    suspend fun turns(id: String): JSONArray = getArr("/tracks/$id/turns")
    suspend fun diff(id: String): String = req("GET", "/tracks/$id/diff")

    /** thinking is a level key ("think" | "think-hard" | "ultrathink"), mode the
     *  permission mode - the same knobs the desktop composer exposes. */
    suspend fun steer(id: String, text: String, model: String? = null,
                      thinking: String? = null, mode: String? = null): JSONObject =
        post("/tracks/$id/steer", JSONObject().put("text", text).apply {
            if (!model.isNullOrEmpty()) put("model", model)
            if (!thinking.isNullOrEmpty()) put("thinking", thinking)
            if (!mode.isNullOrEmpty()) put("mode", mode)
        })

    suspend fun cancel(id: String): JSONObject = post("/tracks/$id/cancel")
    suspend fun moveLane(id: String, lane: String): JSONObject =
        post("/tracks/$id/lane", JSONObject().put("lane", lane))
    /** Edit any card field the desktop can edit (task, description, priority,
     *  due, billing, rate, client, driver, value, work_by...). */
    suspend fun update(id: String, patch: JSONObject): JSONObject = post("/tracks/$id/update", patch)
    suspend fun archive(id: String): JSONObject = post("/tracks/$id/archive")
    suspend fun delete(id: String): JSONObject = post("/tracks/$id/delete")
    suspend fun fork(id: String, fromRef: String = ""): JSONObject =
        post("/tracks/$id/fork", JSONObject().put("from", fromRef))
    suspend fun newTrack(repo: String, task: String, branch: String = "", lane: String = "backlog",
                         priority: String = "medium", client: String = ""): JSONObject =
        post("/tracks/new", JSONObject().put("repo", repo).put("task", task)
            .put("branch", branch).put("lane", lane).put("priority", priority).put("client", client))

    // ---- push --------------------------------------------------------------
    /** Announce this phone's FCM token; the daemon seals pushes to it. */
    suspend fun registerPushToken(token: String): JSONObject =
        post("/push/register", JSONObject().put("token", token))

    // ---- rewind ------------------------------------------------------------
    suspend fun checkpoints(id: String): List<Checkpoint> = Checkpoint.list(getArr("/tracks/$id/checkpoints"))
    suspend fun rewind(id: String, commit: String): JSONObject =
        post("/tracks/$id/rewind", JSONObject().put("commit", commit))

    // ---- attachments -------------------------------------------------------
    suspend fun attachments(id: String): JSONArray = getArr("/tracks/$id/attachments")

    /** Attach a file. The daemon takes [{name, data(base64), mime}] as plain
     *  JSON, so this works through the encrypted relay like everything else. */
    suspend fun attach(id: String, name: String, mime: String, bytes: ByteArray): JSONObject =
        post("/tracks/$id/attach", JSONObject().put("attachments", JSONArray().put(
            JSONObject().put("name", name).put("mime", mime)
                .put("data", android.util.Base64.encodeToString(bytes, android.util.Base64.NO_WRAP)))))

    suspend fun removeAttachment(id: String, name: String): JSONObject =
        post("/tracks/$id/attach/remove", JSONObject().put("name", name))

    // ---- board arrangement --------------------------------------------------
    suspend fun reorder(ids: List<String>): JSONObject =
        post("/tracks/reorder", JSONObject().put("ids", JSONArray(ids)))

    // ---- recordings ---------------------------------------------------------
    suspend fun runTimeline(runId: String): JSONArray = getArr("/runs/$runId/timeline")

    /**
     * Pull a recording down in base64 slices and write it to phone storage.
     *
     * The encrypted relay carries text frames, so a raw video stream cannot
     * cross it. Slicing keeps recordings watchable over the internet without
     * weakening the tunnel. Returns the local file, or null when the run has no
     * video. [onProgress] reports 0..1 so the UI can show real progress.
     */
    suspend fun downloadRecording(runId: String, profile: String = "mobile",
                                  onProgress: (Float) -> Unit = {}): File? =
        withContext(Dispatchers.IO) {
            val chunk = 256 * 1024
            var offset = 0L
            var total = 0L
            var out: File? = null
            var sink: java.io.OutputStream? = null
            try {
                while (true) {
                    val (code, txt) = exec("GET",
                        "/runs/$runId/videochunk?offset=$offset&len=$chunk&profile=$profile", null)
                    if (code == 404) return@withContext null
                    if (code !in 200..299) throw ApiError(code, txt)
                    val o = JSONObject(txt)
                    if (total == 0L) {
                        total = o.optLong("size", 0L)
                        val ext = if (o.optString("mime").contains("webm")) "webm" else "mp4"
                        out = HubStore.recordingFile(runId, "video.$profile.$ext")
                        sink = out.outputStream()
                    }
                    val bytes = android.util.Base64.decode(o.optString("data"), android.util.Base64.DEFAULT)
                    sink?.write(bytes)
                    offset += bytes.size
                    if (total > 0) onProgress((offset.toFloat() / total).coerceIn(0f, 1f))
                    if (o.optBoolean("eof") || bytes.isEmpty()) break
                }
            } finally {
                runCatching { sink?.close() }
            }
            onProgress(1f)
            out
        }

    // ---- users (owner) ------------------------------------------------------
    suspend fun users(): JSONArray = getArr("/users")
    suspend fun createUser(name: String, password: String, role: String): JSONObject =
        post("/users", JSONObject().put("name", name).put("password", password).put("role", role))
    suspend fun setUserRole(name: String, role: String): JSONObject =
        post("/users/$name/role", JSONObject().put("role", role))
    suspend fun setUserPassword(name: String, password: String): JSONObject =
        post("/users/$name/password", JSONObject().put("password", password))
    suspend fun issueToken(name: String, label: String): JSONObject =
        post("/users/$name/tokens", JSONObject().put("label", label))
    suspend fun revokeToken(name: String, token: String): JSONObject =
        post("/users/$name/revoke", JSONObject().put("token", token))
    suspend fun deleteUser(name: String): JSONObject = post("/users/$name/delete")

    // ---- connectors ---------------------------------------------------------
    suspend fun connectors(): JSONArray = getArr("/connectors")
    suspend fun runConnector(name: String): JSONObject = post("/connectors/$name/run")
    suspend fun rollbackConnector(name: String): JSONObject = post("/connectors/$name/rollback")

    // ---- workspace checkpoints (settings history, not card rewind) -----------
    suspend fun workspaceCheckpoints(): JSONArray = getArr("/checkpoints")
    suspend fun checkpointDiff(id: String): JSONObject = getObj("/checkpoints/$id/diff")
    suspend fun restoreCheckpoint(id: String): JSONObject = post("/checkpoints/$id/restore")

    // ---- technical debt register --------------------------------------------
    suspend fun debt(): JSONArray = getArr("/debt")
    suspend fun fixDebt(id: String): JSONObject = post("/debt/$id/fix")

    // ---- processes (write side) ----------------------------------------------
    suspend fun newProcess(name: String, client: String, steps: JSONArray): JSONObject =
        post("/processes/new", JSONObject().put("name", name).put("client", client).put("steps", steps))
    suspend fun advanceStep(processId: String): JSONObject = post("/processes/$processId/step")

    // ---- imports --------------------------------------------------------------
    suspend fun importJira(jql: String): JSONObject = post("/import/jira", JSONObject().put("jql", jql))
    suspend fun importUrl(url: String): JSONObject = post("/import/url", JSONObject().put("url", url))

    // ---- copilot ---------------------------------------------------------------
    suspend fun cancelChat(): JSONObject = post("/chat/cancel")

    // ---- processes / dashboard / history ------------------------------------
    suspend fun processes(): List<Process> = Process.list(getArr("/processes"))
    suspend fun dashboard(): JSONObject = getObj("/dashboard/data")
    /** git audit trail (main + card branches) - an object, not a list. */
    suspend fun gitHistory(): List<Commit> = Commit.fromHistory(getObj("/history"))
    suspend fun runs(): JSONArray = getArr("/runs").also { HubStore.runIndex = it }
    suspend fun timeline(runId: String): JSONArray = getArr("/runs/$runId/timeline")
    /** existing Claude Code sessions on the desktop (~/.claude), adoptable. */
    suspend fun claudeSessions(): List<ClaudeSession> = ClaudeSession.list(getArr("/sessions/claude"))

    /** mode "continue" wraps the session in place; "fork" branches a fresh one. */
    suspend fun adoptSession(s: ClaudeSession, mode: String): JSONObject =
        post("/sessions/claude/adopt", JSONObject()
            .put("session_id", s.id).put("cwd", s.cwd)
            .put("first", s.first).put("mode", mode))

    /** repos known to this workspace: configured projects + the default + every
     *  repo already used by a card - enough for a picker instead of typing. */
    suspend fun knownRepos(): List<String> {
        val out = LinkedHashSet<String>()
        runCatching { settings().optString("default_repo") }.getOrNull()
            ?.takeIf { it.isNotBlank() }?.let { out += it }
        runCatching {
            val a = getArr("/projects")
            for (i in 0 until a.length()) a.optJSONObject(i)?.optString("repo")
                ?.takeIf { it.isNotBlank() }?.let { out += it }
        }
        runCatching { tracks().mapNotNull { it.repo }.filter { it.isNotBlank() } }
            .getOrDefault(emptyList()).forEach { out += it }
        return out.toList()
    }

    // ---- settings / models / me ---------------------------------------------
    suspend fun settings(): JSONObject = getObj("/settings")
    suspend fun saveSettings(patch: JSONObject): JSONObject = post("/settings", patch)
    suspend fun models(): JSONArray = getArr("/models")
    suspend fun me(): JSONObject = getObj("/me")

    // ---- copilot chat --------------------------------------------------------
    /** {messages:[{cls,text,ts,usage}], session_id} - usage feeds the context meter */
    suspend fun chatHistory(): JSONObject = getObj("/chat/history")
    suspend fun chat(text: String): JSONObject = post("/chat", JSONObject().put("text", text))

    // ---- control (desktop recorder) -------------------------------------------
    suspend fun state(): JSONObject = getObj("/control/state")
    suspend fun teachStart(title: String): JSONObject =
        post("/control/teach/start", JSONObject().put("title", title))
    suspend fun teachStop(): JSONObject = post("/control/teach/stop")
    suspend fun distill(runId: String): JSONObject = post("/control/distill", JSONObject().put("id", runId))

    // ---- binary (LAN only; the sealed envelope carries text) ------------------
    suspend fun liveFrame(): ByteArray? = withContext(Dispatchers.IO) {
        if (relayMode()) return@withContext null
        val bld = Request.Builder().url(HubStore.daemonUrl + "/live.jpg")
        if (HubStore.deviceToken.isNotEmpty()) bld.header("Authorization", "Bearer " + HubStore.deviceToken)
        http.newCall(bld.build()).execute().use { r -> if (r.isSuccessful) r.body?.bytes() else null }
    }

    suspend fun downloadVideo(runId: String): File? = withContext(Dispatchers.IO) {
        if (relayMode()) return@withContext null
        val bld = Request.Builder().url(HubStore.daemonUrl + "/runs/$runId/video")
        if (HubStore.deviceToken.isNotEmpty()) bld.header("Authorization", "Bearer " + HubStore.deviceToken)
        http.newCall(bld.build()).execute().use { r ->
            if (!r.isSuccessful) return@withContext null
            val ext = if (r.header("Content-Type")?.contains("webm") == true) "webm" else "mp4"
            val f = HubStore.recordingFile(runId, "video.$ext")
            f.outputStream().use { out -> r.body!!.byteStream().copyTo(out) }
            f
        }
    }
}
