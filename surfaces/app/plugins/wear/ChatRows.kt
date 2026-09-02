package app.helmdeck.wear

/**
 * THE HENRY CHAT'S LAYOUT, as data.
 *
 * Deliberately free of Compose and of Android: no imports at all. That is not
 * tidiness, it is what makes the thing verifiable - `ops/tests/wear_chat_rows.kt`
 * compiles THIS FILE (not a copy of it) with kotlinc and asserts the indices,
 * which is the only way to check the bug below without a paired watch.
 *
 * WHY IT EXISTS (owner report 2026-08-31: "Wear-OS-Chat scrollt NICHT
 * automatisch zur neuesten Nachricht"):
 *
 * The screen used to scroll to `lines.size - 1`. That is an index in LINE
 * space, but a TransformingLazyColumn addresses ITEM space, and the two have
 * never been the same list: item 0 is the "Henry" title, every day change
 * inserts a separator, every unanswered card question adds one button per
 * option, and three fixed buttons close the list. With a single date separator
 * the newest message actually sits at `lines.size + 1`, so the old target
 * landed two items short - and on a watch that shows one or two cards at a
 * time, "two items short" means the new message is below the fold. Every extra
 * separator drifted it one further, so a chat spanning several days scrolled
 * progressively further from the thing it was aiming at.
 *
 * The layout existed ONLY as control flow (a `for` over `lines` with the
 * separators and buttons inlined as `item { }` calls), so nothing could ask it
 * where the newest message had ended up - the scroll target had to be guessed,
 * and the guess was wrong. Building the list as data first means the renderer
 * and the scroller read the SAME description: the index is derived from the
 * layout, not reconstructed alongside it (CLAUDE.md - no monkey patches:
 * one owner, derived, never assumed).
 */

/** One line of the conversation: who said it, what, and when.
 *
 *  `ts` is the daemon's own "HH:mm" (copilot's log stamp, passed through by
 *  wear_chat_get) for a message read back from the server, and the WATCH's
 *  clock for one that was just sent or just answered - /wear/talk returns no
 *  stamp, and the moment the line appears is the honest answer for it. Empty
 *  when neither is available; the chat then shows the name without a time
 *  rather than inventing a minute.
 *
 *  `label`, `card` and `options` are set only on a MIRRORED CARD EVENT (cls
 *  "card" server-side, cells/copilot/card_mirror.py). `label` is the composed
 *  "Frage · Kartenname" that replaces the sender name, so the owner can tell a
 *  worker waiting on a decision from Henry talking; `card` is the id an answer
 *  goes back to; `options` are the worker's own choices when one tap settles
 *  it. All three are empty on an ordinary line, and an older daemon omits them
 *  from the payload entirely - which degrades to exactly the previous
 *  behaviour, never to a blank.
 *
 *  `key` is the server's identity for a SPEAKABLE line (routes_wear's
 *  _wear_msg_key, sent on exactly the classes GET /wear/voice will render), and
 *  its presence is the whole "this one can be spoken" signal - an ordinary line
 *  carries "". It is what lets the screen tell a NEW answer from the same
 *  answer seen again: refresh() replaces the list wholesale, so a position
 *  ("the last one", "lines.size") says nothing about identity, which is the
 *  same trap the auto-scroll below already had to be keyed around. Not cached
 *  by DeviceStore, deliberately: a key restored from disk would let the app
 *  decide on startup that an answer from yesterday is still owed out loud. */
data class Line(val mine: Boolean, val text: String, val ts: String = "",
                val date: String = "", val label: String = "",
                val card: String = "", val options: List<String> = emptyList(),
                val key: String = "")

/** ONE ROW OF THE LIST - and the ONLY description of what the list contains. */
sealed interface Row {
    data object Title : Row
    data class Hint(val text: String) : Row
    data class Day(val date: String) : Row
    data class Msg(val line: Line) : Row
    data class Option(val card: String, val label: String) : Row
    data object Busy : Row
    data class Suggest(val label: String) : Row
    data object Speak : Row
    data object VoiceToggle : Row
    data object Board : Row
}

/** The whole screen as a flat list, in draw order.
 *
 *  `suggestOptions` is Henry's own follow-up choices as plain labels rather
 *  than the QuestionBlock they come from: this file is the one part of the
 *  screen that must stay compilable without org.json, and the labels are all
 *  the layout has ever needed. */
fun buildRows(
    lines: List<Line>, answered: Set<String>, busy: Boolean,
    hint: String, suggestOptions: List<String>,
): List<Row> {
    val rows = ArrayList<Row>(lines.size + 8)
    rows.add(Row.Title)
    if (lines.isEmpty()) rows.add(Row.Hint(hint))
    // DATE SEPARATORS, exactly where the owner's SMS screenshot has them: one
    // centred caption above the first message of each day.
    //
    // Drawn ONLY from a recorded date. copilot._append_log started stamping one
    // on 2026-08-29 and everything older has none, so `date` is "" for the
    // existing transcript - and a line with no date gets no separator and does
    // not close the previous day either. Filing an undated message under
    // whatever day happened to precede it would be a guess rendered as a fact.
    var lastDay = ""
    for (line in lines) {
        if (line.date.isNotBlank() && line.date != lastDay) {
            lastDay = line.date
            rows.add(Row.Day(line.date))
        }
        rows.add(Row.Msg(line))
        // The worker's OWN options, right under the question that offered them -
        // not collected at the bottom like Henry's follow-up suggestions. Two
        // cards can be waiting at once, and a pooled list would give the owner
        // no way to see which card a button belongs to.
        if (line.card.isNotBlank() && line.card !in answered) {
            for (opt in line.options) rows.add(Row.Option(line.card, opt))
        }
    }
    if (busy) rows.add(Row.Busy)
    for (opt in suggestOptions) rows.add(Row.Suggest(opt))
    rows.add(Row.Speak)
    rows.add(Row.VoiceToggle)
    rows.add(Row.Board)
    return rows
}

/** Where the newest message ended up, or -1 when there is none.
 *
 *  -1 is also the "do not scroll" answer: the first version of the auto-follow
 *  scrolled on the very first composition, when the list was still empty, and
 *  pushed the title and the hint up under the clock so the screen opened
 *  half-cut (seen on the watch, 2026-08-29). An empty chat opens at the TOP. */
fun newestMessageIndex(rows: List<Row>): Int = rows.indexOfLast { it is Row.Msg }
