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

    private const val PREFS = "hub"

    private fun encrypted(ctx: Context): SharedPreferences {
        val key = MasterKey.Builder(ctx).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build()
        return EncryptedSharedPreferences.create(
            ctx, PREFS, key,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )
    }

    /**
     * Open the encrypted store, surviving the case where the prefs file outlives
     * its Keystore key - reinstalling or restoring the app leaves the ciphertext
     * behind while the hardware key is gone, and every read then throws
     * AEADBadTagException ("Signature/MAC verification failed"), which used to
     * crash the app on launch. Those bytes are unrecoverable by definition, so
     * discard them and start a fresh store; the user just pairs again.
     */
    fun init(ctx: Context) {
        prefs = try {
            encrypted(ctx).also { it.all }          // touch it: decryption happens here
        } catch (e: Exception) {
            runCatching { ctx.deleteSharedPreferences(PREFS) }
            runCatching {
                java.security.KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
                    .deleteEntry("_androidx_security_master_key_")
            }
            encrypted(ctx)                          // rebuild with a new master key
        }
        filesDir = File(ctx.filesDir, "recordings").apply { mkdirs() }
    }

    /** True once a usable store is open (tests and callers can assert on it). */
    fun isReady(): Boolean = ::prefs.isInitialized

    var daemonUrl: String
        get() = prefs.getString("daemonUrl", "") ?: ""
        set(v) { prefs.edit().putString("daemonUrl", v.trimEnd('/')).apply() }

    var pairSecret: String
        get() = prefs.getString("pairSecret", "") ?: ""
        set(v) { prefs.edit().putString("pairSecret", v).apply() }

    /** Relay reverse-tunnel + E2EE (relay/relay.py, e2ee.py). When set, every
     *  request is NaCl-box sealed and POSTed to relayUrl "/relay?room=<room>";
     *  the relay only sees ciphertext. Empty relayUrl = direct LAN. */
    var relayUrl: String
        get() = prefs.getString("relayUrl", "") ?: ""
        set(v) { prefs.edit().putString("relayUrl", v.trimEnd('/')).apply() }

    var room: String
        get() = prefs.getString("room", "") ?: ""
        set(v) { prefs.edit().putString("room", v).apply() }

    /** the daemon's Curve25519 public key (from the pairing code). */
    var daemonPub: String
        get() = prefs.getString("daemonPub", "") ?: ""
        set(v) { prefs.edit().putString("daemonPub", v).apply() }

    /** this phone's own Curve25519 keypair (generated once, base64). */
    var ownSk: String
        get() = prefs.getString("ownSk", "") ?: ""
        set(v) { prefs.edit().putString("ownSk", v).apply() }
    var ownPub: String
        get() = prefs.getString("ownPub", "") ?: ""
        set(v) { prefs.edit().putString("ownPub", v).apply() }

    /** Daemon device token (Authorization: Bearer), carried INSIDE the sealed
     *  request - authenticates the phone; the relay never sees it. */
    var deviceToken: String
        get() = prefs.getString("deviceToken", "") ?: ""
        set(v) { prefs.edit().putString("deviceToken", v).apply() }

    /** Apply a pairing code from SwarmDeck Settings. Accepts the bare base64 of
     *  {u,r,k,t} OR a whole pairing link (https://.../pair?c=... or
     *  swarmdeck://pair?c=...), because people paste whatever their scanner gave
     *  them. Ensures this phone has its own keypair. @return true on success. */
    fun applyPairingCode(raw: String): Boolean {
        return try {
            var code = raw.trim()
            // When a pairing LINK is given, the link's own origin is the relay -
            // the QR omits the url to keep the symbol small, so recover it here.
            var originFromLink: String? = null
            if (code.contains("://") || code.contains("c=")) {
                if (code.startsWith("http", ignoreCase = true)) {
                    val u = android.net.Uri.parse(code)
                    if (u.scheme != null && u.authority != null) originFromLink = "${u.scheme}://${u.authority}"
                }
                code = code.substringAfter("c=", code).substringBefore("&")
                code = java.net.URLDecoder.decode(code, "UTF-8")
            }
            // the QR uses base64URL (-,_ no padding); the copy/paste code is
            // plain base64 - normalise so both decode with the same call
            val norm = code.trim().replace('-', '+').replace('_', '/')
                .let { it + "=".repeat((4 - it.length % 4) % 4) }
            val json = String(android.util.Base64.decode(norm, android.util.Base64.NO_WRAP))
            val o = org.json.JSONObject(json)
            val url = o.optString("u").ifEmpty { originFromLink ?: "" }
            if (url.isEmpty()) return false          // no relay to talk to
            relayUrl = url; room = o.getString("r")
            daemonPub = o.getString("k"); deviceToken = o.getString("t")
            if (ownSk.isEmpty() || ownPub.isEmpty()) {
                val (sk, pk) = E2ee.generateKeyPair(); ownSk = sk; ownPub = pk
            }
            true
        } catch (e: Exception) { false }
    }

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
