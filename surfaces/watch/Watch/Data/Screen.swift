import Foundation

/// A screen the DAEMON describes (spine/ops/wear_screen.py, protocol v1) - the
/// Swift sibling of ScreenRenderer.kt's model and parser. The watch knows HOW
/// to draw a closed set of blocks and HOW to run a closed set of actions; WHAT
/// is on a screen, in which order, with which words, is the daemon's. So a
/// wording or layout change is a daemon change, not a watchOS build and not a
/// TestFlight/App Store submission (ops/docs/backlog/native-release-diet).
/// A NEW block type or action is the only thing that costs a build.
///
/// Unknown blocks and actions are skipped, never guessed at: a newer daemon on
/// an older watch degrades to a shorter screen rather than a wrong one.
indirect enum ScreenAction {
    case openCard(id: String)
    case nav(to: String)
    case reload
    case back
    /// Remember key=value locally; `then` runs right after (single-select = the answer).
    case pick(key: String, value: String, then: ScreenAction?)
    /// Generic authed POST. `picksInto` names the body field the picks map is put under.
    case post(path: String, body: [String: Any], picksInto: String,
              busy: String, ok: String, fail: String)
    /// Speech/typing to Henry about one card - the watch routes it into the ONE chat.
    case dictate(prompt: String, card: String)
}

enum ScreenBlock {
    case header(String)
    case line(text: String, status: String)
    case age(ts: Int, prefix: String)
    case card(title: String, status: String, action: ScreenAction?)
    /// A short card that opens the FULL text on its own screen. style: title | outlined | surface.
    case preview(title: String, text: String, lines: Int, style: String, detailTitle: String)
    case button(label: String, icon: String, style: String, action: ScreenAction?,
                selKey: String, selValue: String, needs: [String])
}

private func parseScreenAction(_ o: [String: Any]?) -> ScreenAction? {
    guard let o else { return nil }
    switch (o["do"] as? String) ?? "" {
    case "open_card": return .openCard(id: o["id"] as? String ?? "")
    case "nav": return .nav(to: o["to"] as? String ?? "")
    case "reload": return .reload
    case "back": return .back
    case "pick":
        return .pick(key: o["key"] as? String ?? "", value: o["value"] as? String ?? "",
                     then: parseScreenAction(o["then"] as? [String: Any]))
    case "post":
        return .post(path: o["path"] as? String ?? "", body: o["body"] as? [String: Any] ?? [:],
                     picksInto: o["picks_into"] as? String ?? "",
                     busy: o["busy"] as? String ?? "", ok: o["ok"] as? String ?? "",
                     fail: o["fail"] as? String ?? "")
    case "dictate":
        return .dictate(prompt: o["prompt"] as? String ?? "", card: o["card"] as? String ?? "")
    default: return nil
    }
}

/// The `screen` object of a response, or nil when the daemon is older than this
/// build (the watch then draws its own native screen).
func parseScreen(_ data: Data) -> [ScreenBlock]? {
    guard let top = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
          let screen = top["screen"] as? [String: Any],
          (screen["v"] as? Int) == 1,
          let items = screen["items"] as? [[String: Any]]
    else { return nil }
    var out: [ScreenBlock] = []
    for o in items {
        switch (o["t"] as? String) ?? "" {
        case "header": out.append(.header(o["text"] as? String ?? ""))
        case "text": out.append(.line(text: o["text"] as? String ?? "", status: o["status"] as? String ?? ""))
        case "age": out.append(.age(ts: o["ts"] as? Int ?? 0, prefix: o["prefix"] as? String ?? ""))
        case "card":
            out.append(.card(title: o["title"] as? String ?? "", status: o["status"] as? String ?? "",
                             action: parseScreenAction(o["action"] as? [String: Any])))
        case "preview":
            out.append(.preview(title: o["title"] as? String ?? "", text: o["text"] as? String ?? "",
                                lines: o["lines"] as? Int ?? 3, style: o["style"] as? String ?? "",
                                detailTitle: o["detail_title"] as? String ?? ""))
        case "button":
            let sel = o["selected"] as? [String: Any]
            out.append(.button(label: o["label"] as? String ?? "", icon: o["icon"] as? String ?? "",
                               style: o["style"] as? String ?? "",
                               action: parseScreenAction(o["action"] as? [String: Any]),
                               selKey: sel?["key"] as? String ?? "", selValue: sel?["value"] as? String ?? "",
                               needs: o["needs"] as? [String] ?? []))
        default: break
        }
    }
    return out
}
