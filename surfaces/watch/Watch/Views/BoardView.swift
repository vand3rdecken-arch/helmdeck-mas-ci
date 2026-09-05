import Foundation
import SwiftUI

/// GET /wear/board (routes_wear.py) - the Swift sibling of BoardScreen.kt.
/// Reuses glance_payload() unchanged, the same small curated "what needs
/// you" read the glasses already get. Loads once on appear, not on a
/// hanging stream (see ChatView's own "Laden statt Streamen" note) - a pull-
/// to-refresh ("Aktualisieren") is the manual escape hatch.
struct BoardView: View {
    @EnvironmentObject private var app: AppState

    @State private var payload: BoardPayload?
    @State private var status = "Lade…"

    var body: some View {
        List {
            Section(status) {
                ForEach(payload?.needsYou.map(\.card) ?? []) { card in
                    NavigationLink(card.task.isEmpty ? card.id : card.task) {
                        CardView(card: card, question: question(for: card))
                    }
                }
            }
            if let yours = payload?.yours, !yours.isEmpty {
                Section("Nur von dir startbar") {
                    ForEach(yours) { card in
                        NavigationLink(card.task.isEmpty ? card.id : card.task) {
                            CardView(card: card, question: nil)
                        }
                    }
                }
            }
            if let working = payload?.working, working.total > 0 {
                Section(summary.map { $0.wipLimit > 0 ? "In Arbeit: \(working.total) von \($0.wipLimit)" : "In Arbeit: \(working.total)" } ?? "In Arbeit: \(working.total)") {
                    ForEach(working.cards) { card in
                        NavigationLink(card.task.isEmpty ? card.id : card.task) {
                            CardView(card: card, question: nil)
                        }
                    }
                }
            }
            if let backlog = payload?.backlog, backlog.total > 0 {
                Section("Backlog: \(backlog.total)") {
                    ForEach(backlog.cards) { card in
                        NavigationLink(card.task.isEmpty ? card.id : card.task) {
                            CardView(card: card, question: nil)
                        }
                    }
                }
            }
            Section {
                if let summary, !freshness(summary.tsEpochSec, now: Int(Date().timeIntervalSince1970)).isEmpty {
                    Text("Stand: \(freshness(summary.tsEpochSec, now: Int(Date().timeIntervalSince1970)))")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
                NavigationLink("Henry fragen") { ChatView() }
                Button("Aktualisieren") { Task { await reload() } }
            }
        }
        .navigationTitle("HelmDeck")
        .task { await reload() }
    }

    private var summary: BoardSummary? { payload?.summary }

    private func question(for card: BoardCard) -> QuestionBlock? {
        payload?.needsYou.first(where: { $0.card.id == card.id })?.question
    }

    private func reload() async {
        guard let device = app.device else {
            status = "Nicht gekoppelt"
            return
        }
        status = "Lade…"
        guard let result = try? await RelayClient.authedCall(
            relayUrl: device.relayUrl, room: device.room, daemonPubB64: device.daemonPubB64,
            myPublicKeyB64: device.myPublicKeyB64, mySecretKeyB64: device.mySecretKeyB64,
            deviceToken: device.deviceToken, method: "GET", path: "/wear/board"),
            (200...299).contains(result.status),
            let parsed = parseBoardPayload(Data(result.body.utf8))
        else {
            status = "Konnte nicht laden"
            return
        }
        payload = parsed
        let n = parsed.needsYou.count
        status = n == 0 ? "Nichts wartet auf dich" : (n == 1 ? "1 wartet auf dich" : "\(n) warten auf dich")
    }
}
