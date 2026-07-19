package app.swarmdeck

import android.os.Bundle
import android.view.View
import android.widget.*
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject

/**
 * The kanban board on the phone — same verbs as the desktop board. Lanes as tabs
 * (a 4-column drag board doesn't fit a phone), cards per lane, tap a card for the
 * session view: history + steer + the lane verbs (Dispatch / Submit / Accept).
 * Under the hood it's the client-request structure; the user just sees a board.
 */
class BoardActivity : AppCompatActivity() {
    private val lanes = listOf("backlog" to "Backlog", "working" to "Working",
                               "review" to "Review", "done" to "Done")
    private var lane = "working"
    private var all = JSONArray()
    private lateinit var list: ListView
    private lateinit var status: TextView
    private lateinit var tabs: LinearLayout

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        HubStore.init(this)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; setPadding(24, 40, 24, 24)
        }
        status = TextView(this)
        tabs = LinearLayout(this)
        list = ListView(this)
        val newBtn = Button(this).apply { text = "+ File request"; setOnClickListener { fileRequest() } }
        root.addView(tabs); root.addView(status)
        root.addView(list, LinearLayout.LayoutParams(-1, 0, 1f))
        root.addView(newBtn)
        setContentView(root)
        buildTabs()
        refresh()
    }

    private fun buildTabs() {
        tabs.removeAllViews()
        for ((key, label) in lanes) {
            tabs.addView(Button(this).apply {
                text = label
                alpha = if (key == lane) 1f else 0.5f
                layoutParams = LinearLayout.LayoutParams(0, -2, 1f)
                setOnClickListener { lane = key; buildTabs(); render() }
            })
        }
    }

    private fun refresh() {
        lifecycleScope.launch {
            try { all = DaemonClient.tracks(); status.text = ""; render() }
            catch (e: Exception) { status.text = "daemon unreachable" }
        }
    }

    private fun inLane(): List<JSONObject> =
        (0 until all.length()).map { all.getJSONObject(it) }
            .filter { it.optString("lane", "working") == lane }

    private fun render() {
        val ts = inLane()
        val items = ts.map {
            "${it.optString("task").take(60)}\n${it.optString("branch")} · " +
            "${it.optInt("turns")} turns · ${it.optString("status")}"
        }.ifEmpty { listOf("nothing in ${lane}") }
        list.adapter = ArrayAdapter(this, android.R.layout.simple_list_item_1, items)
        list.setOnItemClickListener { _, _: View?, pos, _ ->
            if (pos < ts.size) openTrack(ts[pos])
        }
    }

    private fun openTrack(t: JSONObject) {
        val id = t.optString("id")
        val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(40, 16, 40, 0) }
        val hist = TextView(this).apply { textSize = 13f; maxLines = 18 }
        val steer = EditText(this).apply { hint = "steer — context continues, no rebuild" }
        box.addView(hist); box.addView(steer)
        val dlg = AlertDialog.Builder(this)
            .setTitle(t.optString("branch"))
            .setView(box)
            .setPositiveButton("Steer") { _, _ ->
                val txt = steer.text.toString().trim()
                if (txt.isNotEmpty()) lifecycleScope.launch {
                    try { DaemonClient.steerTrack(id, txt); toast("steer sent — session resuming") }
                    catch (e: Exception) { toast("daemon unreachable") }
                    refresh()
                }
            }
            .setNeutralButton(nextVerb(t).second) { _, _ ->
                lifecycleScope.launch {
                    try { DaemonClient.moveLane(id, nextVerb(t).first); toast(nextVerb(t).second + " ✓") }
                    catch (e: Exception) { toast("daemon unreachable") }
                    refresh()
                }
            }
            .setNegativeButton("Close", null)
            .create()
        dlg.show()
        lifecycleScope.launch {
            try {
                val h = DaemonClient.trackHistory(id)
                hist.text = (0 until h.length()).joinToString("\n") {
                    val r = h.getJSONObject(it)
                    when (r.optString("kind")) {
                        "steer" -> "▸ " + r.optString("detail")
                        "reply" -> r.optString("detail").take(300)
                        else -> "· " + r.optString("detail").take(80)
                    }
                }
            } catch (e: Exception) { hist.text = "(history unavailable)" }
        }
    }

    /** The card's next workflow verb, mirroring a board drag. */
    private fun nextVerb(t: JSONObject): Pair<String, String> =
        when (t.optString("lane", "working")) {
            "backlog" -> "working" to "Dispatch"
            "working" -> "review" to "Submit"
            "review" -> "done" to "Accept"
            else -> "working" to "Reopen"
        }

    private fun toast(m: String) = Toast.makeText(this, m, Toast.LENGTH_SHORT).show()

    private fun fileRequest() {
        val box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(40, 16, 40, 0) }
        val repo = EditText(this).apply { hint = "repo path on the PC"; setText(HubStore.lastRepo) }
        val branch = EditText(this).apply { hint = "branch" }
        val task = EditText(this).apply { hint = "what needs doing" }
        box.addView(repo); box.addView(branch); box.addView(task)
        AlertDialog.Builder(this).setTitle("File a request (to Backlog)").setView(box)
            .setPositiveButton("File") { _, _ ->
                lifecycleScope.launch {
                    try {
                        HubStore.lastRepo = repo.text.toString()
                        DaemonClient.newTrack(repo.text.toString(), branch.text.toString(),
                                              task.text.toString())
                        toast("request filed"); lane = "backlog"; buildTabs(); refresh()
                    } catch (e: Exception) { toast("daemon unreachable") }
                }
            }
            .setNegativeButton("Cancel", null).show()
    }
}
