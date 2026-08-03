package app.swarmdeck

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * Signal-style push: the daemon seals {title, body, track} with the pairing
 * keys (NaCl box) and FCM delivers only that ciphertext. This service opens
 * the box locally - Google never sees content, and a message that does not
 * decrypt with OUR pairing keys is silently dropped (it cannot be from our
 * daemon). Tapping the notification opens the app on the card.
 */
class PushService : FirebaseMessagingService() {

    override fun onMessageReceived(msg: RemoteMessage) {
        val cipher = msg.data["cipher"] ?: return
        val plain = try {
            HubStore.init(applicationContext)
            String(E2ee.open(cipher, HubStore.ownSk, HubStore.daemonPub))
        } catch (_: Exception) { return }          // not sealed for this pairing
        val o = try { JSONObject(plain) } catch (_: Exception) { return }
        show(applicationContext, o.optString("title", "SwarmDeck"),
             o.optString("body"), o.optString("track"))
    }

    override fun onNewToken(token: String) {
        // token rotated while the app was closed - re-announce it to the daemon
        try { HubStore.init(applicationContext) } catch (_: Exception) { return }
        if (!DaemonClient.configured()) return
        CoroutineScope(Dispatchers.IO).launch {
            runCatching { DaemonClient.registerPushToken(token) }
        }
    }

    companion object {
        private const val CHANNEL = "cards"

        fun show(ctx: Context, title: String, body: String, track: String) {
            val nm = ctx.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL, "Card updates", NotificationManager.IMPORTANCE_HIGH))
            val open = Intent(ctx, MainActivity::class.java).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
                putExtra("track", track)
            }
            val pi = PendingIntent.getActivity(ctx, track.hashCode(), open,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            nm.notify(track.hashCode(), NotificationCompat.Builder(ctx, CHANNEL)
                .setSmallIcon(android.R.drawable.stat_notify_sync)
                .setContentTitle(title).setContentText(body)
                .setStyle(NotificationCompat.BigTextStyle().bigText(body))
                .setAutoCancel(true).setContentIntent(pi).build())
        }
    }
}
