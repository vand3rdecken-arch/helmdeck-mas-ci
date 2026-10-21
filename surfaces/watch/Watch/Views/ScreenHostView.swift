import Foundation
import SwiftUI

/// Draws one daemon-described screen (Data/Screen.swift) and runs its actions.
/// The Swift sibling of ScreenHost in ScreenRenderer.kt. It decides nothing:
/// what a card, a button or a pick MEANS comes from the daemon. Local state is
/// only what an action needs (the picks, the status of a post).
///
/// Two deliberate differences from the Wear build: the system provides the
/// back button, so a `back` button is not drawn; and "ask Henry" navigates into
/// the ONE chat (ChatView) rather than growing a second local dialog (the Wear
/// parity audit's bug, see CardView).
struct ScreenHostView: View {
    @EnvironmentObject private var app: AppState

    let blocks: [ScreenBlock]
    let cardFor: (String) -> BoardCard?
    let onReload: () -> Void

    @State private var picks: [String: String] = [:]
    @State private var postStatus: String?

    var body: some View {
        List {
            ForEach(Array(blocks.enumerated()), id: \.offset) { _, block in
                row(block)
            }
            if let postStatus {
                Text(postStatus).font(.footnote).foregroundStyle(.secondary)
            }
        }
    }

    private func blankCard(_ id: String, title: String = "", status: String = "") -> BoardCard {
        BoardCard(id: id, task: title, reason: "", detail: "", body: "", status: status)
    }

    @ViewBuilder
    private func row(_ block: ScreenBlock) -> some View {
        switch block {
        case .header(let text):
            Text(text).font(.headline)
        case .line(let text, let status):
            Text(text).foregroundStyle(status.isEmpty ? Color.primary : screenStatusColor(status))
        case .age(let ts, let prefix):
            let age = freshness(ts, now: Int(Date().timeIntervalSince1970))
            if !age.isEmpty {
                Text(prefix + age).font(.footnote).foregroundStyle(.secondary)
            }
        case .card(let title, let status, let action):
            if case .openCard(let id)? = action {
                NavigationLink {
                    CardScreenView(card: cardFor(id) ?? blankCard(id, title: title, status: status))
                } label: {
                    cardLabel(title, status)
                }
            } else {
                cardLabel(title, status)
            }
        case .preview(let title, let text, let lines, let style, let detailTitle):
            NavigationLink {
                ScrollView { Text(text).padding() }
                    .navigationTitle(detailTitle.isEmpty ? title : detailTitle)
            } label: {
                VStack(alignment: .leading, spacing: 2) {
                    if !title.isEmpty {
                        Text(title).font(.footnote).foregroundStyle(.secondary)
                    }
                    Text(text).lineLimit(lines)
                        .foregroundStyle(style == "surface" ? Color.secondary : Color.primary)
                }
            }
        case .button(let label, _, _, let action, let selKey, let selValue, let needs):
            buttonRow(label: label, action: action, selKey: selKey, selValue: selValue, needs: needs)
        }
    }

    private func cardLabel(_ title: String, _ status: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).lineLimit(2)
            if !status.isEmpty {
                Text(status).font(.footnote).foregroundStyle(screenStatusColor(status))
            }
        }
    }

    @ViewBuilder
    private func buttonRow(label: String, action: ScreenAction?, selKey: String,
                           selValue: String, needs: [String]) -> some View {
        if case .back? = action {
            EmptyView()   // the system back button does this
        } else if case .nav(let to)? = action, to == "henry" {
            NavigationLink(label) { ChatView() }
        } else if case .dictate(_, let cardId)? = action {
            NavigationLink {
                ChatView(cardContext: cardFor(cardId) ?? blankCard(cardId))
            } label: {
                Label(label, systemImage: "mic")
            }
        } else if case .reload? = action {
            Button(label) { onReload() }
        } else {
            let selected = !selKey.isEmpty && picks[selKey] == selValue
            Button((selected ? "> " : "") + label) {
                if let action { run(action, picks) }
            }
            .disabled(!needs.allSatisfy { picks[$0] != nil })
        }
    }

    /// `current` is the picks map AS OF this tap: a single-select answer picks
    /// and posts in one go, and the post must see the pick it just made.
    private func run(_ action: ScreenAction, _ current: [String: String]) {
        switch action {
        case .pick(let key, let value, let then):
            var next = current
            next[key] = value
            picks = next
            if let then { run(then, next) }
        case .post(let path, let body, let picksInto, let busy, let ok, let fail):
            Task {
                await post(path: path, body: body, picksInto: picksInto, picks: current,
                           busy: busy, ok: ok, fail: fail)
            }
        default:
            break
        }
    }

    private func post(path: String, body: [String: Any], picksInto: String,
                      picks current: [String: String], busy: String, ok: String, fail: String) async {
        guard let device = app.device else { return }
        postStatus = busy.isEmpty ? nil : busy
        var payload = body
        if !picksInto.isEmpty { payload[picksInto] = current }
        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let bodyStr = String(data: data, encoding: .utf8)
        else { return }
        let result = try? await RelayClient.authedCall(
            relayUrl: device.relayUrl, room: device.room, daemonPubB64: device.daemonPubB64,
            myPublicKeyB64: device.myPublicKeyB64, mySecretKeyB64: device.mySecretKeyB64,
            deviceToken: device.deviceToken, method: "POST", path: path, body: bodyStr)
        postStatus = (result != nil && (200...299).contains(result!.status)) ? ok : fail
    }
}

/// The card screen: fetched from the daemon as a screen description
/// (GET /wear/card?id=). Falls back to the native CardView when the fetch does
/// not produce one (without its live question - that rode on the board payload).
struct CardScreenView: View {
    @EnvironmentObject private var app: AppState

    let card: BoardCard

    @State private var blocks: [ScreenBlock]?
    @State private var tried = false

    var body: some View {
        Group {
            if let blocks {
                ScreenHostView(blocks: blocks, cardFor: { _ in nil }, onReload: {})
            } else if !tried {
                Text("Lade…")
            } else {
                CardView(card: card, question: nil)
            }
        }
        .navigationTitle(card.task.isEmpty ? card.id : card.task)
        .task { await load() }
    }

    private func load() async {
        defer { tried = true }
        guard let device = app.device else { return }
        let id = card.id.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? card.id
        guard let result = try? await RelayClient.authedCall(
            relayUrl: device.relayUrl, room: device.room, daemonPubB64: device.daemonPubB64,
            myPublicKeyB64: device.myPublicKeyB64, mySecretKeyB64: device.mySecretKeyB64,
            deviceToken: device.deviceToken, method: "GET", path: "/wear/card?id=" + id),
            (200...299).contains(result.status),
            let parsed = parseScreen(Data(result.body.utf8))
        else { return }
        blocks = parsed
    }
}

/// Mirrors WearSemantics.status (Kotlin) and CardView's table, so red means red
/// on every surface. Kept here (CardView's own copy is file-private).
private func screenStatusColor(_ value: String) -> Color {
    switch value {
    case "running": return .blue
    case "needs_you": return .orange
    case "gating", "submitted": return .purple
    case "accepted", "done": return .green
    case "bounced", "failed": return .red
    default: return .secondary
    }
}
