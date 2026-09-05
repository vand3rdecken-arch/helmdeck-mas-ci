import Foundation
import SwiftUI

/// Henry as a text chat - the Swift sibling of HenryScreen.kt, and the
/// landing screen when paired (ContentView).
///
/// "Laden statt Streamen" (watchOS UI/UX design doc §1/§4): unlike the Wear
/// OS build's WearStream hanging-GET, this screen has NO background channel.
/// watchOS suspends a third-party process within seconds of leaving the
/// foreground (verified, no ambient-mode equivalent - see
/// ops/docs/backlog/watchos-technik-machbarkeit/README.md §2.2), so every
/// screen loads fresh on `.onAppear`/foreground-return instead of holding a
/// long-poll open. A push wake-up (APNs, watch-owned device token) is
/// deliberately out of scope here - the scaffold declares no push
/// entitlement yet (surfaces/watch/README.md, "deferred on purpose").
struct ChatView: View {
    @EnvironmentObject private var app: AppState

    /// Set when opened from a card's "Henry fragen" button - scopes every
    /// message to that card (POST /wear/talk's own `card` field), same
    /// semantics as CardScreen.kt's askHenry: advisory only
    /// (allow_actions=False server-side for a card-scoped ask), never the
    /// worker's own answer path.
    var cardContext: BoardCard?

    @State private var lines: [HenryLine] = []
    @State private var busy = false
    @State private var loadingHistory = false
    @State private var suggestions: QuestionBlock?
    @State private var answered: Set<String> = []
    @State private var draft = ""
    /// nil = not primed yet (first load must adopt the newest speakable line
    /// WITHOUT speaking it - never recite history on open). "" = primed,
    /// nothing spoken yet.
    @State private var spokenKey: String?
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        VStack(spacing: 0) {
            ScrollViewReader { proxy in
                List {
                    if lines.isEmpty {
                        Text(loadingHistory ? "Verlauf wird geladen…" : "Tippe unten und stelle deine Frage.")
                            .foregroundStyle(.secondary)
                    }
                    ForEach(buildChatRows(lines, answered: answered)) { row in
                        rowView(row).id(row.id)
                    }
                    if busy {
                        Text("Henry denkt …").foregroundStyle(.secondary)
                    }
                    ForEach(suggestions?.questions.first?.options ?? []) { opt in
                        Button(opt.label) { Task { await ask(opt.label) } }
                    }
                    if cardContext == nil {
                        NavigationLink("Board") { BoardView() }
                    }
                }
                .onChange(of: lines.count) { _, _ in
                    if let last = buildChatRows(lines, answered: answered).last {
                        withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
                    }
                }
            }
            HStack {
                TextField("Frag Henry", text: $draft)
                Button("Senden") { submitDraft() }
                    .disabled(busy || draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
            .padding(.horizontal, 4)
            Toggle("Stimme", isOn: Binding(
                get: { app.voiceOn },
                set: { app.setVoiceOn($0) }))
                .font(.footnote)
                .padding(.horizontal, 4)
                .padding(.bottom, 4)
        }
        .navigationTitle(cardContext.map { "Henry · \($0.task.isEmpty ? $0.id : $0.task)" } ?? "Henry")
        .task {
            lines = DeviceStore.loadChat().map {
                HenryLine(mine: $0.mine, text: $0.text, ts: $0.ts, date: $0.date, label: $0.label)
            }
            await refresh()
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { Task { await refresh() } }
        }
    }

    @ViewBuilder
    private func rowView(_ row: ChatRow) -> some View {
        switch row {
        case .day(let date):
            Text(dayLabel(date))
                .font(.caption2)
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, alignment: .center)
        case .msg(_, let line):
            VStack(alignment: line.mine ? .trailing : .leading, spacing: 2) {
                HStack {
                    Text(senderOf(line)).font(.caption2).foregroundStyle(.secondary)
                    if !line.ts.isEmpty {
                        Text(line.ts).font(.caption2).foregroundStyle(.secondary)
                    }
                }
                Text(line.text)
            }
            .frame(maxWidth: .infinity, alignment: line.mine ? .trailing : .leading)
        case .option(_, _, let card, let label):
            Button(label) { Task { await answerCard(card, label: label) } }
                .disabled(busy)
        }
    }

