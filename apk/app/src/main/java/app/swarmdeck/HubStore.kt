package app.swarmdeck

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import org.json.JSONArray
import java.io.File

/**
 * The hub's memory - THE APK RULE lives here: pairing secret, daemon address, the recording
 * index, and downloaded recordings are all stored ON THE PHONE. The cloud never sees them.
 */
object HubStore {
    private lateinit var prefs: SharedPreferences
    private lateinit var filesDir: File

    fun init(ctx: Context) {
        val key = MasterKey.Builder(ctx).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build()
        prefs = EncryptedSharedPreferences.create(
            ctx, "hub", key,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )
        filesDir = File(ctx.filesDir, "recordings").apply { mkdirs() }
    }

    var daemonUrl: String
        get() = prefs.getString("daemonUrl", "") ?: ""
        set(v) { prefs.edit().putString("daemonUrl", v.trimEnd('/')).apply() }

    var pairSecret: String
        get() = prefs.getString("pairSecret", "") ?: ""
        set(v) { prefs.edit().putString("pairSecret", v).apply() }

    /** Last repo path used when filing a request - saves phone typing. */
    var lastRepo: String
        get() = prefs.getString("lastRepo", "") ?: ""
        set(v) { prefs.edit().putString("lastRepo", v).apply() }

    /** Cached run index (JSON as served by the daemon /runs) - usable offline. */
    var runIndex: JSONArray
        get() = try { JSONArray(prefs.getString("runIndex", "[]")) } catch (e: Exception) { JSONArray() }
        set(v) { prefs.edit().putString("runIndex", v.toString()).apply() }

    /** Local home of a downloaded recording (keep-all retention, phone-side archive). */
    fun recordingFile(runId: String, name: String): File =
        File(File(filesDir, runId).apply { mkdirs() }, name)
}
