import Foundation

/// The Henry chat's layout, as data - the Swift sibling of ChatRows.kt.
/// SwiftUI's `List` + `ScrollViewReader.scrollTo(id:)` addresses rows by
/// stable IDENTITY rather than by index, which is what the Kotlin file's
/// whole index-arithmetic bug (auto-scroll landing short of the newest
/// message on a TransformingLazyColumn) does not have a Swift equivalent
/// of - so this stays intentionally smaller: day separators and per-question
/// option rows, the two things that are genuinely list CONTENT rather than
/// chrome a SwiftUI List/Toolbar already gives for free (a title, an input
/// field, a voice toggle).
enum ChatRow: Identifiable {
    case day(String)
    case msg(Int, HenryLine)
    case option(Int, Int, String, String)

    var id: String {
        switch self {
        case .day(let date): return "day-\(date)"
        case .msg(let i, let line): return "msg-\(i)-\(line.id)"
        case .option(let i, let j, _, _): return "opt-\(i)-\(j)"
        }
    }
}

/// One row per message in order, a `Row.Day` above the first message of a
/// new calendar day, and the worker's own option buttons directly under the
/// question that offered them (never pooled at the bottom - two cards can be
/// waiting at once, and the owner needs to see which card a button belongs
/// to).
func buildChatRows(_ lines: [HenryLine], answered: Set<String>) -> [ChatRow] {
    var rows: [ChatRow] = []
    var lastDay = ""
    for (i, line) in lines.enumerated() {
        if !line.date.isEmpty && line.date != lastDay {
            lastDay = line.date
            rows.append(.day(line.date))
        }
        rows.append(.msg(i, line))
        if !line.card.isEmpty && !answered.contains(line.card) {
            for (j, opt) in line.options.enumerated() {
                rows.append(.option(i, j, line.card, opt))
            }
        }
    }
    return rows
}

private let dayKeyFormatter: DateFormatter = {
    let f = DateFormatter()
    f.dateFormat = "yyyy-MM-dd"
    f.locale = Locale(identifier: "de_DE")
    f.timeZone = .current
    return f
}()

private let dayCaptionFormatter: DateFormatter = {
    let f = DateFormatter()
    f.dateFormat = "dd.MM.yy"
    f.locale = Locale(identifier: "de_DE")
    return f
}()

private let hmFormatter: DateFormatter = {
    let f = DateFormatter()
    f.dateFormat = "HH:mm"
    f.locale = Locale(identifier: "de_DE")
    return f
}()

/// "HH:mm", 24h, matching the daemon's own time.strftime("%H:%M").
func nowHm() -> String { hmFormatter.string(from: Date()) }

/// "yyyy-MM-dd", matching copilot._append_log's own stamp - the key the
/// separator groups on.
func nowDate() -> String { dayKeyFormatter.string(from: Date()) }

/// "Heute", "Gestern", else "dd.MM.yy" - what every chat app does. An
/// unparseable stamp is printed verbatim rather than swallowed.
func dayLabel(_ date: String) -> String {
    let today = dayKeyFormatter.string(from: Date())
    if date == today { return "Heute" }
    if let yesterday = Calendar.current.date(byAdding: .day, value: -1, to: Date()),
       date == dayKeyFormatter.string(from: yesterday) {
        return "Gestern"
    }
    guard let d = dayKeyFormatter.date(from: date) else { return date }
    return dayCaptionFormatter.string(from: d)
}

/// Who is speaking, as the chat shows it - a mirrored card event uses its
/// own label ("Frage · Kartenname") instead of a name, because the message
/// is a card waiting on the owner, not Henry speaking.
func senderOf(_ line: HenryLine) -> String {
    if !line.label.isEmpty { return line.label }
    return line.mine ? "Du" : "Henry"
}
