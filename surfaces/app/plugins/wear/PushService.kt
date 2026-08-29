package app.helmdeck.wear

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import app.helmdeck.wear.crypto.HelmDeckBox
import app.helmdeck.wear.data.DeviceStore
import app.helmdeck.wear.data.RelayClient
import com.google.firebase.messaging.FirebaseMessaging
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import org.json.JSONObject
import kotlin.concurrent.thread

/**
 * W2d - the watch as its own push recipient, no longer dependent on the phone
 * being nearby to bridge a notification.
 *
 * Mirrors the phone's path (surfaces/app/src/data/push.ts) rather than
 * inventing a second protocol: the daemon sends a DATA-ONLY FCM message whose
 * single `cipher` field is a NaCl box, and the client opens it locally and
 * raises the notification itself. Google transports ciphertext only and never
 * sees a card title - the same zero-knowledge property notify.py's own comment
 * describes for the phone.
 *
 * Two things are DIFFERENT from the phone and both matter:
 *   1. The box is sealed to THIS DEVICE's key (DeviceStore.myPublicKeyB64), not
 *      to the phone's. notify.recipients() seals per device precisely so the
 *      watch cannot open the phone's mail and vice versa.
 *   2. The token is registered through the SEALED RELAY, exactly like every
 *      other call this app makes - never over a plain HTTPS route. It carries
 *      this device's pubkey so the daemon can verify the key is one it actually
 *      admitted (routes_system.push_register_post refuses an unpinned key).
 */
object Push {
    // v2, and the version bump is the WHOLE FIX. A channel's importance and
    // vibration are IMMUTABLE after the first createNotificationChannel with a
    // given id - a later call with the same id only refreshes name/description
    // and silently ignores everything else. v1 was created without
    // enableVibration(true), and the watch recorded exactly that (measured
    // 2026-08-29 with `dumpsys notification`):
    //     mImportance=4, mVibrationEnabled=false, mVibrationPattern=null
    //     flags=AUTO_CANCEL|SILENT   (originalFlags=AUTO_CANCEL)
    // i.e. the notification ARRIVED and rendered, but the system added SILENT
    // and it never buzzed the wrist - useless on a device you do not look at.
    // Re-creating "helmdeck_cards" with vibration enabled would have changed
    // nothing; a new id is the only way to re-specify it.
    const val CHANNEL_ID = "helmdeck_cards_v2"
    private const val CHANNEL_ID_V1 = "helmdeck_cards"
    const val TAG = "HelmDeckPush"

    /** Android 8+ refuses to post without a channel; creating one that already
     *  exists is a documented no-op, so this is safe to call on every path. */
    fun ensureChannel(ctx: Context) {
        val mgr = ctx.getSystemService(NotificationManager::class.java) ?: return
        // Drop the silent v1 so it does not linger in the watch's own
        // notification settings as a second, confusing "HelmDeck" entry.
        runCatching { mgr.deleteNotificationChannel(CHANNEL_ID_V1) }
        val ch = NotificationChannel(CHANNEL_ID, "HelmDeck", NotificationManager.IMPORTANCE_HIGH)
        ch.enableVibration(true)
        // A short double buzz: long enough to feel through a sleeve, short
        // enough not to be the thing that makes him take the watch off.
        ch.vibrationPattern = longArrayOf(0L, 250L, 150L, 250L)
        mgr.createNotificationChannel(ch)
    }

    /**
     * Hand the current FCM token to the daemon. Safe to call repeatedly and
     * from anywhere - it is a no-op while unpaired.
     *
     * Called from THREE places on purpose, because any one of them alone loses
     * the token in a real sequence:
     *   - onNewToken (Firebase rotated it),
     *   - right after pairing (the token almost always arrived BEFORE there was
     *     a daemon to send it to - first launch mints it within seconds),
     *   - app start (covers a registration that failed while offline).
     */
    fun syncToken(ctx: Context) {
        val device = DeviceStore.load(ctx)
        if (device == null) {
            Log.i(TAG, "syncToken: not paired yet - nothing to register")
            return
        }
        // EVERY leg logs. The first cut of this function used a bare
        // addOnSuccessListener plus runCatching{} with no else and no catch
        // body: when the watch failed to register there was literally nothing
        // in logcat to say whether the token fetch, the relay call or the
        // daemon had refused - the same silent-failure shape this repo rejects
        // everywhere else. Cost one build cycle to find out; now it says.
        FirebaseMessaging.getInstance().token
            .addOnSuccessListener { token ->
                if (token.isNullOrEmpty()) {
                    Log.w(TAG, "syncToken: Firebase returned an empty token")
                    return@addOnSuccessListener
                }
                Log.i(TAG, "syncToken: got FCM token (len=${token.length}), registering")
                thread {
                    try {
                        val body = JSONObject()
                            .put("token", token)
                            .put("pub", device.myPublicKeyB64)
                            .put("label", "Watch")
                            .toString()
                        val (status, reply) = RelayClient.authedCall(
                            device.relayUrl, device.room, device.daemonPubB64,
                            device.myPublicKeyB64, device.mySecretKeyB64,
                            device.deviceToken, "POST", "/push/register", body)
                        // 403 here means the daemon does not consider this
                        // device's key pinned - a real, actionable answer, not
                        // a network hiccup. Worth saying out loud.
                        Log.i(TAG, "syncToken: /push/register -> $status $reply")
                    } catch (e: Exception) {
                        Log.w(TAG, "syncToken: relay call failed: $e")
                    }
                }
            }
            .addOnFailureListener { e ->
                Log.w(TAG, "syncToken: FCM token fetch failed: $e")
            }
    }
}

class PushService : FirebaseMessagingService() {

    override fun onNewToken(token: String) {
        Push.syncToken(applicationContext)
    }

    override fun onMessageReceived(message: RemoteMessage) {
        // Unpaired: there is no key to open the box with. Dropping is correct -
        // a notification we cannot read has no content to show.
        val device = DeviceStore.load(applicationContext) ?: return
        val cipher = message.data["cipher"] ?: return
        val plain = runCatching {
            HelmDeckBox.openB64(cipher, device.mySecretKeyB64, device.daemonPubB64)
        }.getOrNull() ?: return          // tampered, or sealed to another device
        val o = runCatching { JSONObject(plain) }.getOrNull() ?: return
        show(
            title = o.optString("title", "HelmDeck"),
            body = o.optString("body", ""),
            trackId = o.optString("track", ""),
        )
    }

    private fun show(title: String, body: String, trackId: String) {
        Push.ensureChannel(applicationContext)
        // POST_NOTIFICATIONS is a RUNTIME permission from API 33 on, and this
        // watch is API 36. Posting without it throws nothing - it silently does
        // nothing, which would look exactly like "push is broken". Checked here
        // so the failure is at least visible in logcat.
        if (androidx.core.content.ContextCompat.checkSelfPermission(
                applicationContext, android.Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED) {
            android.util.Log.w("HelmDeckPush",
                "notification dropped - POST_NOTIFICATIONS not granted")
            return
        }
        val open = Intent(applicationContext, MainActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        }
        val pending = PendingIntent.getActivity(
            applicationContext, 0, open,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val n = NotificationCompat.Builder(applicationContext, Push.CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setContentIntent(pending)
            .build()
        // One notification per CARD: a second push about the same card replaces
        // the first instead of stacking, which on a wrist is the difference
        // between a reminder and a pile. Cards without an id fall back to a
        // single shared slot rather than to a random one.
        NotificationManagerCompat.from(applicationContext)
            .notify(if (trackId.isEmpty()) 1 else trackId.hashCode(), n)
    }
}
