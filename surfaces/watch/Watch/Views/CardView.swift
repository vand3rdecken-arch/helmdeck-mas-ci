import Foundation
import SwiftUI

/// One card: the worker's pending question (if any, answered directly via
/// POST /tracks/<id>/answer - the one case the wear docs allow to reach the
/// worker, since it is a structured pick, not authorship) and a "Henry
/// fragen" link into the SAME chat screen with this card as context - the
/// Swift sibling of CardScreen.kt, but deliberately NOT reproducing that
/// screen's own local Henry-dialog state, which the Wear parity audit found
/// to be a bug (a dialog that does not survive a screen change and is not a
/// real chat history). §2 of the watchOS UI/UX design doc calls this out
/// explicitly: navigate into the one Henry chat, never draw a second one.
struct CardView: View {
    @EnvironmentObject private var app: AppState
    let card: BoardCard
    let question: QuestionBlock?

    @State private var picks: [String: String] = [:]
    @State private var answerStatus: String?

    var body: some View {
        List {
            let label = reasonLabel(card.reason)
            if !label.isEmpty {
                Text(label).foregroundStyle(statusColor(card.status.isEmpty ? card.reason : card.status))
            }
            if !card.detail.isEmpty {
                Text(card.detail)
            }
            if !card.body.isEmpty {
                Text(card.body).foregroundStyle(.secondary)
            }
            if let question {
                ForEach(question.questions, id: \.header) { item in
                    Text(item.question).font(.footnote)
                    ForEach(item.options) { opt in
                        Button((picks[item.header] == opt.label ? "> " : "") + opt.label) {
                            picks[item.header] = opt.label
                            // Single question, single-select: this IS the
                            // whole answer - submit immediately. Multi-
                            // question needs every header filled first.
                            if question.questions.count == 1 && !item.multiSelect {
                                Task { await submitAnswer(requestId: question.id) }
                            }
                        }
                    }
                }
                if question.questions.count > 1 {
                    Button("Antworten") { Task { await submitAnswer(requestId: question.id) } }
                        .disabled(!question.questions.allSatisfy { picks[$0.header] != nil })
                }
                if let answerStatus {
                    Text(answerStatus).font(.footnote).foregroundStyle(.secondary)
                }
            }
            NavigationLink("Henry fragen") { ChatView(cardContext: card) }
        }
        .navigationTitle(card.task.isEmpty ? card.id : card.task)
    }

    private func submitAnswer(requestId: String) async {
        guard let device = app.device else { return }
        answerStatus = "Sende…"
        let payload: [String: Any] = ["answers": picks, "request_id": requestId]
        guard let bodyData = try? JSONSerialization.data(withJSONObject: payload),
              let bodyStr = String(data: bodyData, encoding: .utf8)
        else { return }
        let result = try? await RelayClient.authedCall(
            relayUrl: device.relayUrl, room: device.room, daemonPubB64: device.daemonPubB64,
            myPublicKeyB64: device.myPublicKeyB64, mySecretKeyB64: device.mySecretKeyB64,
            deviceToken: device.deviceToken, method: "POST", path: "/tracks/\(card.id)/answer", body: bodyStr)
        answerStatus = (result != nil && (200...299).contains(result!.status)) ? "Beantwortet" : "Fehlgeschlagen"
    }
}

/// Mirrors WearSemantics.status (Kotlin) - the phone's own statusColor()
/// table, so red means red on every surface.
private func statusColor(_ value: String) -> Color {
    switch value {
    case "running": return .blue
    case "needs_you": return .orange
    case "gating": return .purple
    case "submitted": return .purple
    case "accepted", "done": return .green
    case "bounced", "failed": return .red
    default: return .secondary
    }
}
