package app.swarmdeck

import android.net.Uri
import android.os.Bundle
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch

/**
 * Timeline-first review (locked decision): the step list leads, video is drill-down.
 * The video is DOWNLOADED into phone storage before playing — the phone is the archive
 * of record (APK rule), so a reviewed run survives the desktop deleting anything.
 */
class ReviewActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        HubStore.init(this)
        val runId = intent.getStringExtra("runId") ?: return finish()

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 48, 32, 32)
        }
        val title = TextView(this).apply { text = runId; textSize = 18f }
        val steps = ListView(this)
        val video = VideoView(this)
        val load = Button(this).apply { text = "Load video (pulls to phone)" }
        root.addView(title)
        root.addView(steps, LinearLayout.LayoutParams(-1, 0, 1f))
        root.addView(load)
        root.addView(video, LinearLayout.LayoutParams(-1, 600))
        setContentView(root)

        lifecycleScope.launch {
            try {
                val tl = DaemonClient.timeline(runId)
                val items = ArrayList<String>()
                for (i in 0 until tl.length()) {
                    val s = tl.getJSONObject(i)
                    val mark = if (s.optString("kind") == "flag") "⚑ " else ""
                    items.add("%s%.1fs  %s — %s".format(
                        mark, s.optDouble("t"), s.optString("kind"), s.optString("detail")))
                }
                steps.adapter = ArrayAdapter(this@ReviewActivity,
                    android.R.layout.simple_list_item_1, items)
            } catch (e: Exception) {
                title.text = "$runId — timeline unavailable (${e.message})"
            }
        }
        load.setOnClickListener {
            load.isEnabled = false; load.text = "downloading…"
            lifecycleScope.launch {
                val f = DaemonClient.downloadVideo(runId)
                if (f != null) {
                    load.text = "saved on phone ✓"
                    video.setVideoURI(Uri.fromFile(f))
                    video.setMediaController(MediaController(this@ReviewActivity))
                    video.start()
                } else {
                    load.text = "no video for this run"
                }
            }
        }
    }
}
