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

/**
 * `detail` and `body` are two DIFFERENT things and the card screen shows both:
 *
 *   detail - WHY this card is stuck on the owner (glance_payload's own field,
 *            160 chars, from blockers.blocker(); empty for a card that is not
 *            blocked, i.e. every pipeline row).
 *   body   - WHAT last happened on it: the machine's last reply, ask-block and
 *            markdown stripped by routes_wear._wear_text.
 *
 * Both were on the wire (detail) or trivially derivable (body) all along and the
 * watch carried neither, which is why an opened card showed only its title -
 * owner, 2026-08-29: "wenn ich auf Karte gehe ist nichts da."
 */
data class BoardCard(
    val id: String, val task: String, val reason: String,
    val question: QuestionBlock?,
    val detail: String = "", val body: String = "", val status: String = "",
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

/**
 * The rest of glance_payload() - everything the watch used to throw away.
 *
 * Owner, 2026-08-29: "Wie funktioniert boards? Es zeigt derzeit nichts an."
 * The route was never the problem: spine/ops/glances.py returns `needs_you`,
 * a SECOND bucket `yours` (cards only the owner can ever start - mode
 * human/teach/cowork, which every auto-dispatch path structurally skips), an
 * `econ` block with the work-in-progress numbers, and a timestamp. The watch
 * parsed only `needs_you`, so an empty first bucket rendered as "Alles klar."
 * while the daemon had just told it how much work was in flight.
 *
 * `ts` matters for the same reason glances.py's own comment gives: "a stale
 * all-clear is the exact failure this endpoint exists to prevent". A watch
 * screen that says nothing is wrong, without saying WHEN that was true, is
 * precisely that failure.
 */
data class BoardSummary(
    val yours: Int,
    val wip: Int,
    val wipLimit: Int,
    val tsEpochSec: Long,
)

fun parseBoardSummary(boardJson: String): BoardSummary? {
    val o = runCatching { JSONObject(boardJson) }.getOrNull() ?: return null
    val econ = o.optJSONObject("econ")
    return BoardSummary(
        // Prefer econ's counts - glances.py builds the number and the list from
        // ONE derivation on purpose, "they cannot disagree the way a separately
        // counted total could". Fall back to the array only if econ is absent.
        yours = econ?.optInt("yours") ?: (o.optJSONArray("yours")?.length() ?: 0),
        wip = econ?.optInt("wip") ?: 0,
        wipLimit = econ?.optInt("wip_limit") ?: 0,
        tsEpochSec = o.optLong("ts", 0L),
    )
}

/** "gerade eben" / "vor 5 min" / "vor 2 h" - so an all-clear can be told apart
 *  from a stale one at a glance. 0 means the daemon sent no stamp. */
fun freshness(tsEpochSec: Long, nowEpochSec: Long): String {
    if (tsEpochSec <= 0L) return ""
    val age = nowEpochSec - tsEpochSec
    return when {
        age < 0L -> ""              // clock skew - say nothing rather than lie
        age < 90L -> "gerade eben"
        age < 3600L -> "vor ${age / 60} min"
        age < 86400L -> "vor ${age / 3600} h"
        else -> "vor ${age / 86400} d"
    }
}

/** The `yours` bucket as real, tappable cards - not just a number.
 *
 *  glances.py keeps these separate from needs_you on purpose ("merging them
 *  would bury a red gate under a backlog"), and the watch keeps that order:
 *  blocked work first, unstarted-only-you work after. But a count alone tells
 *  the owner there IS work without telling him which, which on a wrist is the
 *  same as not telling him. They carry no question (nothing has run yet), so
 *  `question` is null by construction. */
fun parseYours(boardJson: String): List<BoardCard> {
    val o = runCatching { JSONObject(boardJson) }.getOrNull() ?: return emptyList()
    val arr = o.optJSONArray("yours") ?: return emptyList()
    val out = mutableListOf<BoardCard>()
    for (i in 0 until arr.length()) {
        val c = arr.optJSONObject(i) ?: continue
        out.add(BoardCard(
            id = c.optString("id"), task = c.optString("task"),
            reason = "yours", question = null,
            body = c.optString("body"), status = c.optString("status")))
    }
    return out
}

/** The pipeline sections /wear/board adds on top of glance_payload: what the
 *  machine is doing, and what is queued behind it. `total` can exceed the list
 *  length - the route caps each section at 5 rows for the wire. */
data class BoardSection(val cards: List<BoardCard>, val total: Int)

private fun sectionOf(o: JSONObject?, listKey: String, totalKey: String): BoardSection {
    val arr = o?.optJSONArray(listKey)
    val out = mutableListOf<BoardCard>()
    if (arr != null) {
        for (i in 0 until arr.length()) {
            val c = arr.optJSONObject(i) ?: continue
            out.add(BoardCard(id = c.optString("id"), task = c.optString("task"),
                              reason = listKey, question = null,
                              body = c.optString("body"),
                              status = c.optString("status")))
        }
    }
    return BoardSection(out, o?.optInt(totalKey, out.size) ?: out.size)
}

/** (in Arbeit, Backlog). Empty sections when the daemon is older than this
 *  build and sends no `pipeline` - the screen then simply shows fewer rows
 *  rather than breaking. */
fun parsePipeline(boardJson: String): Pair<BoardSection, BoardSection> {
    val o = runCatching { JSONObject(boardJson) }.getOrNull()
    val p = o?.optJSONObject("pipeline")
    return Pair(sectionOf(p, "working", "working_total"),
                sectionOf(p, "backlog", "backlog_total"))
}

/** The blocker vocabulary (spine/turn/blockers.py BLOCKER_REASONS) plus the two
 *  watch-only pipeline buckets, in the owner's language. Unknown values fall
 *  back to "" rather than to a guess: a wrong label on a wrist is worse than
 *  none, and the body text below it carries the substance either way. */
fun reasonLabel(reason: String): String = when (reason) {
    "gate" -> "Gate rot"
    "conflict" -> "Merge-Konflikt"
    "failed" -> "Fehlgeschlagen"
    "question" -> "Frage offen"
    "review" -> "Wartet auf Abnahme"
    "delivered" -> "Fertig - abnehmen"
    "yours" -> "Nur von dir startbar"
    "working" -> "In Arbeit"
    "backlog" -> "Backlog"
    else -> ""
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
            question = parseQuestionBlock(c.optJSONObject("question")),
            detail = c.optString("detail"), body = c.optString("body"),
            status = c.optString("status")))
    }
    return out
}
