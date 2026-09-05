import Foundation

/// App-root state - exactly ONE owner for pairing and the voice toggle,
/// read by every screen (Chat, Board, Card). Mirrors the watchOS UI/UX
/// design doc §3's own requirement: `voiceOn` used to live only on
/// HenryScreen in the Wear OS build, which is precisely the bug the Wear
/// parity audit found (a card's own dialog spoke unconditionally because it
/// read no such flag). One `ObservableObject` at app-root scope is how this
/// build avoids that from the start rather than fixing it later.
@MainActor
final class AppState: ObservableObject {
    @Published private(set) var device: DeviceStore.Device?
    @Published private(set) var voiceOn: Bool

    init() {
        device = DeviceStore.load()
        voiceOn = DeviceStore.loadVoiceOn()
    }

    func setPaired(_ device: DeviceStore.Device) {
        DeviceStore.save(device)
        self.device = device
    }

    func setVoiceOn(_ on: Bool) {
        voiceOn = on
        DeviceStore.saveVoiceOn(on)
        // Switching off mid-sentence must stop THAT sentence, not merely the
        // next one.
        if !on { VoicePlayer.shared.stop() }
    }
}
