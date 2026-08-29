package app.helmdeck.wear.data

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * Where the watch's own pairing material lives: relay URL, room, the
 * daemon's public key, this device's own NaCl keypair, and its Bearer
 * device token - the Kotlin equivalent of what config.ts persists via
 * expo-secure-store on the phone (Persisted in config.ts). Every field here
 * is either a live credential (deviceToken) or the key material that
 * derives one (mySecretKeyB64), so EncryptedSharedPreferences (Android
 * Jetpack's at-rest encryption for exactly this case) is the floor, not an
 * upgrade - plain SharedPreferences would leave a lost/stolen watch's
 * daemon access sitting in cleartext.
 */
object DeviceStore {
    private const val FILE = "helmdeck_device"
    private const val K_URL = "relay_url"
    private const val K_ROOM = "room"
    private const val K_DAEMON_PUB = "daemon_pub"
    private const val K_MY_SEC = "my_sec"
    private const val K_MY_PUB = "my_pub"
    private const val K_DEVICE_TOKEN = "device_token"

    data class Device(
        val relayUrl: String,
        val room: String,
        val daemonPubB64: String,
        val mySecretKeyB64: String,
        val myPublicKeyB64: String,
        val deviceToken: String,
    )

    private fun prefs(context: Context): SharedPreferences {
        // AES256_GCM per MasterKey's own documented default - the same
        // scheme EncryptedSharedPreferences itself insists on for its value
        // encryption below, so there is no second, weaker scheme quietly in
        // play for the key that protects the rest.
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        return EncryptedSharedPreferences.create(
            context, FILE, masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    fun save(context: Context, d: Device) {
        prefs(context).edit()
            .putString(K_URL, d.relayUrl)
            .putString(K_ROOM, d.room)
            .putString(K_DAEMON_PUB, d.daemonPubB64)
            .putString(K_MY_SEC, d.mySecretKeyB64)
            .putString(K_MY_PUB, d.myPublicKeyB64)
            .putString(K_DEVICE_TOKEN, d.deviceToken)
            .apply()
    }

    /** null when any required field is missing - a partially-written store
     *  (e.g. a crash mid-pairing) must never be read as "paired". */
    fun load(context: Context): Device? {
        val p = prefs(context)
        val url = p.getString(K_URL, null)
        val room = p.getString(K_ROOM, null)
        val daemonPub = p.getString(K_DAEMON_PUB, null)
        val mySec = p.getString(K_MY_SEC, null)
        val myPub = p.getString(K_MY_PUB, null)
        val token = p.getString(K_DEVICE_TOKEN, null)
        if (url.isNullOrEmpty() || room.isNullOrEmpty() || daemonPub.isNullOrEmpty() ||
            mySec.isNullOrEmpty() || myPub.isNullOrEmpty() || token.isNullOrEmpty()
        ) return null
        return Device(url, room, daemonPub, mySec, myPub, token)
    }

    /** Forget this device's own pairing - does NOT reach the daemon (unlike
     *  the phone's owner-only /relay/unpair, which revokes every device).
     *  A lost-watch story is: the OWNER revokes this device's token from the
     *  phone/desktop app (auth.revoke_token, already built and per-device -
     *  see README.md §4.6); this call only clears the LOCAL copy, for a
     *  "re-pair this watch" flow. */
    fun clear(context: Context) {
        prefs(context).edit().clear().apply()
    }

    // ---- Henry transcript ----------------------------------------------------
    // Owner, 2026-08-29: "Der chat sollte gecacht sein, nicht dass die Uhr immer
    // alle Nachrichten jedes Mal laden muss."
    //
    // Kept in the ENCRYPTED store above, deliberately NOT in the plain UI file
    // below: these lines are whatever Henry said about the owner's cards, i.e.
    // the same class of content the relay is end-to-end encrypted for. Writing
    // them in cleartext onto a device that leaves the house on a wrist would
    // quietly undo that. The cache is local only - the watch never re-fetches a
    // history from the daemon, so this costs no round trip.
    private const val K_CHAT = "chat"
    /** Bounded on purpose. EncryptedSharedPreferences rewrites the whole value
     *  on every save, so an unbounded transcript would make each reply slower
     *  than the last; 40 lines is far more than a round screen can usefully
     *  scroll and still trivially small to re-encrypt. */
    const val CHAT_MAX = 40

    /** One cached message. `ts` is the "HH:mm" stamp the chat shows next to the
     *  sender - EMPTY, never faked, for a line cached before this field existed
     *  or for one the daemon sent without a stamp. The chat simply omits the
     *  time in that case; inventing one would put a wrong minute on a real
     *  message, which is worse than showing none.
     *
     *  `label` is the mirrored card event's "Frage · Kartenname" (empty on an
     *  ordinary line). Cached along with the text because the alternative is
     *  worse than losing it: a card line restored WITHOUT its label renders
     *  under Henry's name, so for the moment before the server transcript
     *  arrives the owner would read a worker waiting on a decision as Henry
     *  talking. The card id and its option buttons are deliberately NOT cached
     *  - they are live interaction state, and offering a tap on a question
     *  whose current state we have not re-read is how a stale answer happens. */
    data class ChatLine(val mine: Boolean, val text: String, val ts: String,
                        val date: String = "", val label: String = "")

    /** Cached messages, oldest first. Empty when nothing is stored or the blob
     *  is unreadable - a corrupt cache must cost the history, never the
     *  screen. */
    fun loadChat(context: Context): List<ChatLine> {
        val raw = prefs(context).getString(K_CHAT, null) ?: return emptyList()
        return try {
            val arr = org.json.JSONArray(raw)
            val out = ArrayList<ChatLine>(arr.length())
            for (i in 0 until arr.length()) {
                val o = arr.optJSONObject(i) ?: continue
                // "s" is absent in a blob written before timestamps existed, and
                // optString then yields "" - which is exactly the "no stamp"
                // case above. An old cache stays readable; it just shows no
                // times until the server history replaces it a second later.
                out.add(ChatLine(o.optBoolean("m"), o.optString("t"),
                                 o.optString("s"), o.optString("d"),
                                 // "l" absent in a blob written before the card
                                 // mirror existed -> "" -> an ordinary line,
                                 // which is exactly what those all were.
                                 o.optString("l")))
            }
            out
        } catch (_: Exception) {
            emptyList()
        }
    }

    fun saveChat(context: Context, lines: List<ChatLine>) {
        val kept = if (lines.size > CHAT_MAX) lines.subList(lines.size - CHAT_MAX, lines.size) else lines
        val arr = org.json.JSONArray()
        for (line in kept) {
            arr.put(org.json.JSONObject()
                .put("m", line.mine).put("t", line.text).put("s", line.ts)
                .put("d", line.date).put("l", line.label))
        }
        prefs(context).edit().putString(K_CHAT, arr.toString()).apply()
    }

    fun clearChat(context: Context) {
        prefs(context).edit().remove(K_CHAT).apply()
    }

    // ---- UI preferences (NOT credentials) -----------------------------------
    // Deliberately a SEPARATE, PLAIN SharedPreferences file. Everything in the
    // encrypted store above is either a live credential or key material; a
    // "should Henry speak out loud" toggle is neither, and putting it there
    // would mean every tap rewrites an AES-GCM blob and unlocks the Android
    // Keystore for a boolean. Losing this file costs the owner one tap.
    private const val UI_FILE = "helmdeck_ui"
    private const val K_VOICE_ON = "voice_on"

    /** Defaults to FALSE (owner, 2026-08-29: "Text chat zuerst, dann gibt es
     *  eine Taste um voice zu aktivieren"). The daemon renders the clip
     *  unconditionally either way (routes_wear.py); this only decides whether
     *  the watch PLAYS it. Starting silent is the safe direction to be wrong
     *  in: an unexpected voice in a meeting costs more than a tap. */
    fun loadVoiceOn(context: Context): Boolean =
        context.getSharedPreferences(UI_FILE, Context.MODE_PRIVATE)
            .getBoolean(K_VOICE_ON, false)

    fun saveVoiceOn(context: Context, on: Boolean) {
        context.getSharedPreferences(UI_FILE, Context.MODE_PRIVATE)
            .edit().putBoolean(K_VOICE_ON, on).apply()
    }
}