    // MARK: - Networking

    private func record(_ line: HenryLine) {
        lines.append(line)
        DeviceStore.saveChat(lines.map {
            DeviceStore.ChatLine(mine: $0.mine, text: $0.text, ts: $0.ts, date: $0.date, label: $0.label)
        })
    }

    private func submitDraft() {
        let message = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !message.isEmpty else { return }
        draft = ""
        Task { await ask(message) }
    }

    private func ask(_ message: String) async {
        guard let device = app.device else {
            record(HenryLine(mine: false, text: "Nicht gekoppelt.", ts: nowHm(), date: nowDate()))
            return
        }
        record(HenryLine(mine: true, text: message, ts: nowHm(), date: nowDate()))
        busy = true
        suggestions = nil
        var payload: [String: Any] = ["message": message, "voice": app.voiceOn]
        if let cardContext { payload["card"] = cardContext.id }
        guard let bodyData = try? JSONSerialization.data(withJSONObject: payload),
              let bodyStr = String(data: bodyData, encoding: .utf8)
        else { busy = false; return }

        let result = await RelayClient.talk(
            relayUrl: device.relayUrl, room: device.room, daemonPubB64: device.daemonPubB64,
            myPublicKeyB64: device.myPublicKeyB64, mySecretKeyB64: device.mySecretKeyB64,
            deviceToken: device.deviceToken, body: bodyStr)
        busy = false
        guard let result, (200...299).contains(result.status) else {
            record(HenryLine(
                mine: false,
                text: "Henry nicht erreichbar - falls die Antwort noch entsteht, erscheint sie gleich im Verlauf.",
                ts: nowHm(), date: nowDate()))
            return
        }
        let o = try? JSONSerialization.jsonObject(with: Data(result.body.utf8)) as? [String: Any]
        let replyText = o?["reply"] as? String ?? ""
        record(HenryLine(mine: false, text: replyText.isEmpty ? "(keine Antwort)" : replyText, ts: nowHm(), date: nowDate()))
        suggestions = parseQuestionBlock(o?["question"] as? [String: Any])
        // Claim first, then play - the same reply is about to arrive again
        // over refresh(); recording the key here is what stops the watch
        // saying the same sentence twice.
        if let vk = o?["voiceKey"] as? String, !vk.isEmpty { spokenKey = vk }
        if app.voiceOn, let v = o?["voice"] as? [String: Any],
           let b64 = v["b64"] as? String, !b64.isEmpty {
            VoicePlayer.shared.play(mime: v["mime"] as? String ?? "audio/mpeg", b64: b64)
        }
    }

    /// Answers a MIRRORED card question from the chat - same POST as ask(),
    /// plus `reply_to_card`, which routes it to that card's worker
    /// (sessions.reply_door) instead of Henry's advisory session.
    private func answerCard(_ card: String, label: String) async {
        guard let device = app.device else {
            record(HenryLine(mine: false, text: "Nicht gekoppelt.", ts: nowHm(), date: nowDate()))
            return
        }
        record(HenryLine(mine: true, text: label, ts: nowHm(), date: nowDate()))
        answered.insert(card)
        busy = true
        let payload: [String: Any] = ["message": label, "reply_to_card": card]
        guard let bodyData = try? JSONSerialization.data(withJSONObject: payload),
              let bodyStr = String(data: bodyData, encoding: .utf8)
        else { busy = false; return }
        let result = try? await RelayClient.authedCall(
            relayUrl: device.relayUrl, room: device.room, daemonPubB64: device.daemonPubB64,
            myPublicKeyB64: device.myPublicKeyB64, mySecretKeyB64: device.mySecretKeyB64,
            deviceToken: device.deviceToken, method: "POST", path: "/wear/talk", body: bodyStr)
        busy = false
        guard let result, (200...299).contains(result.status) else {
            // Put the buttons back: an answer that never landed must not
            // look like one that did.
            answered.remove(card)
            record(HenryLine(mine: false, text: "Antwort nicht angekommen.", ts: nowHm(), date: nowDate()))
            return
        }
    }

