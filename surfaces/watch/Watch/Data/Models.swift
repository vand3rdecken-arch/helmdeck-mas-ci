import Foundation

/// Mirrors _glance_question()'s shape (spine/ops/glances.py) - the Swift
/// sibling of BoardModel.kt's QuestionOption/QuestionItem/QuestionBlock.
/// Reused unchanged by both GET /wear/board (per card) and POST /wear/talk
/// (Henry's own suggested next moves).
struct QuestionOption: Identifiable, Hashable {
    var id: String { label }
    let label: String
    let description: String
}

struct QuestionItem {
    let question: String
    let header: String
    let multiSelect: Bool
    let options: [QuestionOption]
}

struct QuestionBlock {
    let id: String
    let questions: [QuestionItem]
}

func parseQuestionBlock(_ o: [String: Any]?) -> QuestionBlock? {
    guard let o, let qs = o["questions"] as? [[String: Any]], !qs.isEmpty else { return nil }
    let items: [QuestionItem] = qs.map { q in
        let opts = (q["options"] as? [[String: Any]] ?? []).map {
            QuestionOption(label: $0["label"] as? String ?? "", description: $0["description"] as? String ?? "")
        }
        return QuestionItem(
            question: q["question"] as? String ?? "",
            header: q["header"] as? String ?? "",
            multiSelect: q["multiSelect"] as? Bool ?? false,
            options: opts)
    }
    return QuestionBlock(id: o["id"] as? String ?? "", questions: items)
}

/// `detail` (why this card is stuck, from blockers.blocker()) and `body`
/// (what last happened, the machine's last reply) are two different things -
/// mirrors BoardModel.kt's BoardCard.
struct BoardCard: Identifiable, Hashable {
    let id: String
    let task: String
    let reason: String
    let detail: String
    let body: String
    let status: String

    static func == (l: BoardCard, r: BoardCard) -> Bool { l.id == r.id }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }
}

/// A needs_you card carries its own live question - kept OUT of `Hashable`
/// equality (BoardCard above) since QuestionBlock has no Equatable of its
/// own and identity by `id` is all List/NavigationLink need.
struct NeedsYouCard {
    let card: BoardCard
    let question: QuestionBlock?
}

struct BoardSummary {
    let yours: Int
    let wip: Int
    let wipLimit: Int
    let tsEpochSec: Int
}

struct BoardSection {
    let cards: [BoardCard]
    let total: Int
}

struct BoardPayload {
    let needsYou: [NeedsYouCard]
    let yours: [BoardCard]
    let working: BoardSection
    let backlog: BoardSection
    let summary: BoardSummary?
}

private func plainCard(_ c: [String: Any], reasonFallback: String) -> BoardCard {
    BoardCard(
        id: c["id"] as? String ?? "", task: c["task"] as? String ?? "",
        reason: (c["reason"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? reasonFallback,
        detail: c["detail"] as? String ?? "", body: c["body"] as? String ?? "",
        status: c["status"] as? String ?? "")
}

private func sectionOf(_ pipeline: [String: Any]?, listKey: String, totalKey: String) -> BoardSection {
    let arr = (pipeline?[listKey] as? [[String: Any]]) ?? []
    let cards = arr.map { plainCard($0, reasonFallback: listKey) }
    return BoardSection(cards: cards, total: pipeline?[totalKey] as? Int ?? cards.count)
}

/// Parses GET /wear/board's payload (routes_wear.py's wear_board_get) -
/// the Swift sibling of BoardModel.kt's parseBoardCards/parseYours/
/// parsePipeline/parseBoardSummary, folded into one entry point since Swift
/// has no equivalent need to keep each parse independently unit-testable
/// the way ops/tests/wear_chat_rows.kt drove the Kotlin file.
func parseBoardPayload(_ data: Data) -> BoardPayload? {
    guard let o = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
    let needsYou: [NeedsYouCard] = (o["needs_you"] as? [[String: Any]] ?? []).map { c in
        NeedsYouCard(card: plainCard(c, reasonFallback: ""), question: parseQuestionBlock(c["question"] as? [String: Any]))
    }
    let yours = (o["yours"] as? [[String: Any]] ?? []).map { plainCard($0, reasonFallback: "yours") }
    let pipeline = o["pipeline"] as? [String: Any]
    let working = sectionOf(pipeline, listKey: "working", totalKey: "working_total")
    let backlog = sectionOf(pipeline, listKey: "backlog", totalKey: "backlog_total")
    let econ = o["econ"] as? [String: Any]
    let summary = BoardSummary(
        yours: econ?["yours"] as? Int ?? yours.count,
        wip: econ?["wip"] as? Int ?? 0,
        wipLimit: econ?["wip_limit"] as? Int ?? 0,
        tsEpochSec: o["ts"] as? Int ?? 0)
    return BoardPayload(needsYou: needsYou, yours: yours, working: working, backlog: backlog, summary: summary)
}

/// "gerade eben" / "vor 5 min" / "vor 2 h" - so an all-clear can be told
/// apart from a stale one. 0 means the daemon sent no stamp.
func freshness(_ tsEpochSec: Int, now: Int) -> String {
    guard tsEpochSec > 0 else { return "" }
    let age = now - tsEpochSec
    if age < 0 { return "" }
    if age < 90 { return "gerade eben" }
    if age < 3600 { return "vor \(age / 60) min" }
    if age < 86400 { return "vor \(age / 3600) h" }
    return "vor \(age / 86400) d"
}

/// The blocker vocabulary (spine/turn/blockers.py BLOCKER_REASONS) plus the
/// two watch-only pipeline buckets, in the owner's language.
func reasonLabel(_ reason: String) -> String {
    switch reason {
    case "gate": return "Gate rot"
    case "conflict": return "Merge-Konflikt"
    case "failed": return "Fehlgeschlagen"
    case "question": return "Frage offen"
    case "review": return "Wartet auf Abnahme"
    case "delivered": return "Fertig - abnehmen"
    case "yours": return "Nur von dir startbar"
    case "working": return "In Arbeit"
    case "backlog": return "Backlog"
    default: return ""
    }
}

/// One line of the Henry conversation - the Swift sibling of ChatRows.kt's
/// `Line`. `key` is the server's identity for a SPEAKABLE line
/// (routes_wear's _wear_msg_key); its presence is the whole "can be spoken"
/// signal. Not cached by DeviceStore, deliberately - a key restored from
/// disk would let the app decide on startup that yesterday's answer is
/// still owed out loud.
struct HenryLine: Identifiable {
    let id = UUID()
    var mine: Bool
    var text: String
    var ts: String = ""
    var date: String = ""
    var label: String = ""
    var card: String = ""
    var options: [String] = []
    var key: String = ""
}
