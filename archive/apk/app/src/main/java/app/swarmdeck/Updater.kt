package app.swarmdeck

import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * Self-update over the owner's relay host - the answer to "sideloaded means
 * manual installs forever". The relay's web server statically serves
 * /apk/version.json and the latest signed APK; the app compares versionCode,
 * downloads over plain HTTPS (no E2EE tunnel needed: the APK is public and
 * Android verifies the signature - an update only installs if it is signed
 * with the same key as the running app), and hands the file to the system
 * installer. One tap instead of find-transfer-install.
 */
object Updater {
    data class Info(val versionCode: Long, val versionName: String, val url: String)

    private val http = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .build()

    fun ownVersion(ctx: Context): Long =
        ctx.packageManager.getPackageInfo(ctx.packageName, 0).longVersionCode

    /** Newer version on the relay host? null = up to date / unreachable / not paired. */
    suspend fun check(ctx: Context): Info? = withContext(Dispatchers.IO) {
        val base = HubStore.relayUrl.trimEnd('/')
        if (base.isEmpty()) return@withContext null
        try {
            http.newCall(Request.Builder().url("$base/apk/version.json").build())
                .execute().use { r ->
                    if (!r.isSuccessful) return@withContext null
                    val o = JSONObject(r.body?.string() ?: return@withContext null)
                    val code = o.optLong("versionCode", 0)
                    if (code <= ownVersion(ctx)) return@withContext null
                    Info(code, o.optString("versionName", "$code"),
                        // path-only url stays valid if the host ever moves
                        base + o.optString("url", "/apk/swarmdeck.apk"))
                }
        } catch (_: Exception) { null }   // offline is not an error, just no update
    }

    /** Stream the APK into app-private cache; returns null on failure. */
    suspend fun download(ctx: Context, info: Info, onProgress: (Float) -> Unit): File? =
        withContext(Dispatchers.IO) {
            val dir = File(ctx.cacheDir, "updates").apply { mkdirs() }
            // stale downloads from older checks are dead weight - drop them
            dir.listFiles()?.forEach { it.delete() }
            val out = File(dir, "swarmdeck-${info.versionCode}.apk")
            try {
                http.newCall(Request.Builder().url(info.url).build()).execute().use { r ->
                    if (!r.isSuccessful) return@withContext null
                    val body = r.body ?: return@withContext null
                    val total = body.contentLength().coerceAtLeast(1)
                    body.byteStream().use { src ->
                        out.outputStream().use { dst ->
                            val buf = ByteArray(64 * 1024)
                            var done = 0L
                            while (true) {
                                val n = src.read(buf); if (n < 0) break
                                dst.write(buf, 0, n); done += n
                                onProgress(done.toFloat() / total)
                            }
                        }
                    }
                }
                if (out.length() > 0) out else null
            } catch (_: Exception) { out.delete(); null }
        }

    /** Hand the APK to the system installer (user confirms with one tap). */
    fun install(ctx: Context, apk: File) {
        val uri = FileProvider.getUriForFile(ctx, ctx.packageName + ".fileprovider", apk)
        ctx.startActivity(Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        })
    }
}