    /// The server transcript is the truth - GET /wear/chat returns the same
    /// copilot session the phone renders.
    private func refresh() async {
        guard let device = app.device else { return }
        loadingHistory = lines.isEmpty
        guard let result = try? await RelayClient.authedCall(
            relayUrl: device.relayUrl, room: device.room, daemonPubB64: device.daemonPubB64,
            myPublicKeyB64: device.myPublicKeyB64, mySecretKeyB64: device.mySecretKeyB64,
            deviceToken: device.deviceToken, method: "GET", path: "/wear/chat")
        else {
            loadingHistory = false
            return
        }
        loadingHistory = false
        guard (200...299).contains(result.status),
              let o = try? JSONSerialization.jsonObject(with: Data(result.body.utf8)) as? [String: Any],
              let arr = o["messages"] as? [[String: Any]]
        else { return }

        let kindLabels = ["question": "Frage", "result": "Ergebnis", "blocker": "Blocker"]
        var fresh: [HenryLine] = []
        for m in arr {
            let text = (m["text"] as? String) ?? ""
            if text.isEmpty { continue }
            let kind = (m["kind"] as? String) ?? ""
            var label = ""
            if !kind.isEmpty {
                let cardName = (m["cardName"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? (m["card"] as? String ?? "")
                label = "\(kindLabels[kind] ?? "Karte") · \(cardName)"
            }
            var opts: [String] = []
            if kind == "question",
               let q = m["question"] as? [String: Any],
               let qs = q["questions"] as? [[String: Any]],
               let first = qs.first,
               let oa = first["options"] as? [[String: Any]] {
                opts = oa.compactMap { $0["label"] as? String }.filter { !$0.isEmpty }
            }
            fresh.append(HenryLine(
                mine: m["mine"] as? Bool ?? false, text: text,
                ts: m["ts"] as? String ?? "", date: m["date"] as? String ?? "",
                label: label, card: m["card"] as? String ?? "", options: opts,
                key: m["key"] as? String ?? ""))
        }
        // An empty server history is a real answer (fresh session), but
        // never let it wipe a cache the owner can still read for an
        // unexpected reason.
        guard !fresh.isEmpty || lines.isEmpty else { return }
        lines = fresh
        DeviceStore.saveChat(lines.map {
            DeviceStore.ChatLine(mine: $0.mine, text: $0.text, ts: $0.ts, date: $0.date, label: $0.label)
        })

        let newestVoice = fresh.last(where: { !$0.key.isEmpty })?.key
        if spokenKey == nil {
            // First load: adopt, do not speak.
            spokenKey = newestVoice ?? ""
        } else if let newestVoice, newestVoice != spokenKey {
            spokenKey = newestVoice
            if app.voiceOn { await speak(newestVoice) }
        }
    }

    /// Fetches and plays the clip for ONE transcript line, named by its
    /// server key - the catch-up half of the voice toggle (an answer that
    /// outlived talk()'s own HTTP request, or one to a turn started on the
    /// phone/glasses).
    private func speak(_ key: String) async {
        guard let device = app.device else { return }
        guard let result = try? await RelayClient.authedCall(
            relayUrl: device.relayUrl, room: device.room, daemonPubB64: device.daemonPubB64,
            myPublicKeyB64: device.myPublicKeyB64, mySecretKeyB64: device.mySecretKeyB64,
            deviceToken: device.deviceToken, method: "GET", path: "/wear/voice?key=\(key)", timeout: 60),
            (200...299).contains(result.status),
            let o = try? JSONSerialization.jsonObject(with: Data(result.body.utf8)) as? [String: Any],
            let v = o["voice"] as? [String: Any],
            let b64 = v["b64"] as? String, !b64.isEmpty
        else { return }
        // Asked again after the wait - the owner may have toggled voice off
        // while the clip was rendering.
        guard app.voiceOn else { return }
        VoicePlayer.shared.play(mime: v["mime"] as? String ?? "audio/mpeg", b64: b64)
    }
}
