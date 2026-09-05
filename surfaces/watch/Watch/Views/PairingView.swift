import SwiftUI

/// The dedicated, always-on Cloudflare Worker that proxies EXACTLY
/// GET /relay/pair/claim (surfaces/relay/pair_worker) - same constant and
/// same reasoning as PairingScreen.kt's DEFAULT_CLAIM_BASE_URL: a raw
/// cloudflared tunnel origin would expose the daemon's whole HTTP surface,
/// not just pairing.
private let defaultClaimBaseURL = "https://helmdeck-pair.van-d3r-decken.workers.dev"

/// The device-code pairing screen - the Swift sibling of PairingScreen.kt.
/// No camera on the watch to scan a QR code, so this is address (pre-filled,
/// "meist unnötig") + the six-character code from POST /relay/pair/code on
/// the phone/desktop.
///
/// Dictation itself needs no extra code here: a watchOS `TextField` presents
/// the system text-input controller (Scribble/dictation/QWERTY, the owner's
/// choice) automatically on tap - documented default behaviour, but NOT
/// verified against a real watch from this worktree (no device/simulator
/// reachable), unlike the Kotlin screen's explicit
/// `RecognizerIntent.ACTION_RECOGNIZE_SPEECH` launch, which Wear OS has no
/// implicit equivalent for.
struct PairingView: View {
    @EnvironmentObject private var app: AppState

    @State private var claimBaseUrl = defaultClaimBaseURL
    @State private var code = ""
    @State private var status: String?
    @State private var busy = false

    var body: some View {
        ScrollView {
            VStack(spacing: 10) {
                Text("HelmDeck koppeln")
                    .font(.headline)
                    .multilineTextAlignment(.center)
                // Code first: with the address defaulted, this is the only
                // field the owner needs to touch in the common case.
                TextField("Code", text: $code)
                    .multilineTextAlignment(.center)
                Button(busy ? "…" : "Koppeln") { Task { await submit() } }
                    .disabled(busy)
                TextField("Adresse (meist unnötig)", text: $claimBaseUrl)
                    .multilineTextAlignment(.center)
                    .font(.footnote)
                if let status {
                    Text(status)
                        .font(.footnote)
                        .multilineTextAlignment(.center)
                        .foregroundStyle(.secondary)
                }
            }
            .padding()
        }
    }

    private func submit() async {
        let trimmedCode = code.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedBase = claimBaseUrl.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedBase.isEmpty, !trimmedCode.isEmpty else {
            status = "Adresse und Code eingeben"
            return
        }
        busy = true
        status = "Koppeln…"
        guard let claimed = await RelayClient.claim(claimBaseUrl: trimmedBase, code: trimmedCode) else {
            busy = false
            status = "Code unbekannt oder abgelaufen"
            return
        }
        guard let kp = HelmDeckBox.generateKeyPair() else {
            busy = false
            status = "Schlüsselerzeugung fehlgeschlagen"
            return
        }
        let completed = await RelayClient.completePairing(
            relayUrl: claimed.relayUrl, room: claimed.room, daemonPubB64: claimed.daemonPubB64,
            myPublicKeyB64: kp.publicKeyB64, mySecretKeyB64: kp.secretKeyB64, deviceToken: claimed.deviceToken)
        busy = false
        guard completed else {
            status = "Gekoppelt, aber der erste Abruf ist fehlgeschlagen - erneut versuchen"
            return
        }
        app.setPaired(DeviceStore.Device(
            relayUrl: claimed.relayUrl, room: claimed.room, daemonPubB64: claimed.daemonPubB64,
            mySecretKeyB64: kp.secretKeyB64, myPublicKeyB64: kp.publicKeyB64, deviceToken: claimed.deviceToken))
        status = "Gekoppelt"
    }
}
