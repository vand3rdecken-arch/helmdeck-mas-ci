package app.swarmdeck

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch
import org.json.JSONArray

/**
 * Hub home: daemon pairing + the run list, timeline-first. Tap a run -> ReviewActivity;
 * LIVE button -> LiveActivity glance. Programmatic UI to stay dependency-thin in v0.1.
 */
class MainActivity : AppCompatActivity() {
    private lateinit var list: ListView
    private lateinit var status: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        HubStore.init(this)

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 48, 32, 32)
        }
        val addr = EditText(this).apply {
            hint = "daemon url, e.g. http://192.168.1.20:8140"
            setText(HubStore.daemonUrl)
        }
        status = TextView(this)
        val row = LinearLayout(this)
        val save = Button(this).apply {
            text = "Pair"
            setOnClickListener {
                HubStore.daemonUrl = addr.text.toString()
                refresh()
            }
        }
        val live = Button(this).apply {
            text = "Live"
            setOnClickListener { startActivity(Intent(this@MainActivity, LiveActivity::class.java)) }
        }
        row.addView(save); row.addView(live)
        list = ListView(this)
        root.addView(addr); root.addView(row); root.addView(status)
        root.addView(list, LinearLayout.LayoutParams(-1, -1))
        setContentView(root)

        if (HubStore.daemonUrl.isNotEmpty()) refresh() else renderIndex(HubStore.runIndex)
    }

    private fun refresh() {
        status.text = "syncing…"
        lifecycleScope.launch {
            try {
                renderIndex(DaemonClient.runs())
                status.text = ""
            } catch (e: Exception) {
                status.text = "daemon unreachable — showing cached index"
                renderIndex(HubStore.runIndex)
            }
        }
    }

    private fun renderIndex(idx: JSONArray) {
        val items = ArrayList<String>()
        val ids = ArrayList<String>()
        for (i in 0 until idx.length()) {
            val m = idx.getJSONObject(i)
            items.add("${m.optString("title")}\n${m.optString("id")} · ${m.optString("kind")} · " +
                    "${m.optString("status")} · ${m.optInt("steps")} steps")
            ids.add(m.optString("id"))
        }
        if (items.isEmpty()) {
            items.add("No runs yet — record a demo or start a task on the desktop.")
        }
        list.adapter = ArrayAdapter(this, android.R.layout.simple_list_item_1, items)
        list.setOnItemClickListener { _, _: View?, pos, _ ->
            if (pos < ids.size) startActivity(
                Intent(this, ReviewActivity::class.java).putExtra("runId", ids[pos]))
        }
    }
}
