// Where the Wear chat's newest message ACTUALLY sits.
//
// Compiles the REAL production file (surfaces/app/plugins/wear/ChatRows.kt) -
// not a copy of it - and checks the arithmetic that the owner's 2026-08-31
// report was about ("Wear-OS-Chat scrollt NICHT automatisch zur neuesten
// Nachricht"). The watch itself cannot answer this without a paired daemon, and
// the bug was never about the network: it was an index computed in LINE space
// against a list addressed in ITEM space.
//
// Run (from repo root):
//   py -3.12 ops/tests/wear_chat_rows.py
// which shells out to the Kotlin compiler already in the Gradle cache.

package helmdeck.check

import app.helmdeck.wear.Line
import app.helmdeck.wear.Row
import app.helmdeck.wear.buildRows
import app.helmdeck.wear.newestMessageIndex

private var failures = 0

private fun check(what: String, ok: Boolean, detail: String = "") {
    if (ok) println("  ok    $what")
    else { failures++; println("  FAIL  $what${if (detail.isEmpty()) "" else " - $detail"}") }
}

/** What the screen USED to aim at: `lines.size - 1`. Kept here so the check
 *  shows the defect, not just the fix - a test that only asserts the new
 *  behaviour cannot tell you whether it ever differed from the old one. */
private fun oldTarget(lines: List<Line>): Int = maxOf(0, lines.size - 1)

private const val HINT = "Tippe auf Sprechen und stelle deine Frage."

fun main() {
    // ---- 1. an ordinary one-day chat -------------------------------------
    val oneDay = (1..6).map { Line(mine = it % 2 == 1, text = "m$it", ts = "10:0$it", date = "2026-08-31") }
    var rows = buildRows(oneDay, emptySet(), busy = false, hint = HINT, suggestOptions = emptyList())
    var newest = newestMessageIndex(rows)
    check("newest index points at a message row", rows[newest] is Row.Msg, "row=${rows[newest]}")
    check("newest index points at the LAST message",
        (rows[newest] as Row.Msg).line.text == "m6", "got ${(rows[newest] as Row.Msg).line.text}")
    check("one-day chat: the OLD formula was wrong", oldTarget(oneDay) != newest,
        "old=${oldTarget(oneDay)} new=$newest")
    println("  ..    one day, 6 lines: rows=${rows.size} newest=$newest old=${oldTarget(oneDay)} " +
        "(old pointed at ${rows[oldTarget(oneDay)]::class.simpleName})")

    // ---- 2. several days: the drift grows one item per separator ----------
    val threeDays = listOf(
        Line(false, "a", "09:00", "2026-08-29"), Line(true, "b", "09:01", "2026-08-29"),
        Line(false, "c", "10:00", "2026-08-30"), Line(true, "d", "10:01", "2026-08-30"),
        Line(false, "e", "11:00", "2026-08-31"), Line(true, "f", "11:01", "2026-08-31"),
    )
    rows = buildRows(threeDays, emptySet(), busy = false, hint = HINT, suggestOptions = emptyList())
    newest = newestMessageIndex(rows)
    check("three-day chat: newest is still the last message",
        (rows[newest] as Row.Msg).line.text == "f")
    val drift = newest - oldTarget(threeDays)
    check("three-day chat: old formula drifted further than one-day (title + 3 separators)",
        drift == 4, "drift=$drift")
    println("  ..    three days, 6 lines: rows=${rows.size} newest=$newest " +
        "old=${oldTarget(threeDays)} drift=$drift")

    // ---- 3. an open card question adds option buttons --------------------
    val withCard = oneDay + Line(false, "Welche Option?", "10:07", "2026-08-31",
        label = "Frage · Karte", card = "c1", options = listOf("A", "B", "C"))
    rows = buildRows(withCard, emptySet(), busy = false, hint = HINT, suggestOptions = emptyList())
    newest = newestMessageIndex(rows)
    check("option buttons follow the question, not the end of the list",
        rows.getOrNull(newest + 1) is Row.Option && rows.last() is Row.Board)
    check("newest is the QUESTION itself, not a button",
        (rows[newest] as Row.Msg).line.card == "c1")

    // answered -> the buttons go away, and the newest index moves with them
    val answered = buildRows(withCard, setOf("c1"), busy = false, hint = HINT, suggestOptions = emptyList())
    check("answering a card removes exactly its option rows",
        rows.size - answered.size == 3, "delta=${rows.size - answered.size}")
    check("newest still lands on the question after answering",
        (answered[newestMessageIndex(answered)] as Row.Msg).line.card == "c1")

    // ---- 4. the trailing furniture is always last ------------------------
    rows = buildRows(oneDay, emptySet(), busy = true, hint = HINT, suggestOptions = listOf("ja", "nein"))
    newest = newestMessageIndex(rows)
    check("busy + suggestions sit AFTER the newest message", newest < rows.size - 6)
    check("list always ends Speak, VoiceToggle, Board",
        rows[rows.size - 3] is Row.Speak && rows[rows.size - 2] is Row.VoiceToggle &&
            rows[rows.size - 1] is Row.Board)

    // ---- 5. an empty chat must NOT scroll --------------------------------
    rows = buildRows(emptyList(), emptySet(), busy = false, hint = HINT, suggestOptions = emptyList())
    check("empty chat reports no newest message (opens at the top)", newestMessageIndex(rows) == -1)
    check("empty chat shows the hint", rows.any { it is Row.Hint })

    // ---- 6. undated lines get no separator (forward-only stamp) ----------
    val undated = listOf(Line(false, "old1"), Line(true, "old2"),
        Line(false, "new", "12:00", "2026-08-31"))
    rows = buildRows(undated, emptySet(), busy = false, hint = HINT, suggestOptions = emptyList())
    check("exactly one separator for one dated day", rows.count { it is Row.Day } == 1)
    check("newest is the dated line",
        (rows[newestMessageIndex(rows)] as Row.Msg).line.text == "new")

    println()
    println(if (failures == 0) "RESULT: PASS" else "RESULT: FAIL ($failures)")
    if (failures != 0) kotlin.system.exitProcess(1)
}
