import Foundation
import AVFoundation

/// Plays the inline voice clip POST /wear/talk / GET /wear/voice return
/// ({mime, b64} - spine/media/voice.py's render_b64()) - the Swift sibling
/// of app.helmdeck.wear.data.VoicePlayer (Kotlin, MediaPlayer). Voice stays
/// SERVER-RENDERED throughout (ops/docs/glasses-reference.md §4, standing
/// owner decision) - nothing here synthesises anything, it only plays back
/// an MP3 the daemon already produced.
///
/// Decoded to a temp file rather than an in-memory `AVAudioPlayer(data:)`
/// buffer for the same file-lifetime reasons the Kotlin sibling gives
/// (MediaPlayer's own API shape there); `AVAudioPlayer(data:)` exists on
/// watchOS too, but a file gives an unambiguous cleanup point (delete on
/// completion/error/stop) that a `Data` buffer does not need but a file on
/// disk does.
@MainActor
final class VoicePlayer: NSObject, AVAudioPlayerDelegate {
    static let shared = VoicePlayer()

    private var player: AVAudioPlayer?
    private var tempFile: URL?

    func play(mime: String, b64: String) {
        stop()
        guard let bytes = Data(base64Encoded: b64), !bytes.isEmpty else { return }
        let ext = (mime.contains("mpeg") || mime.contains("mp3")) ? "mp3" : "audio"
        let file = FileManager.default.temporaryDirectory
            .appendingPathComponent("henry_\(UUID().uuidString).\(ext)")
        do {
            try bytes.write(to: file)
            // USAGE_ASSISTANT/CONTENT_TYPE_SPEECH on the Kotlin side has no
            // 1:1 AVAudioSession category - `.playback`/`.spokenAudio` is the
            // closest documented pairing for "an assistant reading text
            // aloud" on watchOS.
            let session = AVAudioSession.sharedInstance()
            try? session.setCategory(.playback, mode: .spokenAudio)
            try? session.setActive(true)
            let newPlayer = try AVAudioPlayer(contentsOf: file)
            newPlayer.delegate = self
            player = newPlayer
            tempFile = file
            newPlayer.play()
        } catch {
            try? FileManager.default.removeItem(at: file)
        }
    }

    func stop() {
        player?.stop()
        player = nil
        if let tempFile { try? FileManager.default.removeItem(at: tempFile) }
        tempFile = nil
    }

    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in self.stop() }
    }

    nonisolated func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?) {
        Task { @MainActor in self.stop() }
    }
}
