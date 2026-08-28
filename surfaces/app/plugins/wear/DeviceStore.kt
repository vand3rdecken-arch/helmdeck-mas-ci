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
}
