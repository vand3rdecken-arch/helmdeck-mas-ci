package app.swarmdeck

import android.graphics.BitmapFactory
import android.os.Bundle
import android.widget.ImageView
import android.widget.TextView
import android.widget.LinearLayout
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * Live glance: refresh the daemon's newest frame ~1/s while this screen is open.
 * Same "newest frame only" philosophy as the Herald cast relay — no stream state,
 * nothing stored, dies silently when no run is active.
 */
class LiveActivity : AppCompatActivity() {
    private var watching = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        HubStore.init(this)
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        val label = TextView(this).apply { text = "LIVE — what the swarm is doing"; setPadding(32, 48, 32, 8) }
        val img = ImageView(this)
        root.addView(label)
        root.addView(img, LinearLayout.LayoutParams(-1, -1))
        setContentView(root)

        watching = true
        lifecycleScope.launch {
            while (watching) {
                try {
                    val bytes = DaemonClient.liveFrame()
                    if (bytes != null) {
                        img.setImageBitmap(BitmapFactory.decodeByteArray(bytes, 0, bytes.size))
                        label.text = "LIVE — what the swarm is doing"
                    } else {
                        label.text = "no agent is on the desk right now"
                    }
                } catch (e: Exception) {
                    label.text = "daemon unreachable"
                }
                delay(1000)
            }
        }
    }

    override fun onDestroy() {
        watching = false
        super.onDestroy()
    }
}
