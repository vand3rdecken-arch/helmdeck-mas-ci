package app.helmdeck.wear

import org.json.JSONObject

/** Kotlin mirror of _glance_question()'s shape (spine/ops/glances.py, read
 *  this session) - reused UNCHANGED by both GET /wear/board (per card) and
 *  POST /wear/talk (Henry's own suggested next moves). One shape, one
 *  parser, both call sites. */
data class QuestionOption(val label: String, val description: String)
data class QuestionItem(
    val question: String, val header: String, val multiSelect: Boolean,
    val options: List<QuestionOption>,
)
data class QuestionBlock(val id: String, val questions: List<QuestionItem>)

data class BoardCard(
    val id: String, val task: String, val reason: String,
    val question: QuestionBlock?,
)

/** Parses a `question` field (routes_wear.py's _glance_question() JSON) into
 *  QuestionBlock, or null - mirrors the exact field names read from
 *  spine/ops/glances.py this session, not guessed. */
fun parseQuestionBlock(o: JSONObject?): QuestionBlock? {
    if (o == null) return null
    val qs = o.optJSONArray("questions") ?: return null
    val items = mutableListOf<QuestionItem>()
    for (i in 0 until qs.length()) {
        val q = qs.getJSONObject(i)
        val opts = mutableListOf<QuestionOption>()
        val optsArr = q.optJSONArray("options")
        if (optsArr != null) {
            for (j in 0 until optsArr.length()) {
                val op = optsArr.getJSONObject(j)
                opts.add(QuestionOption(op.optString("label"), op.optString("description")))
            }
        }
        items.add(QuestionItem(
            question = q.optString("question"), header = q.optString("header"),
            multiSelect = q.optBoolean("multiSelect", false), options = opts))
    }
    if (items.isEmpty()) return null
    return QuestionBlock(id = o.optString("id"), questions = items)
}

fun parseBoardCards(boardJson: String): List<BoardCard> {
    val o = JSONObject(boardJson)
    val ny = o.optJSONArray("needs_you") ?: return emptyList()
    val out = mutableListOf<BoardCard>()
    for (i in 0 until ny.length()) {
        val c = ny.getJSONObject(i)
        out.add(BoardCard(
            id = c.optString("id"), task = c.optString("task"),
            reason = c.optString("reason"),
            question = parseQuestionBlock(c.optJSONObject("question"))))
    }
    return out
}
