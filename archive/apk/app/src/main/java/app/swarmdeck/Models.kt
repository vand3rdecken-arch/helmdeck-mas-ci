package app.swarmdeck

import org.json.JSONArray
import org.json.JSONObject

/** Mirrors the daemon's track shape (see daemon/sessions.py) - the fields the
 *  desktop card surface uses, so the phone can offer the same operations. */
data class Track(
    val id: String,
    val task: String,
    val lane: String,
    val status: String?,
    val client: String?,
    val branch: String?,
    val repo: String?,
    val driver: String?,
    val priority: String?,
    val due: String?,
    val description: String?,
    val billing: String?,
    val rate: Double?,
    val value: Double?,
    val aiCost: Double,
    val turns: Int,
    val sessionId: String?,
    val workBy: String?,
    val mode: String?,
    val updated: String?,
    val lastReply: String?,
) {
    companion object {
        fun from(o: JSONObject) = Track(
            id = o.optString("id"),
            task = o.optString("task"),
            lane = o.optString("lane", "backlog"),
            status = o.optString("status").ifEmpty { null },
            client = o.optString("client").ifEmpty { null },
            branch = o.optString("branch").ifEmpty { null },
            repo = o.optString("repo").ifEmpty { null },
            driver = o.optString("driver").ifEmpty { null },
            priority = o.optString("priority").ifEmpty { null },
            due = o.optString("due").ifEmpty { null },
            description = o.optString("description").ifEmpty { null },
            billing = o.optString("billing").ifEmpty { null },
            rate = if (o.isNull("rate")) null else o.optDouble("rate"),
            value = if (o.isNull("value")) null else o.optDouble("value"),
            aiCost = o.optDouble("ai_cost", 0.0),
            turns = o.optInt("turns", 0),
            sessionId = o.optString("session_id").ifEmpty { null },
            workBy = o.optString("work_by").ifEmpty { null },
            mode = o.optString("mode").ifEmpty { null },
            updated = o.optString("updated").ifEmpty { null },
            lastReply = o.optString("last_reply").ifEmpty { null },
        )
        fun list(a: JSONArray): List<Track> =
            (0 until a.length()).mapNotNull { i -> a.optJSONObject(i)?.let { from(it) } }
    }
}

/** One rendered line of a session transcript (daemon/claude_sessions.py). */
data class Step(
    val kind: String,          // text | thinking | tool | todos | plan | compaction
    val role: String?,
    val text: String?,
    val tool: String?,
    val result: String?,
    val ok: Boolean,
    val running: Boolean,
    val streaming: Boolean,
    val ts: String?,
    val todos: List<Pair<String, String>>,   // content to status
) {
    companion object {
        fun from(o: JSONObject): Step {
            val todos = mutableListOf<Pair<String, String>>()
            o.optJSONArray("todos")?.let { arr ->
                for (i in 0 until arr.length()) arr.optJSONObject(i)?.let {
                    todos += it.optString("content") to it.optString("status")
                }
            }
            return Step(
                kind = o.optString("kind", "text"),
                role = o.optString("role").ifEmpty { null },
                text = o.optString("text").ifEmpty { null },
                tool = o.optString("tool").ifEmpty { null },
                result = o.optString("result").ifEmpty { null },
                ok = o.optBoolean("ok", true),
                running = o.optBoolean("running", false),
                streaming = o.optBoolean("streaming", false),
                ts = o.optString("ts").ifEmpty { null },
                todos = todos,
            )
        }
        fun list(a: JSONArray): List<Step> =
            (0 until a.length()).mapNotNull { i -> a.optJSONObject(i)?.let { from(it) } }
    }
}

/** Capacity/economics header the desktop shows above the board. */
data class Metrics(
    val wip: Int, val wipLimit: Int, val touches: Int, val touchBudget: Int, val headroom: Int,
    val billed: Double, val aiCost: Double, val margin: Double,
) {
    companion object {
        /** Parses /dashboard/data (daemon events.metrics) - the same payload the
         *  desktop header and dashboard use. */
        fun from(o: JSONObject): Metrics {
            val cap = o.optJSONObject("capacity") ?: JSONObject()
            val tot = o.optJSONObject("totals") ?: JSONObject()
            return Metrics(
                wip = cap.optInt("wip"), wipLimit = cap.optInt("wip_limit"),
                touches = cap.optInt("touches_today"), touchBudget = cap.optInt("touch_budget_day"),
                headroom = cap.optInt("headroom"),
                billed = tot.optDouble("value_delivered", 0.0),
                aiCost = tot.optDouble("ai_spend", 0.0),
                margin = tot.optDouble("margin", 0.0),
            )
        }
    }
}

data class Checkpoint(val turn: Int, val commit: String, val ts: String, val reply: String) {
    companion object {
        fun list(a: JSONArray): List<Checkpoint> = (0 until a.length()).mapNotNull { i ->
            a.optJSONObject(i)?.let {
                Checkpoint(it.optInt("turn"), it.optString("commit"), it.optString("ts"), it.optString("reply"))
            }
        }
    }
}

/** An existing Claude Code session from ~/.claude, adoptable onto the board. */
data class ClaudeSession(
    val id: String, val cwd: String, val project: String,
    val first: String, val lastActive: String,
) {
    companion object {
        fun list(a: JSONArray): List<ClaudeSession> = (0 until a.length()).mapNotNull { i ->
            a.optJSONObject(i)?.let {
                ClaudeSession(it.optString("id"), it.optString("cwd"), it.optString("project"),
                    it.optString("first"), it.optString("last_active"))
            }
        }
    }
}

data class Process(val id: String, val name: String, val client: String, val status: String, val steps: Int) {
    companion object {
        fun list(a: JSONArray): List<Process> = (0 until a.length()).mapNotNull { i ->
            a.optJSONObject(i)?.let {
                Process(it.optString("id"), it.optString("name"), it.optString("client"),
                    it.optString("status"), it.optJSONArray("steps")?.length() ?: 0)
            }
        }
    }
}

/** A commit from /history - the daemon returns the git audit trail
 *  ({head, main:[{h,msg,author,date}], branches:[...]}), not an event list. */
data class Commit(val hash: String, val msg: String, val author: String, val date: String, val branch: String) {
    companion object {
        fun fromHistory(o: JSONObject): List<Commit> {
            val out = mutableListOf<Commit>()
            fun add(arr: JSONArray?, branch: String) {
                if (arr == null) return
                for (i in 0 until arr.length()) arr.optJSONObject(i)?.let {
                    out += Commit(it.optString("h"), it.optString("msg"),
                        it.optString("author"), it.optString("date"), branch)
                }
            }
            add(o.optJSONArray("main"), o.optString("head", "main"))
            o.optJSONArray("branches")?.let { bs ->
                for (i in 0 until bs.length()) bs.optJSONObject(i)?.let { b ->
                    add(b.optJSONArray("commits"), b.optString("branch", "?"))
                }
            }
            return out
        }
    }
}

/** Per-card action log (/tracks/<id>/history) - this one IS a list. */
data class HistoryRow(val kind: String, val detail: String, val ts: String, val actor: String) {
    companion object {
        fun list(a: JSONArray): List<HistoryRow> = (0 until a.length()).mapNotNull { i ->
            a.optJSONObject(i)?.let {
                HistoryRow(it.optString("kind"), it.optString("detail"),
                    it.optString("ts"), it.optString("actor"))
            }
        }
    }
}
